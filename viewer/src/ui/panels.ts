// Side panels: vitals and inventory, thought and action, observation, memory, event feed.
// Each panel re-renders only when the step it shows changes.
import type { RunData } from "../data/run";
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
  private lastT = -1;
  private title = el("div", { class: "run-title" });
  private clock = el("div", { class: "clock" });
  private bars = el("div", { class: "bars" });
  private inv = el("div", { class: "inventory" });
  private barEls: Record<string, { fill: HTMLElement; label: HTMLElement }> = {};
  private lastInv = "";

  constructor() {
    this.root.append(this.title, this.clock, this.bars, this.inv);
    for (const [key, cls] of [["health", "health"], ["food", "food"], ["air", "air"]]) {
      const fill = el("div", { class: `fill ${cls}` });
      const label = el("span", { class: "bar-label" });
      const row = el("div", { class: "bar-row" }, el("span", { class: "bar-name", text: key }), el("div", { class: "bar" }, fill), label);
      this.bars.append(row);
      this.barEls[key] = { fill, label };
    }
  }

  update(run: RunData, t: number, opts: NameOpts, status: string): void {
    const s = run.stateAt(t);
    if (!s) return;
    const m = run.meta;
    this.title.textContent = `${m.runId}  ·  ${m.controller}${m.model ? " · " + m.model : ""}${m.memoryChars ? ` · memory ${m.memoryChars}` : ""}${m.names === "alien" ? " · alien" : ""}`;
    const inDay = t % m.dayLength;
    this.clock.textContent = `day ${s.day}  ·  step ${t} / ${run.maxT}  ·  ${inDay}/${m.dayLength} ${s.light}  ·  agent step ${s.i}${status ? "  ·  " + status : ""}`;
    if (t === this.lastT) return;
    this.lastT = t;
    const a = s.agent;
    const max = { health: 20, food: 20, air: 10 };
    for (const key of ["health", "food", "air"] as const) {
      const v = a[key];
      this.barEls[key].fill.style.width = `${Math.max(0, Math.min(100, (v / max[key]) * 100))}%`;
      this.barEls[key].label.textContent = `${v}/${max[key]}`;
    }
    const rename = namer(run, opts);
    const items = Object.entries(a.inventory ?? {});
    const sig = JSON.stringify(items) + JSON.stringify(a.tools ?? {}) + String(opts.alien);
    if (sig === this.lastInv) return;
    this.lastInv = sig;
    clear(this.inv);
    if (items.length === 0) this.inv.append(el("span", { class: "muted", text: "inventory empty" }));
    for (const [name, count] of items) {
      const uses = a.tools?.[name];
      const chip = el("span", { class: "chip" }, el("i", { class: "swatch", style: `background:${swatch(name)}` }),
        `${rename(name)}`, el("b", { text: ` x${count}` }), uses != null ? el("small", { text: ` ${uses} uses` }) : null);
      this.inv.append(chip);
    }
  }
}

const SWATCHES: Record<string, string> = {
  grass: "#8dd27f", dirt: "#bf8f67", sand: "#f4e3ad", stone: "#b9bcc9", log: "#a97c55", leaves: "#6fc48d",
  "iron ore": "#e0a884", planks: "#e6bd85", workbench: "#cf9152", furnace: "#8d8a99", torch: "#ffd56a", door: "#bd7f45",
  sticks: "#c9a06e", coal: "#4f4b5c", "iron ingot": "#d8dce8", berries: "#d47f99", "raw meat": "#f0918f", "cooked meat": "#b86b4a",
  "wood pickaxe": "#b9915f", "stone pickaxe": "#9ea2b3", "iron pickaxe": "#e4e7f2", "stone sword": "#9ea2b3", "iron sword": "#e4e7f2",
};
function swatch(name: string): string { return SWATCHES[name] ?? "#ccc"; }

export class AgentPanel {
  root = el("div", { class: "panel agent" });
  private lastI = -1;
  private lastAlien = false;
  private head = el("div", { class: "panel-head", text: "agent" });
  private thought = el("div", { class: "thought" });
  private action = el("div", { class: "action" });
  private result = el("div", { class: "result" });
  private obsHead = el("div", { class: "panel-head", text: "observation" });
  private obs = el("pre", { class: "observation" });

  constructor() {
    this.root.append(this.head, this.thought, this.action, this.result, this.obsHead, this.obs);
  }

  update(run: RunData, t: number, opts: NameOpts): void {
    const i = run.agentStepIndexAt(t);
    if (i === this.lastI && opts.alien === this.lastAlien) return;
    this.lastI = i; this.lastAlien = opts.alien;
    const rec = run.stepRecord(i);
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
  }
}

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

  constructor() {
    this.usage.append(this.usageFill);
    this.root.append(this.head, el("div", { class: "usage-row" }, this.usage, this.usageLabel), this.editInfo, this.body, this.ops);
  }

  update(run: RunData, t: number): void {
    const i = run.agentStepIndexAt(t);
    const k = run.memoryIndexAt(i);
    const key = `${i}:${k}:${run.memory.length}`;
    if (key === this.lastKey) return;
    this.lastKey = key;
    const limit = k >= 0 ? run.memory[k].limit : run.meta.memoryChars;
    const text = k >= 0 ? run.memory[k].text : "";
    const chars = text.length;
    const frac = limit > 0 ? chars / limit : 0;
    this.usageFill.style.width = `${Math.min(100, frac * 100)}%`;
    this.usageFill.className = `usage-fill ${frac > 0.9 ? "hot" : frac > 0.7 ? "warm" : ""}`;
    this.usageLabel.textContent = limit > 0 ? `${chars} / ${limit} chars` : `${chars} chars (no memory)`;
    clear(this.body); clear(this.ops);
    if (k <= 0) {
      this.editInfo.textContent = limit > 0 ? "no edits yet" : "this run has no memory file";
      this.editInfo.className = "edit-info muted";
      this.body.append(el("span", { class: "muted", text: text || "(empty)" }));
      return;
    }
    const m = run.memory[k];
    const before = run.memoryTextBefore(k);
    const opNames = m.ops.map((o) => o.op).join(", ");
    if (m.accepted) {
      this.editInfo.textContent = `last edit at agent step ${m.i} (${opNames})${m.i === i ? "" : "  ·  unchanged since"}`;
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
      this.editInfo.textContent = `edit at agent step ${m.i} rejected (${m.over_by} chars over). File unchanged.`;
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
