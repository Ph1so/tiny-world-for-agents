// Terrain as merged chunk meshes with hidden faces removed. Each chunk has one opaque mesh and
// one water mesh. Only chunks touched by a block change are rebuilt.
import * as THREE from "three";
import type { RunData } from "../data/run";
import { BLOCK_COLORS, FACE_SHADE, SIDE_TINT, TOP_TINT, TRANSPARENT } from "./palette";

export const CHUNK_X = 16;
export const CHUNK_Z = 16;

// Faces: +y, -y, +x, -x, +z, -z. Each face is 4 corners (unit cube) in CCW order seen from outside.
const FACES: { n: [number, number, number]; v: [number, number, number][] }[] = [
  { n: [0, 1, 0], v: [[0, 1, 1], [1, 1, 1], [1, 1, 0], [0, 1, 0]] },
  { n: [0, -1, 0], v: [[0, 0, 0], [1, 0, 0], [1, 0, 1], [0, 0, 1]] },
  { n: [1, 0, 0], v: [[1, 0, 1], [1, 0, 0], [1, 1, 0], [1, 1, 1]] },
  { n: [-1, 0, 0], v: [[0, 0, 0], [0, 0, 1], [0, 1, 1], [0, 1, 0]] },
  { n: [0, 0, 1], v: [[0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1]] },
  { n: [0, 0, -1], v: [[1, 0, 0], [0, 0, 0], [0, 1, 0], [1, 1, 0]] },
];

class GeomBuilder {
  pos: number[] = [];
  nor: number[] = [];
  col: number[] = [];
  idx: number[] = [];
  private tmp = new THREE.Color();

  box(x0: number, y0: number, z0: number, x1: number, y1: number, z1: number, color: number,
      jitter: number, faceMask = 63, shade = FACE_SHADE): void {
    const dx = x1 - x0, dy = y1 - y0, dz = z1 - z0;
    for (let f = 0; f < 6; f++) {
      if (!(faceMask & (1 << f))) continue;
      const face = FACES[f];
      const s = shade[f] * jitter;
      this.tmp.setHex(color);
      const r = this.tmp.r * s, g = this.tmp.g * s, b = this.tmp.b * s;
      const base = this.pos.length / 3;
      for (const [vx, vy, vz] of face.v) {
        this.pos.push(x0 + vx * dx, y0 + vy * dy, z0 + vz * dz);
        this.nor.push(face.n[0], face.n[1], face.n[2]);
        this.col.push(r, g, b);
      }
      this.idx.push(base, base + 1, base + 2, base, base + 2, base + 3);
    }
  }

  build(): THREE.BufferGeometry | null {
    if (this.idx.length === 0) return null;
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(this.pos, 3));
    g.setAttribute("normal", new THREE.Float32BufferAttribute(this.nor, 3));
    g.setAttribute("color", new THREE.Float32BufferAttribute(this.col, 3));
    g.setIndex(this.idx);
    g.computeBoundingSphere();
    return g;
  }
}

function hash3(x: number, y: number, z: number): number {
  let h = (x * 374761393 + y * 668265263 + z * 2147483647) | 0;
  h = Math.imul(h ^ (h >>> 13), 1274126177);
  return ((h ^ (h >>> 16)) >>> 0) / 4294967295;
}

export class Terrain {
  group = new THREE.Group();
  private run: RunData;
  private chunks: { solid: THREE.Mesh | null; water: THREE.Mesh | null }[] = [];
  private dirty = new Set<number>();
  private nx = 0;
  private nz = 0;
  private solidMat: THREE.Material;
  private waterMat: THREE.Material;
  private ids = { air: 0, water: 0, torch: 0, door: 0, leaves: 0 };
  private transparentIds = new Set<number>();
  private colorOf: number[] = [];
  private topOf: number[] = [];
  private sideOf: number[] = [];
  /** Positions of torches, kept for the glow sprites and lights. Key is the cell index. */
  torches = new Map<number, [number, number, number]>();
  torchesChanged = false;

  constructor(run: RunData) {
    this.run = run;
    this.solidMat = new THREE.MeshLambertMaterial({ vertexColors: true, flatShading: true });
    this.waterMat = new THREE.MeshLambertMaterial({
      vertexColors: true, flatShading: true, transparent: true, opacity: 0.72, depthWrite: false,
    });
    this.group.name = "terrain";
  }

  /** Call once the snapshot has been decoded. */
  init(): void {
    const run = this.run;
    const [sx, , sz] = run.size;
    this.nx = Math.ceil(sx / CHUNK_X);
    this.nz = Math.ceil(sz / CHUNK_Z);
    this.chunks = [];
    for (let i = 0; i < this.nx * this.nz; i++) this.chunks.push({ solid: null, water: null });
    this.ids = {
      air: run.paletteId.get("air") ?? 0, water: run.paletteId.get("water") ?? -1,
      torch: run.paletteId.get("torch") ?? -1, door: run.paletteId.get("door") ?? -1,
      leaves: run.paletteId.get("leaves") ?? -1,
    };
    this.transparentIds = new Set(run.palette.map((n, i) => TRANSPARENT.has(n) ? i : -1).filter((i) => i >= 0));
    this.colorOf = run.palette.map((n) => BLOCK_COLORS[n] ?? 0xff00ff);
    this.topOf = run.palette.map((n) => TOP_TINT[n] ?? BLOCK_COLORS[n] ?? 0xff00ff);
    this.sideOf = run.palette.map((n) => SIDE_TINT[n] ?? BLOCK_COLORS[n] ?? 0xff00ff);
    this.torches.clear();
    for (let y = 0; y < run.size[1]; y++) for (let z = 0; z < sz; z++) for (let x = 0; x < sx; x++) {
      if (run.blocks[run.index(x, y, z)] === this.ids.torch) this.torches.set(run.index(x, y, z), [x, y, z]);
    }
    this.torchesChanged = true;
    for (let i = 0; i < this.chunks.length; i++) this.dirty.add(i);
    run.onBlockChange = (x, y, z, id) => this.onBlockChange(x, y, z, id);
    this.flush();
  }

  onBlockChange(x: number, y: number, z: number, id: number): void {
    const k = this.run.index(x, y, z);
    if (id === this.ids.torch) { this.torches.set(k, [x, y, z]); this.torchesChanged = true; }
    else if (this.torches.delete(k)) this.torchesChanged = true;
    const cx = Math.floor(x / CHUNK_X), cz = Math.floor(z / CHUNK_Z);
    this.dirty.add(cx + cz * this.nx);
    // Neighbouring chunks share faces at the border.
    if (x % CHUNK_X === 0 && cx > 0) this.dirty.add(cx - 1 + cz * this.nx);
    if (x % CHUNK_X === CHUNK_X - 1 && cx < this.nx - 1) this.dirty.add(cx + 1 + cz * this.nx);
    if (z % CHUNK_Z === 0 && cz > 0) this.dirty.add(cx + (cz - 1) * this.nx);
    if (z % CHUNK_Z === CHUNK_Z - 1 && cz < this.nz - 1) this.dirty.add(cx + (cz + 1) * this.nx);
  }

  /** Rebuild every dirty chunk. Called once per frame; usually a no-op. */
  flush(): number {
    if (this.dirty.size === 0) return 0;
    let n = 0;
    for (const c of this.dirty) { this.rebuild(c); n++; }
    this.dirty.clear();
    return n;
  }

  get drawCalls(): number {
    let n = 0;
    for (const c of this.chunks) { if (c.solid) n++; if (c.water) n++; }
    return n;
  }

  private rebuild(c: number): void {
    const run = this.run;
    const [sx, sy, sz] = run.size;
    const cx = c % this.nx, cz = Math.floor(c / this.nx);
    const x0 = cx * CHUNK_X, z0 = cz * CHUNK_Z;
    const x1 = Math.min(sx, x0 + CHUNK_X), z1 = Math.min(sz, z0 + CHUNK_Z);
    const solid = new GeomBuilder();
    const water = new GeomBuilder();
    const blocks = run.blocks;
    const { air, water: waterId, torch, door } = this.ids;
    const idx = (x: number, y: number, z: number) => x + z * sx + y * sx * sz;
    const at = (x: number, y: number, z: number) =>
      (x < 0 || y < 0 || z < 0 || x >= sx || y >= sy || z >= sz) ? -1 : blocks[idx(x, y, z)];

    for (let y = 0; y < sy; y++) {
      for (let z = z0; z < z1; z++) {
        for (let x = x0; x < x1; x++) {
          const id = blocks[idx(x, y, z)];
          if (id === air) continue;
          if (id === torch) {
            // A short stick with a bright tip. Neighbours treat it as air.
            solid.box(x + 0.4, y, z + 0.4, x + 0.6, y + 0.55, z + 0.6, 0x8a6a4a, 1);
            solid.box(x + 0.33, y + 0.5, z + 0.33, x + 0.67, y + 0.8, z + 0.67, 0xffe08a, 1.35);
            continue;
          }
          const jitter = 0.96 + 0.08 * hash3(x, y, z);
          let mask = 0;
          const neighbours = [at(x, y + 1, z), at(x, y - 1, z), at(x + 1, y, z), at(x - 1, y, z), at(x, y, z + 1), at(x, y, z - 1)];
          if (id === waterId) {
            for (let f = 0; f < 6; f++) {
              const nb = neighbours[f];
              if (nb === air || nb === torch) mask |= 1 << f;
            }
            if (mask === 0) continue;
            const top = neighbours[0] === air ? y + 0.86 : y + 1;
            water.box(x, y, z, x + 1, top, z + 1, this.colorOf[id], jitter, mask);
            continue;
          }
          for (let f = 0; f < 6; f++) {
            const nb = neighbours[f];
            if (nb === -1) { if (f === 1) continue; mask |= 1 << f; continue; }   // map edge: draw sides, skip bottom
            if (this.transparentIds.has(nb)) mask |= 1 << f;
          }
          if (mask === 0) continue;
          if (id === door) {
            solid.box(x + 0.1, y, z + 0.1, x + 0.9, y + 1, z + 0.9, this.colorOf[id], jitter);
            solid.box(x + 0.62, y + 0.45, z + 0.05, x + 0.72, y + 0.55, z + 0.95, 0xffe28a, 1);
            continue;
          }
          // Top face in the top tint, sides in the side tint, bottom in the base colour.
          if (mask & 1) solid.box(x, y, z, x + 1, y + 1, z + 1, this.topOf[id], jitter, 1);
          if (mask & 2) solid.box(x, y, z, x + 1, y + 1, z + 1, this.colorOf[id], jitter, 2);
          if (mask & 60) solid.box(x, y, z, x + 1, y + 1, z + 1, this.sideOf[id], jitter, mask & 60);
        }
      }
    }

    const slot = this.chunks[c];
    if (slot.solid) { this.group.remove(slot.solid); slot.solid.geometry.dispose(); slot.solid = null; }
    if (slot.water) { this.group.remove(slot.water); slot.water.geometry.dispose(); slot.water = null; }
    const sg = solid.build();
    if (sg) {
      const m = new THREE.Mesh(sg, this.solidMat);
      m.castShadow = true; m.receiveShadow = true; m.matrixAutoUpdate = false; m.frustumCulled = true;
      slot.solid = m; this.group.add(m);
    }
    const wg = water.build();
    if (wg) {
      const m = new THREE.Mesh(wg, this.waterMat);
      m.receiveShadow = false; m.matrixAutoUpdate = false; m.renderOrder = 2;
      slot.water = m; this.group.add(m);
    }
  }
}
