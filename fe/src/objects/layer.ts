import * as THREE from 'three';
import { groundedObject, type Ground } from '../scene/ground.ts';
import { categoryModel } from './models.ts';
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

  update(objects: RoomObject[], templates = new Map<string, THREE.Group>(), ground: Ground | null = null): void {
    disposeTree(this.group);
    this.group.clear();
    for (const observed of objects) {
      const object = groundedObject(observed, ground);
      if (![...object.center_m, ...object.size_m, object.yaw_rad].every(Number.isFinite)
          || object.size_m.some((value) => value <= 0)) continue;
      const box = new THREE.BoxGeometry(...object.size_m);
      const edges = new THREE.LineSegments(
        new THREE.EdgesGeometry(box),
        new THREE.LineBasicMaterial({ color: 0xffd580, depthTest: false, transparent: true, opacity: 0.8 }),
      );
      box.dispose();
      const instance = new THREE.Group();
      instance.position.fromArray(object.center_m);
      instance.rotation.y = object.yaw_rad;
      instance.userData.objectId = object.object_id;
      const model = categoryModel(object.label, templates.get(object.label));
      model.scale.multiply(new THREE.Vector3(...object.size_m));
      edges.userData.bounds = true;
      edges.renderOrder = 2;
      instance.add(model, edges);
      this.group.add(instance);
    }
    this.select(this.selected);
  }

  select(id: string | null): void {
    this.selected = id;
    for (const child of this.group.children) {
      const line = child.children.find((node) => node.userData.bounds) as THREE.LineSegments<THREE.EdgesGeometry, THREE.LineBasicMaterial>;
      line.visible = child.userData.objectId === id;
      line.material.color.setHex(0xff784f);
      line.material.opacity = 1;
    }
  }
}
