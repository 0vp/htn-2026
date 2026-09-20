import { useEffect, useState } from 'react';
import { apiUrl, fetchScene, listRooms, type RoomScene, type ProcessingStatus, type Room } from './api';

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
  const [scene, setScene] = useState<RoomScene | null>(null);
  const [link, setLink] = useState<RoomLink>('connecting');
  const [error, setError] = useState<string | null>(null);

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
    setStatus(null);
    setScene(null);
    if (!roomId) return;
    setLink('connecting');
    const controller = new AbortController();
    let wanted: number | null = null;
    let loaded: number | null = null;
    let loading = false;
    const refresh = async () => {
      if (loading || wanted === null || wanted === loaded) return;
      loading = true;
      try {
        const next = await fetchScene(roomId, controller.signal);
        if (!controller.signal.aborted) {
          loaded = next.revision;
          setScene(next);
          setError(null);
        }
      } catch (cause) {
        if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : 'Map unavailable');
      } finally {
        loading = false;
      }
    };
    let events: EventSource;
    let reconnect = 0;
    const connect = () => {
      events = new EventSource(apiUrl(`/v1/rooms/${roomId}/events`));
      events.addEventListener('processing', (event) => {
        if (controller.signal.aborted) return;
        try {
          const next = JSON.parse((event as MessageEvent<string>).data) as ProcessingStatus;
          setStatus(next);
          setLink(next.map ? 'live' : 'waiting');
          setError(next.error?.detail ?? null);
          wanted = next.map?.revision ?? null;
          if (!next.map) {
            // The room was reset: revisions restart, so forget the one already shown.
            loaded = null;
            setScene(null);
          }
          void refresh();
        } catch {
          setError('Invalid room update');
        }
      });
      events.onerror = () => {
        if (controller.signal.aborted) return;
        setLink('offline');
        // A refused stream (a 502 while the backend restarts) closes for good; the browser
        // only retries dropped ones, so reopen it ourselves.
        if (events.readyState !== EventSource.CLOSED) return;
        window.clearTimeout(reconnect);
        reconnect = window.setTimeout(connect, 3000);
      };
    };
    connect();
    const retry = window.setInterval(() => void refresh(), 1000);
    return () => {
      controller.abort();
      window.clearTimeout(reconnect);
      events.close();
      window.clearInterval(retry);
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

  return { rooms, roomId, setRoomId, status, scene, link, error };
}
