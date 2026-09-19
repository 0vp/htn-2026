import test from 'node:test';
import assert from 'node:assert/strict';
import { PlaneGeometry, Mesh, BoxGeometry, MeshStandardMaterial, Group } from 'three';
import { groundedObject, estimateGround, type Ground } from '../src/scene/ground.ts';
import { smoothSurface } from '../src/scene/smoothing.ts';
import { categoryModel } from '../src/objects/models.ts';
import type { RoomObject } from '../src/rooms/api.ts';
const ground: Ground={height:-1.2,area:4,minX:-3,maxX:3,minZ:-3,maxZ:3};
const table: RoomObject={object_id:'table',label:'dining table',center_m:[0,-0.4,0],size_m:[1,0.1,0.8],yaw_rad:0.2};

test('table keeps observed top and metric footprint while its legs reach floor',()=>{
 const result=groundedObject(table,ground);
 assert.ok(Math.abs(result.center_m[1]-result.size_m[1]/2-ground.height)<1e-9);
 assert.ok(Math.abs(result.center_m[1]+result.size_m[1]/2-(-0.35))<1e-9);
 assert.deepEqual([result.size_m[0],result.size_m[2]],[1,0.8]);
 assert.deepEqual(table.size_m,[1,0.1,0.8]);
});
test('no support estimate, tabletop object, out-of-room object and wall TV remain untouched',()=>{
 assert.equal(groundedObject(table,null),table);
 for(const label of ['laptop','bottle','tv']) {
  const object={...table,label};assert.equal(groundedObject(object,ground),object);
 }
 const outside={...table,center_m:[10,0,0] as [number,number,number]};
 assert.equal(groundedObject(outside,ground),outside);
});
test('a flat tabletop alone is insufficient to infer a room floor',()=>{
 const surface=new PlaneGeometry(2,2,4,4);surface.rotateX(-Math.PI/2);
 assert.equal(estimateGround(surface),null);
});
test('denoising reduces interior spikes while preserving open edges',()=>{
 const surface=new PlaneGeometry(2,2,8,8),p=surface.getAttribute('position');
 p.setZ(40,0.06);
 const edge=[p.getX(0),p.getY(0),p.getZ(0)];
 smoothSurface(surface);
 assert.ok(p.getZ(40)<0.03);
 assert.deepEqual([p.getX(0),p.getY(0),p.getZ(0)],edge);
});
test('model material color is preserved and owns an independent material',()=>{
 const material=new MeshStandardMaterial({color:0x985b32});
 const template=new Group();template.add(new Mesh(new BoxGeometry(),material));
 const model=categoryModel('chair',template);
 model.traverse(node=>{if(node instanceof Mesh){assert.equal(node.material.color.getHex(),0x985b32);assert.notEqual(node.material,material);}});
});
