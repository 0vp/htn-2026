import { useEffect, useState } from 'react';
import { listRooms, type Room } from './api';

export type RoomList = {
  rooms: Room[];
  /** null until the first request settles. */
  online: boolean | null;
};

/** Polls the capture API for rooms so new phone sessions show up without a reload. */
export function useRooms(intervalMs = 5000): RoomList {
  const [state, setState] = useState<RoomList>({ rooms: [], online: null });

  useEffect(() => {
    const abort = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const load = async () => {
      try {
        const rooms = await listRooms(abort.signal);
        setState({ rooms, online: true });
      } catch {
        if (abort.signal.aborted) return;
        setState((s) => ({ ...s, online: false }));
      }
      timer = setTimeout(load, intervalMs);
    };
    void load();
    return () => {
      abort.abort();
      clearTimeout(timer);
    };
  }, [intervalMs]);

  return state;
}

/** Newest open room that already holds frames, else the newest open room. */
export function defaultRoom(rooms: Room[]): Room | undefined {
  const open = rooms.filter((r) => !r.closed);
  return open.find((r) => r.frames_stored > 0) ?? open[0];
}

type Props = {
  list: RoomList;
  value: string | null;
  onPick: (roomId: string | null) => void;
};

export function RoomPicker({ list, value, onPick }: Props) {
  const known = list.rooms.some((r) => r.room_id === value);
  return (
    <label className="flex items-center gap-2">
      <span className="flex items-center gap-2 text-blue-soft">
        <span className={`size-2 ${list.online ? 'bg-white' : list.online === false ? 'bg-signal' : 'bg-blue-soft'}`} />
        Room
      </span>
      <select
        value={value ?? ''}
        onChange={(event) => onPick(event.target.value || null)}
        disabled={!list.online && !value}
        className="hairline-light border bg-blue px-2 py-1 font-mono text-[11px] tracking-normal normal-case text-white focus:outline-none"
      >
        <option value="">{list.online === false ? 'API offline' : 'None'}</option>
        {value && !known && <option value={value}>{value}</option>}
        {list.rooms.map((room) => (
          <option key={room.room_id} value={room.room_id}>
            {room.room_id} · {room.frames_stored} frames{room.closed ? ' · closed' : ''}
          </option>
        ))}
      </select>
    </label>
  );
}
