export type Room = {
  room_id: string;
  name: string;
  created_at: number;
  closed: boolean;
  frames_stored: number;
  devices: Array<{ device_id: string; name: string; joined_at: number }>;
};

export type ProcessingStatus = {
  room_id: string;
  received: number;
  mapped: number;
  pending: number;
  awaiting_alignment: number;
  error: { detail: string; updated_at: number } | null;
  map: ({ revision: number; updated_at: number } & Record<string, unknown>) | null;
};

const configuredBase = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? '';

export function apiUrl(path: string): string {
  return `${configuredBase}${path}`;
}

export async function listRooms(signal?: AbortSignal): Promise<Room[]> {
  const response = await fetch(apiUrl('/v1/rooms'), { signal });
  if (!response.ok) throw new Error(`Backend returned ${response.status}`);
  const payload = (await response.json()) as { rooms: Room[] };
  return payload.rooms;
}

export async function fetchMesh(roomId: string, signal?: AbortSignal): Promise<ArrayBuffer> {
  const response = await fetch(apiUrl(`/v1/rooms/${roomId}/mesh.glb`), { signal });
  if (!response.ok) throw new Error(`Map returned ${response.status}`);
  return response.arrayBuffer();
}
