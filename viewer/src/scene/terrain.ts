// Terrain as merged chunk meshes with hidden faces removed. Each chunk has one opaque mesh and
// one water mesh. Only chunks touched by a block change are rebuilt.
import * as THREE from "three";
import type { RunData } from "../data/run";
import { BLOCK_COLORS, DETAIL, FACE_SHADE, SIDE_TINT, TOP_TINT, TRANSPARENT } from "./palette";

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

  /** A flat patch on side face f (2..5) of cell (x,y,z), standing slightly proud of the face.
   *  u runs along the face from 0 to 1, v runs up it. */
  sidePatch(f: number, x: number, y: number, z: number, u0: number, u1: number, v0: number, v1: number,
            color: number, bright: number, out = 0.02): void {
    const ya = y + v0, yb = y + v1;
    if (f === 2) this.box(x + 1, ya, z + u0, x + 1 + out, yb, z + u1, color, bright, 63 & ~(1 << 3));
    else if (f === 3) this.box(x - out, ya, z + u0, x, yb, z + u1, color, bright, 63 & ~(1 << 2));
    else if (f === 4) this.box(x + u0, ya, z + 1, x + u1, yb, z + 1 + out, color, bright, 63 & ~(1 << 5));
    else if (f === 5) this.box(x + u0, ya, z - out, x + u1, yb, z, color, bright, 63 & ~(1 << 4));
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
  private ids = { air: 0, water: 0, torch: 0, door: 0, leaves: 0, bush: 0, sprout: 0, wheat: 0, workbench: 0, furnace: 0, chest: 0, bed: 0, coal: 0, iron: 0 };
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
      leaves: run.paletteId.get("leaves") ?? -1, bush: run.paletteId.get("berry bush") ?? -1,
      sprout: run.paletteId.get("sprout") ?? -1, wheat: run.paletteId.get("wheat") ?? -1,
      workbench: run.paletteId.get("workbench") ?? -1, furnace: run.paletteId.get("furnace") ?? -1,
      chest: run.paletteId.get("chest") ?? -1, bed: run.paletteId.get("bed") ?? -1,
      coal: run.paletteId.get("coal ore") ?? -1, iron: run.paletteId.get("iron ore") ?? -1,
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

  /** A low leafy mound, smaller than a cell, dotted with red berries. */
  private bush(g: GeomBuilder, x: number, y: number, z: number): void {
    const j = 0.94 + 0.1 * hash3(x, y, z);
    g.box(x + 0.1, y, z + 0.1, x + 0.9, y + 0.62, z + 0.9, BLOCK_COLORS["berry bush"], j);
    g.box(x + 0.22, y + 0.62, z + 0.22, x + 0.78, y + 0.8, z + 0.78, DETAIL.bushTop, j);
    const s = 0.13;
    for (let k = 0; k < 7; k++) {
      const a = hash3(x + k * 7, y, z), b = hash3(x, y + k * 11, z), c = hash3(x, y, z + k * 13);
      const f = k % 5;    // 0 = top, 1..4 = the four sides
      let bx: number, by: number, bz: number;
      if (f === 0) { bx = x + 0.25 + a * 0.4; by = y + 0.8; bz = z + 0.25 + c * 0.4; }
      else {
        const u = 0.15 + a * 0.57, v = y + 0.12 + b * 0.38;
        if (f === 1) { bx = x + 0.9 - s / 2; bz = z + u; }
        else if (f === 2) { bx = x + 0.1 - s / 2; bz = z + u; }
        else if (f === 3) { bx = x + u; bz = z + 0.9 - s / 2; }
        else { bx = x + u; bz = z + 0.1 - s / 2; }
        by = v;
      }
      g.box(bx, by, bz, bx + s, by + s, bz + s, DETAIL.berry, 1.15);
    }
  }

  /** A clump of thin stalks: tall and golden with heads when ripe, short and green as a sprout. */
  private crop(g: GeomBuilder, x: number, y: number, z: number, ripe: boolean): void {
    const spots = [[0.2, 0.22], [0.62, 0.18], [0.42, 0.48], [0.18, 0.7], [0.68, 0.66], [0.45, 0.82]];
    for (let k = 0; k < spots.length; k++) {
      const r = hash3(x + k, y, z - k);
      const sx = x + spots[k][0] + (r - 0.5) * 0.08, sz = z + spots[k][1] + (hash3(z, k, x) - 0.5) * 0.08;
      if (ripe) {
        const h = 0.62 + 0.18 * r;
        g.box(sx, y, sz, sx + 0.06, y + h, sz + 0.06, DETAIL.wheatStalk, 0.95);
        g.box(sx - 0.03, y + h, sz - 0.03, sx + 0.09, y + h + 0.22, sz + 0.09, DETAIL.wheatHead, 1.1);
      } else {
        const h = 0.18 + 0.14 * r;
        g.box(sx, y, sz, sx + 0.07, y + h, sz + 0.07, DETAIL.sproutLeaf, 1);
      }
    }
  }

  /** Chest: a box a little smaller than the cell, with a lighter lid, dark bands and a gold latch on every side. */
  private chest(g: GeomBuilder, x: number, y: number, z: number): void {
    const j = 0.96 + 0.08 * hash3(x, y, z);
    g.box(x + 0.08, y, z + 0.08, x + 0.92, y + 0.6, z + 0.92, BLOCK_COLORS.chest, j);
    g.box(x + 0.06, y + 0.6, z + 0.06, x + 0.94, y + 0.86, z + 0.94, DETAIL.chestLid, j);
    g.box(x + 0.05, y + 0.56, z + 0.05, x + 0.95, y + 0.64, z + 0.95, DETAIL.chestBand, 1, 60);
    for (const [a, b] of [[0.2, 0.3], [0.7, 0.8]]) {
      g.box(x + a, y + 0.86, z + 0.06, x + b, y + 0.88, z + 0.94, DETAIL.chestBand, 1, 1);
    }
    for (let f = 2; f < 6; f++) {
      const xi = f === 2 ? x - 0.06 : f === 3 ? x + 0.06 : x, zi = f === 4 ? z - 0.06 : f === 5 ? z + 0.06 : z;
      g.sidePatch(f, xi, y, zi, 0.42, 0.58, 0.46, 0.7, DETAIL.chestLatch, 1.2, 0.03);
    }
  }

  /** Bed: a low wooden frame on short legs, a red blanket and a white pillow at the -z end. */
  private bed(g: GeomBuilder, x: number, y: number, z: number): void {
    const c = DETAIL.bedFrame;
    for (const [a, b] of [[0.04, 0.16], [0.84, 0.96]]) for (const [d, e] of [[0.04, 0.16], [0.84, 0.96]]) {
      g.box(x + a, y, z + d, x + b, y + 0.18, z + e, c, 1);
    }
    g.box(x + 0.04, y + 0.18, z + 0.04, x + 0.96, y + 0.3, z + 0.96, c, 1);
    g.box(x + 0.04, y + 0.18, z + 0.02, x + 0.96, y + 0.62, z + 0.1, c, 1);              // headboard
    g.box(x + 0.08, y + 0.3, z + 0.1, x + 0.92, y + 0.44, z + 0.94, DETAIL.bedPillow, 0.95);   // mattress
    g.box(x + 0.06, y + 0.32, z + 0.36, x + 0.94, y + 0.5, z + 0.96, BLOCK_COLORS.bed, 1); // blanket
    g.box(x + 0.18, y + 0.44, z + 0.13, x + 0.82, y + 0.56, z + 0.32, DETAIL.bedPillow, 1.05);
  }

  /** Workbench: a 2x2 crafting grid on top and dark legs under a table edge on each visible side. */
  private benchDetail(g: GeomBuilder, x: number, y: number, z: number, mask: number): void {
    if (mask & 1) {
      g.box(x + 0.1, y + 1, z + 0.1, x + 0.9, y + 1.015, z + 0.9, DETAIL.benchGrid, 1, 1);
      for (const [a, b] of [[0.14, 0.47], [0.53, 0.86]]) for (const [c, d] of [[0.14, 0.47], [0.53, 0.86]]) {
        g.box(x + a, y + 1, z + c, x + b, y + 1.03, z + d, TOP_TINT.workbench, 1.04, 1 | 60);
      }
    }
    for (let f = 2; f < 6; f++) {
      if (!(mask & (1 << f))) continue;
      g.sidePatch(f, x, y, z, 0, 1, 0.74, 0.84, DETAIL.benchGrid, 1);
      g.sidePatch(f, x, y, z, 0.04, 0.2, 0, 0.74, DETAIL.benchLeg, 1);
      g.sidePatch(f, x, y, z, 0.8, 0.96, 0, 0.74, DETAIL.benchLeg, 1);
    }
  }

  /** Furnace: a dark mouth with a glowing fire on each visible side and a vent on top. */
  private furnaceDetail(g: GeomBuilder, x: number, y: number, z: number, mask: number): void {
    if (mask & 1) g.box(x + 0.3, y + 1, z + 0.3, x + 0.7, y + 1.03, z + 0.7, DETAIL.furnaceMouth, 1, 1 | 60);
    for (let f = 2; f < 6; f++) {
      if (!(mask & (1 << f))) continue;
      g.sidePatch(f, x, y, z, 0.22, 0.78, 0.12, 0.58, DETAIL.furnaceMouth, 1);
      g.sidePatch(f, x, y, z, 0.3, 0.7, 0.16, 0.36, DETAIL.furnaceFire, 1.45, 0.03);
    }
  }

  /** Ore: stone with chunky specks on every visible face, black for coal and rusty orange for
   *  iron (with a bright glint on each iron speck). */
  private oreDetail(g: GeomBuilder, x: number, y: number, z: number, mask: number, iron: boolean): void {
    const color = BLOCK_COLORS[iron ? "iron ore" : "coal ore"];
    const spots = [[0.12, 0.14], [0.56, 0.1], [0.3, 0.46], [0.66, 0.56], [0.14, 0.7]];
    for (let f = 0; f < 6; f++) {
      if (f === 1 || !(mask & (1 << f))) continue;
      for (let k = 0; k < spots.length; k++) {
        const r = hash3(x * 3 + f, y + k * 5, z * 7 - k);
        const size = 0.16 + 0.1 * r;
        const u0 = Math.min(0.92 - size, spots[k][0] + (r - 0.5) * 0.1);
        const v0 = Math.min(0.92 - size, spots[k][1] + (hash3(z, f, k + x) - 0.5) * 0.1);
        if (f === 0) {
          g.box(x + u0, y + 1, z + v0, x + u0 + size, y + 1.025, z + v0 + size, color, 1, 1 | 60);
          if (iron) g.box(x + u0, y + 1.025, z + v0, x + u0 + 0.06, y + 1.035, z + v0 + 0.06, DETAIL.ironShine, 1.1, 1);
        } else {
          g.sidePatch(f, x, y, z, u0, u0 + size, v0, v0 + size, color, 1, 0.025);
          if (iron) g.sidePatch(f, x, y, z, u0, u0 + 0.06, v0 + size - 0.06, v0 + size, DETAIL.ironShine, 1.1, 0.035);
        }
      }
    }
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
    const { air, water: waterId, torch, door, bush, sprout, wheat, workbench, furnace, chest, bed, coal, iron } = this.ids;
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
          if (id === bush) { this.bush(solid, x, y, z); continue; }
          if (id === wheat || id === sprout) { this.crop(solid, x, y, z, id === wheat); continue; }
          if (id === chest) { this.chest(solid, x, y, z); continue; }
          if (id === bed) { this.bed(solid, x, y, z); continue; }
          const jitter = 0.96 + 0.08 * hash3(x, y, z);
          let mask = 0;
          const neighbours = [at(x, y + 1, z), at(x, y - 1, z), at(x + 1, y, z), at(x - 1, y, z), at(x, y, z + 1), at(x, y, z - 1)];
          if (id === waterId) {
            for (let f = 0; f < 6; f++) {
              const nb = neighbours[f];
              if (nb !== waterId && this.transparentIds.has(nb)) mask |= 1 << f;
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
          if (id === workbench) this.benchDetail(solid, x, y, z, mask);
          else if (id === furnace) this.furnaceDetail(solid, x, y, z, mask);
          else if (id === coal || id === iron) this.oreDetail(solid, x, y, z, mask, id === iron);
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
