// The 3D view of one run: renderer, cameras, terrain, creatures, sky, action effects. render(pt)
// draws the world at fractional world step pt, interpolating agent and creature positions and
// animating the agent's current action.
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import type { RunData, WorldState } from "../data/run";
import type { Vec3 } from "../data/types";
import { actionAt, resultFloat, type ActionNow } from "./action";
import type { PoseKind } from "./agent";
import { Creatures } from "./creatures";
import { OthersLayer } from "./others";
import { Effects } from "./fx";
import { BLOCK_COLORS } from "./palette";
import { swatch } from "../ui/panels";
import { Sky } from "./sky";
import { Terrain } from "./terrain";

export type CameraMode = "orbit" | "follow" | "top" | "pov";

/** Colour of what a block drops, where it differs from the block. */
const DROP_COLOR: Record<string, number> = { "coal ore": 0x3d3a45, "berry bush": 0xd8456b };
const FOOD_COLOR: Record<string, number> = { berries: 0xd8456b, "raw meat": 0xe8857c, "cooked meat": 0xa8643f };
const PICK_TIER: Record<string, number> = { "wood pickaxe": 1, "stone pickaxe": 2, "iron pickaxe": 3 };
const POSE: Record<string, PoseKind> = { mine: "mine", place: "place", craft: "craft", eat: "eat", attack: "attack",
  store: "place", take: "place", drop: "place", jump: "place" };
/** Colour of an item for the cube in hand or in flight. */
const itemColor = (name: string): number => {
  if (FOOD_COLOR[name] !== undefined) return FOOD_COLOR[name];
  if (BLOCK_COLORS[name] !== undefined) return BLOCK_COLORS[name];
  const hex = swatch(name).slice(1);
  const full = hex.length === 3 ? hex.split("").map((c) => c + c).join("") : hex;   // "#ccc" style
  return parseInt(full, 16) || 0xcccccc;
};

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
  others = new OthersLayer(new THREE.MeshLambertMaterial({ vertexColors: true, flatShading: true }));
  sky: Sky | null = null;
  run: RunData;
  private timer = new THREE.Timer();
  private agentPos = new THREE.Vector3();
  private agentPrev = new THREE.Vector3();
  private agentYaw = 0;
  private povYaw = 0;
  private bodyYaw = 0;
  private povLook = new THREE.Vector3();
  private moving = 0;
  private followTilt = 0;
  fx = new Effects();
  /** The action on screen this frame, for the panels. */
  act: ActionNow | null = null;
  /** True while a live run waits for the model's next reply. */
  thinking = false;
  private lastT = -1;
  private crossFrom = 0;
  private crossTo = 0;
  private changes: { x: number; y: number; z: number; from: string; to: string }[] = [];
  private lookCell: Vec3 | null = null;
  /** The item of the last action that held one, kept while its pose lingers into the next action. */
  private heldItem = "";
  private lastEmit = 0;
  private chest = new THREE.Vector3();
  private head = new THREE.Vector3();
  private creatureYaw = new Map<number, number>();
  private followOffset = new THREE.Vector3(6, 7, 6);
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
    this.scene.add(this.terrain.group, this.creatures.group, this.fx.group, this.others.group);
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
    if (this.mode === "pov") this.setMode("pov");
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
    this.controls.enabled = mode === "orbit" || mode === "follow";
    this.topControls.enabled = mode === "top";
    // POV: eye height, wider lens, own body hidden, fog at the agent's view radius.
    const pov = mode === "pov";
    this.creatures.agent.visible = !pov;
    this.persp.fov = pov ? 75 : 45;
    this.persp.near = pov ? 0.05 : 0.5;
    this.povYaw = this.agentYaw;
    this.povLook.set(this.agentPos.x + 0.5 - Math.sin(this.povYaw), this.agentPos.y + 1.1, this.agentPos.z + 0.5 - Math.cos(this.povYaw));
    if (this.sky) {
      const r = this.run.meta.viewRadius;
      this.sky.fog.near = pov ? r * 0.5 : 90;
      this.sky.fog.far = pov ? r + 1 : 260;
    }
    if (!pov && this.initialised) {
      // Leave POV with the orbit camera looking at the agent again.
      this.controls.target.copy(this.agentPos).addScalar(0.5);
      this.persp.position.copy(this.controls.target).add(this.followOffset);
    }
    if (mode === "follow" && this.initialised) {
      // Start close enough to see what the agent is doing; the wheel still zooms.
      this.followOffset.copy(this.persp.position).sub(this.controls.target);
      if (this.followOffset.length() > 13) this.followOffset.setLength(13);
    }
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
    this.act = actionAt(run, pt);
    this.collect(t0);
    run.setBlocksT(t0);
    if (this.terrain.flush() > 0 || this.terrain.torchesChanged) {
      if (this.terrain.torchesChanged && this.sky) { this.sky.setTorches(this.terrain.torches.values()); this.terrain.torchesChanged = false; }
    }
    const a = run.stateAt(t0), b = run.stateAt(t1) ?? a;
    if (a && b) this.placeActors(a, b, f, time, dt);
    if (a && b && a.agents) this.others.update(run, a, b, f, time, dt, this.agentPos);
    this.animate(a, time, dt);
    if (this.sky && a) {
      const { dayLength, nightStart, dimSteps } = run.meta;
      const stepInDay = ((pt % dayLength) + dayLength) % dayLength;
      this.sky.update(stepInDay, dayLength, nightStart, dimSteps, a.light, time, a.weather ?? "clear", dt);
      this.scene.background = this.sky.background;
    }
    if (this.mode === "follow") {
      this.tmp.copy(this.agentPos).addScalar(0.5);
      this.tmp.y += 0.6;
      this.controls.target.lerp(this.tmp, Math.min(1, dt * 6));
      this.persp.position.copy(this.controls.target).add(this.followOffset);
    }
    if (this.mode === "pov") {
      // Turn smoothly toward the way the agent faces (the model faces -z at yaw 0), and look at
      // the block it is mining or placing.
      let d = this.agentYaw - this.povYaw;
      d = Math.atan2(Math.sin(d), Math.cos(d));
      this.povYaw += d * Math.min(1, dt * 8);
      this.persp.position.set(this.agentPos.x + 0.5, this.agentPos.y + 1.2, this.agentPos.z + 0.5);
      if (this.lookCell) this.tmp.set(this.lookCell[0] + 0.5, this.lookCell[1] + 0.5, this.lookCell[2] + 0.5);
      else this.tmp.set(-Math.sin(this.povYaw), -0.08, -Math.cos(this.povYaw)).add(this.persp.position);
      this.povLook.lerp(this.tmp, Math.min(1, dt * 8));
      this.persp.lookAt(this.povLook);
    } else if (this.mode === "top") this.topControls.update(); else this.controls.update();
    if (this.mode === "follow") {
      this.followOffset.copy(this.persp.position).sub(this.controls.target);
      // If terrain hides the agent, tilt the camera up (same distance and direction) until it
      // sees over it, toward looking straight down. Eased, for this frame only: the tilt is not
      // baked into the offset, so the camera settles back once the view is clear.
      this.followTilt += (this.neededTilt() - this.followTilt) * Math.min(1, dt * 5);
      if (this.followTilt > 0.002) {
        const o = this.followOffset, d = o.length();
        const az = Math.atan2(o.x, o.z), el = Math.min(1.45, Math.asin(Math.max(-1, Math.min(1, o.y / d))) + this.followTilt);
        this.persp.position.set(this.controls.target.x + d * Math.cos(el) * Math.sin(az),
          this.controls.target.y + d * Math.sin(el), this.controls.target.z + d * Math.cos(el) * Math.cos(az));
        this.persp.lookAt(this.controls.target);
      }
    }
    this.renderer.render(this.scene, this.camera);
    this.lastDrawCalls = this.renderer.info.render.calls;
  }

  get drawCalls(): number { return this.lastDrawCalls; }

  /** Extra elevation (radians) the follow camera needs to see the agent over the terrain. */
  private neededTilt(): number {
    const run = this.run, t = this.controls.target, o = this.followOffset, d = o.length();
    if (d < 0.1) return 0;
    const az = Math.atan2(o.x, o.z), el0 = Math.asin(Math.max(-1, Math.min(1, o.y / d)));
    const blocked = (el: number) => {
      const cx = d * Math.cos(el) * Math.sin(az), cy = d * Math.sin(el), cz = d * Math.cos(el) * Math.cos(az);
      for (let k = 2; k <= 16; k++) {                   // skip the agent's own cell
        const u = k / 16;
        const id = run.blockAt(Math.floor(t.x + cx * u), Math.floor(t.y + cy * u), Math.floor(t.z + cz * u));
        if (id !== 0) {
          const n = run.palette[id];
          if (n !== "leaves" && n !== "water" && n !== "torch") return true;
        }
      }
      return false;
    };
    for (let el = el0; el < 1.45; el += 0.06) if (!blocked(el)) return el - el0;
    return 1.45 - el0;
  }

  private placeActors(a: WorldState, b: WorldState, f: number, time: number, dt: number): void {
    const pa = a.agent.pos, pb = b.agent.pos;
    const x = pa[0] + (pb[0] - pa[0]) * f, y = pa[1] + (pb[1] - pa[1]) * f, z = pa[2] + (pb[2] - pa[2]) * f;
    const dx = pb[0] - pa[0], dz = pb[2] - pa[2];
    const moving = (dx !== 0 || dz !== 0) ? 1 : 0;
    this.moving = moving;
    if (moving) this.agentYaw = Math.atan2(-dx, -dz);   // model faces -z
    else {
      // Face what the action is aimed at: the block being mined or placed, or the creature attacked.
      const act = this.act;
      let tx: number | null = null, tz = 0;
      if (act?.target) { tx = act.target[0]; tz = act.target[2]; }
      else if (act?.creatureId != null) {
        const c = a.creatures.find((q) => q.id === act.creatureId);
        if (c) { tx = c.pos[0]; tz = c.pos[2]; }
      }
      if (tx !== null && (tx !== Math.round(x) || tz !== Math.round(z))) this.agentYaw = Math.atan2(-(tx - x), -(tz - z));
    }
    let dy = this.agentYaw - this.bodyYaw;
    dy = Math.atan2(Math.sin(dy), Math.cos(dy));
    this.bodyYaw += dy * Math.min(1, dt * 12);
    this.agentPos.set(x, y, z);
    this.creatures.setAgent(x, y, z, this.bodyYaw, moving, time);
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

  /** Block changes and world steps passed since the last frame. Only small forward moves count,
   *  so scrubbing or jumping does not set off a pile of effects. Call before setBlocksT. */
  private collect(t0: number): void {
    this.changes.length = 0;
    const from = this.lastT;
    this.lastT = t0;
    this.crossFrom = this.crossTo = 0;
    if (from < 0 || t0 <= from || t0 - from > 8) return;
    this.crossFrom = from + 1;
    this.crossTo = t0;
    const run = this.run;
    for (let k = from + 1; k <= t0; k++) {
      const line = run.worldByT[k];
      if (!line) continue;
      for (const [x, y, z, name] of line.blocks) this.changes.push({ x, y, z, from: run.palette[run.blockAt(x, y, z)] ?? "air", to: name });
    }
  }

  /** Pose the agent for its action and fire the effects for whatever just happened. */
  private animate(a: WorldState | null, time: number, dt: number): void {
    const run = this.run, fx = this.fx, model = this.creatures.agentModel, act = this.act, p = this.agentPos;
    const fwdX = -Math.sin(this.bodyYaw), fwdZ = -Math.cos(this.bodyYaw);
    this.chest.set(p.x + 0.5, p.y + 0.9, p.z + 0.5);
    if (this.mode === "pov") this.head.copy(this.persp.position).addScaledVector(this.persp.getWorldDirection(this.tmp), 2.2).setY(this.persp.position.y - 0.2);
    else this.head.set(p.x + 0.5, p.y + 1.7, p.z + 0.5);

    // Blocks that broke or appeared.
    for (const c of this.changes) {
      const cx = c.x + 0.5, cy = c.y + 0.5, cz = c.z + 0.5;
      const solidBefore = c.from !== "air" && c.from !== "water";
      if (c.to === "air" && solidBefore) {
        fx.burst(cx, cy, cz, BLOCK_COLORS[c.from] ?? 0xaaaaaa, 18, 2.2);
        if (act?.name === "mine") fx.pickup(this.tmp.set(cx, cy, cz), DROP_COLOR[c.from] ?? BLOCK_COLORS[c.from] ?? 0xaaaaaa);
      } else if (c.to !== "air" && c.to !== "water" && !solidBefore) {
        fx.placed(c.x, c.y, c.z);
        fx.burst(cx, c.y + 0.1, cz, BLOCK_COLORS[c.to] ?? 0xaaaaaa, 10, 1.4, 0.5);
      }
    }
    // Events and finished actions in the steps just passed.
    if (this.crossTo > 0) {
      for (const e of run.events) {
        if (e.t < this.crossFrom) continue;
        if (e.t > this.crossTo) break;
        if (e.type === "hurt") { model.flash(time); fx.burst(this.chest.x, this.chest.y, this.chest.z, 0xff5a5a, 12, 1.8, 0.5); }
        else if (e.type === "death") fx.burst(this.chest.x, this.chest.y, this.chest.z, 0xffffff, 36, 3, 0.9);
        else if (e.type === "respawn") fx.burst(this.chest.x, this.chest.y, this.chest.z, 0xffe27a, 28, 2.4, 1.0, 2);
      }
      for (let k = this.crossFrom; k <= this.crossTo; k++) {
        const rec = run.stepRecord(run.agentStepIndexAt(k));
        if (!rec || rec.t_end !== k) continue;
        const fl = resultFloat(rec.result);
        if (fl) fx.float(fl.text, this.head, fl.ok ? "#3b2f52" : "#c0392b");
        const ra = (rec.action ?? {}) as Record<string, unknown>;
        const hx = this.chest.x + fwdX * 0.45, hz = this.chest.z + fwdZ * 0.45;
        if (ra.name === "craft" && fl?.ok) fx.burst(hx, this.chest.y + 0.1, hz, 0xffe27a, 20, 1.8, 0.8, 3, 0.2);
        else if (ra.name === "eat" && fl?.ok) fx.burst(hx, p.y + 1.15, hz, FOOD_COLOR[String(ra.item)] ?? 0xd8456b, 10, 1.2, 0.5);
        else if (ra.name === "mine" && !fl?.ok && typeof ra.x === "number") fx.burst(Number(ra.x) + 0.5, Number(ra.y) + 0.5, Number(ra.z) + 0.5, 0xfff3c4, 8, 2.5, 0.25, 4, 0.1);
        else if ((ra.name === "store" || ra.name === "take") && fl?.ok && typeof ra.x === "number") {
          // One cube per item kind, between the agent's hands and the chest.
          const chest = this.tmp.set(Number(ra.x) + 0.5, Number(ra.y) + 0.8, Number(ra.z) + 0.5).clone();
          const hand = new THREE.Vector3(hx, this.chest.y, hz);
          Object.keys((ra.items ?? {}) as object).slice(0, 4).forEach((name, n) => {
            if (ra.name === "store") fx.pickup(hand, itemColor(name), chest, n * 0.12);
            else fx.pickup(chest, itemColor(name), null, n * 0.12);
          });
        } else if (ra.name === "drop" && fl?.ok) {
          for (const name of Object.keys((ra.items ?? {}) as object).slice(0, 4)) fx.burst(hx, this.chest.y, hz, itemColor(name), 10, 1.2, 0.7);
          fx.burst(hx, p.y + 0.2, hz, 0xd9d4e4, 8, 0.8, 0.5, 2, 0.3);       // a little dust where it lands
        }
        else if (ra.name === "attack" && fl?.ok && a) {
          const c = a.creatures.find((q) => q.id === Number(ra.id));
          if (c) fx.burst(c.pos[0] + 0.5, c.pos[1] + 0.6, c.pos[2] + 0.5, 0xff6b6b, 14, 2, 0.5);
        }
      }
    }

    // The ongoing action: pose, what is in hand, cracks on the block being mined.
    let pose: PoseKind = this.moving ? "walk" : "idle";
    if (act && !this.moving) pose = POSE[act.name] ?? "idle";
    if (this.thinking && (!act || act.done)) pose = "think";
    model.request(pose, time);
    let tier = 0;
    if (a) for (const k in a.agent.inventory) tier = Math.max(tier, PICK_TIER[k] ?? 0);
    const shown = model.pose;
    if (act?.item && POSE[act.name]) this.heldItem = act.item;
    const item = this.heldItem;
    const handsFull = shown === "place" && act?.name !== "take";      // take: hands empty until it is done
    model.setHeld(tier, handsFull ? itemColor(item) : shown === "eat" ? FOOD_COLOR[item] ?? 0xd8456b : null);
    // The chest being used opens its lid toward the agent while the pose lasts.
    const usingChest = shown === "place" && (act?.name === "store" || act?.name === "take") && act.target;
    fx.setLid(usingChest ? act!.target : null, this.chest);
    model.update(time, dt);

    let crack: Vec3 | null = null;
    if (act?.name === "mine" && act.target && !act.done && act.rec.result.startsWith("Got")
        && run.blockAt(act.target[0], act.target[1], act.target[2]) !== 0) crack = act.target;
    fx.setCrack(crack, act?.p ?? 0, time);
    if (crack && time - this.lastEmit > 0.12) {
      this.lastEmit = time;
      const name = run.palette[run.blockAt(crack[0], crack[1], crack[2])];
      fx.burst(crack[0] + 0.5 - fwdX * 0.4, crack[1] + 0.6, crack[2] + 0.5 - fwdZ * 0.4, BLOCK_COLORS[name] ?? 0xaaaaaa, 3, 1.3, 0.35, 9, 0.3);
    }
    if (shown === "eat" && time - this.lastEmit > 0.15) {
      this.lastEmit = time;
      fx.burst(this.chest.x + fwdX * 0.3, p.y + 1.1, this.chest.z + fwdZ * 0.3, FOOD_COLOR[item] ?? 0xd8456b, 2, 0.8, 0.4, 9, 0.1);
    }
    // POV looks at the block being worked on while the pose lasts.
    if (shown !== "mine" && shown !== "place") this.lookCell = null;
    else if (act?.target) this.lookCell = act.target;
    fx.update(time, dt, this.chest);
  }

  get agentWorldPos(): THREE.Vector3 { return this.agentPos; }

  dispose(): void {
    this.controls.dispose();
    this.topControls.dispose();
    this.renderer.dispose();
  }
}
