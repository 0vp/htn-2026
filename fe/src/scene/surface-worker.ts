import * as THREE from 'three';
import { roomSurfaces } from './surfaces';

self.onmessage = (event) => {
  const { positions, indices, objects } = event.data;
  try {
    const source = new THREE.BufferGeometry();
    source.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    if (indices) source.setIndex(new THREE.BufferAttribute(indices, 1));
    const result = roomSurfaces(source, objects);
    const output = {
      positions: result.geometry.getAttribute('position').array,
      normals: result.geometry.getAttribute('normal').array,
      indices: result.geometry.index!.array,
      stats: result.stats,
      ground: result.ground,
    };
    self.postMessage(output, { transfer: [output.positions.buffer, output.normals.buffer, output.indices.buffer] });
  } catch (error) {
    self.postMessage({ error: error instanceof Error ? error.message : 'Surface processing failed' });
  }
};
