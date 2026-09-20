import { toBatch, type LidarBatch } from './protocol';

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
