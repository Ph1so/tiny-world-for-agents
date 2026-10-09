// Agent stats: per agent counts up to the current step (deaths, kills, crops planted, what was
// crafted, placed, gathered and eaten), read from the step results and the event log. A table
// compares the agents; tabs below break one agent's counts down by item.
import type { RunData } from "../data/run";
import type { EventLine, StepLine } from "../data/types";
import { button, clear, el } from "./dom";
import { namer, swatch, type NameOpts } from "./panels";

type Tally = Record<string, number>;

/** What one finished step adds. Item names are as the result shows them (display names). */
interface StepDelta { crafted: Tally; placed: Tally; planted: number; gathered: Tally; eaten: Tally; given: Tally;
  said: number; slept: number; invalid: number; cost: number }

interface AgentStats {
  id: number; name: string; alive: boolean;
  actions: number; invalid: number; cost: number; said: number; slept: number; planted: number;
  deaths: number; deathCauses: Tally; kills: Tally; hurt: number;
  crafted: Tally; placed: Tally; gathered: Tally; eaten: Tally; given: Tally;
}

const add = (t: Tally, k: string, n = 1) => { t[k] = (t[k] ?? 0) + n; };
const sum = (t: Tally) => Object.values(t).reduce((a, b) => a + b, 0);

/** seeds: the name results use for seeds (it differs in alien-name runs). */
function parseStep(s: StepLine, seeds: string): StepDelta {
  const d: StepDelta = { crafted: {}, placed: {}, planted: 0, gathered: {}, eaten: {}, given: {}, said: 0, slept: 0,
    invalid: s.valid ? 0 : 1, cost: s.cost_usd ?? 0 };
  const r = s.result ?? "";
  const name = s.action?.name;
  for (const m of r.matchAll(/Made (\d+) (.+?)\./g)) add(d.crafted, m[2], Number(m[1]));
  for (const m of r.matchAll(/Got (\d+) (.+?)\./g)) add(d.gathered, m[2], Number(m[1]));
  for (const m of r.matchAll(/Ate 1 (.+?)\./g)) add(d.eaten, m[1]);
  for (const m of r.matchAll(/Placed (.+?) at \(/g)) {
    if (m[1] === seeds) d.planted++;
    else add(d.placed, m[1]);
  }
  const gave = r.match(/^Gave (.+) to agent #/);
  if (gave) for (const m of gave[1].matchAll(/(.+?) x(\d+)(?:, |$)/g)) add(d.given, m[1], Number(m[2]));
  if (name === "say" && r.startsWith("Said")) d.said = 1;
  if (name === "sleep" && r.startsWith("Slept")) d.slept = 1;
  return d;
}

export class StatsPanel {
  root = el("details", { class: "panel stats", open: "" });
  private table = el("table", { class: "stats-table" });
  private tabs = el("div", { class: "stats-tabs" });
  private detail = el("div", { class: "stats-detail" });
  private cache = new WeakMap<StepLine, StepDelta>();
  private lastKey = "";
  private selected: number | null = null;
  private gen = -1;

  constructor() {
    this.root.append(el("summary", { class: "panel-head", text: "agent stats" }), this.table, this.tabs, this.detail);
  }

  private delta(s: StepLine, seeds: string): StepDelta {
    let d = this.cache.get(s);
    if (!d) { d = parseStep(s, seeds); this.cache.set(s, d); }
    return d;
  }

  /** Every agent's stats from the steps that finished by t and the events up to t. */
  private collect(run: RunData, t: number): AgentStats[] {
    const roster = run.stateAt(t)?.agents;
    const lists: [number, string, boolean, StepLine[]][] = roster?.length
      ? roster.map((g) => [g.id, g.name ?? `agent #${g.id}`, g.alive, run.stepsByAgent.get(g.id) ?? []])
      : [[-1, "agent", true, run.steps]];
    const byId = new Map<number, AgentStats>();
    const seeds = run.displayName("seeds");
    const out = lists.map(([id, name, alive, steps]) => {
      const a: AgentStats = { id, name, alive, actions: 0, invalid: 0, cost: 0, said: 0, slept: 0, planted: 0,
        deaths: 0, deathCauses: {}, kills: {}, hurt: 0, crafted: {}, placed: {}, gathered: {}, eaten: {}, given: {} };
      for (const s of steps) {
        if (s.t_end > t) break;
        const d = this.delta(s, seeds);
        a.actions++; a.invalid += d.invalid; a.cost += d.cost; a.said += d.said; a.slept += d.slept; a.planted += d.planted;
        for (const k of ["crafted", "placed", "gathered", "eaten", "given"] as const) {
          for (const [item, n] of Object.entries(d[k])) add(a[k], item, n);
        }
      }
      byId.set(id, a);
      return a;
    });
    const single = lists.length === 1 && lists[0][0] === -1 ? out[0] : null;
    for (const e of run.events as EventLine[]) {
      if (e.t > t) break;
      const who = single ?? byId.get(Number(e.detail.agent));
      if (!who) continue;
      if (e.type === "death") { who.deaths++; add(who.deathCauses, String(e.detail.cause ?? "unknown")); }
      else if (e.type === "kill") add(who.kills, String(e.detail.kind ?? "?"));
      else if (e.type === "hurt") who.hurt += Number(e.detail.amount ?? 0);
    }
    return out;
  }

  update(run: RunData, t: number, opts: NameOpts): void {
    if (!run.ready || !this.root.open) return;
    if (run.agentGen !== this.gen) { this.gen = run.agentGen; this.selected = run.primaryAgent; }   // follow the followed agent
    const key = `${t}:${run.version}:${opts.alien}:${this.selected}`;
    if (key === this.lastKey) return;
    this.lastKey = key;
    const stats = this.collect(run, t);
    if (this.selected === null || !stats.some((a) => a.id === this.selected)) this.selected = stats[0]?.id ?? null;
    const rename = namer(run, opts);
    const internal = new Map(Object.entries(run.snapshot?.display_names ?? {}).map(([k, v]) => [v, k]));
    const fam = (shown: string) => internal.get(shown) ?? shown;

    // The comparison table: one column per agent.
    clear(this.table);
    const head = el("tr", {}, el("th", {}));
    for (const a of stats) head.append(el("th", { class: a.alive ? "" : "gone", text: a.name }));
    this.table.append(el("thead", {}, head));
    const body = el("tbody");
    const zombies = (a: AgentStats) => a.kills.zombie ?? 0;
    const rows: [string, (a: AgentStats) => string | number, string?][] = [
      ["deaths", (a) => a.deaths, "bad"],
      ["damage taken", (a) => a.hurt],
      ["zombies killed", zombies],
      ["animals killed", (a) => sum(a.kills) - zombies(a)],
      ["crops planted", (a) => a.planted],
      ["wheat harvested", (a) => a.gathered[run.displayName("wheat")] ?? 0],
      ["items crafted", (a) => sum(a.crafted)],
      ["blocks placed", (a) => sum(a.placed)],
      ["items gathered", (a) => sum(a.gathered)],
      ["food eaten", (a) => sum(a.eaten)],
      ["items given", (a) => sum(a.given)],
      ["times spoke", (a) => a.said],
      ["times slept", (a) => a.slept],
      ["actions", (a) => a.actions],
      ["invalid actions", (a) => a.invalid],
      ["cost", (a) => `$${a.cost.toFixed(2)}`],
    ];
    for (const [label, get, cls] of rows) {
      const vals = stats.map(get);
      const tr = el("tr", {}, el("td", { class: "label", text: label }));
      const nums = vals.map((v) => (typeof v === "number" ? v : NaN));
      const best = Math.max(...nums.filter((n) => !Number.isNaN(n)));
      vals.forEach((v) => {
        const zero = v === 0;
        const top = stats.length > 1 && typeof v === "number" && v > 0 && v === best;
        tr.append(el("td", { class: `num${zero ? " zero" : ""}${top ? ` top${cls ? " " + cls : ""}` : ""}`, text: String(v) }));
      });
      body.append(tr);
    }
    this.table.append(body);

    // Tabs, then the selected agent broken down by item.
    clear(this.tabs);
    if (stats.length > 1) {
      for (const a of stats) {
        this.tabs.append(button(a.name, () => { this.selected = a.id; this.lastKey = ""; },
          a.id === this.selected ? "active" : ""));
      }
    }
    clear(this.detail);
    const a = stats.find((s) => s.id === this.selected);
    if (!a) return;
    const section = (title: string, tally: Tally, shown = true) => {
      const entries = Object.entries(tally).sort((x, y) => y[1] - x[1] || x[0].localeCompare(y[0]));
      const row = el("div", { class: "stats-row" }, el("span", { class: "stats-label", text: title }));
      if (entries.length === 0) row.append(el("span", { class: "muted", text: "none" }));
      for (const [item, n] of entries) {
        const f = shown ? fam(item) : item;
        row.append(el("span", { class: "chip small" }, el("i", { class: "swatch", style: `background:${swatch(f)}` }),
          shown ? rename(f) : item, el("b", { text: ` x${n}` })));
      }
      this.detail.append(row);
    };
    section("crafted", a.crafted);
    section("placed", a.placed);
    section("gathered", a.gathered);
    section("eaten", a.eaten);
    section("killed", a.kills, false);
    section("died of", a.deathCauses, false);
    if (sum(a.given) > 0) section("gave away", a.given);
  }
}
