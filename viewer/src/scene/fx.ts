// Short lived effects that show what the agent is doing: block particles, cracks on a block being
// mined, a flash where a block is placed, items flying to the agent or into a chest, a chest lid
// that opens while the agent uses it, and floating text.
// Everything is pooled and runs on wall clock time, so effects look the same at any play speed.
import * as THREE from "three";

const MAX_PARTICLES = 600;
const FLYERS = 8;
const FLOATERS = 6;
const FLASHES = 4;

function crackTexture(): THREE.CanvasTexture {
  const c = document.createElement("canvas");
  c.width = c.height = 64;
  const g = c.getContext("2d")!;
  g.strokeStyle = "rgba(30, 24, 40, 0.9)";
  g.lineWidth = 2.5;
  g.lineCap = "round";
  // Fixed jagged lines from near the centre outwards (seeded, so every block cracks the same way).
  let s = 7;
  const rnd = () => { s = (s * 16807) % 2147483647; return s / 2147483647; };
  for (let k = 0; k < 7; k++) {
    let x = 26 + rnd() * 12, y = 26 + rnd() * 12;
    const a = (k / 7) * Math.PI * 2 + rnd() * 0.6;
    g.beginPath();
    g.moveTo(x, y);
    for (let j = 0; j < 4; j++) {
      x += Math.cos(a + (rnd() - 0.5) * 1.2) * 8;
      y += Math.sin(a + (rnd() - 0.5) * 1.2) * 8;
      g.lineTo(x, y);
    }
    g.stroke();
  }
  const t = new THREE.CanvasTexture(c);
  t.magFilter = THREE.NearestFilter;
  return t;
}

/** to null means the agent's chest (the point moves with the agent). */
interface Flyer { mesh: THREE.Mesh; from: THREE.Vector3; to: THREE.Vector3 | null; toFixed: THREE.Vector3; start: number; delay: number }
interface Floater { sprite: THREE.Sprite; ctx: CanvasRenderingContext2D; tex: THREE.CanvasTexture; origin: THREE.Vector3; start: number }
interface Flash { lines: THREE.LineSegments; start: number }

export class Effects {
  group = new THREE.Group();
  private pos = new Float32Array(MAX_PARTICLES * 3);
  private col = new Float32Array(MAX_PARTICLES * 3);
  private vel = new Float32Array(MAX_PARTICLES * 3);
  private life = new Float32Array(MAX_PARTICLES);
  private grav = new Float32Array(MAX_PARTICLES);
  private next = 0;
  private points: THREE.Points;
  private crack: THREE.Mesh;
  private crackMat: THREE.MeshBasicMaterial;
  private flyers: Flyer[] = [];
  private floaters: Floater[] = [];
  private flashes: Flash[] = [];
  private tmpC = new THREE.Color();
  private tmpV = new THREE.Vector3();
  private now = 0;
  // Chest lid: a hinge group on the far edge of the chest top, opened toward the agent.
  private lid = new THREE.Group();
  private lidHinge = new THREE.Group();
  private lidOpen = 0;
  private lidTarget = 0;

  constructor() {
    const geo = new THREE.BufferGeometry();
    for (let i = 0; i < MAX_PARTICLES; i++) this.pos[i * 3 + 1] = -9999;
    geo.setAttribute("position", new THREE.BufferAttribute(this.pos, 3).setUsage(THREE.DynamicDrawUsage));
    geo.setAttribute("color", new THREE.BufferAttribute(this.col, 3).setUsage(THREE.DynamicDrawUsage));
    geo.boundingSphere = new THREE.Sphere(new THREE.Vector3(), 1e6);
    this.points = new THREE.Points(geo, new THREE.PointsMaterial({ size: 0.11, vertexColors: true, sizeAttenuation: true }));
    this.points.frustumCulled = false;
    this.crackMat = new THREE.MeshBasicMaterial({ map: crackTexture(), transparent: true, opacity: 0, depthWrite: false,
      polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2 });
    this.crack = new THREE.Mesh(new THREE.BoxGeometry(1.01, 1.01, 1.01), this.crackMat);
    this.crack.visible = false;
    this.group.add(this.points, this.crack);
    for (let i = 0; i < FLYERS; i++) {
      const mesh = new THREE.Mesh(new THREE.BoxGeometry(0.24, 0.24, 0.24), new THREE.MeshLambertMaterial({ flatShading: true }));
      mesh.visible = false;
      this.group.add(mesh);
      this.flyers.push({ mesh, from: new THREE.Vector3(), to: null, toFixed: new THREE.Vector3(), start: -1, delay: 0 });
    }
    for (let i = 0; i < FLOATERS; i++) {
      const canvas = document.createElement("canvas");
      canvas.width = 256; canvas.height = 64;
      const tex = new THREE.CanvasTexture(canvas);
      tex.colorSpace = THREE.SRGBColorSpace;
      // Fixed size on screen (sizeAttenuation off: scale is a fraction of the view height).
      const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: false, fog: false, sizeAttenuation: false }));
      sprite.scale.set(0.2, 0.05, 1);
      sprite.renderOrder = 10;
      sprite.visible = false;
      this.group.add(sprite);
      this.floaters.push({ sprite, ctx: canvas.getContext("2d")!, tex, origin: new THREE.Vector3(), start: -1 });
    }
    const lidMat = new THREE.MeshLambertMaterial({ color: 0xc99556, flatShading: true });
    const lidMesh = new THREE.Mesh(new THREE.BoxGeometry(1.04, 0.26, 1.04), lidMat);
    lidMesh.position.set(0, -0.13, -0.52);            // hangs from the hinge toward the agent (-z)
    const latch = new THREE.Mesh(new THREE.BoxGeometry(0.16, 0.2, 0.06), new THREE.MeshLambertMaterial({ color: 0x5a4632 }));
    latch.position.set(0, -0.2, -1.05);
    lidMesh.castShadow = true;
    this.lidHinge.add(lidMesh, latch);
    this.lid.add(this.lidHinge);
    this.lid.visible = false;
    this.group.add(this.lid);
    const edges = new THREE.EdgesGeometry(new THREE.BoxGeometry(1, 1, 1));
    for (let i = 0; i < FLASHES; i++) {
      const lines = new THREE.LineSegments(edges, new THREE.LineBasicMaterial({ color: 0xffffff, transparent: true }));
      lines.visible = false;
      this.group.add(lines);
      this.flashes.push({ lines, start: -1 });
    }
  }

  /** n particles from a point, flung outwards and up, falling under gravity. */
  burst(x: number, y: number, z: number, color: number, n: number, speed = 2.5, life = 0.7, gravity = 9, spread = 0.35): void {
    for (let k = 0; k < n; k++) {
      const i = this.next;
      this.next = (this.next + 1) % MAX_PARTICLES;
      const j = i * 3;
      this.pos[j] = x + (Math.random() - 0.5) * spread;
      this.pos[j + 1] = y + (Math.random() - 0.5) * spread;
      this.pos[j + 2] = z + (Math.random() - 0.5) * spread;
      const a = Math.random() * Math.PI * 2, u = Math.random();
      this.vel[j] = Math.cos(a) * speed * (0.4 + u);
      this.vel[j + 1] = speed * (0.6 + Math.random() * 0.8);
      this.vel[j + 2] = Math.sin(a) * speed * (0.4 + u);
      // Vary the shade a little so a burst does not look flat.
      this.tmpC.setHex(color).multiplyScalar(0.8 + Math.random() * 0.35);
      this.col[j] = this.tmpC.r; this.col[j + 1] = this.tmpC.g; this.col[j + 2] = this.tmpC.b;
      this.life[i] = life * (0.6 + Math.random() * 0.6);
      this.grav[i] = gravity;
    }
  }

  /** Cracks over the block at (x, y, z), more visible as p goes from 0 to 1. null hides them. */
  setCrack(cell: [number, number, number] | null, p: number, time: number): void {
    this.crack.visible = cell !== null;
    if (!cell) return;
    const shake = 0.02 * Math.sin(time * 40);
    this.crack.position.set(cell[0] + 0.5 + shake, cell[1] + 0.5, cell[2] + 0.5 - shake);
    this.crackMat.opacity = 0.25 + 0.75 * Math.min(1, p);
  }

  /** An item cube that flies from a point into the agent, or to a fixed point. delay staggers several. */
  pickup(from: THREE.Vector3, color: number, to: THREE.Vector3 | null = null, delay = 0): void {
    const f = this.flyers.find((q) => q.start < 0) ?? this.flyers[0];
    f.from.copy(from);
    f.to = to ? f.toFixed.copy(to) : null;
    f.start = this.now;
    f.delay = delay;
    (f.mesh.material as THREE.MeshLambertMaterial).color.setHex(color);
    f.mesh.visible = false;                           // shown once its delay has passed
  }

  /** Open the lid of the chest at cell, facing the point `toward` (the agent). null closes it. */
  setLid(cell: [number, number, number] | null, toward: THREE.Vector3): void {
    if (cell) {
      const cx = cell[0] + 0.5, cz = cell[2] + 0.5;
      this.lid.position.set(cx, cell[1] + 1.02, cz);
      // Local -z points at the agent, so the hinge sits on the far edge.
      this.lid.rotation.y = Math.atan2(-(toward.x - cx), -(toward.z - cz));
      this.lidHinge.position.set(0, 0, 0.52);
      this.lid.visible = true;
    }
    this.lidTarget = cell ? 1 : 0;
  }

  /** Outline that settles onto a newly placed block. */
  placed(x: number, y: number, z: number): void {
    const f = this.flashes.find((q) => q.start < 0) ?? this.flashes[0];
    f.lines.position.set(x + 0.5, y + 0.5, z + 0.5);
    f.start = this.now;
    f.lines.visible = true;
  }

  /** Text that rises from a point and fades. */
  float(text: string, at: THREE.Vector3, color = "#3b2f52"): void {
    const f = this.floaters.find((q) => q.start < 0) ?? this.floaters.reduce((a, b) => (a.start < b.start ? a : b));
    const g = f.ctx;
    g.clearRect(0, 0, 256, 64);
    g.font = "600 30px ui-sans-serif, system-ui, sans-serif";
    const w = Math.min(248, g.measureText(text).width + 32);
    g.fillStyle = "rgba(255, 255, 255, 0.92)";
    g.beginPath();
    g.roundRect((256 - w) / 2, 8, w, 48, 24);
    g.fill();
    g.fillStyle = color;
    g.textAlign = "center";
    g.textBaseline = "middle";
    g.fillText(text, 128, 33, 232);
    f.tex.needsUpdate = true;
    f.origin.copy(at);
    f.start = this.now;
    f.sprite.visible = true;
  }

  update(time: number, dt: number, agentChest: THREE.Vector3): void {
    this.now = time;
    for (let i = 0; i < MAX_PARTICLES; i++) {
      if (this.life[i] <= 0) continue;
      const j = i * 3;
      this.life[i] -= dt;
      if (this.life[i] <= 0) { this.pos[j + 1] = -9999; continue; }
      this.vel[j + 1] -= this.grav[i] * dt;
      this.pos[j] += this.vel[j] * dt;
      this.pos[j + 1] += this.vel[j + 1] * dt;
      this.pos[j + 2] += this.vel[j + 2] * dt;
    }
    const geo = this.points.geometry;
    geo.attributes.position.needsUpdate = true;
    geo.attributes.color.needsUpdate = true;

    this.lidOpen += (this.lidTarget - this.lidOpen) * Math.min(1, dt * 10);
    this.lidHinge.rotation.x = this.lidOpen * 1.25;
    if (this.lidTarget === 0 && this.lidOpen < 0.02) this.lid.visible = false;

    for (const f of this.flyers) {
      if (f.start < 0) continue;
      const u = (time - f.start - f.delay) / 0.45;
      if (u < 0) continue;
      f.mesh.visible = true;
      if (u >= 1) { f.start = -1; f.mesh.visible = false; continue; }
      this.tmpV.copy(f.from).lerp(f.to ?? agentChest, u * u);
      this.tmpV.y += Math.sin(u * Math.PI) * 0.6;
      f.mesh.position.copy(this.tmpV);
      f.mesh.rotation.set(time * 6, time * 8, 0);
      f.mesh.scale.setScalar(1 - 0.6 * u);
    }
    for (const f of this.floaters) {
      if (f.start < 0) continue;
      const u = (time - f.start) / 1.4;
      if (u >= 1) { f.start = -1; f.sprite.visible = false; continue; }
      f.sprite.position.copy(f.origin);
      f.sprite.position.y += 0.3 + u * 0.9;
      (f.sprite.material as THREE.SpriteMaterial).opacity = u < 0.7 ? 1 : 1 - (u - 0.7) / 0.3;
    }
    for (const f of this.flashes) {
      if (f.start < 0) continue;
      const u = (time - f.start) / 0.4;
      if (u >= 1) { f.start = -1; f.lines.visible = false; continue; }
      f.lines.scale.setScalar(1.35 - 0.33 * u);
      (f.lines.material as THREE.LineBasicMaterial).opacity = 1 - u;
    }
  }
}
