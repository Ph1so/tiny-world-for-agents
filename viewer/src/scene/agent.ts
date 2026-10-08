// The agent: a body with jointed arms and legs, a pickaxe or block it can hold, and a red flash
// when hurt. The view picks a pose for the current action; the model eases its joints toward it
// so poses blend instead of snapping, and holds a short action for long enough to be seen.
import * as THREE from "three";
import { Builder, xrayMaterial } from "./builder";
import { CREATURE_COLORS as C } from "./palette";

export type PoseKind = "idle" | "walk" | "mine" | "place" | "craft" | "eat" | "attack" | "think";

/** Pickaxe head colour by tier (1 wood, 2 stone, 3 iron). */
const PICK_HEAD = [0, 0xc99a62, 0x9fa2b2, 0xe4e4ee];
/** Seconds an action pose stays up after its step ends, so a one step action is still visible. */
const HOLD = 0.6;
const ACTIONS = new Set<PoseKind>(["mine", "place", "craft", "eat", "attack"]);

// Front is -z (north). Faces sit on the -z side of heads.
function bodyGeometry(): THREE.BufferGeometry {
  const b = new Builder();
  b.add(0, 0.65, 0, 0.5, 0.5, 0.3, C.agentShirt, 0.06);                 // body
  b.add(0, 1.25, 0, 0.62, 0.6, 0.62, C.agentSkin, 0.08);                 // head
  b.add(0, 1.52, 0.03, 0.66, 0.16, 0.66, C.agentHair, 0.05);             // hair
  b.add(0, 1.34, -0.26, 0.66, 0.2, 0.14, C.agentHair, 0.04);             // fringe
  b.add(-0.14, 1.26, -0.32, 0.1, 0.12, 0.04, C.eye, 0, false);           // eyes
  b.add(0.14, 1.26, -0.32, 0.1, 0.12, 0.04, C.eye, 0, false);
  b.add(0, 1.1, -0.32, 0.16, 0.05, 0.04, C.mouth, 0, false);             // mouth
  b.add(-0.22, 1.16, -0.315, 0.1, 0.06, 0.03, 0xf4a8a0, 0, false);       // blush
  b.add(0.22, 1.16, -0.315, 0.1, 0.06, 0.03, 0xf4a8a0, 0, false);
  return b.build();
}

/** An arm hanging from its shoulder pivot at the origin. */
function armGeometry(): THREE.BufferGeometry {
  return new Builder()
    .add(0, -0.22, 0, 0.14, 0.44, 0.16, C.agentShirt, 0.04)
    .add(0, -0.48, 0, 0.13, 0.1, 0.15, C.agentSkin, 0.03)
    .build();
}

/** A leg hanging from its hip pivot at the origin. */
function legGeometry(): THREE.BufferGeometry {
  return new Builder().add(0, -0.2, 0, 0.18, 0.4, 0.2, C.agentPants, 0.04).build();
}

function handleGeometry(): THREE.BufferGeometry {
  return new Builder().add(0, 0, -0.2, 0.05, 0.05, 0.5, 0x9b6b43, 0.02).build();
}

interface Joints { armLX: number; armLZ: number; armRX: number; armRZ: number; legL: number; legR: number }

export class AgentModel {
  group = new THREE.Group();
  private material: THREE.MeshLambertMaterial;
  private armL = new THREE.Group();
  private armR = new THREE.Group();
  private legL = new THREE.Group();
  private legR = new THREE.Group();
  private pick = new THREE.Group();
  private pickHeadMat = new THREE.MeshLambertMaterial({ color: PICK_HEAD[1], flatShading: true });
  private held: THREE.Mesh;
  private heldMat = new THREE.MeshLambertMaterial({ color: 0xffffff, flatShading: true });
  private cur: Joints = { armLX: 0, armLZ: 0, armRX: 0, armRZ: 0, legL: 0, legR: 0 };
  private goal: Joints = { armLX: 0, armLZ: 0, armRX: 0, armRZ: 0, legL: 0, legR: 0 };
  private kind: PoseKind = "idle";
  private holdUntil = 0;
  private flashUntil = 0;

  constructor(shared: THREE.MeshLambertMaterial) {
    // Own copy of the material, so the hurt flash does not tint the creatures.
    this.material = shared.clone();
    this.group.name = "agent";
    // Every part carries a silhouette child, so the agent shows through terrain in a tunnel.
    const xray = xrayMaterial(0x5b8cff, 0.55);
    const mesh = (g: THREE.BufferGeometry, m: THREE.Material = this.material) => {
      const x = new THREE.Mesh(g, m);
      x.castShadow = true;
      const ghost = new THREE.Mesh(g, xray);
      ghost.renderOrder = 3;
      x.add(ghost);
      return x;
    };
    this.group.add(mesh(bodyGeometry()));
    const arm = armGeometry(), leg = legGeometry();
    this.armL.position.set(-0.33, 0.88, 0);
    this.armR.position.set(0.33, 0.88, 0);
    this.legL.position.set(-0.12, 0.4, 0);
    this.legR.position.set(0.12, 0.4, 0);
    this.armL.add(mesh(arm));
    this.armR.add(mesh(arm));
    this.legL.add(mesh(leg));
    this.legR.add(mesh(leg));
    this.group.add(this.armL, this.armR, this.legL, this.legR);
    // Pickaxe: handle pointing forward out of the right hand, head across its far end.
    this.pick.add(mesh(handleGeometry()));
    this.pick.add(mesh(new THREE.BoxGeometry(0.07, 0.36, 0.08), this.pickHeadMat));
    this.pick.children[1].position.set(0, 0, -0.43);
    this.pick.position.set(0, -0.48, -0.02);
    this.pick.visible = false;
    this.armR.add(this.pick);
    this.held = mesh(new THREE.BoxGeometry(0.22, 0.22, 0.22), this.heldMat);
    this.held.position.set(0, -0.56, -0.1);
    this.held.visible = false;
    this.armR.add(this.held);
  }

  /** What is in the right hand: a pickaxe of a tier (1 to 3), a block or food of a colour, or nothing. */
  setHeld(pickTier: number, color: number | null): void {
    this.pick.visible = color === null && pickTier > 0;
    if (this.pick.visible) this.pickHeadMat.color.setHex(PICK_HEAD[Math.min(3, pickTier)]);
    this.held.visible = color !== null;
    if (color !== null) this.heldMat.color.setHex(color);
  }

  flash(time: number): void { this.flashUntil = time + 0.35; }

  /** Ask for a pose. A short action keeps its pose for HOLD seconds before going back to idle. */
  request(kind: PoseKind, time: number): void {
    if (kind === this.kind) {
      if (ACTIONS.has(kind)) this.holdUntil = time + HOLD;
      return;
    }
    if (!ACTIONS.has(kind) && kind !== "walk" && time < this.holdUntil) return;
    this.kind = kind;
    this.holdUntil = ACTIONS.has(kind) ? time + HOLD : kind === "walk" ? time + 0.25 : 0;
  }

  get pose(): PoseKind { return this.kind; }

  update(time: number, dt: number): void {
    const g = this.goal;
    g.armLZ = 0.05; g.armRZ = -0.05; g.legL = 0; g.legR = 0;
    switch (this.kind) {
      case "walk": {
        const s = Math.sin(time * 9);
        g.armLX = 0.7 * s; g.armRX = -0.7 * s; g.legL = -0.6 * s; g.legR = 0.6 * s;
        break;
      }
      case "mine":                                   // chop: raised high, down hard, repeat
        g.armRX = 1.5 + 0.9 * Math.sin(time * 12); g.armLX = 0.3;
        break;
      case "place":                                  // reach out and set it down
        g.armRX = 1.35 + 0.15 * Math.sin(time * 8); g.armLX = 0.2;
        break;
      case "craft": {                                // both hands working in front
        const s = Math.sin(time * 14);
        g.armLX = 1.15 + 0.2 * s; g.armRX = 1.15 - 0.2 * s; g.armLZ = 0.35; g.armRZ = -0.35;
        break;
      }
      case "eat":                                    // hand to mouth
        g.armRX = 2.25 + 0.2 * Math.sin(time * 16); g.armRZ = -0.45; g.armLX = 0.1;
        break;
      case "attack":                                 // fast swings
        g.armRX = 0.4 + 1.8 * Math.max(0, Math.sin(time * 15)); g.armLX = -0.2;
        break;
      case "think":                                  // hand on chin while the model answers
        g.armRX = 1.95; g.armRZ = -0.5; g.armLX = 0.75; g.armLZ = 0.45;
        break;
      default:                                       // idle: a little sway
        g.armLX = 0.05 * Math.sin(time * 1.5); g.armRX = -g.armLX;
    }
    const k = Math.min(1, dt * 16), c = this.cur;
    c.armLX += (g.armLX - c.armLX) * k; c.armLZ += (g.armLZ - c.armLZ) * k;
    c.armRX += (g.armRX - c.armRX) * k; c.armRZ += (g.armRZ - c.armRZ) * k;
    c.legL += (g.legL - c.legL) * k; c.legR += (g.legR - c.legR) * k;
    this.armL.rotation.set(c.armLX, 0, c.armLZ);
    this.armR.rotation.set(c.armRX, 0, c.armRZ);
    this.legL.rotation.set(c.legL, 0, 0);
    this.legR.rotation.set(c.legR, 0, 0);
    const f = Math.max(0, (this.flashUntil - time) / 0.35);
    this.material.emissive.setRGB(0.9 * f, 0.1 * f, 0.1 * f);
  }

  get drawCalls(): number {
    return 5 + (this.pick.visible ? 2 : 0) + (this.held.visible ? 1 : 0);
  }
}
