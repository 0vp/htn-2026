import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';

const files: Record<string, string> = {
  chair: 'furniture/chair', 'dining table': 'furniture/table', laptop: 'furniture/laptop',
  tv: 'furniture/televisionModern', bed: 'furniture/bedDouble', couch: 'furniture/loungeSofa',
  refrigerator: 'fixtures/kitchenFridge', oven: 'fixtures/kitchenStove',
  sink: 'fixtures/bathroomSink', toilet: 'fixtures/toilet',
};
const cache = new Map<string, Promise<THREE.Group | null>>();

// Shared templates live for the page lifetime; every displayed instance owns its resources.
export async function loadModels(labels: string[]): Promise<Map<string, THREE.Group>> {
  const entries = await Promise.all([...new Set(labels)].map(async (label) => {
    if (!files[label]) return [label, null] as const;
    if (!cache.has(label)) {
      const base = import.meta.env?.BASE_URL ?? '/';
      cache.set(label, new GLTFLoader().loadAsync(`${base}models/${files[label]}.glb`)
        .then(({ scene }) => scene)
        .catch(() => { cache.delete(label); return null; }));
    }
    return [label, await cache.get(label)] as const;
  }));
  return new Map(entries.filter((entry): entry is readonly [string, THREE.Group] => !!entry[1]));
}

export function categoryModel(label: string, template?: THREE.Group): THREE.Group {
  const root = new THREE.Group();
  if (template) {
    const copy = template.clone(true);
    copy.traverse((node) => {
      if (!(node instanceof THREE.Mesh)) return;
      node.geometry = node.geometry.clone();
      const materials = Array.isArray(node.material) ? node.material : [node.material];
      const copies = materials.map(material => {
        const copy = material.clone();
        if (copy instanceof THREE.MeshStandardMaterial) { copy.roughness = 0.8; copy.metalness = 0.05; }
        return copy;
      });
      node.material = Array.isArray(node.material) ? copies : copies[0];
      node.castShadow = true;
      node.receiveShadow = true;
    });
    root.add(copy);
  } else {
    const material = new THREE.MeshStandardMaterial({ color: 0xbac6ce, roughness: 0.85 });
    const geometry = label === 'bottle' || label === 'cup'
      ? new THREE.CylinderGeometry(label === 'bottle' ? 0.22 : 0.45, 0.42, 1, 20)
      : new THREE.BoxGeometry(1, 1, 1);
    root.add(new THREE.Mesh(geometry, material));
    if (label === 'bottle') {
      const cap = new THREE.Mesh(new THREE.CylinderGeometry(0.16, 0.16, 0.18, 20), material.clone());
      cap.position.y = 0.56;
      root.add(cap);
    }
  }
  // Align the longest horizontal model axis with the backend's principal width axis.
  let bounds = new THREE.Box3().setFromObject(root);
  let size = bounds.getSize(new THREE.Vector3());
  if (size.z > size.x) root.rotation.y = Math.PI / 2;
  root.updateMatrixWorld(true);
  bounds = new THREE.Box3().setFromObject(root);
  size = bounds.getSize(new THREE.Vector3());
  const center = bounds.getCenter(new THREE.Vector3());
  const normalized = new THREE.Group();
  root.position.sub(center);
  normalized.add(root);
  normalized.scale.set(1 / Math.max(size.x, 1e-6), 1 / Math.max(size.y, 1e-6), 1 / Math.max(size.z, 1e-6));
  return normalized;
}
