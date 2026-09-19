/**
 * Client for the HTN capture API (`be`). Phones join a room and upload R3D frames;
 * the dashboard lists rooms and replays their frames.
 *
 * The API sends no CORS headers, so in development the dashboard calls it through
 * the Vite proxy at `/api` (see vite.config.ts). Set `VITE_API_URL` to call a
 * CORS-enabled deployment directly.
 */

export const API_BASE = (import.meta.env.VITE_API_URL ?? '/api').replace(/\/$/, '');

export type Device = { device_id: string; name: string; joined_at: number };

export type Room = {
  room_id: string;
  name: string;
  created_at: number;
  closed: boolean;
  frames_stored: number;
  bytes_stored: number;
  devices: Device[];
};

/** Mirrors `FrameHeader` in be/src/htn_backend/capture/frame.py. */
export type FrameHeader = {
  version: 1;
  session_id: string;
  epoch: number;
  frame_id: number;
  timestamp_s: number;
  tracking: 'normal' | 'limited' | 'unavailable';
  camera_convention: 'arkit' | 'opencv';
  depth_width: number;
  depth_height: number;
  rgb_width: number;
  rgb_height: number;
  rgb_bytes: number;
  fx: number;
  fy: number;
  cx: number;
  cy: number;
  /** Column-major T_world_camera in metres. */
  camera_to_world: number[];
};

export type FrameSummary = {
  sequence: number;
  device_id: string;
  header: FrameHeader;
  bytes: number;
  received_at: number;
  sha256: string;
};

export type FramePage = { frames: FrameSummary[]; next_after: number };

export type Health = { status: string; version: string; protocols: string[] };

async function request(path: string, signal?: AbortSignal): Promise<Response> {
  const response = await fetch(`${API_BASE}${path}`, { signal, cache: 'no-store' });
  if (!response.ok) throw new Error(`${path} → HTTP ${response.status}`);
  return response;
}

export async function health(signal?: AbortSignal): Promise<Health> {
  return (await request('/health', signal)).json() as Promise<Health>;
}

export async function listRooms(signal?: AbortSignal): Promise<Room[]> {
  const body = (await (await request('/v1/rooms', signal)).json()) as { rooms: Room[] };
  return body.rooms;
}

export async function listFrames(roomId: string, after: number, limit = 100, signal?: AbortSignal): Promise<FramePage> {
  const query = new URLSearchParams({ after: String(after), limit: String(limit) });
  return (await request(`/v1/rooms/${roomId}/frames?${query}`, signal)).json() as Promise<FramePage>;
}

export async function framePayload(roomId: string, sequence: number, signal?: AbortSignal): Promise<ArrayBuffer> {
  return (await request(`/v1/rooms/${roomId}/frames/${sequence}`, signal)).arrayBuffer();
}

export const ROOM_ID = /^[A-F0-9]{8}$/;
