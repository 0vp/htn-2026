import { useSyncExternalStore } from 'react';
import { feed } from '../lidar/feed';
import { telemetryBus } from '../telemetry/bus';
import { encodeHeader, encodeRecord, type SessionRecord } from './format';

export type RecorderState = { recording: boolean; startedAt: number };

/** Updated per record without notifying React (LiDAR arrives at 30 Hz); the UI polls it. */
export const progress = { bytes: 0, lidarBatches: 0 };

/** Stop automatically before the in-memory buffer gets large enough to hurt the tab. */
const MAX_BYTES = 300 * 1024 * 1024;

let state: RecorderState = { recording: false, startedAt: 0 };
let chunks: ArrayBuffer[] = [];
let detach: (() => void) | null = null;
const listeners = new Set<() => void>();

const publish = (patch: Partial<RecorderState>) => {
  state = { ...state, ...patch };
  for (const listener of listeners) listener();
};

function append(record: SessionRecord) {
  if (!state.recording) return;
  const chunk = encodeRecord(record);
  chunks.push(chunk);
  progress.bytes += chunk.byteLength;
  if (record.kind === 'lidar') progress.lidarBatches += 1;
  if (progress.bytes > MAX_BYTES) stopRecording();
}

export function startRecording() {
  if (state.recording) return;
  const startedAt = Date.now();
  const t0 = performance.now();
  const t = () => performance.now() - t0;
  chunks = [encodeHeader(startedAt)];
  progress.bytes = 16;
  progress.lidarBatches = 0;
  publish({ recording: true, startedAt });

  const offLidar = feed.subscribe((batch, origin) => {
    if (origin === 'live') append({ kind: 'lidar', t: t(), batch });
  });
  const offTelemetry = telemetryBus.subscribe((sample, origin) => {
    if (origin !== 'replay') append({ kind: 'telemetry', t: t(), sample });
  });
  const offCommands = commandTap.add((packet) => append({ kind: 'command', t: t(), packet }));
  detach = () => {
    offLidar();
    offTelemetry();
    offCommands();
  };
}

export function stopRecording() {
  if (!state.recording) return;
  detach?.();
  detach = null;
  publish({ recording: false });

  const stamp = new Date(state.startedAt).toISOString().slice(0, 19).replace(/[:T]/g, '-');
  const url = URL.createObjectURL(new Blob(chunks, { type: 'application/octet-stream' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = `htn-session-${stamp}.htnrec`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
  chunks = [];
}

/** The command link reports every packet it sends here. */
export const commandTap = {
  listeners: new Set<(packet: unknown) => void>(),
  add(listener: (packet: unknown) => void) {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  },
  emit(packet: unknown) {
    for (const listener of this.listeners) listener(packet);
  },
};

export const recorder = {
  get: () => state,
  subscribe(listener: () => void) {
    listeners.add(listener);
    return () => listeners.delete(listener);
  },
};

export function useRecorder(): RecorderState {
  return useSyncExternalStore(recorder.subscribe, recorder.get);
}
