import { feed, type LinkState } from '../lidar/feed';
import { framePayload, listFrames, type FrameSummary } from './api';
import { decodeFrame, toBatch } from './r3d';

/** Frames replayed on connect; about what the renderer's point capacity holds. */
const REPLAY = 40;
const POLL_MS = 500;
const PARALLEL = 4;

/** Source string for a room, accepted by the LiDAR source field alongside ws:// URLs. */
export const roomSource = (roomId: string) => `room:${roomId}`;

export function parseRoomSource(source: string): string | null {
  const match = /^room:([A-Fa-f0-9]{8})$/.exec(source.trim());
  return match ? match[1].toUpperCase() : null;
}

/**
 * Follows a capture room: replays its most recent frames, then polls for new ones,
 * back-projecting each depth frame into the shared point feed in sequence order.
 */
export function connectRoom(roomId: string, onState: (state: LinkState) => void): () => void {
  const abort = new AbortController();
  const { signal } = abort;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let cursor = 0;
  let failures = 0;
  let session = '';

  const emit = (summary: FrameSummary, payload: ArrayBuffer) =>
    decodeFrame(payload).then((frame) => {
      // A new ARKit session or epoch has a new world origin, so earlier points no longer line up.
      const key = `${summary.device_id}/${frame.header.session_id}/${frame.header.epoch}`;
      const batch = toBatch(frame);
      feed.emit({ ...batch, reset: key !== session });
      session = key;
    });

  const drain = async (frames: FrameSummary[]) => {
    for (let i = 0; i < frames.length; i += PARALLEL) {
      const chunk = frames.slice(i, i + PARALLEL);
      const payloads = await Promise.all(chunk.map((f) => framePayload(roomId, f.sequence, signal)));
      for (let j = 0; j < chunk.length; j++) {
        try {
          await emit(chunk[j], payloads[j]);
        } catch (error) {
          console.warn(`[backend] skipped frame ${chunk[j].sequence}`, error);
        }
      }
    }
  };

  /** Newest unseen frames, capped at REPLAY so a long backlog does not delay live frames. */
  const pending = async (): Promise<{ frames: FrameSummary[]; next: number }> => {
    const frames: FrameSummary[] = [];
    let next = cursor;
    for (;;) {
      const page = await listFrames(roomId, next, 200, signal);
      frames.push(...page.frames);
      if (frames.length > REPLAY) frames.splice(0, frames.length - REPLAY);
      next = page.next_after;
      if (page.frames.length < 200) return { frames, next };
    }
  };

  const tick = async () => {
    try {
      const { frames, next } = await pending();
      await drain(frames);
      cursor = next;
      failures = 0;
      onState('live');
    } catch (error) {
      if (signal.aborted) return;
      failures += 1;
      onState('retrying');
      console.warn('[backend] room poll failed', error);
    }
    if (!signal.aborted) timer = setTimeout(tick, Math.min(8000, POLL_MS * 2 ** failures));
  };

  onState('connecting');
  void tick();
  return () => {
    abort.abort();
    clearTimeout(timer);
  };
}
