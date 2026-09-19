import { useEffect, useState } from 'react';
import { createSim } from './sim';
import { WHEEL_DIAMETER_M, type Telemetry } from './types';

export type TelemetryFeed = {
  now: Telemetry | null;
  history: { volts: number[]; amps: number[]; speed: number[] };
  source: 'sim' | 'live' | 'waiting';
};

const HISTORY = 300; // 30 s at 10 Hz
const push = (series: number[], value: number) => [...series.slice(-(HISTORY - 1)), value];

function telemetryUrl(): string {
  return new URLSearchParams(location.search).get('telemetry') ?? import.meta.env.VITE_TELEMETRY_URL ?? '';
}

/** Samples the simulator at 10 Hz, or merges JSON telemetry from `?telemetry=ws://…`. */
export function useTelemetry(): TelemetryFeed {
  const [feed, setFeed] = useState<TelemetryFeed>({
    now: null,
    history: { volts: [], amps: [], speed: [] },
    source: telemetryUrl() ? 'waiting' : 'sim',
  });

  useEffect(() => {
    const record = (sample: Telemetry, source: TelemetryFeed['source']) =>
      setFeed((f) => {
        const speed = ((sample.rpm.left + sample.rpm.right) / 2) * Math.PI * WHEEL_DIAMETER_M / 60;
        return {
          now: sample,
          source,
          history: {
            volts: push(f.history.volts, sample.packVolts),
            amps: push(f.history.amps, sample.ampsEstimate),
            speed: push(f.history.speed, speed),
          },
        };
      });

    const url = telemetryUrl();
    if (!url) {
      const step = createSim();
      let last = performance.now();
      const timer = setInterval(() => {
        const now = performance.now();
        record(step((now - last) / 1000), 'sim');
        last = now;
      }, 100);
      return () => clearInterval(timer);
    }

    let latest: Telemetry | null = null;
    let socket: WebSocket | null = null;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let stopped = false;
    const open = () => {
      socket = new WebSocket(url);
      socket.onmessage = (event) => {
        try {
          latest = { ...(latest ?? ({} as Telemetry)), ...(JSON.parse(String(event.data)) as Partial<Telemetry>) };
        } catch {
          // Ignore non-JSON frames.
        }
      };
      socket.onclose = () => {
        if (!stopped) retry = setTimeout(open, 1500);
      };
    };
    open();
    // Sample at a fixed rate so charts keep a steady time base whatever the robot's send rate.
    const timer = setInterval(() => latest && record(latest, 'live'), 100);
    return () => {
      stopped = true;
      clearInterval(timer);
      clearTimeout(retry);
      socket?.close();
    };
  }, []);

  return feed;
}
