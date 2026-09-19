/**
 * LiDAR point stream protocol.
 *
 * Coordinates are metres in a right-handed, Y-up world frame (the ARKit convention).
 * Send either message form over a WebSocket, or call `window.lidar.push(...)`.
 *
 * JSON text message:
 *   { "type": "points", "points": [[x, y, z], ...] }         nested triplets
 *   { "type": "points", "xyz": [x, y, z, x, y, z, ...] }      flat triplets
 *   Optional fields on either form:
 *     "pose":  [x, y, z, yaw]          robot pose for the marker and follow camera;
 *                                      yaw is radians about +Y, and 0 faces +X
 *     "reset": true                    clear the cloud before adding these points
 *   { "type": "pose", "pose": [x, y, z, yaw] }                 pose only
 *   { "type": "reset" }                                         clear only
 *
 * Binary message: little-endian float32 x, y, z triplets with no header.
 */

export type Pose = { x: number; y: number; z: number; yaw: number };

export type LidarBatch = {
  xyz: Float32Array;
  pose?: Pose;
  reset?: boolean;
};

type JsonMessage = {
  type?: string;
  points?: unknown;
  xyz?: unknown;
  pose?: unknown;
  reset?: unknown;
};

const finite = (value: unknown): value is number =>
  typeof value === 'number' && Number.isFinite(value);

function parsePose(value: unknown): Pose | undefined {
  if (!Array.isArray(value) || value.length < 3 || !value.slice(0, 4).every(finite)) {
    return undefined;
  }
  const [x, y, z, yaw = 0] = value as number[];
  return { x, y, z, yaw };
}

function parseTriplets(message: JsonMessage): Float32Array {
  if (Array.isArray(message.xyz)) {
    const flat = message.xyz;
    const usable = flat.length - (flat.length % 3);
    const out = new Float32Array(usable);
    for (let i = 0; i < usable; i++) out[i] = finite(flat[i]) ? flat[i] : 0;
    return out;
  }
  if (Array.isArray(message.points)) {
    const rows = message.points as unknown[];
    const out = new Float32Array(rows.length * 3);
    let n = 0;
    for (const row of rows) {
      if (Array.isArray(row) && finite(row[0]) && finite(row[1]) && finite(row[2])) {
        out[n++] = row[0];
        out[n++] = row[1];
        out[n++] = row[2];
      }
    }
    return out.subarray(0, n);
  }
  return new Float32Array(0);
}

/** Returns null for messages that are not part of the protocol. */
export function parseMessage(data: string | ArrayBuffer): LidarBatch | null {
  if (data instanceof ArrayBuffer) {
    const count = Math.floor(data.byteLength / 12) * 3;
    return { xyz: new Float32Array(data, 0, count) };
  }
  let message: JsonMessage;
  try {
    message = JSON.parse(data) as JsonMessage;
  } catch {
    return null;
  }
  switch (message.type) {
    case 'points':
      return { xyz: parseTriplets(message), pose: parsePose(message.pose), reset: message.reset === true };
    case 'pose':
      return { xyz: new Float32Array(0), pose: parsePose(message.pose) };
    case 'reset':
      return { xyz: new Float32Array(0), reset: true };
    default:
      return null;
  }
}

/** Accepts the same shapes as the WebSocket for console and in-app callers. */
export function toBatch(
  points: ArrayLike<number> | ArrayLike<ArrayLike<number>>,
  options: { pose?: [number, number, number, number?]; reset?: boolean } = {},
): LidarBatch {
  const first = points.length ? points[0] : undefined;
  const message: JsonMessage =
    typeof first === 'object' ? { points: Array.from(points as ArrayLike<ArrayLike<number>>, (p) => Array.from(p)) } : { xyz: Array.from(points as ArrayLike<number>) };
  return { xyz: parseTriplets(message), pose: parsePose(options.pose), reset: options.reset };
}
