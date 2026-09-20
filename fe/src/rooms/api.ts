export type Room = {
  room_id: string;
  name: string;
  created_at: number;
  closed: boolean;
  frames_stored: number;
  devices: Array<{ device_id: string; name: string; joined_at: number }>;
};

export type GeographicAnchor = {
  latitude: number;
  longitude: number;
  horizontal_accuracy_m: number;
  heading?: { degrees: number; reference_direction_world: [number, number, number] };
};

export type ProcessingStatus = {
  room_id: string;
  geography?: { anchors: Array<{ anchor: GeographicAnchor }> };
  received: number;
  mapped: number;
  pending: number;
  awaiting_alignment: number;
  error: { detail: string; updated_at: number } | null;
  map: ({ revision: number; updated_at: number } & Record<string, unknown>) | null;
};

const configuredBase = (import.meta.env?.VITE_API_URL as string | undefined)?.replace(/\/$/, '')
  ?? (import.meta.env?.DEV ? '' : 'https://qasim-test.35-253-10-71.sslip.io');

export function apiUrl(path: string): string {
  return `${configuredBase}${path}`;
}

export async function listRooms(signal?: AbortSignal): Promise<Room[]> {
  const response = await fetch(apiUrl('/v1/rooms'), { signal });
  if (!response.ok) throw new Error(`Backend returned ${response.status}`);
  const payload = (await response.json()) as { rooms: Room[] };
  return payload.rooms;
}

export type RoomObject = {
  object_id: string;
  label: string;
  center_m: [number, number, number];
  size_m: [number, number, number];
  yaw_rad: number;
  confirmed_views?: number;
  evidence_digest?: string;
  orientation_status?: string;
  visibility?: string;
};

export type RoomScene = { revision: number; objects: RoomObject[]; mesh: ArrayBuffer };

export async function fetchScene(roomId: string, signal?: AbortSignal): Promise<RoomScene> {
  const path = `/v1/rooms/${encodeURIComponent(roomId)}`;
  const response = await fetch(apiUrl(`${path}/map`), { signal, cache: 'no-store' });
  if (!response.ok) throw new Error(`Map returned ${response.status}`);
  const snapshot = await response.json() as { revision: number; objects: RoomObject[] };
  const mesh = await fetch(apiUrl(`${path}/mesh.glb`), { signal, cache: 'no-store' });
  if (!mesh.ok) throw new Error(`Mesh returned ${mesh.status}`);
  if (mesh.headers.get('ETag') !== `"${roomId}-${snapshot.revision}"`) {
    throw new Error('Map changed during download; retrying');
  }
  return { ...snapshot, mesh: await mesh.arrayBuffer() };
}

export function evidenceUrl(roomId: string, object: RoomObject): string {
  return apiUrl(`/v1/rooms/${encodeURIComponent(roomId)}/objects/${encodeURIComponent(object.object_id)}/evidence.jpg?version=${encodeURIComponent(object.evidence_digest ?? '')}`);
}
