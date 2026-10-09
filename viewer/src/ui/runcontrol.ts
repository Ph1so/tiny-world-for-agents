// Controlling the run itself (not playback): the pause / resume / stop buttons in the run view,
// and the new run form on the picker. Both talk to the server's /api/runs control endpoints.
import { controlRun, getOptions, getRun, startRun, type AgentSpec, type Options, type RunState, type SettingDef } from "../data/source";
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

const NAMES = ["Ada", "Bo", "Cy", "Dee", "Eli", "Fay", "Gus", "Hal"];

/** One row of the agents list. */
class AgentRow {
  root = el("div", { class: "agent-row" });
  name: HTMLInputElement;
  kind: HTMLSelectElement;
  model: HTMLSelectElement;
  memory: HTMLInputElement;
  persona: HTMLTextAreaElement;
  private personaBox: HTMLElement;

  constructor(opts: Options, n: number, onChange: () => void, onRemove: (r: AgentRow) => void) {
    this.name = el("input", { type: "text", value: NAMES[n % NAMES.length], maxlength: "32", pattern: "[A-Za-z0-9][A-Za-z0-9 _\\-]{0,31}" }) as HTMLInputElement;
    this.kind = el("select") as HTMLSelectElement;
    for (const [v, t] of [["llm", "model agent"], ["sensible_bot", "sensible bot"], ["random_bot", "random bot"]]) this.kind.append(el("option", { value: v, text: t }));
    this.model = el("select") as HTMLSelectElement;
    for (const m of opts.models) {
      const price = m.input_per_m != null ? `  ($${m.input_per_m} / $${m.output_per_m} per M)` : m.provider === "mock" ? "  (free, offline)" : "";
      this.model.append(el("option", { value: m.name, text: m.name + price }));
    }
    if (opts.models.some((m) => m.name === "haiku")) this.model.value = "haiku";
    this.memory = el("input", { type: "number", min: "0", max: "20000", step: "100", value: "2000", title: "memory file size in characters; 0 turns it off" }) as HTMLInputElement;
    this.persona = el("textarea", { rows: "2", maxlength: "1500",
      placeholder: "optional: a paragraph added to the end of this agent's instructions, e.g. a personality or a role" }) as HTMLTextAreaElement;
    this.personaBox = el("div", { class: "persona" }, this.persona);
    const personaBtn = button("persona", () => { this.personaBox.classList.toggle("open"); this.persona.focus(); }, "small");
    const remove = button("✕", () => onRemove(this), "small");
    remove.title = "remove this agent";
    const modelBits = el("span", { class: "llm-only" }, this.model, el("span", { class: "muted", text: "memory" }), this.memory, personaBtn);
    this.root.append(el("div", { class: "agent-line" }, this.name, this.kind, modelBits, remove), this.personaBox);
    const sync = () => { modelBits.style.display = this.kind.value === "llm" ? "" : "none"; if (this.kind.value !== "llm") this.personaBox.classList.remove("open"); onChange(); };
    this.kind.addEventListener("change", sync);
    for (const x of [this.model, this.memory, this.name]) x.addEventListener("input", onChange);
    sync();
  }

  spec(): AgentSpec {
    const llm = this.kind.value === "llm";
    return { name: this.name.value.trim(), controller: this.kind.value,
      ...(llm ? { model: this.model.value, memory_chars: Number(this.memory.value), persona: this.persona.value.trim() || undefined } : {}) };
  }
}

/** The world settings, grouped, filled with the base world's values. Only changed ones are sent. */
class SettingsBox {
  root: HTMLDetailsElement;
  private summary = el("summary");
  private inputs = new Map<string, { def: SettingDef; input: HTMLInputElement | HTMLSelectElement; wrap: HTMLElement }>();
  private base: Record<string, unknown> = {};

  constructor(defs: SettingDef[], onChange: () => void) {
    this.root = el("details", { class: "settings-box" }) as HTMLDetailsElement;
    const reset = button("reset all", () => { this.fill(this.base); onChange(); }, "small");
    this.root.append(this.summary);
    const groups = new Map<string, HTMLElement>();
    for (const d of defs) {
      let g = groups.get(d.group);
      if (!g) {
        g = el("div", { class: "fields" });
        groups.set(d.group, g);
        this.root.append(el("div", { class: "settings-group", text: d.group }), g);
      }
      let input: HTMLInputElement | HTMLSelectElement;
      if (d.kind === "bool") input = el("input", { type: "checkbox" }) as HTMLInputElement;
      else if (d.kind === "choice") {
        input = el("select") as HTMLSelectElement;
        for (const c of d.choices ?? []) input.append(el("option", { value: c, text: c.replace(/_/g, " ") }));
      } else {
        input = el("input", { type: "number", ...(d.min != null ? { min: String(d.min) } : {}), ...(d.max != null ? { max: String(d.max) } : {}),
          step: String(d.step ?? (d.kind === "int" ? 1 : "any")) }) as HTMLInputElement;
      }
      const wrap = d.kind === "bool"
        ? el("label", { class: "field check" }, input, el("span", { text: d.label }), d.hint ? el("small", { class: "muted", text: d.hint }) : null)
        : field(d.label, input, d.hint ?? "");
      input.addEventListener("input", () => { this.mark(); onChange(); });
      input.addEventListener("change", () => { this.mark(); onChange(); });
      this.inputs.set(d.key, { def: d, input, wrap });
      g.append(wrap);
    }
    this.root.append(el("div", { class: "form-row" }, reset));
  }

  setBase(values: Record<string, unknown>): void {
    this.base = values;
    this.fill(values);
  }

  private fill(values: Record<string, unknown>): void {
    for (const [k, { def, input }] of this.inputs) {
      const v = values[k];
      if (def.kind === "bool") (input as HTMLInputElement).checked = Boolean(v);
      else input.value = v == null ? "" : String(v);
    }
    this.mark();
  }

  private read(k: string): unknown {
    const { def, input } = this.inputs.get(k)!;
    if (def.kind === "bool") return (input as HTMLInputElement).checked;
    if (def.kind === "choice") return input.value;
    return def.kind === "int" ? Math.round(Number(input.value)) : Number(input.value);
  }

  changed(): Record<string, unknown> {
    const out: Record<string, unknown> = {};
    for (const k of this.inputs.keys()) {
      const v = this.read(k);
      if (v !== this.base[k] && !(typeof v === "number" && Number.isNaN(v))) out[k] = v;
    }
    return out;
  }

  private mark(): void {
    const ch = this.changed();
    for (const [k, { wrap }] of this.inputs) wrap.classList.toggle("changed", k in ch);
    const n = Object.keys(ch).length;
    this.summary.textContent = `world settings${n ? `  ·  ${n} changed` : "  ·  as the base world"}`;
  }

  value(k: string): unknown { return this.inputs.has(k) ? this.read(k) : this.base[k]; }
}

/** The "new run" form: agents, run length, clock, seed, base world and any world setting. On
 *  success it opens the run live. */
export function newRunForm(opts: Options): HTMLElement {
  const form = el("form", { class: "new-run" }) as HTMLFormElement;
  // The server checks every value and its message shows here; browser checks would block a
  // submit silently over a hidden field.
  form.noValidate = true;
  const rows: AgentRow[] = [];
  const agentList = el("div", { class: "agent-list" });
  const addBtn = button("＋ add agent", () => addRow(), "small");

  const steps = el("input", { type: "number", min: "1", max: "20000", value: "1200" }) as HTMLInputElement;
  const seed = el("input", { type: "number", value: String(1 + Math.floor(Math.random() * 999)) }) as HTMLInputElement;
  const dice = button("🎲", () => { seed.value = String(1 + Math.floor(Math.random() * 999)); update(); }, "small");
  dice.title = "a new map";
  const world = el("select") as HTMLSelectElement;
  for (const w of opts.worlds) world.append(el("option", { value: w, text: w === "world" ? "normal" : w.replace(/^world_/, "") }));
  const runId = el("input", { type: "text", placeholder: "automatic", pattern: "[A-Za-z0-9][A-Za-z0-9_.\\-]{0,63}" }) as HTMLInputElement;
  const clock = el("select") as HTMLSelectElement;
  clock.append(el("option", { value: "realtime", text: "real time: the world does not wait" }),
    el("option", { value: "lockstep", text: "step by step: waits for every agent" }));
  const tick = el("input", { type: "number", min: "0.05", max: "10", step: "0.05", value: "1" }) as HTMLInputElement;
  const delay = el("input", { type: "number", min: "0", max: "5", step: "0.1", value: "0.3" }) as HTMLInputElement;
  const lineage = el("input", { type: "text", placeholder: "none", list: "lineage-list", pattern: "[A-Za-z0-9][A-Za-z0-9_.\\-]{0,63}" }) as HTMLInputElement;
  const lineageList = el("datalist", { id: "lineage-list" });
  for (const l of opts.lineages ?? []) lineageList.append(el("option", { value: l.name, text: `${l.generations} generations${l.busy ? ", busy" : ""}` }));
  const longterm = el("input", { type: "number", min: "1", max: "20000", step: "100", value: "800" }) as HTMLInputElement;

  const clockField = field("clock", clock, "with several agents");
  const tickField = field("seconds per world step", tick, "real time only; agents think in about 3 s");
  const delayField = field("bot step delay (s)", delay, "slows a lone bot so you can watch");
  const lineageField = el("label", { class: "field" }, el("span", { text: "lineage" }), lineage, lineageList,
    el("small", { class: "muted", text: "carries a long-term file between runs (one model agent)" }));
  const longtermField = field("long-term chars", longterm);
  const settings = new SettingsBox(opts.settings ?? [], () => update());
  const estimate = el("p", { class: "estimate muted" });
  const msg = el("p", { class: "form-msg" });
  const go = el("button", { type: "submit", class: "play wide", text: "start run" }) as HTMLButtonElement;

  const haiku = opts.models.find((m) => m.name === "haiku");
  function update(): void {
    const n = rows.length, llms = rows.filter((r) => r.kind.value === "llm");
    const multi = n > 1;
    clockField.style.display = multi ? "" : "none";
    tickField.style.display = multi && clock.value === "realtime" ? "" : "none";
    delayField.style.display = !multi && llms.length === 0 ? "" : "none";
    lineageField.style.display = !multi && llms.length === 1 ? "" : "none";
    longtermField.style.display = !multi && llms.length === 1 && lineage.value.trim() ? "" : "none";
    addBtn.disabled = n >= 8;
    for (const r of rows) (r.root.querySelector("button[title='remove this agent']") as HTMLButtonElement).disabled = n === 1;
    // Rough cost and time from past Haiku runs: a decision costs about $0.00043 and takes about 3 s;
    // an action lasts about 2 world steps.
    const S = Number(steps.value) || 0;
    const realtime = multi && clock.value === "realtime";
    const tickS = Number(tick.value) || 1;
    const perStep = realtime ? 1 / (2 + 3 / tickS) : 0.5;
    let cost = 0;
    for (const r of llms) {
      const m = opts.models.find((x) => x.name === r.model.value);
      const ratio = m?.input_per_m != null && haiku?.input_per_m ? m.input_per_m / haiku.input_per_m : m?.provider === "mock" ? 0 : 1;
      cost += S * perStep * 0.00043 * ratio;
    }
    const secs = realtime ? S * tickS : llms.length ? S * perStep * 3 : S * (Number(delay.value) || 0.01) * 0.6;
    const t = secs < 90 ? `${Math.round(secs)} s` : secs < 5400 ? `${Math.round(secs / 60)} min` : `${(secs / 3600).toFixed(1)} h`;
    estimate.textContent = `${n} agent${n === 1 ? "" : "s"} · ${S} world steps (${(S / Number(settings.value("day_length") || 300)).toFixed(1)} days) · about ${t}`
      + (llms.length ? ` · roughly $${cost < 0.1 ? cost.toFixed(3) : cost.toFixed(2)}` : " · free");
  }

  function addRow(): void {
    const r = new AgentRow(opts, rows.length, update, (x) => {
      rows.splice(rows.indexOf(x), 1);
      x.root.remove();
      update();
    });
    rows.push(r);
    agentList.append(r.root);
    update();
  }

  addRow();
  world.addEventListener("change", () => { settings.setBase(opts.world_defaults?.[world.value] ?? {}); update(); });
  settings.setBase(opts.world_defaults?.[world.value] ?? {});
  for (const x of [steps, clock, tick, delay, lineage]) { x.addEventListener("input", update); x.addEventListener("change", update); }

  form.append(
    el("div", { class: "settings-group", text: "agents" }), agentList, el("div", { class: "form-row" }, addBtn),
    el("div", { class: "settings-group", text: "run" }),
    el("div", { class: "fields" }, field("world steps", steps, "a day is 300 steps; night starts at 200"),
      el("label", { class: "field" }, el("span", { text: "seed (the map)" }), el("span", { class: "seed-row" }, seed, dice)),
      field("base world", world), field("run id", runId), clockField, tickField, delayField, lineageField, longtermField),
    settings.root, estimate,
    el("div", { class: "form-row" }, go, msg));
  update();

  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    go.disabled = true;
    msg.className = "form-msg muted";
    msg.textContent = "starting…";
    const multi = rows.length > 1;
    const llms = rows.filter((r) => r.kind.value === "llm");
    try {
      const r = await startRun({
        agents: rows.map((x) => x.spec()), max_steps: Number(steps.value), seed: Number(seed.value), world: world.value,
        run_id: runId.value.trim() || undefined, settings: settings.changed(),
        ...(multi ? { clock: clock.value as "realtime" | "lockstep", tick_ms: Math.round(Number(tick.value) * 1000) } : {}),
        ...(!multi && llms.length === 0 ? { step_delay: Number(delay.value) } : {}),
        ...(!multi && llms.length === 1 && lineage.value.trim() ? { lineage: lineage.value.trim(), longterm_chars: Number(longterm.value) } : {}),
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
