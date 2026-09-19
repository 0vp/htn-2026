import test from 'node:test';
import assert from 'node:assert/strict';
import { Box3, Vector3 } from 'three';
import { ObjectLayer } from '../src/objects/layer.ts';
import { fetchScene, evidenceUrl, type RoomObject } from '../src/rooms/api.ts';

const object: RoomObject = {
  object_id: '0:42', label: 'chair', center_m: [3, -1, 5], size_m: [2, 1, 4], yaw_rad: Math.PI / 2,
};

test('server Y-up metric bounds preserve center, size and yaw in Three.js', () => {
  const layer = new ObjectLayer();
  layer.update([object]);
  const bounds = new Box3().setFromObject(layer.group);
  assert.deepEqual(bounds.getCenter(new Vector3()).toArray(), object.center_m);
  bounds.getSize(new Vector3()).toArray().forEach((value, i) => {
    assert.ok(Math.abs(value - [4, 1, 2][i]) < 1e-6);
  });
  let disposed = false;
  layer.group.children[0].geometry.addEventListener('dispose', () => { disposed = true; });
  layer.update([]);
  assert.equal(disposed, true);
  assert.equal(layer.group.children.length, 0);
});

test('selection stays on stable identity when the scene updates', () => {
  const layer = new ObjectLayer();
  layer.select(object.object_id);
  layer.update([object]);
  assert.equal(layer.group.children[0].material.color.getHex(), 0xff784f);
  layer.update([{ ...object, object_id: 'other' }]);
  assert.equal(layer.group.children[0].material.opacity, 0.3);
});

test('mesh/object revision mismatch fails safely, and a subsequent retry succeeds', async (t) => {
  let revision = 8;
  t.mock.method(globalThis, 'fetch', async (url: string) => url.endsWith('/map')
    ? Response.json({ revision: 7, objects: [object] })
    : new Response(new Uint8Array([1, 2, 3]), { headers: { ETag: `"ROOM-${revision}"` } }));
  await assert.rejects(fetchScene('ROOM'), /changed during download/);
  revision = 7;
  const scene = await fetchScene('ROOM');
  assert.equal(scene.revision, 7);
  assert.deepEqual(scene.objects, [object]);
  assert.equal(scene.mesh.byteLength, 3);
});

test('non-success API responses surface rather than producing an empty scene', async (t) => {
  t.mock.method(globalThis, 'fetch', async () => new Response('', { status: 503 }));
  await assert.rejects(fetchScene('ROOM'), /503/);
});

test('evidence uses encoded object identity and version', () => {
  assert.ok(evidenceUrl('ROOM', { ...object, evidence_digest: 'abc' })
    .endsWith('/objects/0%3A42/evidence.jpg?version=abc'));
});
