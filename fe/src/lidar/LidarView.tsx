import { useEffect, useRef, useState } from 'react';
import { feed } from './feed';
import { LidarRenderer, type CloudStats, type ColorMode, type ViewMode } from './renderer';
import { CameraFeed } from '../camera/CameraFeed';
import { canMove, control, useControl } from '../control/store';
import { usePlayer } from '../session/player';
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
  const [view, setView] = useState<ViewMode>('orbit');
  const [color, setColor] = useState<ColorMode>('height');
  const [paused, setPaused] = useState(false);
  const [stats, setStats] = useState<CloudStats | null>(null);
  const [camera, setCamera] = useState(true);
  const [picking, setPicking] = useState(false);
  const controlState = useControl();
  const { goal } = controlState;
  const player = usePlayer();
  const replaying = !!player && !player.error;
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

  useEffect(() => {
    if (room.mesh) void renderer.current?.loadRoomMesh(room.mesh);
  }, [room.mesh]);

  useEffect(() => renderer.current?.clearRoomMesh(), [room.roomId]);

  useEffect(() => renderer.current?.setView(view), [view]);
  useEffect(() => renderer.current?.setColorMode(color), [color]);
  useEffect(() => renderer.current?.setPaused(paused), [paused]);
  useEffect(() => renderer.current?.setGoal(goal), [goal]);
  useEffect(() => {
    renderer.current?.setPicking(
      picking
        ? (point) => {
            control.set({ goal: point, stick: { x: 0, y: 0 } });
            setPicking(false);
          }
        : null,
    );
  }, [picking]);

  const pose = stats?.pose;
  const goalDistance = goal && pose ? Math.hypot(goal.x - pose.x, goal.z - pose.z) : null;
  const canGo = canMove(controlState) && !replaying;
  if (picking && !canGo) setPicking(false);
  return (
    <section id="lidar" className="relative bg-blue text-white">
      <div ref={host} className="h-[78vh] min-h-[520px] w-full cursor-grab active:cursor-grabbing" />

      <div className="pointer-events-none absolute inset-x-0 top-0 flex flex-wrap items-start justify-between gap-6 p-6 sm:p-9">
        <div>
          <p className="label text-blue-soft">01 — LiDAR</p>
          <h1 className="mt-3 font-pixel text-5xl leading-none sm:text-6xl">Room scan</h1>
        </div>
        <div className="pointer-events-auto flex flex-col items-end gap-2">
          <Segmented
            tone="dark"
            value={view}
            onChange={setView}
            options={[
              ['orbit', 'Orbit'],
              ['top', 'Top'],
              ['follow', 'Follow'],
            ]}
          />
          <Segmented
            tone="dark"
            value={color}
            onChange={setColor}
            options={[
              ['height', 'Height'],
              ['age', 'Age'],
            ]}
          />
          <div className="flex gap-2">
            <TextButton tone="dark" onClick={() => setCamera((c) => !c)} active={camera}>
              Camera
            </TextButton>
            <TextButton tone="dark" onClick={() => setPaused((p) => !p)} active={paused}>
              {paused ? 'Resume' : 'Pause'}
            </TextButton>
            <TextButton tone="dark" onClick={() => renderer.current?.clear()}>
              Clear
            </TextButton>
          </div>
        </div>
      </div>

      <div className="absolute bottom-20 left-6 flex flex-col items-start gap-3 sm:left-9">
        {camera && <CameraFeed />}
        <div className="label flex items-center gap-2">
          <button
            type="button"
            disabled={!canGo}
            onClick={() => setPicking((p) => !p)}
            title={canGo ? 'Click the floor to send the robot there' : 'Arm the robot to set a goal'}
            className={`px-3 py-1.5 disabled:opacity-40 ${picking ? 'bg-signal text-white' : 'bg-paper text-blue hover:bg-white'}`}
          >
            {picking ? 'Click the floor…' : 'Go to point'}
          </button>
          {goal && (
            <>
              <span className="text-white/85 tabular-nums">
                Goal {goal.x.toFixed(2)}, {goal.z.toFixed(2)}
                {goalDistance !== null && ` · ${goalDistance.toFixed(2)} m`}
              </span>
              <button type="button" onClick={() => control.set({ goal: null })} className="text-blue-soft hover:text-white">
                Cancel
              </button>
            </>
          )}
        </div>
      </div>

      <div className="pointer-events-none absolute right-6 bottom-20 text-right sm:right-9">
        <p className="label text-blue-soft">Points in view</p>
        <p className="font-pixel text-7xl leading-none tabular-nums sm:text-8xl">
          {compact(stats?.points ?? 0)}
        </p>
      </div>

      <div className="absolute inset-x-0 bottom-0 px-6 sm:px-9">
        <div className="hairline-light flex flex-wrap items-center gap-x-6 gap-y-2 border-b py-4 label text-white/85">
          <span className="flex items-center gap-2">
            <span className={`size-2 ${replaying ? 'bg-signal' : room.link === 'live' ? 'bg-white' : room.link === 'waiting' ? 'bg-blue-soft' : 'bg-signal'}`} />
            {replaying ? 'Replay' : LINK_LABEL[room.link]}
          </span>
          <span>{room.status ? `${room.status.mapped}/${room.status.received} frames mapped` : 'No frames'}</span>
          <span>{stats?.fps ?? 0} fps</span>
          <span>
            {pose ? `x ${pose.x.toFixed(2)}  z ${pose.z.toFixed(2)}  θ ${((pose.yaw * 180) / Math.PI).toFixed(0)}°` : 'No pose'}
          </span>
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
          {room.error && <span className="max-w-64 truncate text-signal" title={room.error}>{room.error}</span>}
        </div>
      </div>
    </section>
  );
}
