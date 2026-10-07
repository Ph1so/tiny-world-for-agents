// The 3D view of one run: renderer, cameras, terrain, creatures, sky. render(pt) draws the
// world at fractional world step pt, interpolating agent and creature positions.
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import type { RunData, WorldState } from "../data/run";
import { Creatures } from "./creatures";
import { Sky } from "./sky";
import { Terrain } from "./terrain";

export type CameraMode = "orbit" | "follow" | "top";

export class SceneView {
  canvas: HTMLCanvasElement;
  renderer: THREE.WebGLRenderer;
  scene = new THREE.Scene();
  persp: THREE.PerspectiveCamera;
  ortho: THREE.OrthographicCamera;
  controls: OrbitControls;
  topControls: OrbitControls;
  mode: CameraMode = "orbit";
  terrain: Terrain;
  creatures: Creatures;
  sky: Sky | null = null;
  run: RunData;
  private timer = new THREE.Timer();
  private agentPos = new THREE.Vector3();
  private agentPrev = new THREE.Vector3();
  private agentYaw = 0;
  private creatureYaw = new Map<number, number>();
  private followOffset = new THREE.Vector3(10, 12, 10);
  private tmp = new THREE.Vector3();
  private initialised = false;
  private lastDrawCalls = 0;
  /** Set to false to skip rendering while hidden. */
  active = true;

  constructor(canvas: HTMLCanvasElement, run: RunData) {
    this.canvas = canvas;
    this.run = run;
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: true, powerPreference: "high-performance" });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFShadowMap;
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.persp = new THREE.PerspectiveCamera(45, 1, 0.5, 600);
    this.ortho = new THREE.OrthographicCamera(-40, 40, 40, -40, 0.1, 400);
    this.controls = new OrbitControls(this.persp, canvas);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.1;
    this.controls.maxPolarAngle = Math.PI * 0.49;
    this.controls.minDistance = 4;
    this.controls.maxDistance = 220;
    this.topControls = new OrbitControls(this.ortho, canvas);
    this.topControls.enableRotate = false;
    this.topControls.enableDamping = true;
    this.topControls.enabled = false;
    this.topControls.screenSpacePanning = true;
    this.terrain = new Terrain(run);
    this.creatures = new Creatures();
    this.scene.add(this.terrain.group, this.creatures.group);
    this.resize();
  }

  /** Call when the snapshot is in. Builds terrain and places cameras. */
  init(): void {
    if (this.initialised) return;
    this.initialised = true;
    const run = this.run;
    const [sx, sy, sz] = run.size;
    this.terrain.init();
    this.sky = new Sky(run.size);
    this.scene.add(this.sky.group);
    this.scene.fog = this.sky.fog;
    this.sky.setTorches(this.terrain.torches.values());
    this.terrain.torchesChanged = false;
    const spawn = run.snapshot?.spawn ?? [sx / 2, sy / 2, sz / 2];
    this.agentPos.set(spawn[0], spawn[1], spawn[2]);
    this.agentPrev.copy(this.agentPos);
    this.controls.target.set(spawn[0] + 0.5, spawn[1] + 1, spawn[2] + 0.5);
    this.persp.position.set(spawn[0] + 22, spawn[1] + 18, spawn[2] + 26);
    this.controls.update();
    this.ortho.position.set(sx / 2, sy + 60, sz / 2);
    this.ortho.up.set(0, 0, -1);
    this.ortho.lookAt(sx / 2, 0, sz / 2);
    this.topControls.target.set(sx / 2, 0, sz / 2);
    this.topControls.update();
    this.resize();
  }

  setMode(mode: CameraMode): void {
    this.mode = mode;
    this.controls.enabled = mode !== "top";
    this.topControls.enabled = mode === "top";
    if (mode === "follow" && this.initialised) this.followOffset.copy(this.persp.position).sub(this.controls.target);
    this.resize();
  }

  resize(): void {
    const w = this.canvas.clientWidth || 800, h = this.canvas.clientHeight || 600;
    this.renderer.setSize(w, h, false);
    this.persp.aspect = w / h;
    this.persp.updateProjectionMatrix();
    const [sx, , sz] = this.run.size;
    const half = Math.max(sx, sz) * 0.55;
    const aspect = w / h;
    this.ortho.left = -half * Math.max(1, aspect); this.ortho.right = half * Math.max(1, aspect);
    this.ortho.top = half * Math.max(1, 1 / aspect); this.ortho.bottom = -half * Math.max(1, 1 / aspect);
    this.ortho.updateProjectionMatrix();
  }

  get camera(): THREE.Camera { return this.mode === "top" ? this.ortho : this.persp; }

  /** Draw the world at fractional step pt. */
  render(pt: number): void {
    const run = this.run;
    if (!run.ready) return;
    if (!this.initialised) this.init();
    this.timer.update();
    const dt = Math.min(0.1, this.timer.getDelta());
    const time = this.timer.getElapsed();
    const t0 = Math.floor(pt), t1 = Math.min(run.maxT, t0 + 1);
    const f = Math.min(1, Math.max(0, pt - t0));
    run.setBlocksT(t0);
    if (this.terrain.flush() > 0 || this.terrain.torchesChanged) {
      if (this.terrain.torchesChanged && this.sky) { this.sky.setTorches(this.terrain.torches.values()); this.terrain.torchesChanged = false; }
    }
    const a = run.stateAt(t0), b = run.stateAt(t1) ?? a;
    if (a && b) this.placeActors(a, b, f, time, dt);
    if (this.sky && a) {
      const { dayLength, nightStart, dimSteps } = run.meta;
      const stepInDay = ((pt % dayLength) + dayLength) % dayLength;
      this.sky.update(stepInDay, dayLength, nightStart, dimSteps, a.light, time);
      this.scene.background = this.sky.background;
    }
    if (this.mode === "follow") {
      this.tmp.copy(this.agentPos).addScalar(0.5);
      this.tmp.y += 0.6;
      this.controls.target.lerp(this.tmp, Math.min(1, dt * 6));
      this.persp.position.copy(this.controls.target).add(this.followOffset);
    }
    if (this.mode === "top") this.topControls.update(); else this.controls.update();
    if (this.mode === "follow") this.followOffset.copy(this.persp.position).sub(this.controls.target);
    this.renderer.render(this.scene, this.camera);
    this.lastDrawCalls = this.renderer.info.render.calls;
  }

  get drawCalls(): number { return this.lastDrawCalls; }

  private placeActors(a: WorldState, b: WorldState, f: number, time: number, dt: number): void {
    const pa = a.agent.pos, pb = b.agent.pos;
    const x = pa[0] + (pb[0] - pa[0]) * f, y = pa[1] + (pb[1] - pa[1]) * f, z = pa[2] + (pb[2] - pa[2]) * f;
    const dx = pb[0] - pa[0], dz = pb[2] - pa[2];
    const moving = (dx !== 0 || dz !== 0) ? 1 : 0;
    if (moving) this.agentYaw = Math.atan2(-dx, -dz);   // model faces -z
    this.agentPos.set(x, y, z);
    this.creatures.setAgent(x, y, z, this.agentYaw, moving, time);
    this.agentPrev.lerp(this.agentPos, Math.min(1, dt * 10));

    const cr = this.creatures;
    cr.beginFrame();
    const bs = b.creatures;
    for (let i = 0; i < a.creatures.length; i++) {
      const c = a.creatures[i];
      let q: [number, number, number] = c.pos;
      // Find the same creature in the next step. Lists are small and mostly in the same order.
      let n = bs[i] && bs[i].id === c.id ? bs[i] : undefined;
      if (!n) for (let j = 0; j < bs.length; j++) if (bs[j].id === c.id) { n = bs[j]; break; }
      if (n) q = n.pos;
      const cx = c.pos[0] + (q[0] - c.pos[0]) * f, cy = c.pos[1] + (q[1] - c.pos[1]) * f, cz = c.pos[2] + (q[2] - c.pos[2]) * f;
      const ddx = q[0] - c.pos[0], ddz = q[2] - c.pos[2];
      let yaw = this.creatureYaw.get(c.id) ?? (c.id * 2.1) % (Math.PI * 2);
      if (ddx !== 0 || ddz !== 0) { yaw = Math.atan2(-ddx, -ddz); this.creatureYaw.set(c.id, yaw); }
      cr.setInstance(c.kind, c.id, cx, cy, cz, yaw, time);
    }
    cr.endFrame();
  }

  get agentWorldPos(): THREE.Vector3 { return this.agentPos; }

  dispose(): void {
    this.controls.dispose();
    this.topControls.dispose();
    this.renderer.dispose();
  }
}
