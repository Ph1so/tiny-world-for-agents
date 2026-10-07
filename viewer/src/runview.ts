// One run on screen: the 3D stage plus its panels. The compare view makes two of these.
import { RunData } from "./data/run";
import { connectLive, loadReplay } from "./data/source";
import type { Player } from "./player";
import { SceneView, type CameraMode } from "./scene/view";
import { el } from "./ui/dom";
import { AgentPanel, EventFeed, MemoryPanel, StatusPanel, type NameOpts } from "./ui/panels";
import { Timeline } from "./ui/timeline";
import { Recorder } from "./ui/controls";

export class RunView {
  root = el("div", { class: "run-view" });
  stage = el("div", { class: "stage" });
  canvas = el("canvas", { class: "world" });
  run: RunData;
  scene: SceneView;
  status = new StatusPanel();
  agent = new AgentPanel();
  memory = new MemoryPanel();
  timeline = new Timeline();
  events = new EventFeed();
  recorder: Recorder;
  private overlay = el("div", { class: "overlay", text: "loading…" });
  private statusText = "";
  private stop: (() => void) | null = null;
  private debug = el("div", { class: "debug" });

  constructor(runId: string, public live: boolean, private player: Player, private names: NameOpts) {
    this.run = new RunData(runId);
    this.stage.append(this.canvas, this.overlay, this.debug);
    const side = el("div", { class: "side" }, this.status.root, this.agent.root, this.memory.root, this.timeline.root, this.events.root);
    this.root.append(this.stage, side);
    this.scene = new SceneView(this.canvas, this.run);
    this.recorder = new Recorder(this.canvas, runId);
    this.events.onJump = (t) => { player.seek(t); player.live = false; };
    this.timeline.onSeekAgentStep = (i) => { player.seek(this.run.tOfAgentStep(i)); player.live = false; };
    this.run.onReady = () => { this.scene.init(); this.overlay.style.display = "none"; };
  }

  async start(): Promise<void> {
    try {
      if (this.live) {
        this.stop = connectLive(this.run, (s) => { this.statusText = s; });
      } else {
        await loadReplay(this.run, (msg) => { this.overlay.textContent = msg; });
        this.statusText = "";
      }
    } catch (e) {
      this.overlay.textContent = `could not load run “${this.run.meta.runId}”: ${(e as Error).message}`;
      this.overlay.classList.add("error");
    }
  }

  setCamera(m: CameraMode): void { this.scene.setMode(m); }

  resize(): void { this.scene.resize(); }

  /** Draw the world and refresh panels for the player's time. */
  private frameMs = 0;
  private renderMs = 0;

  frame(showDebug: boolean): void {
    const pt = Math.min(this.player.pt, this.run.maxT);
    const t = Math.floor(pt);
    const t0 = showDebug ? performance.now() : 0;
    this.scene.render(pt);
    const t1 = showDebug ? performance.now() : 0;
    this.status.update(this.run, t, this.names, this.live ? this.statusText : "");
    this.agent.update(this.run, t, this.names);
    this.memory.update(this.run, t);
    this.timeline.update(this.run, t);
    this.events.update(this.run, t, this.names);
    if (showDebug) {
      const t2 = performance.now();
      this.renderMs = this.renderMs * 0.9 + (t1 - t0) * 0.1;
      this.frameMs = this.frameMs * 0.9 + (t2 - t0) * 0.1;
      this.debug.textContent = `draw calls ${this.scene.drawCalls} · tris ${this.scene.renderer.info.render.triangles} · scene ${this.renderMs.toFixed(1)} ms · panels ${(this.frameMs - this.renderMs).toFixed(1)} ms`;
      this.debug.style.display = "block";
    }
  }

  dispose(): void {
    this.stop?.();
    this.scene.dispose();
  }
}
