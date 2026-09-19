import { useSyncExternalStore } from 'react';
import { feed } from '../lidar/feed';
import { telemetryBus } from '../telemetry/bus';
import { decodeSession, type SessionRecord } from './format';

export type PlayerState = {
  name: string;
  startedAt: number;
  duration: number;
  position: number;
  playing: boolean;
  speed: number;
  error: string;
} | null;

let state: PlayerState = null;
let records: SessionRecord[] = [];
let cursor = 0;
let timer: ReturnType<typeof setInterval> | undefined;
let lastTick = 0;
const listeners = new Set<() => void>();

const publish = (next: PlayerState) => {
  state = next;
  for (const listener of listeners) listener();
};

/** Replays records up to `position`. Commands are shown in the file but never re-sent. */
function drain(position: number) {
  while (cursor < records.length && records[cursor].t <= position) {
    const record = records[cursor++];
    if (record.kind === 'lidar') feed.emit(record.batch, 'replay');
    else if (record.kind === 'telemetry') telemetryBus.emit(record.sample, 'replay');
  }
}

function tick() {
  if (!state?.playing) return;
  const now = performance.now();
  const position = Math.min(state.duration, state.position + (now - lastTick) * state.speed);
  lastTick = now;
  drain(position);
  publish({ ...state, position, playing: position < state.duration });
}

export async function openSession(file: File) {
  try {
    const session = decodeSession(await file.arrayBuffer());
    closeSession();
    records = session.records;
    cursor = 0;
    feed.setReplaying(true);
    telemetryBus.setReplaying(true);
    publish({
      name: file.name,
      startedAt: session.startedAt,
      duration: records.at(-1)?.t ?? 0,
      position: 0,
      playing: false,
      speed: 1,
      error: '',
    });
    timer = setInterval(tick, 33);
    play();
  } catch (error) {
    publish({
      name: file.name,
      startedAt: 0,
      duration: 0,
      position: 0,
      playing: false,
      speed: 1,
      error: error instanceof Error ? error.message : 'Could not read session',
    });
  }
}

export function play() {
  if (!state || state.error) return;
  if (state.position >= state.duration) seek(0);
  lastTick = performance.now();
  publish({ ...state!, playing: true });
}

export function pause() {
  if (state) publish({ ...state, playing: false });
}

export function setSpeed(speed: number) {
  if (state) publish({ ...state, speed });
}

/** Rebuilds the cloud from the start so seeking backwards shows the right map. */
export function seek(position: number) {
  if (!state) return;
  feed.emit({ xyz: new Float32Array(0), reset: true }, 'replay');
  cursor = 0;
  drain(position);
  lastTick = performance.now();
  publish({ ...state, position });
}

export function closeSession() {
  clearInterval(timer);
  records = [];
  cursor = 0;
  if (state) {
    feed.setReplaying(false);
    telemetryBus.setReplaying(false);
  }
  publish(null);
}

export function usePlayer(): PlayerState {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => state,
  );
}
