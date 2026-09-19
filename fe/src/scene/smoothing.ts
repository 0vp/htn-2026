import * as THREE from 'three';

/** Weld shared positions before smoothing triangle-soup maps. Keep open boundaries fixed. */
export function smoothSurface(geometry: THREE.BufferGeometry, iterations = 12): void {
  const position = geometry.getAttribute('position');
  const index = geometry.index!;
  const keys = new Map<string, number>();
  const ids = new Int32Array(position.count);
  const points: THREE.Vector3[] = [];
  const neighbors: Set<number>[] = [];
  for (let i = 0; i < position.count; i++) {
    const point = new THREE.Vector3().fromBufferAttribute(position, i);
    const key = point.toArray().map(v => Math.round(v * 1000)).join(':');
    let id = keys.get(key);
    if (id === undefined) { id = points.length; keys.set(key, id); points.push(point); neighbors.push(new Set()); }
    ids[i] = id;
  }
  const edges = new Map<string, number>();
  for (let i = 0; i < index.count; i += 3) {
    const tri = [0,1,2].map(j => ids[index.getX(i+j)]);
    for (let j=0;j<3;j++) {
      const a=tri[j],b=tri[(j+1)%3];
      if(a===b) continue;
      neighbors[a].add(b); neighbors[b].add(a);
      const key = a<b ? `${a}:${b}` : `${b}:${a}`;
      edges.set(key,(edges.get(key) ?? 0)+1);
    }
  }
  const boundary = new Set<number>();
  for (const [key,count] of edges) if(count===1) key.split(':').forEach(id=>boundary.add(Number(id)));
  const original=points.map(p=>p.clone());
  const mean=new THREE.Vector3(),delta=new THREE.Vector3();
  for(let iteration=0;iteration<iterations;iteration++) {
    const next=points.map(p=>p.clone());
    for(let i=0;i<points.length;i++) {
      if(boundary.has(i)||neighbors[i].size<3) continue;
      mean.set(0,0,0);
      for(const id of neighbors[i]) mean.add(points[id]);
      mean.multiplyScalar(1/neighbors[i].size);
      next[i].lerp(mean,0.45);
      delta.copy(next[i]).sub(original[i]);
      if(delta.length()>0.1) next[i].copy(original[i]).add(delta.setLength(0.1));
    }
    next.forEach((p,i)=>points[i].copy(p));
  }
  for(let i=0;i<position.count;i++) position.setXYZ(i,...points[ids[i]].toArray());
}
