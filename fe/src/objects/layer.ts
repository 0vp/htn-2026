import * as THREE from 'three';
import type { RoomObject } from '../rooms/api';

export function disposeTree(root: THREE.Object3D): void {
  root.traverse((node) => {
    if (!(node instanceof THREE.Mesh || node instanceof THREE.LineSegments)) return;
    node.geometry.dispose();
    const materials = Array.isArray(node.material) ? node.material : [node.material];
    for (const material of materials) material.dispose();
  });
}

export class ObjectLayer {
  readonly group = new THREE.Group();
  private selected: string | null = null;

  update(objects: RoomObject[]): void {
    disposeTree(this.group);
    this.group.clear();
    for (const object of objects) {
      if (![...object.center_m, ...object.size_m, object.yaw_rad].every(Number.isFinite)
          || object.size_m.some((value) => value <= 0)) continue;
      const box = new THREE.BoxGeometry(...object.size_m);
      const edges = new THREE.LineSegments(
        new THREE.EdgesGeometry(box),
        new THREE.LineBasicMaterial({ color: 0xffd580, depthTest: false, transparent: true, opacity: 0.8 }),
      );
      box.dispose();
      edges.position.fromArray(object.center_m);
      edges.rotation.y = object.yaw_rad;
      edges.userData.objectId = object.object_id;
      edges.renderOrder = 2;
      this.group.add(edges);
    }
    this.select(this.selected);
  }

  select(id: string | null): void {
    this.selected = id;
    for (const child of this.group.children) {
      const line = child as THREE.LineSegments<THREE.EdgesGeometry, THREE.LineBasicMaterial>;
      line.material.color.setHex(line.userData.objectId === id ? 0xff784f : 0xffd580);
      line.material.opacity = id && line.userData.objectId !== id ? 0.3 : 1;
    }
  }
}
