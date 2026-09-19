import test from 'node:test';
import assert from 'node:assert/strict';
import { BufferGeometry, Float32BufferAttribute, Box3, Vector3, Group, Mesh, BoxGeometry, MeshBasicMaterial } from 'three';
import { roomSurfaces } from '../src/scene/surfaces.ts';
import { categoryModel } from '../src/objects/models.ts';

function geometry(points: number[]) {
  return new BufferGeometry().setAttribute('position', new Float32BufferAttribute(points, 3));
}
const floor = [0,0,0, 3,0,0, 0,0,3, 3,0,0, 3,0,3, 0,0,3];
const ceiling = floor.map((v,i) => i % 3 === 1 ? 2.5 : v);

test('ceiling is hidden while floor and original backend mesh remain intact', () => {
  const input = geometry([...floor,...ceiling]);
  const before = Array.from(input.getAttribute('position').array);
  const output = roomSurfaces(input);
  assert.equal(output.stats.ceilingTriangles,2);
  assert.equal(output.geometry.index!.count,6);
  assert.deepEqual(Array.from(input.getAttribute('position').array), before);
  assert.equal(input.index, null);
});

test('a table-height horizontal scan does not get treated as a ceiling', () => {
  const table = floor.map((v,i) => i % 3 === 1 ? 0.8 : v);
  assert.equal(roomSurfaces(geometry([...floor,...table])).stats.ceilingTriangles,0);
});

test('supported noisy wall is flattened without adding faces or closing openings', () => {
  const wall = geometry([0,0,0.01, 3,0,-0.01, 0,2.5,0, 3,0,-0.01, 3,2.5,0.01, 0,2.5,0]);
  const result = roomSurfaces(wall);
  assert.ok(result.stats.planarVertices > 0);
  assert.equal(result.geometry.index!.count,6);
  const z = Array.from({length:6},(_,i)=>result.geometry.getAttribute('position').getZ(i));
  assert.ok(Math.max(...z)-Math.min(...z)<1e-5);
});

test('category normalization honors measured extents without changing cached model', () => {
  const template = new Group();
  template.add(new Mesh(new BoxGeometry(1,2,4),new MeshBasicMaterial()));
  template.position.set(5,6,7);
  const model = categoryModel('chair', template);
  const bounds = new Box3().setFromObject(model);
  bounds.getSize(new Vector3()).toArray().forEach(v=>assert.ok(Math.abs(v-1)<1e-6));
  bounds.getCenter(new Vector3()).toArray().forEach(v=>assert.ok(Math.abs(v)<1e-6));
  assert.deepEqual(template.position.toArray(),[5,6,7]);
});

test('all bundled GLB models load and normalize to finite unit bounds', async () => {
  const { readFileSync, readdirSync } = await import('node:fs');
  const { GLTFLoader } = await import('three/examples/jsm/loaders/GLTFLoader.js');
  for (const folder of ['furniture','fixtures']) {
    const directory = new URL(`../public/models/${folder}/`, import.meta.url);
    for (const filename of readdirSync(directory)) {
      const bytes = readFileSync(new URL(filename, directory));
      const gltf = await new GLTFLoader().parseAsync(bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength),'');
      const model = categoryModel(filename, gltf.scene);
      const size = new Box3().setFromObject(model).getSize(new Vector3());
      size.toArray().forEach(value=>assert.ok(Number.isFinite(value) && Math.abs(value-1)<1e-5,filename));
    }
  }
});
