import * as THREE from 'three';

// Approximate outdoor context around the room map: OpenStreetMap tiles and extruded
// building footprints, in local metres about a GPS anchor. East is +x, north is -z.

export type GeoAnchor = {
  latitude: number;
  longitude: number;
  /** Rotation about +y that carries the east/north frame into the scene, when a heading is known. */
  north: number | null;
};

const EARTH = 6378137;
const RAD = Math.PI / 180;
const ZOOM = 18;
const TILE_RING = 2; // (2n+1)^2 tiles, ~110 m each at mid latitudes.
const RADIUS_M = 300;
const OVERPASS = 'https://overpass-api.de/api/interpreter';

type Way = { geometry?: Array<{ lat: number; lon: number }>; tags?: Record<string, string> };

export class GeoLayer {
  readonly group = new THREE.Group();
  private key = '';
  private abort = new AbortController();

  setNorth(radians: number): void {
    this.group.rotation.y = radians;
  }

  setGround(height: number): void {
    // Just under the floor so the scanned ground wins the depth test.
    this.group.position.y = height - 0.03;
  }

  load(anchor: GeoAnchor | null): void {
    const key = anchor ? `${anchor.latitude.toFixed(4)},${anchor.longitude.toFixed(4)}` : '';
    if (key === this.key) return;
    this.key = key;
    this.abort.abort();
    this.abort = new AbortController();
    this.clear();
    if (!anchor) return;
    this.addTiles(anchor);
    void this.addBuildings(anchor, this.abort.signal).catch(() => undefined);
  }

  dispose(): void {
    this.abort.abort();
    this.clear();
  }

  private clear(): void {
    for (const child of [...this.group.children]) {
      this.group.remove(child);
      child.traverse((node) => {
        const mesh = node as THREE.Mesh;
        mesh.geometry?.dispose();
        const material = mesh.material as THREE.MeshBasicMaterial | undefined;
        material?.map?.dispose();
        material?.dispose();
      });
    }
  }

  private addTiles({ latitude, longitude }: GeoAnchor): void {
    const n = 2 ** ZOOM;
    const tileX = (lon: number) => ((lon + 180) / 360) * n;
    const tileY = (lat: number) => ((1 - Math.asinh(Math.tan(lat * RAD)) / Math.PI) / 2) * n;
    const lonOf = (x: number) => (x / n) * 360 - 180;
    const latOf = (y: number) => Math.atan(Math.sinh(Math.PI * (1 - (2 * y) / n))) / RAD;
    const local = projector(latitude, longitude);
    const cx = Math.floor(tileX(longitude));
    const cy = Math.floor(tileY(latitude));
    const loader = new THREE.TextureLoader().setCrossOrigin('anonymous');
    for (let dx = -TILE_RING; dx <= TILE_RING; dx++) {
      for (let dy = -TILE_RING; dy <= TILE_RING; dy++) {
        const [x, y] = [cx + dx, cy + dy];
        const [west, north] = local(latOf(y), lonOf(x));
        const [east, south] = local(latOf(y + 1), lonOf(x + 1));
        const geometry = new THREE.PlaneGeometry(east - west, north - south).rotateX(-Math.PI / 2);
        const material = new THREE.MeshBasicMaterial({
          color: 0x8e9bff, // Multiplies the tile toward the scene's blue.
          transparent: true,
          opacity: 0,
          depthWrite: false,
        });
        const tile = new THREE.Mesh(geometry, material);
        tile.position.set((west + east) / 2, 0, -(north + south) / 2);
        tile.renderOrder = -2;
        this.group.add(tile);
        loader.load(`https://tile.openstreetmap.org/${ZOOM}/${x}/${y}.png`, (texture) => {
          texture.colorSpace = THREE.SRGBColorSpace;
          texture.anisotropy = 8;
          material.map = texture;
          material.opacity = 0.6;
          material.needsUpdate = true;
        });
      }
    }
  }

  private async addBuildings({ latitude, longitude }: GeoAnchor, signal: AbortSignal): Promise<void> {
    const query = `[out:json][timeout:20];way["building"](around:${RADIUS_M},${latitude},${longitude});out geom tags;`;
    const response = await fetch(`${OVERPASS}?data=${encodeURIComponent(query)}`, {
      signal,
      headers: { Accept: 'application/json' },
    });
    if (!response.ok) return;
    const { elements } = (await response.json()) as { elements: Way[] };
    if (signal.aborted) return;
    const local = projector(latitude, longitude);
    const fill = new THREE.MeshLambertMaterial({ color: 0xdfe4ff, transparent: true, opacity: 0.3, depthWrite: false });
    const edge = new THREE.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.45 });
    const buildings = new THREE.Group();
    for (const way of elements) {
      const ring = way.geometry?.map(({ lat, lon }) => new THREE.Vector2(...local(lat, lon)));
      if (!ring || ring.length < 4) continue;
      const tags = way.tags ?? {};
      const height = parseFloat(tags.height) || parseFloat(tags['building:levels']) * 3.2 || 8;
      // Extrude in the east/north plane, then stand it up: north becomes -z, depth becomes +y.
      const geometry = new THREE.ExtrudeGeometry(new THREE.Shape(ring), { depth: height, bevelEnabled: false })
        .rotateX(-Math.PI / 2);
      // The building the scan is inside would bury it, so keep only its outline.
      if (!contains(ring)) buildings.add(new THREE.Mesh(geometry, fill));
      buildings.add(new THREE.LineSegments(new THREE.EdgesGeometry(geometry, 30), edge));
    }
    buildings.renderOrder = -1;
    this.group.add(buildings);
  }
}

function projector(latitude: number, longitude: number) {
  const metresPerLon = EARTH * RAD * Math.cos(latitude * RAD);
  return (lat: number, lon: number): [number, number] => [
    (lon - longitude) * metresPerLon,
    (lat - latitude) * EARTH * RAD,
  ];
}

/** Whether the ring contains the local origin (even-odd rule). */
function contains(ring: THREE.Vector2[]): boolean {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [a, b] = [ring[i], ring[j]];
    if (a.y > 0 !== b.y > 0 && 0 < ((b.x - a.x) * -a.y) / (b.y - a.y) + a.x) inside = !inside;
  }
  return inside;
}
