// Transport bar: play, pause, speed, scrubber, jumps, camera, record, name toggle.
import { Player, SPEEDS } from "../player";
import { button, el } from "./dom";
import type { CameraMode } from "../scene/view";

export interface ControlHooks {
  nextEvent: () => void;
  prevEvent: () => void;
  nextMemory: () => void;
  prevMemory: () => void;
  setCamera: (m: CameraMode) => void;
  toggleRecord: () => boolean;      // returns true while recording
  toggleAlien: () => boolean;       // returns the new state
  showAlienToggle: boolean;
  alienOn?: boolean;
  goLive?: () => void;
}

export class Controls {
  root = el("div", { class: "controls" });
  private playBtn: HTMLButtonElement;
  private scrub: HTMLInputElement;
  private label = el("span", { class: "scrub-label" });
  private speedSel: HTMLSelectElement;
  private recBtn: HTMLButtonElement;
  private liveBtn: HTMLButtonElement | null = null;
  private camBtns: Record<CameraMode, HTMLButtonElement>;
  private scrubbing = false;

  constructor(private player: Player, hooks: ControlHooks) {
    this.playBtn = button("▶", () => player.toggle(), "play");
    this.speedSel = el("select", { class: "speed" });
    for (const s of SPEEDS) this.speedSel.append(el("option", { value: String(s), text: `${s}x` }));
    this.speedSel.value = String(player.speed);
    this.speedSel.addEventListener("change", () => player.setSpeed(Number(this.speedSel.value)));
    this.scrub = el("input", { type: "range", min: "0", max: "1", step: "1", value: "0", class: "scrub" });
    this.scrub.addEventListener("input", () => { this.scrubbing = true; player.seek(Number(this.scrub.value)); player.live = false; });
    this.scrub.addEventListener("change", () => { this.scrubbing = false; });
    const jumps = el("div", { class: "group" },
      button("⏮ event", hooks.prevEvent, "small"), button("event ⏭", hooks.nextEvent, "small"),
      button("⏮ memory", hooks.prevMemory, "small"), button("memory ⏭", hooks.nextMemory, "small"));
    this.camBtns = {
      orbit: button("orbit", () => this.cam("orbit", hooks), "small cam active"),
      follow: button("follow", () => this.cam("follow", hooks), "small cam"),
      top: button("map", () => this.cam("top", hooks), "small cam"),
      pov: button("pov", () => this.cam("pov", hooks), "small cam"),
    };
    this.recBtn = button("● record", () => {
      const on = hooks.toggleRecord();
      this.recBtn.textContent = on ? "■ stop" : "● record";
      this.recBtn.classList.toggle("recording", on);
    }, "small rec");
    const right = el("div", { class: "group" }, this.camBtns.orbit, this.camBtns.follow, this.camBtns.top, this.camBtns.pov, this.recBtn);
    if (hooks.showAlienToggle) {
      const b = button("alien names", () => b.classList.toggle("active", hooks.toggleAlien()), `small ${hooks.alienOn ? "active" : ""}`);
      right.append(b);
    }
    if (hooks.goLive) {
      this.liveBtn = button("● live", () => { hooks.goLive?.(); }, "small live");
      right.append(this.liveBtn);
    }
    this.root.append(
      el("div", { class: "group" }, this.playBtn, this.speedSel),
      el("div", { class: "group grow" }, this.scrub, this.label),
      jumps, right,
    );
    player.onChange(() => this.refresh());
    window.addEventListener("keydown", (ev) => {
      if ((ev.target as HTMLElement)?.tagName === "INPUT" || (ev.target as HTMLElement)?.tagName === "SELECT") return;
      if (ev.code === "Space") { ev.preventDefault(); player.toggle(); }
      else if (ev.key === "ArrowRight") player.seek(player.t + (ev.shiftKey ? 50 : 1));
      else if (ev.key === "ArrowLeft") player.seek(player.t - (ev.shiftKey ? 50 : 1));
      else if (ev.key === "e") hooks.nextEvent();
      else if (ev.key === "m") hooks.nextMemory();
    });
  }

  private cam(m: CameraMode, hooks: ControlHooks): void {
    hooks.setCamera(m);
    for (const k of Object.keys(this.camBtns) as CameraMode[]) this.camBtns[k].classList.toggle("active", k === m);
  }

  refresh(): void {
    const p = this.player;
    this.playBtn.textContent = p.playing ? "❚❚" : "▶";
    if (String(p.maxT) !== this.scrub.max) this.scrub.max = String(p.maxT);
    if (!this.scrubbing) this.scrub.value = String(p.t);
    this.label.textContent = `${p.t} / ${p.maxT}`;
    if (this.liveBtn) this.liveBtn.classList.toggle("active", p.live);
  }
}

/** Records the canvas with MediaRecorder and downloads a webm when stopped. */
export class Recorder {
  private rec: MediaRecorder | null = null;
  private chunks: Blob[] = [];

  constructor(private canvas: HTMLCanvasElement, private name: string) {}

  get recording(): boolean { return this.rec !== null; }

  toggle(): boolean {
    if (this.rec) { this.rec.stop(); return false; }
    if (typeof MediaRecorder === "undefined") { alert("MediaRecorder is not available in this browser"); return false; }
    const stream = this.canvas.captureStream(60);
    const mime = ["video/webm;codecs=vp9", "video/webm;codecs=vp8", "video/webm", "video/mp4"].find((m) => MediaRecorder.isTypeSupported(m));
    const rec = new MediaRecorder(stream, mime ? { mimeType: mime, videoBitsPerSecond: 8_000_000 } : undefined);
    this.chunks = [];
    rec.ondataavailable = (e) => { if (e.data.size) this.chunks.push(e.data); };
    rec.onstop = () => {
      const blob = new Blob(this.chunks, { type: rec.mimeType || "video/webm" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = `${this.name}-${Date.now()}.${(rec.mimeType || "webm").includes("mp4") ? "mp4" : "webm"}`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 5000);
      this.rec = null;
    };
    rec.start(250);
    this.rec = rec;
    return true;
  }
}
