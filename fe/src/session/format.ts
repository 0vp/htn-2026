import type { LidarBatch } from '../lidar/protocol';
import type { Telemetry } from '../telemetry/types';

/**
 * `.htnrec` session file, little-endian:
 *   header  "HTNR" · u32 version (1) · f64 wall-clock start (ms since epoch)
 *   record  u8 kind · f64 t (ms since start) · u32 payload bytes · payload
 *     kind 1 LiDAR    u8 flags (1 reset, 2 pose) · 3 pad · f32×4 pose · f32 xyz…
 *     kind 2 telemetry, kind 3 command: UTF-8 JSON
 */

export const MAGIC = 'HTNR';
export const VERSION = 1;

export type SessionRecord =
  | { kind: 'lidar'; t: number; batch: LidarBatch }
  | { kind: 'telemetry'; t: number; sample: Telemetry }
  | { kind: 'command'; t: number; packet: unknown };

const KIND = { lidar: 1, telemetry: 2, command: 3 } as const;
const encoder = new TextEncoder();
const decoder = new TextDecoder();

export function encodeHeader(startedAt: number): ArrayBuffer {
  const buffer = new ArrayBuffer(16);
  const view = new DataView(buffer);
  encoder.encodeInto(MAGIC, new Uint8Array(buffer, 0, 4));
  view.setUint32(4, VERSION, true);
  view.setFloat64(8, startedAt, true);
  return buffer;
}

function frame(kind: number, t: number, payload: Uint8Array): ArrayBuffer {
  const buffer = new ArrayBuffer(13 + payload.byteLength);
  const view = new DataView(buffer);
  view.setUint8(0, kind);
  view.setFloat64(1, t, true);
  view.setUint32(9, payload.byteLength, true);
  new Uint8Array(buffer, 13).set(payload);
  return buffer;
}

export function encodeRecord(record: SessionRecord): ArrayBuffer {
  if (record.kind !== 'lidar') {
    const body = record.kind === 'telemetry' ? record.sample : record.packet;
    return frame(KIND[record.kind], record.t, encoder.encode(JSON.stringify(body)));
  }
  const { xyz, pose, reset } = record.batch;
  const payload = new Uint8Array(20 + xyz.byteLength);
  const view = new DataView(payload.buffer);
  view.setUint8(0, (reset ? 1 : 0) | (pose ? 2 : 0));
  if (pose) [pose.x, pose.y, pose.z, pose.yaw].forEach((v, i) => view.setFloat32(4 + i * 4, v, true));
  payload.set(new Uint8Array(xyz.buffer, xyz.byteOffset, xyz.byteLength), 20);
  return frame(KIND.lidar, record.t, payload);
}

export function decodeSession(buffer: ArrayBuffer): { startedAt: number; records: SessionRecord[] } {
  const view = new DataView(buffer);
  if (buffer.byteLength < 16 || decoder.decode(new Uint8Array(buffer, 0, 4)) !== MAGIC) {
    throw new Error('Not an .htnrec session file');
  }
  if (view.getUint32(4, true) !== VERSION) throw new Error('Unsupported session version');
  const startedAt = view.getFloat64(8, true);
  const records: SessionRecord[] = [];
  let offset = 16;

  while (offset + 13 <= buffer.byteLength) {
    const kind = view.getUint8(offset);
    const t = view.getFloat64(offset + 1, true);
    const length = view.getUint32(offset + 9, true);
    const start = offset + 13;
    if (start + length > buffer.byteLength) break; // Truncated tail: keep what is whole.
    offset = start + length;

    if (kind === KIND.lidar) {
      const flags = view.getUint8(start);
      const pose =
        flags & 2
          ? {
              x: view.getFloat32(start + 4, true),
              y: view.getFloat32(start + 8, true),
              z: view.getFloat32(start + 12, true),
              yaw: view.getFloat32(start + 16, true),
            }
          : undefined;
      // Copy so the Float32Array is aligned regardless of where the record sits.
      const xyz = new Float32Array(buffer.slice(start + 20, start + length));
      records.push({ kind: 'lidar', t, batch: { xyz, pose, reset: !!(flags & 1) } });
    } else {
      const json = JSON.parse(decoder.decode(new Uint8Array(buffer, start, length)));
      if (kind === KIND.telemetry) records.push({ kind: 'telemetry', t, sample: json as Telemetry });
      else if (kind === KIND.command) records.push({ kind: 'command', t, packet: json });
    }
  }
  return { startedAt, records };
}
