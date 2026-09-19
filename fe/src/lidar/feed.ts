import { parseMessage, toBatch, type LidarBatch } from './protocol';

export type LinkState = 'demo' | 'connecting' | 'live' | 'retrying';

type Listener = (batch: LidarBatch) => void;

/** Fan-out of point batches. Kept outside React so the renderer never waits on state. */
export class LidarFeed {
  private listeners = new Set<Listener>();

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  emit(batch: LidarBatch): void {
    for (const listener of this.listeners) listener(batch);
  }
}

export const feed = new LidarFeed();

declare global {
  interface Window {
    lidar: {
      push: typeof pushPoints;
      reset: () => void;
    };
  }
}

export function pushPoints(...args: Parameters<typeof toBatch>): void {
  feed.emit(toBatch(...args));
}

window.lidar = {
  push: pushPoints,
  reset: () => feed.emit({ xyz: new Float32Array(0), reset: true }),
};

/** Opens a socket and keeps it open with capped exponential backoff. */
export function connectSocket(url: string, onState: (state: LinkState) => void): () => void {
  let socket: WebSocket | null = null;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let attempt = 0;
  let stopped = false;

  const open = () => {
    onState(attempt === 0 ? 'connecting' : 'retrying');
    try {
      socket = new WebSocket(url);
    } catch {
      schedule();
      return;
    }
    socket.binaryType = 'arraybuffer';
    socket.onopen = () => {
      attempt = 0;
      onState('live');
    };
    socket.onmessage = (event: MessageEvent<string | ArrayBuffer>) => {
      const batch = parseMessage(event.data);
      if (batch) feed.emit(batch);
    };
    socket.onclose = () => {
      if (!stopped) schedule();
    };
  };

  const schedule = () => {
    attempt += 1;
    onState('retrying');
    timer = setTimeout(open, Math.min(8000, 500 * 2 ** attempt));
  };

  open();
  return () => {
    stopped = true;
    clearTimeout(timer);
    socket?.close();
  };
}

const STORAGE_KEY = 'htn.lidarUrl';

export function initialSourceUrl(): string {
  const fromQuery = new URLSearchParams(location.search).get('lidar');
  if (fromQuery) return fromQuery;
  try {
    return localStorage.getItem(STORAGE_KEY) ?? import.meta.env.VITE_LIDAR_URL ?? '';
  } catch {
    return import.meta.env.VITE_LIDAR_URL ?? '';
  }
}

export function rememberSourceUrl(url: string): void {
  try {
    if (url) localStorage.setItem(STORAGE_KEY, url);
    else localStorage.removeItem(STORAGE_KEY);
  } catch {
    // Storage is a convenience only.
  }
}
