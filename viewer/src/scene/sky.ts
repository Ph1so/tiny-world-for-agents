// Sky, sun, stars and torch glow. The sky follows the step within the day (smooth) and the
// world's light field (bright, dim, dark) nudges it, so a dark step always looks like night.
import * as THREE from "three";
import { SKY } from "./palette";

const STAR_COUNT = 500;

function glowTexture(): THREE.Texture {
  const c = document.createElement("canvas");
  c.width = c.height = 64;
  const ctx = c.getContext("2d")!;
  const g = ctx.createRadialGradient(32, 32, 0, 32, 32, 32);
  g.addColorStop(0, "rgba(255, 220, 140, 0.9)");
  g.addColorStop(0.35, "rgba(255, 190, 100, 0.35)");
  g.addColorStop(1, "rgba(255, 160, 80, 0)");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, 64, 64);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

export class Sky {
  group = new THREE.Group();
  sun: THREE.DirectionalLight;
  hemi: THREE.HemisphereLight;
  stars: THREE.Points;
  background = new THREE.Color();
  fog: THREE.Fog;
  private starMat: THREE.PointsMaterial;
  private cSky = new THREE.Color();
  private cHorizon = new THREE.Color();
  private cGround = new THREE.Color();
  private cSun = new THREE.Color();
  private tmpA = new THREE.Color();
  private tmpB = new THREE.Color();
  private glowMat: THREE.SpriteMaterial;
  private glows: THREE.Sprite[] = [];
  private lights: THREE.PointLight[] = [];
  /** 0 = night, 1 = full day. */
  daylight = 1;

  constructor(worldSize: [number, number, number]) {
    const [sx, sy, sz] = worldSize;
    this.sun = new THREE.DirectionalLight(0xffffff, 2.2);
    this.sun.castShadow = true;
    this.sun.shadow.mapSize.set(2048, 2048);
    const cam = this.sun.shadow.camera;
    const r = Math.max(sx, sz) * 0.75;
    cam.left = -r; cam.right = r; cam.top = r; cam.bottom = -r; cam.near = 1; cam.far = 400;
    cam.updateProjectionMatrix();
    this.sun.shadow.bias = -0.0008;
    this.sun.shadow.normalBias = 0.03;
    this.sun.shadow.radius = 3;
    this.sun.target.position.set(sx / 2, sy / 3, sz / 2);
    this.group.add(this.sun, this.sun.target);
    this.hemi = new THREE.HemisphereLight(0xffffff, 0xffffff, 1.0);
    this.group.add(this.hemi);

    const pos = new Float32Array(STAR_COUNT * 3);
    for (let i = 0; i < STAR_COUNT; i++) {
      const u = Math.random() * Math.PI * 2, v = Math.acos(Math.random() * 0.9 + 0.1);
      const rad = 260;
      pos[i * 3] = sx / 2 + rad * Math.sin(v) * Math.cos(u);
      pos[i * 3 + 1] = 10 + rad * Math.cos(v);
      pos[i * 3 + 2] = sz / 2 + rad * Math.sin(v) * Math.sin(u);
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    this.starMat = new THREE.PointsMaterial({ color: 0xfff6d8, size: 2.4, sizeAttenuation: false, transparent: true, opacity: 0, depthWrite: false, fog: false });
    this.stars = new THREE.Points(g, this.starMat);
    this.stars.frustumCulled = false;
    this.group.add(this.stars);
    this.fog = new THREE.Fog(0xffffff, 90, 260);
    this.glowMat = new THREE.SpriteMaterial({ map: glowTexture(), transparent: true, blending: THREE.AdditiveBlending, depthWrite: false, fog: false });
    for (let i = 0; i < 6; i++) {
      const l = new THREE.PointLight(0xffb866, 0, 9, 1.6);
      l.visible = false;
      this.group.add(l);
      this.lights.push(l);
    }
  }

  /** Torch positions changed. Rebuild the glow sprites and point the lights at the first few. */
  setTorches(torches: Iterable<[number, number, number]>): void {
    for (const s of this.glows) this.group.remove(s);
    this.glows.length = 0;
    let n = 0;
    for (const l of this.lights) l.visible = false;
    for (const [x, y, z] of torches) {
      const s = new THREE.Sprite(this.glowMat);
      s.position.set(x + 0.5, y + 0.7, z + 0.5);
      s.scale.setScalar(2.6);
      this.group.add(s);
      this.glows.push(s);
      if (n < this.lights.length) {
        const l = this.lights[n++];
        l.position.set(x + 0.5, y + 0.9, z + 0.5);
        l.visible = true;
      }
    }
  }

  /**
   * stepInDay in [0, dayLength). light is the world's light field. time is seconds, for flicker.
   */
  update(stepInDay: number, dayLength: number, nightStart: number, dimSteps: number, light: string, time: number): void {
    // Daylight curve: 1 during the day, fading over dimSteps before night, back up over the last dimSteps.
    let d: number;
    const dim = Math.max(1, dimSteps);
    if (stepInDay < nightStart - dim) d = 1;
    else if (stepInDay < nightStart) d = 1 - (stepInDay - (nightStart - dim)) / dim;
    else if (stepInDay < dayLength - dim) d = 0;
    else d = (stepInDay - (dayLength - dim)) / dim;
    // The light field is what the agent was told. Let it pull the sky if they disagree.
    if (light === "dark") d = Math.min(d, 0.15);
    if (light === "bright") d = Math.max(d, 0.6);
    this.daylight = d;

    // Blend night -> dusk -> day. Dusk sits in the middle of the fade.
    const dusk = 1 - Math.abs(d - 0.5) * 2;    // 1 at d = 0.5
    const mix = (key: "sky" | "horizon" | "ground" | "sun", out: THREE.Color) => {
      this.tmpA.setHex(SKY.night[key]).lerp(this.tmpB.setHex(SKY.day[key]), d);
      out.copy(this.tmpA).lerp(this.tmpB.setHex(SKY.dusk[key]), dusk * 0.75);
    };
    mix("sky", this.cSky); mix("horizon", this.cHorizon); mix("ground", this.cGround); mix("sun", this.cSun);
    this.background.copy(this.cSky);
    this.fog.color.copy(this.cHorizon);
    this.hemi.color.copy(this.cHorizon);
    this.hemi.groundColor.copy(this.cGround);
    this.hemi.intensity = 0.55 + 0.7 * d;
    this.sun.color.copy(this.cSun);
    this.sun.intensity = 0.35 + 2.0 * d;
    // Sun arcs over the world during the day, a dim moon takes over at night.
    const dayFrac = Math.min(1, stepInDay / Math.max(1, nightStart));
    const ang = d > 0.2 ? Math.PI * (0.15 + 0.7 * dayFrac) : Math.PI * 0.5;
    const tx = this.sun.target.position.x, tz = this.sun.target.position.z;
    this.sun.position.set(tx + Math.cos(ang) * 60, 25 + Math.sin(ang) * 55, tz + 30);
    this.starMat.opacity = Math.max(0, 1 - d * 1.6);
    this.stars.rotation.y = time * 0.004;
    const flicker = 0.85 + 0.15 * Math.sin(time * 11) * Math.sin(time * 7.3);
    const glow = 0.35 + 0.65 * (1 - d);
    this.glowMat.opacity = glow * flicker;
    for (const l of this.lights) l.intensity = 14 * glow * flicker;
  }
}
