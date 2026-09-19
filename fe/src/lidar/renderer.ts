import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { ObjectLayer, disposeTree } from '../objects/layer';
import type { RoomScene } from '../rooms/api';
import type { LidarBatch, Pose } from './protocol';

export type ViewMode = 'orbit' | 'top' | 'follow';
export type ColorMode = 'height' | 'age';

export type CloudStats = {
  points: number;
  capacity: number;
  pointsPerSecond: number;
  fps: number;
  pose: Pose | null;
  lastBatchAt: number;
};

const CAPACITY = 400_000;
const TRAIL = 600;

const vertexShader = /* glsl */ `
  attribute float birth;
  uniform float now;
  uniform float size;
  uniform float scale;
  uniform float colorMode;
  varying vec3 vColor;

  void main() {
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    float age = now - birth;
    float fresh = clamp(1.0 - age / 1.2, 0.0, 1.0);

    vec3 low = vec3(0.34, 0.39, 0.86);
    vec3 mid = vec3(0.80, 0.86, 1.0);
    vec3 high = vec3(1.0);
    float h = clamp(position.y / 2.4, 0.0, 1.0);
    vec3 byHeight = h < 0.5 ? mix(low, mid, h * 2.0) : mix(mid, high, (h - 0.5) * 2.0);
    vec3 byAge = mix(vec3(0.30, 0.35, 0.82), vec3(0.85, 0.89, 1.0), exp(-age / 20.0));
    vec3 base = colorMode < 0.5 ? byHeight : byAge;

    vColor = mix(base, vec3(1.0), fresh * 0.85);
    gl_PointSize = clamp(size * (1.0 + fresh * 0.8) * scale / -mv.z, 1.0, 8.0);
    gl_Position = projectionMatrix * mv;
  }
`;

const fragmentShader = /* glsl */ `
  varying vec3 vColor;
  void main() {
    gl_FragColor = vec4(vColor, 1.0);
  }
`;

export class LidarRenderer {
  private renderer: THREE.WebGLRenderer;
  private scene = new THREE.Scene();
  private camera = new THREE.PerspectiveCamera(50, 1, 0.05, 200);
  private controls: OrbitControls;
  private positions = new Float32Array(CAPACITY * 3);
  private births = new Float32Array(CAPACITY);
  private geometry = new THREE.BufferGeometry();
  private material: THREE.ShaderMaterial;
  private robot = new THREE.Group();
  private trail: THREE.Line;
  private trailPoints = new Float32Array(TRAIL * 3);
  private trailCount = 0;
  private head = 0;
  private filled = 0;
  private clock = new THREE.Clock();
  private paused = false;
  private view: ViewMode = 'orbit';
  private pose: Pose | null = null;
  private rateWindow: { t: number; n: number }[] = [];
  private frames: number[] = [];
  private lastBatchAt = 0;
  private resize: ResizeObserver;
  private goal: { x: number; z: number } | null = null;
  private goalMarker = new THREE.Group();
  private goalLine: THREE.Line;
  private pick: ((point: { x: number; z: number }) => void) | null = null;
  private pressedAt: { x: number; y: number } | null = null;
  private roomMesh: THREE.Group | null = null;
  private meshVertices = 0;
  private meshGeneration = 0;
  private objectLayer = new ObjectLayer();

  constructor(private host: HTMLElement) {
    this.renderer = new THREE.WebGLRenderer({ antialias: false, alpha: true });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    this.renderer.setClearColor(0x000000, 0);
    host.appendChild(this.renderer.domElement);
    this.renderer.domElement.style.display = 'block';

    this.camera.position.set(6.5, 5.5, 7.5);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.08;
    this.controls.maxPolarAngle = Math.PI * 0.495;
    this.controls.minDistance = 1;
    this.controls.maxDistance = 60;

    const position = new THREE.BufferAttribute(this.positions, 3).setUsage(THREE.DynamicDrawUsage);
    const birth = new THREE.BufferAttribute(this.births, 1).setUsage(THREE.DynamicDrawUsage);
    this.geometry.setAttribute('position', position);
    this.geometry.setAttribute('birth', birth);
    this.geometry.setDrawRange(0, 0);
    this.material = new THREE.ShaderMaterial({
      vertexShader,
      fragmentShader,
      uniforms: {
        now: { value: 0 },
        size: { value: 0.028 },
        scale: { value: 800 },
        colorMode: { value: 0 },
      },
    });
    const cloud = new THREE.Points(this.geometry, this.material);
    cloud.frustumCulled = false;
    this.scene.add(cloud);

    const grid = new THREE.GridHelper(24, 24, 0xffffff, 0xffffff);
    const gridMaterial = grid.material as THREE.Material;
    gridMaterial.transparent = true;
    gridMaterial.opacity = 0.1;
    this.scene.add(grid);

    this.scene.add(this.objectLayer.group);
    this.buildRobot();
    const trailGeometry = new THREE.BufferGeometry();
    trailGeometry.setAttribute('position', new THREE.BufferAttribute(this.trailPoints, 3));
    trailGeometry.setDrawRange(0, 0);
    this.trail = new THREE.Line(
      trailGeometry,
      new THREE.LineBasicMaterial({ color: 0xeb1700, transparent: true, opacity: 0.8 }),
    );
    this.trail.frustumCulled = false;
    this.scene.add(this.trail);

    this.goalLine = this.buildGoal();
    const canvas = this.renderer.domElement;
    canvas.addEventListener('pointerdown', this.onPointerDown);
    canvas.addEventListener('pointerup', this.onPointerUp);

    this.resize = new ResizeObserver(() => this.fit());
    this.resize.observe(host);
    this.fit();
    this.renderer.setAnimationLoop(() => this.render());
  }

  private buildRobot(): void {
    const line = (geometry: THREE.BufferGeometry, color: number) =>
      new THREE.LineSegments(new THREE.EdgesGeometry(geometry), new THREE.LineBasicMaterial({ color }));
    const body = line(new THREE.BoxGeometry(0.46, 0.3, 0.4), 0xffffff);
    body.position.y = 0.2;
    const mast = line(new THREE.BoxGeometry(0.08, 0.5, 0.08), 0xffffff);
    mast.position.y = 0.6;
    const nose = new THREE.Mesh(
      new THREE.BoxGeometry(0.1, 0.1, 0.1),
      new THREE.MeshBasicMaterial({ color: 0xeb1700 }),
    );
    nose.position.set(0.3, 0.2, 0);
    this.robot.add(body, mast, nose);
    this.robot.visible = false;
    this.scene.add(this.robot);
  }

  private buildGoal(): THREE.Line {
    const white = new THREE.LineBasicMaterial({ color: 0xffffff });
    const ring = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.PlaneGeometry(0.5, 0.5)), white);
    ring.rotation.x = -Math.PI / 2;
    ring.position.y = 0.01;
    const pole = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(0, 0, 0), new THREE.Vector3(0, 1.2, 0)]),
      white,
    );
    const flag = new THREE.Mesh(new THREE.PlaneGeometry(0.22, 0.14), new THREE.MeshBasicMaterial({ color: 0xeb1700, side: THREE.DoubleSide }));
    flag.position.set(0.11, 1.13, 0);
    this.goalMarker.add(ring, pole, flag);
    this.goalMarker.visible = false;
    this.scene.add(this.goalMarker);

    const line = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3()]),
      new THREE.LineDashedMaterial({ color: 0xffffff, dashSize: 0.12, gapSize: 0.08, transparent: true, opacity: 0.7 }),
    );
    line.visible = false;
    line.frustumCulled = false;
    this.scene.add(line);
    return line;
  }

  /** While set, a click (not a drag) on the floor calls back with the world point. */
  setPicking(callback: ((point: { x: number; z: number }) => void) | null): void {
    this.pick = callback;
    this.renderer.domElement.style.cursor = callback ? 'crosshair' : '';
  }

  private onPointerDown = (event: PointerEvent) => {
    this.pressedAt = { x: event.clientX, y: event.clientY };
  };

  private onPointerUp = (event: PointerEvent) => {
    const start = this.pressedAt;
    this.pressedAt = null;
    if (!this.pick || !start || Math.hypot(event.clientX - start.x, event.clientY - start.y) > 5) return;
    const rect = this.renderer.domElement.getBoundingClientRect();
    const ndc = new THREE.Vector2(
      ((event.clientX - rect.left) / rect.width) * 2 - 1,
      -((event.clientY - rect.top) / rect.height) * 2 + 1,
    );
    const ray = new THREE.Raycaster();
    ray.setFromCamera(ndc, this.camera);
    const hit = ray.ray.intersectPlane(new THREE.Plane(new THREE.Vector3(0, 1, 0), 0), new THREE.Vector3());
    if (hit) this.pick({ x: +hit.x.toFixed(3), z: +hit.z.toFixed(3) });
  };

  setGoal(goal: { x: number; z: number } | null): void {
    this.goal = goal;
    this.goalMarker.visible = !!goal;
    if (goal) this.goalMarker.position.set(goal.x, 0, goal.z);
  }

  private updateGoalLine(): void {
    const show = !!(this.goal && this.pose);
    this.goalLine.visible = show;
    if (!show || !this.goal || !this.pose) return;
    const attribute = this.goalLine.geometry.getAttribute('position') as THREE.BufferAttribute;
    attribute.setXYZ(0, this.pose.x, 0.02, this.pose.z);
    attribute.setXYZ(1, this.goal.x, 0.02, this.goal.z);
    attribute.needsUpdate = true;
    this.goalLine.computeLineDistances();
  }

  private fit(): void {
    const { clientWidth: w, clientHeight: h } = this.host;
    if (!w || !h) return;
    this.renderer.setSize(w, h, false);
    this.renderer.domElement.style.width = `${w}px`;
    this.renderer.domElement.style.height = `${h}px`;
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.material.uniforms.scale.value = h * this.renderer.getPixelRatio() * 0.9;
  }

  ingest(batch: LidarBatch): void {
    if (this.paused) return;
    if (batch.reset) this.clear();
    if (batch.pose) this.setPose(batch.pose);
    const count = batch.xyz.length / 3;
    if (!count) return;

    const now = this.clock.getElapsedTime();
    const position = this.geometry.getAttribute('position') as THREE.BufferAttribute;
    const birth = this.geometry.getAttribute('birth') as THREE.BufferAttribute;
    const src = count > CAPACITY ? batch.xyz.subarray((count - CAPACITY) * 3) : batch.xyz;
    const n = src.length / 3;
    const start = this.head;
    const firstRun = Math.min(n, CAPACITY - start);

    this.positions.set(src.subarray(0, firstRun * 3), start * 3);
    this.births.fill(now, start, start + firstRun);
    if (n > firstRun) {
      this.positions.set(src.subarray(firstRun * 3), 0);
      this.births.fill(now, 0, n - firstRun);
    }
    for (const attribute of [position, birth]) {
      const size = attribute.itemSize;
      attribute.addUpdateRange(start * size, firstRun * size);
      if (n > firstRun) attribute.addUpdateRange(0, (n - firstRun) * size);
      attribute.needsUpdate = true;
    }

    this.head = (start + n) % CAPACITY;
    this.filled = Math.min(CAPACITY, this.filled + n);
    this.geometry.setDrawRange(0, this.filled);
    this.rateWindow.push({ t: performance.now(), n });
    this.lastBatchAt = performance.now();
  }

  private setPose(pose: Pose): void {
    this.pose = pose;
    this.robot.visible = true;
    this.robot.position.set(pose.x, pose.y, pose.z);
    this.robot.rotation.y = pose.yaw;

    const last = this.trailCount - 1;
    const moved =
      last < 0 ||
      Math.hypot(this.trailPoints[last * 3] - pose.x, this.trailPoints[last * 3 + 2] - pose.z) > 0.04;
    if (!moved) return;
    if (this.trailCount === TRAIL) {
      this.trailPoints.copyWithin(0, 3);
      this.trailCount -= 1;
    }
    this.trailPoints.set([pose.x, pose.y + 0.01, pose.z], this.trailCount * 3);
    this.trailCount += 1;
    const attribute = this.trail.geometry.getAttribute('position') as THREE.BufferAttribute;
    attribute.needsUpdate = true;
    this.trail.geometry.setDrawRange(0, this.trailCount);
  }

  clear(): void {
    this.head = 0;
    this.filled = 0;
    this.trailCount = 0;
    this.geometry.setDrawRange(0, 0);
    this.trail.geometry.setDrawRange(0, 0);
  }

  async loadRoomScene(data: RoomScene): Promise<void> {
    const generation = ++this.meshGeneration;
    const gltf = await new GLTFLoader().parseAsync(data.mesh, '');
    if (generation !== this.meshGeneration) {
      disposeTree(gltf.scene);
      return;
    }
    const first = !this.roomMesh;
    if (this.roomMesh) {
      this.scene.remove(this.roomMesh);
      disposeTree(this.roomMesh);
    }
    this.roomMesh = gltf.scene;
    this.meshVertices = 0;
    this.roomMesh.traverse((object) => {
      if (!(object instanceof THREE.Mesh)) return;
      this.meshVertices += object.geometry.getAttribute('position')?.count ?? 0;
      const materials = Array.isArray(object.material) ? object.material : [object.material];
      materials.forEach((material) => material.dispose());
      object.material = new THREE.MeshBasicMaterial({
        color: 0xd8e0ff, wireframe: true, transparent: true, opacity: 0.45,
      });
    });
    this.scene.add(this.roomMesh);
    this.objectLayer.update(data.objects);
    const bounds = new THREE.Box3().setFromObject(this.roomMesh);
    if (first && !bounds.isEmpty()) {
      this.controls.target.copy(bounds.getCenter(new THREE.Vector3()));
      this.setView(this.view);
    }
    this.lastBatchAt = performance.now();
  }

  selectObject(id: string | null): void {
    this.objectLayer.select(id);
    const object = this.objectLayer.group.children.find((item) => item.userData.objectId === id);
    if (object) {
      const direction = this.camera.position.clone().sub(this.controls.target).normalize();
      const size = new THREE.Box3().setFromObject(object).getSize(new THREE.Vector3()).length();
      this.controls.target.copy(object.position);
      this.camera.position.copy(object.position).addScaledVector(direction, Math.max(2, size * 2));
    }
  }

  cancelSceneLoad(): void {
    ++this.meshGeneration;
  }

  clearRoomMesh(): void {
    ++this.meshGeneration;
    if (this.roomMesh) {
      this.scene.remove(this.roomMesh);
      disposeTree(this.roomMesh);
    }
    this.roomMesh = null;
    this.meshVertices = 0;
    this.objectLayer.update([]);
  }

  setPaused(paused: boolean): void {
    this.paused = paused;
  }

  setColorMode(mode: ColorMode): void {
    this.material.uniforms.colorMode.value = mode === 'height' ? 0 : 1;
  }

  setView(mode: ViewMode): void {
    this.view = mode;
    const target = this.controls.target;
    this.controls.enableRotate = mode !== 'top';
    if (mode === 'top') {
      this.camera.position.set(target.x, target.y + 14, target.z + 0.001);
    } else if (mode === 'follow' && this.pose) {
      target.set(this.pose.x, 0.3, this.pose.z);
      const back = new THREE.Vector3(-Math.cos(this.pose.yaw), 0, Math.sin(this.pose.yaw));
      this.camera.position.copy(target).addScaledVector(back, 4).add(new THREE.Vector3(0, 2.4, 0));
    } else if (mode === 'orbit') {
      this.camera.position.set(target.x + 6.5, 5.5, target.z + 7.5);
    }
  }

  stats(): CloudStats {
    const now = performance.now();
    this.rateWindow = this.rateWindow.filter((entry) => now - entry.t < 1000);
    this.frames = this.frames.filter((t) => now - t < 1000);
    return {
      points: this.filled || this.meshVertices,
      capacity: CAPACITY,
      pointsPerSecond: this.rateWindow.reduce((sum, entry) => sum + entry.n, 0),
      fps: this.frames.length,
      pose: this.pose,
      lastBatchAt: this.lastBatchAt,
    };
  }

  private render(): void {
    this.frames.push(performance.now());
    if (this.view === 'follow' && this.pose) {
      const target = this.controls.target;
      const desired = new THREE.Vector3(this.pose.x, 0.3, this.pose.z);
      const delta = desired.sub(target).multiplyScalar(0.12);
      target.add(delta);
      this.camera.position.add(delta);
    }
    this.updateGoalLine();
    this.material.uniforms.now.value = this.clock.getElapsedTime();
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
  }

  dispose(): void {
    this.clearRoomMesh();
    this.renderer.setAnimationLoop(null);
    this.resize.disconnect();
    this.renderer.domElement.removeEventListener('pointerdown', this.onPointerDown);
    this.renderer.domElement.removeEventListener('pointerup', this.onPointerUp);
    this.controls.dispose();
    this.geometry.dispose();
    this.material.dispose();
    this.renderer.dispose();
    this.renderer.domElement.remove();
  }
}
