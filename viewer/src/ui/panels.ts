// Side panels: vitals and inventory, thought and action, observation, memory, event feed.
// Each panel re-renders only when the step it shows changes.
import type { RunData } from "../data/run";
import type { StepLine } from "../data/types";
import { EVENT_ICON, clear, el, fmtAction, fmtEvent } from "./dom";
import { hasChanges, lineDiff } from "./diff";

export interface NameOpts {
  /** Show alien names next to familiar ones. */
  alien: boolean;
}

/** familiar -> "familiar (shown)" when names differ and the toggle is on. */
export function namer(run: RunData, opts: NameOpts): (n: string) => string {
  return (n: string) => {
    const shown = run.displayName(n);
    return opts.alien && shown !== n ? `${n} (${shown})` : n;
  };
}

export class StatusPanel {
  root = el("div", { class: "panel status" });
  private lastT = "";
  /** Multi-agent: called with an agent's id when its name in the roster is clicked. */
  onSelectAgent: ((id: number) => void) | null = null;
  private title = el("div", { class: "run-title" });
  private clock = el("div", { class: "clock" });
  private bars = el("div", { class: "bars" });
  private inv = el("div", { class: "inventory" });
  private chests = el("div", { class: "chests" });
  private roster = el("div", { class: "roster" });
  private barEls: Record<string, { fill: HTMLElement; label: HTMLElement }> = {};
  private lastInv = "";

  constructor() {
    this.root.append(this.title, this.clock, this.roster, this.bars, this.inv, this.chests);
    for (const [key, cls] of [["health", "health"], ["food", "food"], ["air", "air"]]) {
      const fill = el("div", { class: `fill ${cls}` });
      const label = el("span", { class: "bar-label" });
      const row = el("div", { class: "bar-row" }, el("span", { class: "bar-name", text: key }), el("div", { class: "bar" }, fill), label);
      this.bars.append(row);
      this.barEls[key] = { fill, label };
    }
  }

  private lastClock = "";

  update(run: RunData, t: number, opts: NameOpts, status: string): void {
    const s = run.stateAt(t);
    if (!s) return;
    const m = run.meta;
    const clockKey = `${t}:${run.maxT}:${status}:${opts.alien}:${run.version}`;
    if (clockKey === this.lastClock) return;
    this.lastClock = clockKey;
    this.title.textContent = `${m.runId}  ·  ${m.controller}${m.model ? " · " + m.model : ""}${m.memoryChars ? ` · memory ${m.memoryChars}` : ""}${m.names === "alien" ? " · alien" : ""}`;
    const inDay = t % m.dayLength;
    this.clock.textContent = `day ${s.day}  ·  step ${t} / ${run.maxT}  ·  ${inDay}/${m.dayLength} ${s.light}${s.weather && s.weather !== "clear" ? "  ·  " + (s.weather === "storm" ? "⛈ storm" : "🌧 rain") : ""}  ·  agent step ${s.i}${status ? "  ·  " + status : ""}`;
    const tKey = `${t}:${run.agentGen}`;
    if (tKey === this.lastT) return;
    this.lastT = tKey;
    clear(this.roster);
    for (const g of s.agents ?? []) {
      const me = g.id === run.primaryAgent;
      const row = el("button", { type: "button", class: `roster-row${me ? " me" : ""}${g.alive ? "" : " gone"}`,
        title: me ? "the agent the panels and cameras follow" : "follow this agent",
        text: `${me ? "▶ " : ""}${g.name ?? "agent"} #${g.id}  ♥${g.health} 🍗${g.food}${g.alive ? "" : "  ✝"}` });
      row.addEventListener("click", () => this.onSelectAgent?.(g.id));
      this.roster.append(row);
    }
    const a = s.agent;
    const max = { health: 20, food: 20, air: 10 };
    for (const key of ["health", "food", "air"] as const) {
      const v = a[key];
      this.barEls[key].fill.style.width = `${Math.max(0, Math.min(100, (v / max[key]) * 100))}%`;
      this.barEls[key].label.textContent = `${v}/${max[key]}`;
    }
    const rename = namer(run, opts);
    const items = Object.entries(a.inventory ?? {});
    const sig = JSON.stringify(items) + JSON.stringify(a.tools ?? {}) + JSON.stringify(s.chests ?? []) + String(opts.alien);
    if (sig === this.lastInv) return;
    this.lastInv = sig;
    clear(this.inv);
    if (m.inventorySlots > 0) {
      const used = slotsUsed(a.inventory ?? {}, m.stackSize);
      this.inv.append(el("span", { class: `slots ${used >= m.inventorySlots ? "full" : ""}`, text: `${used}/${m.inventorySlots} slots` }));
    }
    if (items.length === 0) this.inv.append(el("span", { class: "muted", text: "inventory empty" }));
    for (const [name, count] of items) {
      const uses = a.tools?.[name];
      const chip = el("span", { class: "chip" }, el("i", { class: "swatch", style: `background:${swatch(name)}` }),
        `${rename(name)}`, el("b", { text: ` x${count}` }), uses != null ? el("small", { text: ` ${uses} uses` }) : null);
      this.inv.append(chip);
    }
    clear(this.chests);
    for (const [x, y, z, held] of s.chests ?? []) {
      const row = el("div", { class: "chest-row" }, el("span", { class: "chest-at", text: `📦 ${rename("chest")} (${x},${y},${z})` }));
      const contents = Object.entries(held);
      if (contents.length === 0) row.append(el("span", { class: "muted", text: " empty" }));
      for (const [name, count] of contents) {
        row.append(el("span", { class: "chip small" }, el("i", { class: "swatch", style: `background:${swatch(name)}` }),
          `${rename(name)}`, el("b", { text: ` x${count}` })));
      }
      this.chests.append(row);
    }
  }
}

const SWATCHES: Record<string, string> = {
  grass: "#8dd27f", dirt: "#bf8f67", sand: "#f4e3ad", stone: "#b9bcc9", log: "#a97c55", leaves: "#6fc48d",
  "iron ore": "#e0a884", planks: "#e6bd85", workbench: "#cf9152", furnace: "#8d8a99", torch: "#ffd56a", door: "#bd7f45",
  sticks: "#c9a06e", coal: "#4f4b5c", "iron ingot": "#d8dce8", berries: "#d47f99", "raw meat": "#f0918f", "cooked meat": "#b86b4a",
  "wood pickaxe": "#b9915f", "stone pickaxe": "#9ea2b3", "iron pickaxe": "#e4e7f2", "wood sword": "#b9915f", "stone sword": "#9ea2b3", "iron sword": "#e4e7f2",
  "iron helmet": "#e4e7f2", "iron chestplate": "#e4e7f2", chest: "#b07a3e",
  seeds: "#c8b46a", wheat: "#e8c95a", bread: "#d9a05b", wool: "#f4efe6", bed: "#d9675f",
};
export function swatch(name: string): string { return SWATCHES[name] ?? "#ccc"; }

/** Everything that wears out takes a slot each; other items fill one slot per stack. */
const ONE_PER_SLOT = /(pickaxe|sword|helmet|chestplate)$/;
export function slotsUsed(items: Record<string, number>, stack: number): number {
  let n = 0;
  for (const [name, c] of Object.entries(items)) n += ONE_PER_SLOT.test(name) ? c : Math.ceil(c / stack);
  return n;
}

export class AgentPanel {
  root = el("div", { class: "panel agent" });
  private lastI = -1;
  private lastAlien = false;
  private lastGen = 0;
  private head = el("div", { class: "panel-head", text: "agent" });
  private thought = el("div", { class: "thought" });
  private action = el("div", { class: "action" });
  private result = el("div", { class: "result" });
  private obsHead = el("div", { class: "panel-head", text: "observation" });
  private obs = el("pre", { class: "observation" });
  private getsHead = el("div", { class: "panel-head", text: "what the agent got this step" });
  private gets = el("div", { class: "gets" });

  constructor() {
    this.root.append(this.head, this.thought, this.action, this.result, this.getsHead, this.gets, this.obsHead, this.obs);
  }

  /** Everything the model was sent for step i: the system prompt (the same every step) and the
   *  user message, rebuilt the way agent/prompt.py builds it (memory file, last K actions, then
   *  the observation, which is shown in full below). */
  private showGets(run: RunData, i: number, rec: StepLine): void {
    clear(this.gets);
    const p = run.prompts;
    const sys = p?.system[String(run.primaryAgent ?? 0)];
    if (!p || !sys) {
      this.gets.append(el("div", { class: "muted", text: run.meta.controller.includes("bot") || !p
        ? "no prompt: a bot reads the world directly (or this run predates prompts.json)" : "no prompt logged for this agent" }));
      return;
    }
    const box = (title: string, body: string, open = false) => {
      const d = el("details", { class: "gets-box" }, el("summary", { text: title }), el("pre", { class: "gets-text", text: body }));
      (d as HTMLDetailsElement).open = open;
      return d;
    };
    this.gets.append(box(`instructions · system prompt, same every step · ${sys.length} chars`, sys));
    const lines: string[] = [];
    if (p.memory_chars > 0) {
      const k = run.memoryIndexAt(i - 1);
      const mem = k >= 0 ? run.memory[k].text : "";
      lines.push(`memory file (${mem.length} of ${p.memory_chars} characters used)`, mem, "");
    }
    const K = p.history_window;
    const prev: StepLine[] = [];
    for (let j = Math.max(1, i - K); j < i; j++) { const s = run.stepRecord(j); if (s) prev.push(s); }
    lines.push(`last ${K} actions:`);
    if (prev.length === 0 || K === 0) lines.push("none yet");
    else prev.forEach((s) => lines.push(`${s.i}. ${pyJson(s.action)} -> ${s.result}`));
    lines.push("", "observation:", "(shown below)");
    const user = lines.join("\n");
    this.gets.append(box(`this step's message · memory + last ${K} actions + observation · ${user.length - 13 + rec.observation.length} chars`, user, true));
  }

  update(run: RunData, t: number, opts: NameOpts): void {
    const i = run.agentStepIndexAt(t);
    const rec = run.stepRecord(i);
    const key = rec ? i : -2 - i;      // a step that has not arrived yet must be redrawn when it does
    if (key === this.lastI && opts.alien === this.lastAlien && run.agentGen === this.lastGen) return;
    this.lastI = key; this.lastAlien = opts.alien; this.lastGen = run.agentGen;
    const rename = namer(run, opts);
    this.head.textContent = `agent step ${i}${rec ? `  (world ${rec.t_start} → ${rec.t_end})` : ""}`;
    if (!rec) {
      this.thought.textContent = i === 0 ? "before the first step" : "step not logged yet";
      this.thought.className = "thought muted";
      this.action.textContent = ""; this.result.textContent = ""; this.obs.textContent = "";
      return;
    }
    this.thought.className = rec.thought ? "thought" : "thought muted";
    this.thought.textContent = rec.thought || (rec.parse_ok ? "(no thought logged)" : "(reply could not be read)");
    clear(this.action);
    this.action.append(el("span", { class: `tag ${rec.valid ? "" : "bad"}`, text: rec.action?.name ?? "?" }), " ", fmtAction(rec.action, rename));
    this.result.textContent = rec.result + (rec.died ? `  💀 died: ${rec.died}` : "");
    this.result.className = `result ${rec.died ? "bad" : ""}`;
    this.obs.textContent = rec.observation;
    this.showGets(run, i, rec);
  }
}

/** json.dumps(x, separators=(", ", ": ")) as Python writes it (agent/prompt.py describe_action). */
function pyJson(v: unknown): string {
  if (v === null || v === undefined) return "null";
  if (typeof v === "string") return JSON.stringify(v).replace(/[\u007f-\uffff]/g, (c) => "\\u" + c.charCodeAt(0).toString(16).padStart(4, "0"));
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  if (Array.isArray(v)) return "[" + v.map(pyJson).join(", ") + "]";
  return "{" + Object.entries(v as Record<string, unknown>).map(([k, x]) => `${pyJson(k)}: ${pyJson(x)}`).join(", ") + "}";
}

/** The memory file, or with kind "longterm" the long-term file of a lineage run. */
export class MemoryPanel {
  root = el("div", { class: "panel memory" });
  private lastKey = "";
  private head = el("div", { class: "panel-head", text: "memory" });
  private usage = el("div", { class: "usage" });
  private usageFill = el("div", { class: "usage-fill" });
  private usageLabel = el("span", { class: "usage-label" });
  private editInfo = el("div", { class: "edit-info" });
  private body = el("div", { class: "memory-text" });
  private ops = el("div", { class: "ops" });
  /** Called when the user asks to see the diff for a version (timeline click lands here too). */

  constructor(private kind: "memory" | "longterm" = "memory") {
    this.usage.append(this.usageFill);
    this.root.append(this.head, el("div", { class: "usage-row" }, this.usage, this.usageLabel), this.editInfo, this.body, this.ops);
    if (kind === "longterm") { this.root.classList.add("longterm"); this.root.style.display = "none"; }
  }

  update(run: RunData, t: number): void {
    const lt = this.kind === "longterm";
    const lines = lt ? run.longterm : run.memory;
    if (lt) {
      if (lines.length === 0) return;
      this.root.style.display = "";
      this.head.textContent = `long-term · ${run.meta.lineage || "lineage"} generation ${run.meta.generation || "?"}`;
    }
    // At the very end of a finished run, show the long-term file after the reflection too.
    const i = lt && run.finished && t >= run.maxT ? Number.MAX_SAFE_INTEGER : run.agentStepIndexAt(t);
    const k = run.memoryIndexAt(i, lines);
    const key = `${i}:${k}:${lines.length}:${run.agentGen}`;
    if (key === this.lastKey) return;
    this.lastKey = key;
    const limit = k >= 0 ? lines[k].limit : lt ? run.meta.longtermChars : run.meta.memoryChars;
    const text = k >= 0 ? lines[k].text : "";
    const chars = text.length;
    const frac = limit > 0 ? chars / limit : 0;
    this.usageFill.style.width = `${Math.min(100, frac * 100)}%`;
    this.usageFill.className = `usage-fill ${frac > 0.9 ? "hot" : frac > 0.7 ? "warm" : ""}`;
    this.usageLabel.textContent = limit > 0 ? `${chars} / ${limit} chars` : `${chars} chars (no memory)`;
    clear(this.body); clear(this.ops);
    if (k <= 0) {
      this.editInfo.textContent = lt ? (run.meta.generation > 1 ? "as handed on by the previous generation" : "first generation: starts empty")
        : limit > 0 ? "no edits yet" : "this run has no memory file";
      this.editInfo.className = "edit-info muted";
      this.body.append(el("span", { class: "muted", text: text || "(empty)" }));
      return;
    }
    const m = lines[k];
    const before = run.memoryTextBefore(k, lines);
    const opNames = m.ops.map((o) => o.op).join(", ") || "no change";
    if (m.accepted) {
      this.editInfo.textContent = m.reflection ? `end of run reflection (${opNames})${m.thought ? `: “${m.thought}”` : ""}`
        : `last edit at agent step ${m.i} (${opNames})${m.i === i ? "" : "  ·  unchanged since"}`;
      this.editInfo.className = "edit-info ok";
      const lines = lineDiff(before, m.text);
      if (!hasChanges(lines)) this.body.append(el("span", { class: "muted", text: m.text || "(empty)" }));
      for (const line of lines) {
        const row = el("div", { class: `dl ${line.kind}` });
        row.append(el("span", { class: "gutter", text: line.kind === "add" ? "+" : line.kind === "del" ? "−" : " " }));
        for (const s of line.spans) row.append(el("span", { class: `ws ${s.kind}`, text: s.text }));
        if (line.spans.length === 0 || line.spans.every((s) => s.text === "")) row.append(" ");
        this.body.append(row);
      }
    } else {
      this.editInfo.textContent = `${m.reflection ? "end of run reflection" : `edit at agent step ${m.i}`} rejected (${m.over_by} chars over). File unchanged.`;
      this.editInfo.className = "edit-info bad";
      for (const line of (m.text || "").split("\n")) this.body.append(el("div", { class: "dl same" }, el("span", { class: "gutter", text: " " }), el("span", { class: "ws same", text: line || " " })));
      this.ops.append(el("div", { class: "ops-head", text: "rejected ops" }));
      for (const o of m.ops) {
        const txt = o.op === "replace" ? `replace “${o.old}” → “${o.new}”` : `${o.op}: ${o.text}`;
        this.ops.append(el("div", { class: "op bad", text: txt }));
      }
    }
  }
}

export class EventFeed {
  root = el("div", { class: "panel events" });
  private list = el("div", { class: "event-list" });
  private shown = 0;
  private lastT = -1;
  private rows: { t: number; el: HTMLElement }[] = [];
  onJump: ((t: number) => void) | null = null;
  private alien = false;

  constructor() {
    this.root.append(el("div", { class: "panel-head", text: "events" }), this.list);
  }

  update(run: RunData, t: number, opts: NameOpts): void {
    if (opts.alien !== this.alien) { this.alien = opts.alien; clear(this.list); this.rows = []; this.shown = 0; }
    const rename = namer(run, opts);
    // Append rows for new events (the feed only ever grows).
    while (this.shown < run.events.length) {
      const e = run.events[this.shown++];
      const row = el("div", { class: `event ${e.type}` },
        el("span", { class: "icon", text: EVENT_ICON[e.type] ?? "•" }),
        el("span", { class: "t", text: `t${e.t}` }),
        el("span", { class: "label", text: fmtEvent(e, rename) }));
      row.addEventListener("click", () => this.onJump?.(e.t));
      this.list.append(row);
      this.rows.push({ t: e.t, el: row });
    }
    if (t === this.lastT) return;
    this.lastT = t;
    let lastPast: HTMLElement | null = null;
    for (const r of this.rows) {
      const past = r.t <= t;
      r.el.classList.toggle("future", !past);
      if (past) lastPast = r.el;
    }
    if (lastPast) {
      // Scroll inside the list only, so the side column does not jump.
      const top = lastPast.offsetTop - this.list.offsetTop, bottom = top + lastPast.offsetHeight;
      if (top < this.list.scrollTop) this.list.scrollTop = top;
      else if (bottom > this.list.scrollTop + this.list.clientHeight) this.list.scrollTop = bottom - this.list.clientHeight;
    }
  }
}
