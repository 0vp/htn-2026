import * as THREE from 'three';
import type { RoomObject } from '../rooms/api';

export type Ground = { height: number; area: number; minX: number; maxX: number; minZ: number; maxZ: number };

export function estimateGround(geometry: THREE.BufferGeometry): Ground | null {
  const p=geometry.getAttribute('position'),index=geometry.index;
  const bands=new Map<number,Ground & { weighted: number; cells: Set<string> }>();
  const a=new THREE.Vector3(),b=new THREE.Vector3(),c=new THREE.Vector3(),normal=new THREE.Vector3();
  geometry.computeBoundingBox();
  const bounds=geometry.boundingBox!;
  if (bounds.max.y-bounds.min.y < 1.5) return null;
  const upper=bounds.min.y+(bounds.max.y-bounds.min.y)*0.45;
  for(let i=0;i<(index?.count ?? p.count);i+=3) {
    a.fromBufferAttribute(p,index?index.getX(i):i);
    b.fromBufferAttribute(p,index?index.getX(i+1):i+1);
    c.fromBufferAttribute(p,index?index.getX(i+2):i+2);
    normal.copy(b).sub(a).cross(c.clone().sub(a));
    const area=normal.length()/2;
    if(area<1e-7||Math.abs(normal.normalize().y)<0.85) continue;
    const y=(a.y+b.y+c.y)/3;
    if(y>upper) continue;
    const key=Math.round(y/0.1);
    const band=bands.get(key) ?? {height:0,area:0,weighted:0,minX:Infinity,maxX:-Infinity,minZ:Infinity,maxZ:-Infinity,cells:new Set<string>()};
    band.area+=area;band.weighted+=y*area;
    for(const v of [a,b,c]) {
      band.minX=Math.min(band.minX,v.x);band.maxX=Math.max(band.maxX,v.x);
      band.minZ=Math.min(band.minZ,v.z);band.maxZ=Math.max(band.maxZ,v.z);
      band.cells.add(`${Math.floor(v.x/0.4)}:${Math.floor(v.z/0.4)}`);
    }
    bands.set(key,band);
  }
  const best=[...bands.values()].filter(b=>b.area>=0.8&&b.cells.size>=6).sort((a,b)=>b.area-a.area)[0];
  if(!best) return null;
  return {height:best.weighted/best.area,area:best.area,minX:best.minX,maxX:best.maxX,minZ:best.minZ,maxZ:best.maxZ};
}

const floorStanding=new Set(['chair','dining table','couch','bed','refrigerator','oven','toilet']);
export function groundedObject(object: RoomObject, ground: Ground | null): RoomObject {
  if(!ground||!floorStanding.has(object.label)) return object;
  const [x,y,z]=object.center_m;
  const [w,h,d]=object.size_m;
  if(x<ground.minX-0.5||x>ground.maxX+0.5||z<ground.minZ-0.5||z>ground.maxZ+0.5) return object;
  const top=y+h/2,newHeight=top-ground.height;
  // Keep the measured top and footprint. Extend unseen legs only with plausible support.
  if(newHeight<0.25||newHeight>2.5||newHeight<h-0.12||newHeight-h>1.2) return object;
  if(object.label==='dining table'&&Math.max(w,d)<0.4) return object;
  return {...object,center_m:[x,ground.height+newHeight/2,z],size_m:[w,newHeight,d]};
}
