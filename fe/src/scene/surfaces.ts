import * as THREE from 'three';
import { smoothSurface } from './smoothing.ts';
import { estimateGround } from './ground.ts';
import type { RoomObject } from '../rooms/api';

type Face = { ids: number[]; center: THREE.Vector3; normal: THREE.Vector3; area: number };
type Plane = { normal: THREE.Vector3; distance: number; area: number; min: number; max: number };
export type SurfaceStats = { ceilingTriangles: number; planarVertices: number; wallPlanes: number };

function inside(point: THREE.Vector3, object: RoomObject): boolean {
  const [x, y, z] = object.center_m;
  const dx = point.x - x, dz = point.z - z, c = Math.cos(object.yaw_rad), s = Math.sin(object.yaw_rad);
  return Math.abs(c * dx - s * dz) <= object.size_m[0] / 2 + 0.015
    && Math.abs(point.y - y) <= object.size_m[1] / 2 + 0.015
    && Math.abs(s * dx + c * dz) <= object.size_m[2] / 2 + 0.015;
}

/** Presentation geometry only. Preserve connectivity and holes; never add inferred walls. */
export function roomSurfaces(source: THREE.BufferGeometry, objects: RoomObject[] = []) {
  const ground = estimateGround(source);
  const geometry = source.clone();
  const positions = geometry.getAttribute('position');
  const index = geometry.getIndex();
  const faces: Face[] = [];
  const bins = new Map<string, Plane>();
  const heights = new Map<number, number>();
  geometry.computeBoundingBox();
  const bounds = geometry.boundingBox!;
  const a = new THREE.Vector3(), b = new THREE.Vector3(), c = new THREE.Vector3();
  for (let i = 0; i < (index?.count ?? positions.count); i += 3) {
    const ids = [0, 1, 2].map((j) => index ? index.getX(i + j) : i + j);
    a.fromBufferAttribute(positions, ids[0]); b.fromBufferAttribute(positions, ids[1]); c.fromBufferAttribute(positions, ids[2]);
    const normal = b.clone().sub(a).cross(c.clone().sub(a));
    const area = normal.length() / 2;
    if (area < 1e-8) continue;
    normal.normalize();
    const center = a.clone().add(b).add(c).multiplyScalar(1 / 3);
    faces.push({ ids, center, normal, area });
    if (Math.abs(normal.y) > 0.9) {
      const height = Math.round(center.y / 0.12);
      heights.set(height, (heights.get(height) ?? 0) + area);
    }
    if (Math.abs(normal.y) > 0.2) continue;
    let angle = Math.atan2(normal.z, normal.x);
    if (angle < 0) angle += Math.PI;
    const direction = Math.round(angle / (Math.PI / 36)) % 36;
    const n = new THREE.Vector3(Math.cos(direction * Math.PI / 36), 0, Math.sin(direction * Math.PI / 36));
    const offset = Math.round(n.dot(center) / 0.12);
    const key = `${direction}:${offset}`;
    const plane = bins.get(key) ?? { normal: n, distance: 0, area: 0, min: Infinity, max: -Infinity };
    plane.distance += n.dot(center) * area;
    plane.area += area;
    plane.min = Math.min(plane.min, a.y, b.y, c.y);
    plane.max = Math.max(plane.max, a.y, b.y, c.y);
    bins.set(key, plane);
  }
  const planes = [...bins.values()].filter((p) => p.area >= 0.8 && p.max - p.min >= 1.2);
  planes.forEach((p) => { p.distance /= p.area; });
  // Require a broad, near-horizontal high surface. Short objects cannot become ceilings.
  const ceiling = [...heights.entries()]
    .filter(([h, area]) => area >= 0.8 && h * 0.12 > bounds.min.y + 1.8
      && h * 0.12 > bounds.min.y + (bounds.max.y - bounds.min.y) * 0.65)
    .sort((a, b) => b[1] - a[1])[0]?.[0];
  const keep: number[] = [];
  const snap = new Map<number, Plane>();
  let ceilingTriangles = 0;
  for (const face of faces) {
    if (ceiling !== undefined && Math.abs(face.normal.y) > 0.65 && face.center.y >= ceiling * 0.12 - 0.18) {
      ceilingTriangles++;
      continue;
    }
    // Replace only fully contained measured triangles with the category proxy.
    if (objects.some((object) => inside(face.center, object)
      && face.ids.every((id) => inside(a.fromBufferAttribute(positions, id), object)))) continue;
    keep.push(...face.ids);
    if (Math.abs(face.normal.y) > 0.3) continue;
    const plane = planes.filter((p) => Math.abs(p.normal.dot(face.normal)) > 0.90
      && Math.abs(p.normal.dot(face.center) - p.distance) < 0.09)
      .sort((a, b) => b.area - a.area)[0];
    if (plane) for (const id of face.ids) {
      a.fromBufferAttribute(positions, id);
      if (Math.abs(plane.normal.dot(a) - plane.distance) <= 0.09) snap.set(id, plane);
    }
  }
  for (const [id, plane] of snap) {
    a.fromBufferAttribute(positions, id);
    a.addScaledVector(plane.normal, plane.distance - plane.normal.dot(a));
    positions.setXYZ(id, a.x, a.y, a.z);
  }
  geometry.setIndex(keep);
  smoothSurface(geometry);
  // Re-project supported planes after denoising to retain flat walls.
  for (const [id, plane] of snap) {
    a.fromBufferAttribute(positions, id);
    a.addScaledVector(plane.normal, plane.distance - plane.normal.dot(a));
    positions.setXYZ(id, a.x, a.y, a.z);
  }
  if (ground) for (let id=0; id<positions.count; id++) {
    if (Math.abs(positions.getY(id)-ground.height)<0.06) positions.setY(id,ground.height);
  }
  geometry.computeVertexNormals();
  geometry.computeBoundingSphere();
  return { geometry, ground, stats: { ceilingTriangles, planarVertices: snap.size, wallPlanes: planes.length } satisfies SurfaceStats };
}
