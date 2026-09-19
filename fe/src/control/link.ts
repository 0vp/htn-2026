import { useEffect, useRef, useState } from 'react';
import { commandTap } from '../session/recorder';
import { control, packet } from './store';

export type CommandLink = {
  state: 'local' | 'connecting' | 'open' | 'closed';
  sent: number;
  last: ReturnType<typeof packet> | null;
};

const RATE_HZ = 20;

function controlUrl(): string {
  return new URLSearchParams(location.search).get('control') ?? import.meta.env.VITE_CONTROL_URL ?? '';
}

/**
 * Streams command packets at 20 Hz. Without a control URL it stays local and only
 * mirrors what it would send. Firmware should stop the robot if packets stop arriving.
 */
export function useCommandLink(): CommandLink {
  const [link, setLink] = useState<CommandLink>({ state: 'local', sent: 0, last: null });
  const seq = useRef(0);

  useEffect(() => {
    const url = controlUrl();
    let socket: WebSocket | null = null;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let stopped = false;

    const open = () => {
      if (!url) return;
      setLink((l) => ({ ...l, state: 'connecting' }));
      socket = new WebSocket(url);
      socket.onopen = () => setLink((l) => ({ ...l, state: 'open' }));
      socket.onclose = () => {
        setLink((l) => ({ ...l, state: 'closed' }));
        if (!stopped) retry = setTimeout(open, 1500);
      };
    };
    open();

    const timer = setInterval(() => {
      seq.current += 1;
      const next = packet(control.get(), seq.current);
      if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify(next));
      commandTap.emit(next);
      setLink((l) => ({ ...l, sent: seq.current, last: next }));
    }, 1000 / RATE_HZ);

    return () => {
      stopped = true;
      clearInterval(timer);
      clearTimeout(retry);
      socket?.close();
    };
  }, []);

  return link;
}
