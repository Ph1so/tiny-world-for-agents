// Memory timeline: file size over agent steps, a mark at every edit (green) and every rejected
// edit (red). Clicking a point scrubs to that step. Drawn on a 2D canvas, redrawn only when the
// data or the cursor changes.
import type { RunData } from "../data/run";
import { el } from "./dom";

const PAD = { l: 44, r: 10, t: 10, b: 20 };

export class Timeline {
  root = el("div", { class: "panel timeline" });
  canvas = el("canvas", { class: "timeline-canvas" });
  private ctx: CanvasRenderingContext2D;
  private lastKey = "";
  private points: { x: number; y: number; i: number; accepted: boolean }[] = [];
  onSeekAgentStep: ((i: number) => void) | null = null;
  private hover = -1;

  constructor() {
    this.root.append(el("div", { class: "panel-head", text: "memory timeline" }), this.canvas);
    this.ctx = this.canvas.getContext("2d")!;
    this.canvas.addEventListener("click", (ev) => {
      const k = this.nearest(ev);
      if (k >= 0) this.onSeekAgentStep?.(this.points[k].i);
    });
    this.canvas.addEventListener("mousemove", (ev) => {
      const k = this.nearest(ev);
      if (k !== this.hover) { this.hover = k; this.lastKey = ""; }
      this.canvas.style.cursor = k >= 0 ? "pointer" : "default";
    });
    this.canvas.addEventListener("mouseleave", () => { this.hover = -1; this.lastKey = ""; });
  }

  private nearest(ev: MouseEvent): number {
    const r = this.canvas.getBoundingClientRect();
    const x = ev.clientX - r.left, y = ev.clientY - r.top;
    let best = -1, bd = 14 * 14;
    for (let k = 0; k < this.points.length; k++) {
      const p = this.points[k];
      const d = (p.x - x) ** 2 + (p.y - y) ** 2;
      if (d < bd) { bd = d; best = k; }
    }
    if (best < 0) {
      // Fall back to the nearest column so clicking the line still scrubs.
      let bx = 1e9;
      for (let k = 0; k < this.points.length; k++) { const d = Math.abs(this.points[k].x - x); if (d < bx) { bx = d; best = k; } }
      if (bx > 30) best = -1;
    }
    return best;
  }

  update(run: RunData, t: number): void {
    const w = this.canvas.clientWidth || 300, h = this.canvas.clientHeight || 110;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const curI = run.agentStepIndexAt(t);
    const maxI = Math.max(run.steps.length ? run.steps[run.steps.length - 1].i : 0, curI, 1);
    const key = `${w}x${h}:${run.memory.length}:${curI}:${maxI}:${this.hover}`;
    if (key === this.lastKey) return;
    this.lastKey = key;
    if (this.canvas.width !== w * dpr || this.canvas.height !== h * dpr) { this.canvas.width = w * dpr; this.canvas.height = h * dpr; }
    const c = this.ctx;
    c.setTransform(dpr, 0, 0, dpr, 0, 0);
    c.clearRect(0, 0, w, h);
    const limit = run.memory.length ? run.memory[0].limit || run.meta.memoryChars : run.meta.memoryChars;
    let maxY = Math.max(limit, 1);
    for (const m of run.memory) maxY = Math.max(maxY, m.chars);
    const X = (i: number) => PAD.l + (i / maxI) * (w - PAD.l - PAD.r);
    const Y = (v: number) => h - PAD.b - (v / maxY) * (h - PAD.t - PAD.b);

    // Axes and limit line.
    c.strokeStyle = "rgba(90, 80, 110, 0.25)"; c.lineWidth = 1;
    c.beginPath(); c.moveTo(PAD.l, PAD.t); c.lineTo(PAD.l, h - PAD.b); c.lineTo(w - PAD.r, h - PAD.b); c.stroke();
    c.fillStyle = "rgba(90, 80, 110, 0.7)"; c.font = "10px system-ui, sans-serif"; c.textAlign = "right";
    c.fillText(String(maxY), PAD.l - 4, PAD.t + 8); c.fillText("0", PAD.l - 4, h - PAD.b + 3);
    c.textAlign = "center"; c.fillText(`agent step (0 – ${maxI})`, (PAD.l + w - PAD.r) / 2, h - 5);
    if (limit > 0) {
      c.setLineDash([3, 3]); c.strokeStyle = "rgba(220, 90, 110, 0.5)";
      c.beginPath(); c.moveTo(PAD.l, Y(limit)); c.lineTo(w - PAD.r, Y(limit)); c.stroke(); c.setLineDash([]);
    }
    // Size over time as a step line, filled.
    const mem = run.memory;
    if (mem.length) {
      c.beginPath();
      c.moveTo(X(0), Y(0));
      let last = 0;
      for (const m of mem) { c.lineTo(X(m.i), Y(last)); c.lineTo(X(m.i), Y(m.chars)); last = m.chars; }
      c.lineTo(X(maxI), Y(last));
      c.strokeStyle = "#6f8fd6"; c.lineWidth = 1.8; c.stroke();
      c.lineTo(X(maxI), Y(0)); c.closePath();
      c.fillStyle = "rgba(111, 143, 214, 0.15)"; c.fill();
    }
    // Cursor.
    c.strokeStyle = "rgba(60, 50, 80, 0.5)"; c.lineWidth = 1;
    c.beginPath(); c.moveTo(X(curI), PAD.t); c.lineTo(X(curI), h - PAD.b); c.stroke();
    // Marks.
    this.points.length = 0;
    for (let k = 0; k < mem.length; k++) {
      const m = mem[k];
      if (m.i === 0) continue;
      const x = X(m.i), y = Y(m.chars);
      this.points.push({ x, y, i: m.i, accepted: m.accepted });
      const hot = this.hover === this.points.length - 1 || m.i === curI;
      if (m.accepted) {
        c.fillStyle = hot ? "#2f9e5c" : "#5cc48a"; c.beginPath(); c.arc(x, y, hot ? 5 : 3.5, 0, Math.PI * 2); c.fill();
      } else {
        c.strokeStyle = hot ? "#c8304f" : "#e06b82"; c.lineWidth = 2;
        c.beginPath(); c.moveTo(x - 4, y - 4); c.lineTo(x + 4, y + 4); c.moveTo(x + 4, y - 4); c.lineTo(x - 4, y + 4); c.stroke();
      }
    }
    if (this.hover >= 0 && this.hover < this.points.length) {
      const p = this.points[this.hover];
      const label = `step ${p.i} · ${p.accepted ? "edit" : "rejected"}`;
      c.font = "11px system-ui, sans-serif"; c.textAlign = "left";
      const tw = c.measureText(label).width + 8;
      const lx = Math.min(p.x + 8, w - tw - 2), ly = Math.max(PAD.t + 2, p.y - 22);
      c.fillStyle = "rgba(40, 34, 56, 0.85)"; c.fillRect(lx, ly, tw, 16);
      c.fillStyle = "#fff"; c.fillText(label, lx + 4, ly + 12);
    }
  }
}
