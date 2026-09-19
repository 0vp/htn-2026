import { readFileSync } from 'node:fs';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { Mesh } from 'three';
import { roomSurfaces } from '../src/scene/surfaces.ts';
const bytes = readFileSync(process.argv[2]);
const data = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
const scene = await new GLTFLoader().parseAsync(data, '');
const objects = JSON.parse(readFileSync(process.argv[3], 'utf8')).objects;
const start = performance.now();
scene.scene.traverse(node => {
  if (!(node instanceof Mesh)) return;
  const input = node.geometry.index?.count ?? node.geometry.getAttribute('position').count;
  const output = roomSurfaces(node.geometry, objects);
  console.log(JSON.stringify({ inputTriangles: input/3, outputTriangles: output.geometry.index!.count/3,
    ...output.stats, elapsedMs: performance.now()-start }));
});
