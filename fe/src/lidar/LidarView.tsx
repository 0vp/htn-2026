import { useEffect, useMemo, useRef, useState } from 'react';
import { resetRoom, type RoomScene } from '../rooms/api';
import { ObjectPanel } from '../objects/ObjectPanel';
import { bestAnchor } from '../geo/anchor';
import { feed } from './feed';
import { LidarRenderer, type CloudStats, type ColorMode } from './renderer';
import { Segmented, TextButton } from '../ui/controls';
import { useRoomStream, type RoomLink } from '../rooms/useRoomStream';

const compact = (n: number) =>
  n >= 1_000_000 ? `${(n / 1_000_000).toFixed(2)}M` : n >= 1000 ? `${(n / 1000).toFixed(1)}K` : `${n}`;

const LINK_LABEL: Record<RoomLink, string> = {
  connecting: 'Connecting to backend',
  live: 'Live room map',
  waiting: 'Waiting for map',
  offline: 'Backend offline',
};

export function LidarView() {
  const host = useRef<HTMLDivElement>(null);
  const renderer = useRef<LidarRenderer | null>(null);
  const [color, setColor] = useState<ColorMode>('height');
  const [stats, setStats] = useState<CloudStats | null>(null);
  const [displayedScene, setDisplayedScene] = useState<RoomScene | null>(null);
  const [selectedObject, setSelectedObject] = useState<string | null>(null);
  const [renderError, setRenderError] = useState<string | null>(null);
  const room = useRoomStream();

  useEffect(() => {
    if (!host.current) return;
    const instance = new LidarRenderer(host.current);
    renderer.current = instance;
    const unsubscribe = feed.subscribe((batch) => instance.ingest(batch));
    const poll = setInterval(() => setStats(instance.stats()), 250);
    return () => {
      clearInterval(poll);
      unsubscribe();
      instance.dispose();
      renderer.current = null;
    };
  }, []);

  const anchor = useMemo(
    () => bestAnchor(room.status),
    // The fix only matters to a few metres; ignore status churn that leaves it unchanged.
    [JSON.stringify(room.status?.geography?.anchors.map((a) => [a.anchor.latitude, a.anchor.longitude]))],
  );
  // Indoor fixes rarely carry a compass heading, so north is hand-set per room and remembered.
  const northKey = `north:${room.roomId}`;
  const [northDegrees, setNorthDegrees] = useState(0);
  useEffect(() => {
    let saved: string | null = null;
    try { saved = localStorage.getItem(northKey); } catch { /* Storage unavailable. */ }
    setNorthDegrees(saved !== null ? +saved : Math.round((((anchor?.north ?? 0) * 180) / Math.PI + 360) % 360));
  }, [northKey, anchor?.north]);
  useEffect(() => renderer.current?.setGeo(anchor), [anchor]);
  useEffect(() => renderer.current?.setNorth((northDegrees * Math.PI) / 180), [northDegrees]);

  useEffect(() => {
    renderer.current?.clearRoomMesh();
    setDisplayedScene(null);
    setSelectedObject(null);
    setRenderError(null);
  }, [room.roomId]);

  useEffect(() => {
    let cancelled = false;
    if (room.scene) {
      void renderer.current?.loadRoomScene(room.scene).then(() => {
        if (!cancelled) {
          setDisplayedScene(room.scene);
          setRenderError(null);
        }
      }).catch((error: unknown) => {
        if (!cancelled) setRenderError(error instanceof Error ? error.message : 'Scene unavailable');
      });
    }
    return () => {
      cancelled = true;
      renderer.current?.cancelSceneLoad();
    };
  }, [room.scene]);

  useEffect(() => {
    if (room.scene) return;
    renderer.current?.clearRoomMesh();
    setDisplayedScene(null);
  }, [room.scene]);

  // Wiping the server's room is permanent, so the button must be pressed twice.
  const [resetting, setResetting] = useState<'idle' | 'confirm' | 'busy'>('idle');
  useEffect(() => {
    if (resetting !== 'confirm') return;
    const timer = window.setTimeout(() => setResetting('idle'), 4000);
    return () => window.clearTimeout(timer);
  }, [resetting]);
  const reset = () => {
    if (resetting === 'idle') return setResetting('confirm');
    if (resetting === 'busy') return;
    setResetting('busy');
    resetRoom(room.roomId)
      .then(() => setRenderError(null))
      .catch((error: unknown) => setRenderError(error instanceof Error ? error.message : 'Reset failed'))
      .finally(() => setResetting('idle'));
  };

  useEffect(() => renderer.current?.selectObject(selectedObject), [selectedObject]);
  useEffect(() => renderer.current?.setColorMode(color), [color]);

  const pose = stats?.pose;
  return (
    <section id="lidar" className="relative bg-blue text-white">
      <div ref={host} className="h-screen min-h-[560px] w-full cursor-grab active:cursor-grabbing" />

      <div className="pointer-events-none absolute inset-x-0 top-0 flex flex-wrap items-start justify-between gap-6 p-6 sm:p-9">
        <div>
          <p className="label text-blue-soft">Granny Waymo · LiDAR</p>
          <h1 className="mt-3 font-pixel text-5xl leading-none sm:text-6xl">Room scan</h1>
        </div>
        <div className="pointer-events-auto flex flex-col items-end gap-2">
          {!room.scene && <Segmented
            tone="dark"
            value={color}
            onChange={setColor}
            options={[
              ['height', 'Height'],
              ['age', 'Age'],
            ]}
          />}
          {anchor && (
            <label className="label flex items-center gap-3 text-blue-soft" title={`${anchor.latitude.toFixed(5)}, ${anchor.longitude.toFixed(5)} · © OpenStreetMap`}>
              Map north {northDegrees}°
              <input
                type="range"
                min={0}
                max={359}
                value={northDegrees}
                onChange={(event) => {
                  setNorthDegrees(+event.target.value);
                  try { localStorage.setItem(northKey, event.target.value); } catch { /* Storage unavailable. */ }
                }}
                className="w-36 accent-white"
              />
            </label>
          )}
          {!room.scene && <TextButton tone="dark" onClick={() => renderer.current?.clear()}>
            Clear
          </TextButton>}
        </div>
      </div>

      <ObjectPanel roomId={room.roomId} objects={displayedScene?.objects ?? []}
        selected={selectedObject} onSelect={setSelectedObject} />
      {renderError && <p role="alert" className="absolute left-6 top-36 bg-blue p-2">{renderError}</p>}

      <div className="absolute inset-x-0 bottom-0 px-6 sm:px-9">
        <div className="hairline-light flex flex-wrap items-center gap-x-6 gap-y-2 border-b py-4 label text-white/85">
          <span className="flex items-center gap-2">
            <span className={`size-2 ${room.link === 'live' ? 'bg-white' : room.link === 'waiting' ? 'bg-blue-soft' : 'bg-signal'}`} />
            {LINK_LABEL[room.link]}
          </span>
          <span>{room.status ? `${room.status.mapped}/${room.status.received} frames mapped` : 'No frames'}</span>
          <span>{compact(stats?.points ?? 0)} vertices · {stats?.fps ?? 0} fps</span>
          <span>
            {pose ? `x ${pose.x.toFixed(2)}  z ${pose.z.toFixed(2)}  θ ${((pose.yaw * 180) / Math.PI).toFixed(0)}°` : 'No pose'}
          </span>
          {anchor && (
            <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer" className="text-blue-soft hover:text-white">
              © OpenStreetMap
            </a>
          )}
          <label htmlFor="room-source" className="ml-auto text-blue-soft">Room</label>
          <select
            id="room-source"
            value={room.roomId}
            onChange={(event) => room.setRoomId(event.target.value)}
            className="hairline-light w-64 border bg-blue px-2 py-1 font-mono text-[11px] tracking-normal normal-case text-white focus:outline-none"
          >
            {!room.rooms.length && <option value="">No backend rooms</option>}
            {room.rooms.map((item) => (
              <option key={item.room_id} value={item.room_id}>
                {item.name} · {item.room_id}{item.closed ? ' · closed' : ''}
              </option>
            ))}
          </select>
          <button
            type="button"
            disabled={!room.roomId || resetting === 'busy'}
            onClick={reset}
            title="Permanently delete this room's captures and map on the server"
            className={`px-3 py-1 disabled:opacity-40 ${resetting === 'idle' ? 'hairline-light border hover:bg-white hover:text-blue' : 'bg-signal text-white'}`}
          >
            {resetting === 'confirm' ? 'Wipe room? Click again' : resetting === 'busy' ? 'Resetting…' : 'Reset room'}
          </button>
          {room.error && <span className="max-w-64 truncate text-signal" title={room.error}>{room.error}</span>}
        </div>
      </div>
    </section>
  );
}
