// Controlling the run itself (not playback): the pause / resume / stop buttons in the run view,
// and the new run form on the picker. Both talk to the server's /api/runs control endpoints.
import { controlRun, getOptions, getRun, startRun, type Options, type RunState } from "../data/source";
import { button, el } from "./dom";

const STATE_TEXT: Record<RunState, string> = {
  running: "run: running", paused: "run: paused", stopping: "run: stopping…", stopped: "run: stopped", finished: "run: finished",
};

/** Buttons for one run. Polls its state; calls onState when it changes. */
export class RunControlBar {
  root = el("div", { class: "group run-control" });
  state: RunState | null = null;
  onState: ((s: RunState) => void) | null = null;
  private label = el("span", { class: "run-state" });
  private pauseBtn: HTMLButtonElement;
  private resumeBtn: HTMLButtonElement;
  private stopBtn: HTMLButtonElement;
  private busy = false;

  constructor(private runId: string, private live: boolean) {
    this.pauseBtn = button("⏸ pause run", () => this.send("pause"), "small");
    this.resumeBtn = button("▶ resume run", () => this.send("resume"), "small");
    this.stopBtn = button("■ stop run", () => this.send("stop"), "small");
    this.pauseBtn.title = "the agent finishes its current step, then waits";
    this.stopBtn.title = "ends the run after the current step; resume continues it later";
    this.root.append(this.label, this.pauseBtn, this.resumeBtn, this.stopBtn);
    this.root.style.display = "none";
    void this.start();
  }

  private async start(): Promise<void> {
    const opts = await getOptions();
    if (!opts.controls) return;
    await this.poll();
    setInterval(() => void this.poll(), 1500);
  }

  private async poll(): Promise<void> {
    if (this.busy) return;
    try { this.set((await getRun(this.runId)).state ?? null); } catch { /* server away; keep the last state */ }
  }

  private set(s: RunState | null): void {
    if (s === this.state) return;
    this.state = s;
    // Finished runs have nothing to control.
    this.root.style.display = s && s !== "finished" ? "" : "none";
    this.label.textContent = s ? STATE_TEXT[s] : "";
    this.label.dataset.state = s ?? "";
    this.pauseBtn.style.display = s === "running" ? "" : "none";
    this.resumeBtn.style.display = s === "paused" || s === "stopped" ? "" : "none";
    this.stopBtn.style.display = s === "running" || s === "paused" ? "" : "none";
    if (s) this.onState?.(s);
  }

  private async send(action: "pause" | "resume" | "stop"): Promise<void> {
    const wasStopped = this.state === "stopped";
    this.busy = true;
    for (const b of [this.pauseBtn, this.resumeBtn, this.stopBtn]) b.disabled = true;
    if (action === "resume" && wasStopped) this.label.textContent = "run: starting…";
    try {
      const r = await controlRun(this.runId, action);
      this.busy = false;
      this.set(r.state ?? null);
      // A stopped run being replayed: follow it live now that it is going again.
      if (action === "resume" && wasStopped && !this.live) location.href = `/?run=${encodeURIComponent(this.runId)}&live=1&cam=follow`;
    } catch (e) {
      alert(`could not ${action} the run:\n${(e as Error).message}`);
    } finally {
      this.busy = false;
      for (const b of [this.pauseBtn, this.resumeBtn, this.stopBtn]) b.disabled = false;
    }
  }
}

/** Resume a stopped run from the picker, then open it live. */
export async function resumeFromPicker(runId: string): Promise<void> {
  try {
    await controlRun(runId, "resume");
    location.href = `/?run=${encodeURIComponent(runId)}&live=1&cam=follow`;
  } catch (e) {
    alert(`could not resume ${runId}:\n${(e as Error).message}`);
  }
}

function field(label: string, input: HTMLElement, hint = ""): HTMLElement {
  return el("label", { class: "field" }, el("span", { text: label }), input, hint ? el("small", { class: "muted", text: hint }) : null);
}

/** The "new run" form. On success it opens the run live. */
export function newRunForm(opts: Options): HTMLElement {
  const form = el("form", { class: "new-run" });
  const controller = el("select", { name: "controller" });
  for (const [v, t] of [["llm", "LLM agent"], ["sensible_bot", "sensible bot"], ["random_bot", "random bot"]]) controller.append(el("option", { value: v, text: t }));
  const model = el("select", { name: "model" });
  for (const m of opts.models) {
    const price = m.input_per_m != null ? `  ($${m.input_per_m} / $${m.output_per_m} per M tokens)` : m.provider === "mock" ? "  (free, offline)" : "";
    model.append(el("option", { value: m.name, text: m.name + price }));
  }
  if (opts.models.some((m) => m.name === "haiku")) model.value = "haiku";
  const memory = el("input", { name: "memory", type: "number", min: "0", max: "20000", step: "100", value: "2000" });
  const steps = el("input", { name: "steps", type: "number", min: "1", max: "10000", value: "300" });
  const seed = el("input", { name: "seed", type: "number", value: "1" });
  const world = el("select", { name: "world" });
  for (const w of opts.worlds) world.append(el("option", { value: w, text: w === "world" ? "normal" : w.replace(/^world_/, "") }));
  const runId = el("input", { name: "run_id", type: "text", placeholder: "automatic", pattern: "[A-Za-z0-9][A-Za-z0-9_.\\-]{0,63}" });
  const delay = el("input", { name: "delay", type: "number", min: "0", max: "5", step: "0.1", value: "0.3" });
  // Long-term file: pick or name a lineage; empty means no long-term file.
  const lineage = el("input", { name: "lineage", type: "text", placeholder: "none", list: "lineage-list",
    pattern: "[A-Za-z0-9][A-Za-z0-9_.\\-]{0,63}" });
  const lineageList = el("datalist", { id: "lineage-list" });
  for (const l of opts.lineages ?? []) lineageList.append(el("option", { value: l.name, text: `${l.generations} generations, ${l.chars} chars${l.busy ? ", busy" : ""}` }));
  const longterm = el("input", { name: "longterm", type: "number", min: "1", max: "20000", step: "100", value: "800" });
  const lineageInfo = el("small", { class: "muted", text: "carries the long-term file between runs" });
  lineage.addEventListener("input", () => {
    const l = (opts.lineages ?? []).find((x) => x.name === lineage.value.trim());
    if (l?.longterm_chars) longterm.value = String(l.longterm_chars);
    lineageInfo.textContent = l ? `generation ${l.generations + 1} next${l.busy ? ` · held by ${l.busy}` : ""}` : lineage.value.trim() ? "new lineage" : "carries the long-term file between runs";
    syncLt();
  });
  const lineageField = el("label", { class: "field" }, el("span", { text: "lineage" }), lineage, lineageList, lineageInfo);
  const longtermField = field("long-term chars", longterm, "limit of the file that carries over");
  const syncLt = () => { longtermField.style.display = controller.value === "llm" && lineage.value.trim() ? "" : "none"; };
  const modelField = field("model", model);
  const memoryField = field("memory chars", memory, "0 turns the memory file off");
  const delayField = field("step delay (s)", delay, "slows a bot down so you can watch");
  const msg = el("p", { class: "form-msg" });
  const go = el("button", { type: "submit", class: "play wide", text: "start run" });
  const sync = () => {
    const llm = controller.value === "llm";
    modelField.style.display = memoryField.style.display = llm ? "" : "none";
    delayField.style.display = llm ? "none" : "";
    lineageField.style.display = llm ? "" : "none";
    syncLt();
  };
  controller.addEventListener("change", sync);
  sync();
  form.append(
    el("div", { class: "fields" }, field("controller", controller), modelField, memoryField, lineageField, longtermField, delayField,
      field("world steps", steps, "a day is 300; night starts at 200"), field("seed", seed), field("world", world),
      field("run id", runId)),
    el("div", { class: "form-row" }, go, msg));
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const llm = controller.value === "llm";
    go.disabled = true;
    msg.className = "form-msg muted";
    msg.textContent = "starting…";
    try {
      const r = await startRun({
        controller: controller.value, model: llm ? model.value : undefined, memory_chars: Number(memory.value),
        max_steps: Number(steps.value), seed: Number(seed.value), world: world.value,
        run_id: runId.value.trim() || undefined, step_delay: llm ? 0 : Number(delay.value),
        lineage: llm && lineage.value.trim() ? lineage.value.trim() : undefined,
        longterm_chars: llm && lineage.value.trim() ? Number(longterm.value) : undefined,
      });
      location.href = `/?run=${encodeURIComponent(r.run_id)}&live=1&cam=follow`;
    } catch (e) {
      msg.className = "form-msg error";
      msg.textContent = (e as Error).message;
      go.disabled = false;
    }
  });
  return form;
}
