import type { Telemetry } from './types';

export type SampleOrigin = 'sim' | 'live' | 'replay';
type Listener = (sample: Telemetry, origin: SampleOrigin) => void;

/** 10 Hz telemetry samples. While replaying, sim and live samples are dropped. */
class TelemetryBus {
  private listeners = new Set<Listener>();
  private replaying = false;

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  emit(sample: Telemetry, origin: SampleOrigin): void {
    if (this.replaying && origin !== 'replay') return;
    for (const listener of this.listeners) listener(sample, origin);
  }

  setReplaying(replaying: boolean): void {
    this.replaying = replaying;
  }
}

export const telemetryBus = new TelemetryBus();
