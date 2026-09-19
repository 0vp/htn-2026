import { useEffect, useRef, useState } from 'react';
import { apiUrl, fetchMesh, listRooms, type ProcessingStatus, type Room } from './api';

export type RoomLink = 'connecting' | 'live' | 'waiting' | 'offline';

const STORAGE_KEY = 'htn.roomId';

function initialRoomId(): string {
  const query = new URLSearchParams(location.search).get('room');
  if (query) return query;
  try {
    return localStorage.getItem(STORAGE_KEY) ?? '';
  } catch {
    return '';
  }
}

export function useRoomStream() {
  const [rooms, setRooms] = useState<Room[]>([]);
  const [roomId, setRoomIdState] = useState(initialRoomId);
  const [status, setStatus] = useState<ProcessingStatus | null>(null);
  const [mesh, setMesh] = useState<ArrayBuffer | null>(null);
  const [link, setLink] = useState<RoomLink>('connecting');
  const [error, setError] = useState<string | null>(null);
  const revision = useRef<number | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    const refresh = async () => {
      try {
        const next = await listRooms(controller.signal);
        setRooms(next);
        setError(null);
        setRoomIdState((current) => {
          if (current && next.some((room) => room.room_id === current)) return current;
          return next.find((room) => !room.closed)?.room_id ?? next[0]?.room_id ?? '';
        });
        if (!next.length) setLink('waiting');
      } catch (cause) {
        if (!controller.signal.aborted) {
          setError(cause instanceof Error ? cause.message : 'Backend unavailable');
          setLink('offline');
        }
      }
    };
    void refresh();
    const timer = window.setInterval(refresh, 5000);
    return () => {
      controller.abort();
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    revision.current = null;
    setStatus(null);
    setMesh(null);
    if (!roomId) return;
    setLink('connecting');
    const controller = new AbortController();
    const events = new EventSource(apiUrl(`/v1/rooms/${roomId}/events`));
    events.addEventListener('processing', (event) => {
      const next = JSON.parse((event as MessageEvent<string>).data) as ProcessingStatus;
      setStatus(next);
      setLink(next.map ? 'live' : 'waiting');
      setError(next.error?.detail ?? null);
      const nextRevision = next.map?.revision ?? null;
      if (nextRevision === null || nextRevision === revision.current) return;
      revision.current = nextRevision;
      void fetchMesh(roomId, controller.signal)
        .then(setMesh)
        .catch((cause: unknown) => {
          if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : 'Map unavailable');
        });
    });
    events.onerror = () => setLink('offline');
    return () => {
      controller.abort();
      events.close();
    };
  }, [roomId]);

  const setRoomId = (next: string) => {
    setRoomIdState(next);
    try {
      if (next) localStorage.setItem(STORAGE_KEY, next);
      else localStorage.removeItem(STORAGE_KEY);
    } catch {
      // Persistence is optional.
    }
  };

  return { rooms, roomId, setRoomId, status, mesh, link, error };
}
