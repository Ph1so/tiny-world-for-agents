// The creatures, plus the agent model from agent.ts. Each kind is one merged, vertex coloured
// geometry. Creatures of a kind share one InstancedMesh (one draw call per kind). Positions are
// interpolated between steps by the caller; this file only knows how to build and pose them.
import * as THREE from "three";
import { AgentModel } from "./agent";
import { Builder } from "./builder";
import { CREATURE_COLORS as C } from "./palette";

export function sheepGeometry(): THREE.BufferGeometry {
  const b = new Builder();
  for (const [x, z] of [[-0.22, -0.22], [0.22, -0.22], [-0.22, 0.22], [0.22, 0.22]]) b.add(x, 0.14, z, 0.14, 0.28, 0.14, C.sheepLeg, 0.04);
  b.add(0, 0.55, 0.02, 0.76, 0.56, 0.9, C.sheepWool, 0.18);              // woolly body
  b.add(0, 0.72, -0.5, 0.42, 0.4, 0.4, C.sheepFace, 0.1);                // head
  b.add(0, 0.95, -0.42, 0.5, 0.2, 0.34, C.sheepWool, 0.08);              // wool on head
  b.add(-0.26, 0.74, -0.48, 0.1, 0.12, 0.06, C.sheepFace, 0.02);         // ears
  b.add(0.26, 0.74, -0.48, 0.1, 0.12, 0.06, C.sheepFace, 0.02);
  b.add(-0.1, 0.74, -0.71, 0.08, 0.09, 0.03, C.eye, 0, false);           // eyes
  b.add(0.1, 0.74, -0.71, 0.08, 0.09, 0.03, C.eye, 0, false);
  b.add(0, 0.62, -0.71, 0.08, 0.04, 0.03, C.mouth, 0, false);
  return b.build();
}

export function chickenGeometry(): THREE.BufferGeometry {
  const b = new Builder();
  b.add(-0.1, 0.1, 0, 0.06, 0.2, 0.06, C.chickenLeg, 0.01);
  b.add(0.1, 0.1, 0, 0.06, 0.2, 0.06, C.chickenLeg, 0.01);
  b.add(-0.1, 0.01, -0.03, 0.14, 0.03, 0.16, C.chickenLeg, 0.01);        // feet
  b.add(0.1, 0.01, -0.03, 0.14, 0.03, 0.16, C.chickenLeg, 0.01);
  b.add(0, 0.4, 0.02, 0.46, 0.42, 0.56, C.chickenBody, 0.12);            // body
  b.add(-0.26, 0.42, 0.02, 0.08, 0.26, 0.34, C.chickenBody, 0.04);       // wings
  b.add(0.26, 0.42, 0.02, 0.08, 0.26, 0.34, C.chickenBody, 0.04);
  b.add(0, 0.72, -0.26, 0.3, 0.32, 0.3, C.chickenBody, 0.08);            // head
  b.add(0, 0.92, -0.26, 0.1, 0.12, 0.2, C.chickenComb, 0.03);            // comb
  b.add(0, 0.68, -0.46, 0.12, 0.08, 0.12, C.chickenBeak, 0.02);          // beak
  b.add(0, 0.6, -0.42, 0.08, 0.1, 0.06, C.chickenComb, 0.02);            // wattle
  b.add(-0.09, 0.76, -0.415, 0.06, 0.07, 0.03, C.eye, 0, false);
  b.add(0.09, 0.76, -0.415, 0.06, 0.07, 0.03, C.eye, 0, false);
  return b.build();
}

export function zombieGeometry(): THREE.BufferGeometry {
  const b = new Builder();
  b.add(-0.13, 0.2, 0, 0.2, 0.4, 0.22, C.zombiePants, 0.04);
  b.add(0.15, 0.17, 0.04, 0.2, 0.34, 0.22, C.zombiePants, 0.04);         // one short leg, goofy
  b.add(0, 0.66, 0, 0.54, 0.52, 0.32, C.zombieShirt, 0.06);              // body
  b.add(-0.3, 0.78, -0.32, 0.15, 0.15, 0.5, C.zombieShirt, 0.04);        // arms straight out
  b.add(0.3, 0.74, -0.34, 0.15, 0.15, 0.5, C.zombieShirt, 0.04);
  b.add(-0.3, 0.78, -0.6, 0.14, 0.12, 0.1, C.zombieSkin, 0.03);          // hands
  b.add(0.3, 0.74, -0.62, 0.14, 0.12, 0.1, C.zombieSkin, 0.03);
  b.add(0.02, 1.26, 0.02, 0.64, 0.62, 0.64, C.zombieSkin, 0.1);          // head, slightly off centre
  b.add(-0.16, 1.3, -0.33, 0.18, 0.2, 0.04, C.zombieEyeWhite, 0, false); // one big eye
  b.add(-0.15, 1.3, -0.35, 0.09, 0.1, 0.03, C.zombieEye, 0, false);
  b.add(0.16, 1.26, -0.33, 0.11, 0.12, 0.04, C.zombieEyeWhite, 0, false); // one small eye
  b.add(0.17, 1.26, -0.35, 0.05, 0.06, 0.03, C.zombieEye, 0, false);
  b.add(0.04, 1.08, -0.33, 0.24, 0.05, 0.04, C.zombieEye, 0, false);     // crooked smile
  b.add(0.14, 1.11, -0.33, 0.05, 0.08, 0.04, C.zombieEye, 0, false);
  b.add(-0.02, 1.04, -0.34, 0.06, 0.06, 0.03, C.zombieEyeWhite, 0, false); // one tooth
  b.add(0, 1.6, 0.08, 0.3, 0.14, 0.3, 0x6fae84, 0.05);                   // tuft of hair
  return b.build();
}

export const KINDS = ["sheep", "chicken", "zombie"] as const;
export type Kind = (typeof KINDS)[number];
const BOB_SPEED: Record<Kind, number> = { sheep: 1.6, chicken: 3.2, zombie: 1.1 };
const BOB_AMP: Record<Kind, number> = { sheep: 0.03, chicken: 0.04, zombie: 0.05 };
const MAX_INSTANCES = 64;

export class Creatures {
  group = new THREE.Group();
  agentModel: AgentModel;
  agent: THREE.Group;
  private meshes: Record<Kind, THREE.InstancedMesh>;
  private dummy = new THREE.Object3D();
  private material: THREE.MeshLambertMaterial;
  private counts: Record<Kind, number> = { sheep: 0, chicken: 0, zombie: 0 };

  constructor() {
    this.material = new THREE.MeshLambertMaterial({ vertexColors: true, flatShading: true });
    this.agentModel = new AgentModel(this.material);
    this.agent = this.agentModel.group;
    this.group.add(this.agent);
    const make = (g: THREE.BufferGeometry, name: string) => {
      const m = new THREE.InstancedMesh(g, this.material, MAX_INSTANCES);
      m.castShadow = true;
      m.count = 0;
      m.name = name;
      m.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
      this.group.add(m);
      return m;
    };
    this.meshes = { sheep: make(sheepGeometry(), "sheep"), chicken: make(chickenGeometry(), "chickens"), zombie: make(zombieGeometry(), "zombies") };
  }

  /** Start a new frame. Call setInstance for every creature, then endFrame. No allocation. */
  beginFrame(): void {
    this.counts.sheep = this.counts.chicken = this.counts.zombie = 0;
  }

  setInstance(kind: string, id: number, x: number, y: number, z: number, yaw: number, time: number): void {
    const k = kind as Kind;
    const mesh = this.meshes[k];
    if (!mesh) return;
    const n = this.counts[k];
    if (n >= MAX_INSTANCES) return;
    const phase = id * 1.37;
    const bob = Math.sin(time * BOB_SPEED[k] + phase) * BOB_AMP[k];
    const d = this.dummy;
    d.position.set(x + 0.5, y + bob + 0.02, z + 0.5);
    d.rotation.set(0, yaw, Math.sin(time * BOB_SPEED[k] * 0.5 + phase) * 0.03);
    d.scale.setScalar(k === "chicken" ? 0.8 : 0.85);
    d.updateMatrix();
    mesh.setMatrixAt(n, d.matrix);
    this.counts[k] = n + 1;
  }

  endFrame(): void {
    for (const k of KINDS) {
      const m = this.meshes[k];
      if (m.count !== this.counts[k] || this.counts[k] > 0) {
        m.count = this.counts[k];
        m.instanceMatrix.needsUpdate = true;
      }
    }
  }

  setAgent(x: number, y: number, z: number, yaw: number, moving: number, time: number): void {
    const a = this.agent;
    a.position.set(x + 0.5, y + 0.02 + Math.abs(Math.sin(time * 9)) * 0.06 * moving, z + 0.5);
    a.rotation.set(0, yaw, 0);
    a.scale.setScalar(0.9);
  }

  get drawCalls(): number {
    let n = this.agentModel.drawCalls;
    for (const k of KINDS) if (this.counts[k] > 0) n++;
    return n;
  }
}
