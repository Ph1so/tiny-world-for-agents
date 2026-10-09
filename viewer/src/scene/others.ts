// Multi-agent runs: every agent but the followed one, as a tinted copy of the agent model with
// a name tag, plus speech bubbles over any agent (the followed one included) for a while after
// it says something.
import * as THREE from "three";
import type { RunData, WorldState } from "../data/run";
import type { AgentEntry } from "../data/types";
import { AgentModel, type PoseKind } from "./agent";

/** Shirt tints, multiplied into the model's colours. */
const TINTS = [0xff9a9a, 0x9affc0, 0xffe08a, 0xc9a6ff, 0x8ad8ff, 0xffb3e6, 0xd2ff8a];

/** An agent's body tint by its place in the run's agent list. The first keeps the plain colours,
 *  so every agent looks the same whichever one the viewer follows. */
export function agentTint(k: number): number { return k <= 0 ? 0xffffff : TINTS[(k - 1) % TINTS.length]; }
/** World steps a bubble stays up after the words were said. */
const BUBBLE_STEPS = 14;

function canvasSprite(draw: (ctx: CanvasRenderingContext2D, c: HTMLCanvasElement) => void, w: number, h: number): THREE.Sprite {
  const c = document.createElement("canvas");
  c.width = w; c.height = h;
  draw(c.getContext("2d")!, c);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: false, fog: false }));
  s.renderOrder = 5;
  return s;
}

function tag(text: string, color: string): THREE.Sprite {
  const s = canvasSprite((ctx, c) => {
    ctx.font = "bold 36px system-ui, sans-serif";
    ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillStyle = "rgba(20, 22, 34, 0.55)";
    const w = Math.min(c.width - 4, ctx.measureText(text).width + 28);
    ctx.beginPath(); ctx.roundRect((c.width - w) / 2, 6, w, c.height - 12, 18); ctx.fill();
    ctx.fillStyle = color;
    ctx.fillText(text, c.width / 2, c.height / 2 + 1);
  }, 320, 64);
  s.scale.set(2.2, 0.44, 1);
  return s;
}

function wrap(ctx: CanvasRenderingContext2D, text: string, width: number, maxLines: number): string[] {
  const words = text.split(" "), lines: string[] = [];
  let cur = "";
  for (const w of words) {
    const next = cur ? cur + " " + w : w;
    if (ctx.measureText(next).width > width && cur) { lines.push(cur); cur = w; } else cur = next;
    if (lines.length === maxLines) break;
  }
  if (lines.length < maxLines && cur) lines.push(cur);
  if (lines.length === maxLines && words.join(" ").length > lines.join(" ").length) lines[maxLines - 1] += "…";
  return lines;
}

function bubble(text: string): THREE.Sprite {
  const s = canvasSprite((ctx, c) => {
    ctx.font = "30px system-ui, sans-serif";
    const lines = wrap(ctx, text, c.width - 48, 4);
    const h = 26 + lines.length * 38;
    ctx.fillStyle = "rgba(255, 255, 255, 0.94)";
    ctx.strokeStyle = "rgba(40, 40, 60, 0.35)"; ctx.lineWidth = 3;
    ctx.beginPath(); ctx.roundRect(6, 6, c.width - 12, h, 22); ctx.fill(); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(c.width / 2 - 16, h + 5); ctx.lineTo(c.width / 2, h + 26); ctx.lineTo(c.width / 2 + 16, h + 5); ctx.fill();
    ctx.fillStyle = "#1f2233"; ctx.textBaseline = "top";
    lines.forEach((l, k) => ctx.fillText(l, 24, 20 + k * 38));
  }, 512, 200);
  s.scale.set(4.4, 1.72, 1);
  s.center.set(0.5, 0);
  return s;
}

interface Other {
  model: AgentModel;
  tag: THREE.Sprite;
  yaw: number;
  health: number;
}

export class OthersLayer {
  group = new THREE.Group();
  private others = new Map<number, Other>();
  private bubbles = new Map<number, { key: string; sprite: THREE.Sprite }>();
  private material: THREE.MeshLambertMaterial;

  constructor(shared: THREE.MeshLambertMaterial) {
    this.material = shared;
  }

  private ensure(e: AgentEntry, k: number): Other {
    let o = this.others.get(e.id);
    if (o) return o;
    const model = new AgentModel(this.material);
    const tint = agentTint(k);
    model.group.traverse((m) => {
      const mesh = m as THREE.Mesh;
      const mat = mesh.material as THREE.MeshLambertMaterial | undefined;
      if (mat && mat.vertexColors && mat.color) mat.color.setHex(tint);
    });
    const t = tag(`${e.name ?? "agent"} #${e.id}`, "#" + tint.toString(16).padStart(6, "0"));
    this.group.add(model.group, t);
    o = { model, tag: t, yaw: 0, health: e.health };
    this.others.set(e.id, o);
    return o;
  }

  /** Place everyone for fractional step f between states a and b. primaryPos is where the
   *  followed agent is drawn (for its bubble). */
  update(run: RunData, a: WorldState, b: WorldState, f: number, time: number, dt: number,
         primaryPos: THREE.Vector3): void {
    const list = a.agents ?? [];
    const seen = new Set<number>();
    list.forEach((e, k) => {
      if (e.id === run.primaryAgent) return;
      const o = this.ensure(e, k);
      seen.add(e.id);
      o.model.group.visible = o.tag.visible = e.alive;
      if (!e.alive) return;
      const n = b.agents?.find((q) => q.id === e.id) ?? e;
      const p = e.pos, q = n.pos;
      const x = p[0] + (q[0] - p[0]) * f, y = p[1] + (q[1] - p[1]) * f, z = p[2] + (q[2] - p[2]) * f;
      const dx = q[0] - p[0], dz = q[2] - p[2];
      if (dx || dz) o.yaw = Math.atan2(-dx, -dz);
      o.model.group.position.set(x + 0.5, y, z + 0.5);
      o.model.group.rotation.y = o.yaw;
      if (e.health < o.health) o.model.flash(time);
      o.health = e.health;
      const step = run.agentStepAt(e.id, a.t);
      let pose: PoseKind = dx || dz ? "walk" : "idle";
      if (!(dx || dz) && step) {
        const name = String(step.action?.name ?? "");
        if (a.t >= step.t_end) pose = "think";
        else if (name === "mine" || name === "attack" || name === "craft" || name === "eat" || name === "place") pose = name;
      }
      o.model.request(pose, time);
      o.model.update(time, dt);
      o.tag.position.set(x + 0.5, y + 2.25, z + 0.5);
    });
    for (const [id, o] of this.others) if (!seen.has(id)) o.model.group.visible = o.tag.visible = false;
    this.updateBubbles(run, a, f, primaryPos);
  }

  private updateBubbles(run: RunData, a: WorldState, f: number, primaryPos: THREE.Vector3): void {
    const t = a.t + f;
    const live = new Set<number>();
    for (let k = run.says.length - 1; k >= 0; k--) {
      const e = run.says[k];
      if (e.t > t) continue;
      if (e.t < t - BUBBLE_STEPS) break;
      const id = Number(e.detail.agent);
      if (live.has(id)) continue;
      live.add(id);
      const key = `${e.t}:${String(e.detail.text)}`;
      let bub = this.bubbles.get(id);
      if (!bub || bub.key !== key) {
        if (bub) this.group.remove(bub.sprite);
        bub = { key, sprite: bubble(String(e.detail.text)) };
        this.bubbles.set(id, bub);
        this.group.add(bub.sprite);
      }
      const pos = id === run.primaryAgent ? primaryPos : this.others.get(id)?.model.group.position;
      if (pos) {
        const dx = id === run.primaryAgent ? 0.5 : 0, dz = id === run.primaryAgent ? 0.5 : 0;
        bub.sprite.position.set(pos.x + dx, pos.y + 2.6, pos.z + dz);
        bub.sprite.visible = true;
      }
    }
    for (const [id, bub] of this.bubbles) if (!live.has(id)) bub.sprite.visible = false;
  }
}
