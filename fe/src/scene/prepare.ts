import * as THREE from 'three';
import type { RoomObject } from '../rooms/api';
import type { Ground } from './ground';
import type { SurfaceStats } from './surfaces';

export function prepareSurfaces(source: THREE.BufferGeometry, objects: RoomObject[], signal: AbortSignal) {
  return new Promise<{ geometry: THREE.BufferGeometry; stats: SurfaceStats; ground: Ground | null }>((resolve, reject) => {
    if (signal.aborted) { reject(new DOMException('Cancelled', 'AbortError')); return; }
    const worker = new Worker(new URL('./surface-worker.ts', import.meta.url), { type: 'module' });
    const stop = () => { worker.terminate(); signal.removeEventListener('abort', abort); };
    const abort = () => { stop(); reject(new DOMException('Cancelled', 'AbortError')); };
    signal.addEventListener('abort', abort, { once: true });
    worker.onerror = () => { stop(); reject(new Error('Unable to prepare room surfaces')); };
    worker.onmessage = ({ data }) => {
      stop();
      if (data.error) { reject(new Error(data.error)); return; }
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute('position', new THREE.BufferAttribute(data.positions, 3));
      geometry.setAttribute('normal', new THREE.BufferAttribute(data.normals, 3));
      geometry.setIndex(new THREE.BufferAttribute(data.indices, 1));
      geometry.computeBoundingSphere();
      resolve({ geometry, stats: data.stats, ground: data.ground });
    };
    const positions = new Float32Array(source.getAttribute('position').array);
    const indices = source.index ? new Uint32Array(source.index.array) : null;
    worker.postMessage({ positions, indices, objects }, [positions.buffer, ...(indices ? [indices.buffer] : [])]);
  });
}
