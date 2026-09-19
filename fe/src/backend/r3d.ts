/**
 * Browser decoder for the capture wire format in be/src/htn_backend/capture/codec.py.
 *
 *   R3D1  "R3D1" u32 headerLen, JSON header, float32 depth[w*h], uint8 confidence[w*h], JPEG
 *   R3Z1  "R3Z1" u32 expandedLen, raw-deflate(R3D1 frame)
 *   R3S1  as R3Z1, but the depth bytes are shuffled into four byte planes before deflate
 */
import type { LidarBatch, Pose } from '../lidar/protocol';
import type { FrameHeader } from './api';

export type DecodedFrame = {
  header: FrameHeader;
  depth: Float32Array;
  confidence: Uint8Array;
};

const ascii = (bytes: Uint8Array) => String.fromCharCode(bytes[0], bytes[1], bytes[2], bytes[3]);

async function inflateRaw(data: Uint8Array<ArrayBuffer>, expected: number): Promise<Uint8Array<ArrayBuffer>> {
  const stream = new Blob([data]).stream().pipeThrough(new DecompressionStream('deflate-raw'));
  const out = new Uint8Array(await new Response(stream).arrayBuffer());
  if (out.length !== expected) throw new Error('Compressed frame size mismatch');
  return out;
}

export async function decodeFrame(buffer: ArrayBuffer): Promise<DecodedFrame> {
  let bytes: Uint8Array<ArrayBuffer> = new Uint8Array(buffer);
  const magic = ascii(bytes);
  const shuffled = magic === 'R3S1';
  if (magic === 'R3Z1' || shuffled) {
    const expected = new DataView(buffer).getUint32(4, true);
    bytes = await inflateRaw(bytes.subarray(8), expected);
  }
  if (ascii(bytes) !== 'R3D1') throw new Error(`Unknown frame magic ${magic}`);

  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const headerLen = view.getUint32(4, true);
  const header = JSON.parse(new TextDecoder().decode(bytes.subarray(8, 8 + headerLen))) as FrameHeader;
  const pixels = header.depth_width * header.depth_height;
  const offset = 8 + headerLen;
  if (bytes.length < offset + pixels * 5) throw new Error('Truncated frame');

  // Copy so the float view is 4-byte aligned whatever the header length was.
  const depthBytes = new Uint8Array(pixels * 4);
  const packed = bytes.subarray(offset, offset + pixels * 4);
  if (shuffled) {
    for (let i = 0; i < pixels; i++) {
      depthBytes[i * 4] = packed[i];
      depthBytes[i * 4 + 1] = packed[pixels + i];
      depthBytes[i * 4 + 2] = packed[pixels * 2 + i];
      depthBytes[i * 4 + 3] = packed[pixels * 3 + i];
    }
  } else {
    depthBytes.set(packed);
  }
  return {
    header,
    depth: new Float32Array(depthBytes.buffer),
    confidence: bytes.slice(offset + pixels * 4, offset + pixels * 5),
  };
}

export type ProjectOptions = {
  /** Sample every `stride`-th pixel in both directions. */
  stride: number;
  /** Minimum ARKit confidence: 0 low, 1 medium, 2 high. */
  minConfidence: number;
  maxDepthM: number;
};

export const DEFAULT_PROJECT: ProjectOptions = { stride: 2, minConfidence: 1, maxDepthM: 5 };

/** Camera position and heading about +Y (0 faces +X), matching the LiDAR protocol pose. */
export function cameraPose(header: FrameHeader): Pose {
  const m = header.camera_to_world;
  // The camera looks down -Z in ARKit and +Z in OpenCV; column 2 is the camera Z axis.
  const sign = header.camera_convention === 'arkit' ? -1 : 1;
  const fx = sign * m[8];
  const fz = sign * m[10];
  return { x: m[12], y: m[13], z: m[14], yaw: Math.atan2(-fz, fx) };
}

/** Back-projects a depth frame into world-space points. */
export function toBatch(frame: DecodedFrame, options: ProjectOptions = DEFAULT_PROJECT): LidarBatch {
  const { header, depth, confidence } = frame;
  const { depth_width: w, depth_height: h, fx, fy, cx, cy } = header;
  const m = header.camera_to_world;
  const arkit = header.camera_convention === 'arkit';
  const step = Math.max(1, Math.floor(options.stride));
  const out = new Float32Array(Math.ceil(w / step) * Math.ceil(h / step) * 3);
  let n = 0;

  for (let v = 0; v < h; v += step) {
    for (let u = 0; u < w; u += step) {
      const i = v * w + u;
      const d = depth[i];
      if (!(d > 0.05 && d <= options.maxDepthM) || confidence[i] < options.minConfidence) continue;
      const x = ((u - cx) * d) / fx;
      const yDown = ((v - cy) * d) / fy;
      // ARKit cameras are x right, y up, looking down -Z; OpenCV is x right, y down, +Z.
      const y = arkit ? -yDown : yDown;
      const z = arkit ? -d : d;
      out[n++] = m[0] * x + m[4] * y + m[8] * z + m[12];
      out[n++] = m[1] * x + m[5] * y + m[9] * z + m[13];
      out[n++] = m[2] * x + m[6] * y + m[10] * z + m[14];
    }
  }
  return { xyz: out.subarray(0, n), pose: cameraPose(header) };
}
