import { feed } from './feed';
import type { Pose } from './protocol';

/**
 * Synthetic scanner for when no source is connected: a 16-channel spinning LiDAR on a
 * robot driving a loop through a furnished room. Output uses the same protocol as live data.
 */

type Box = { min: [number, number, number]; max: [number, number, number] };

const ROOM: Box = { min: [-4, 0, -2.5], max: [4, 2.6, 2.5] };

const box = (x: number, z: number, w: number, d: number, h: number): Box => ({
  min: [x - w / 2, 0, z - d / 2],
  max: [x + w / 2, h, z + d / 2],
});

const OBSTACLES: Box[] = [
  box(0, 0, 1.6, 0.9, 0.75), // table
  box(-3.7, 0.4, 0.5, 2.2, 1.9), // shelf
  box(-1.4, -2.1, 2.1, 0.8, 0.85), // couch
  box(3.3, -1.9, 0.9, 0.9, 1.1), // crates
  box(1.2, 2.05, 0.35, 0.35, 2.6), // pillar
  box(2.9, 1.95, 1.4, 0.6, 0.95), // counter
];

const CHANNELS = 16;
const ELEVATION_MIN = (-18 * Math.PI) / 180;
const ELEVATION_MAX = (32 * Math.PI) / 180;
const AZIMUTH_STEP = (0.7 * Math.PI) / 180;
const SPIN_HZ = 10;
const SENSOR_HEIGHT = 0.42;
const MAX_RANGE = 12;

function hitObstacle(o: number[], d: number[], b: Box): number {
  let near = -Infinity;
  let far = Infinity;
  for (let a = 0; a < 3; a++) {
    if (Math.abs(d[a]) < 1e-9) {
      if (o[a] < b.min[a] || o[a] > b.max[a]) return Infinity;
      continue;
    }
    let t1 = (b.min[a] - o[a]) / d[a];
    let t2 = (b.max[a] - o[a]) / d[a];
    if (t1 > t2) [t1, t2] = [t2, t1];
    near = Math.max(near, t1);
    far = Math.min(far, t2);
  }
  return near <= far && near > 0 ? near : Infinity;
}

function exitRoom(o: number[], d: number[]): number {
  let t = Infinity;
  for (let a = 0; a < 3; a++) {
    if (d[a] > 1e-9) t = Math.min(t, (ROOM.max[a] - o[a]) / d[a]);
    else if (d[a] < -1e-9) t = Math.min(t, (ROOM.min[a] - o[a]) / d[a]);
  }
  return t;
}

function poseAt(seconds: number): Pose {
  const t = seconds * 0.12;
  const x = 2.45 * Math.cos(t);
  const z = 1.2 * Math.sin(t);
  // Tangent of the ellipse; yaw is about +Y with 0 facing +X, so forward = (cos, 0, -sin).
  const dx = -2.45 * Math.sin(t);
  const dz = 1.2 * Math.cos(t);
  return { x, y: 0, z, yaw: Math.atan2(-dz, dx) };
}

export function startDemo(): () => void {
  const started = performance.now();
  let azimuth = 0;
  let last = started;
  feed.emit({ xyz: new Float32Array(0), reset: true });

  const tick = () => {
    const now = performance.now();
    const dt = Math.min(0.1, (now - last) / 1000);
    last = now;
    const pose = poseAt((now - started) / 1000);
    const sweep = 2 * Math.PI * SPIN_HZ * dt;
    const steps = Math.max(1, Math.floor(sweep / AZIMUTH_STEP));
    const out = new Float32Array(steps * CHANNELS * 3);
    const origin = [pose.x, SENSOR_HEIGHT, pose.z];
    const dir = [0, 0, 0];
    let n = 0;

    for (let s = 0; s < steps; s++) {
      azimuth += AZIMUTH_STEP;
      const heading = pose.yaw + azimuth;
      for (let c = 0; c < CHANNELS; c++) {
        const elevation = ELEVATION_MIN + ((ELEVATION_MAX - ELEVATION_MIN) * c) / (CHANNELS - 1);
        const flat = Math.cos(elevation);
        dir[0] = flat * Math.cos(heading);
        dir[1] = Math.sin(elevation);
        dir[2] = -flat * Math.sin(heading);
        let t = exitRoom(origin, dir);
        for (const obstacle of OBSTACLES) t = Math.min(t, hitObstacle(origin, dir, obstacle));
        if (t > MAX_RANGE) continue;
        const noise = 1 + (Math.random() - 0.5) * 0.01;
        out[n++] = origin[0] + dir[0] * t * noise;
        out[n++] = origin[1] + dir[1] * t * noise;
        out[n++] = origin[2] + dir[2] * t * noise;
      }
    }
    azimuth %= 2 * Math.PI;
    feed.emit({ xyz: out.subarray(0, n), pose });
  };

  const timer = setInterval(tick, 1000 / 30);
  return () => clearInterval(timer);
}
