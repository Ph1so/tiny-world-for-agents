// One data model for replay and live mode. Lines are ingested in any order per file, but
// each file in increasing step order. Everything the scene and panels read comes from here.
import type {
  AgentEntry, AgentState, Creature, EventLine, FileName, MemoryLine, SnapshotLine, StepLine, WorldLine,
  WorldStepLine, ChestEntry } from "./types";

export interface WorldState {
  t: number;
  i: number;
  agent: AgentState;
  creatures: Creature[];
  light: string;
  day: number;
  chests?: ChestEntry[];
  weather?: string;
  bed?: [number, number, number] | null;
  agents?: AgentEntry[];
}

export interface RunMeta {
  runId: string;
  dayLength: number;
  nightStart: number;
  dimSteps: number;
  names: string;
  controller: string;
  model: string | null;
  memoryChars: number;
  /** Inventory slots (0 = no limit) and stack size, from the world config. */
  inventorySlots: number;
  stackSize: number;
  /** Long-term file (lineage runs): limit, lineage name, generation. 0 / "" when off. */
  longtermChars: number;
  lineage: string;
  generation: number;
  viewRadius: number;
}

export class RunData {
  meta: RunMeta;
  snapshot: SnapshotLine | null = null;
  size: [number, number, number] = [64, 32, 64];
  palette: string[] = [];
  paletteId: Map<string, number> = new Map();
  /** Blocks at the snapshot. */
  base: Uint8Array = new Uint8Array(0);
  /** Blocks at `blocksT`. */
  blocks: Uint8Array = new Uint8Array(0);
  blocksT = 0;
  worldByT: (WorldStepLine | undefined)[] = [];
  maxT = 0;
  steps: StepLine[] = [];
  stepByI: Map<number, StepLine> = new Map();
  memory: MemoryLine[] = [];
  longterm: MemoryLine[] = [];
  events: EventLine[] = [];
  /** Multi-agent runs: the agent the panels and camera follow (the first), and every agent's
   *  steps and memory lines. The followed agent's also fill steps / stepByI / memory. */
  primaryAgent: number | null = null;
  stepsByAgent: Map<number, StepLine[]> = new Map();
  memoryByAgent: Map<number, MemoryLine[]> = new Map();
  /** prompts.json: the system prompt per agent ("0" when alone), K and the memory size. */
  prompts: { system: Record<string, string>; history_window: number; memory_chars: number } | null = null;
  /** "say" events, for speech bubbles. */
  says: EventLine[] = [];
  /** Bumped on every ingested line, so consumers can poll cheaply. */
  version = 0;
  ready = false;
  historyDone = false;
  finished = false;
  /** Called for every cell that changes when blocksT moves. */
  onBlockChange: ((x: number, y: number, z: number, id: number) => void) | null = null;
  onReady: (() => void) | null = null;

  constructor(runId: string) {
    this.meta = { runId, dayLength: 300, nightStart: 200, dimSteps: 20, names: "familiar",
      controller: "", model: null, memoryChars: 0, viewRadius: 12,
      longtermChars: 0, lineage: "", generation: 0, inventorySlots: 0, stackSize: 32 };
  }

  // ------------------------------------------------------------------ ingest

  applyConfigYaml(text: string): void {
    const num = (key: string, dflt: number) => {
      const m = text.match(new RegExp(`^\\s*${key}:\\s*(\\d+)`, "m"));
      return m ? parseInt(m[1], 10) : dflt;
    };
    const str = (key: string, dflt: string) => {
      const m = text.match(new RegExp(`^${key}:\\s*(\\S+)`, "m"));
      return m ? m[1] : dflt;
    };
    this.meta.dayLength = num("day_length", 300);
    this.meta.nightStart = num("night_start", 200);
    this.meta.dimSteps = num("dim_steps", 20);
    this.meta.names = str("names", "familiar");
    this.meta.controller = str("controller", "");
    const model = str("model", "null");
    this.meta.model = model === "null" ? null : model.replace(/^['"]|['"]$/g, "");
    this.meta.memoryChars = num("memory_chars", 0);
    if (/^mode:\s*multi/m.test(text)) {               // per-agent settings sit under agents:
      const n = (text.match(/^- id:/gm) ?? []).length || (text.match(/^\s+- id:/gm) ?? []).length;
      this.meta.controller = `multi x${n}`;
      const m = text.match(/^\s+model:\s*(\S+)/m);
      this.meta.model = m ? m[1].replace(/^['"]|['"]$/g, "") : null;
    }
    this.meta.longtermChars = num("longterm_chars", 0);
    this.meta.inventorySlots = num("inventory_slots", 0);
    this.meta.stackSize = num("stack_size", 32) || 32;
    this.meta.lineage = str("lineage", "");
    this.meta.generation = num("generation", 0);
    this.meta.viewRadius = num("view_radius", 12);
    this.version++;
  }

  async ingest(file: FileName, line: Record<string, unknown>): Promise<void> {
    switch (file) {
      case "world": await this.ingestWorld(line as unknown as WorldLine); break;
      case "steps": this.ingestStep(line as unknown as StepLine); break;
      case "memory": this.ingestMemory(line as unknown as MemoryLine); break;
      case "longterm": this.longterm.push(line as unknown as MemoryLine); break;
      case "events": this.ingestEvent(line as unknown as EventLine); break;
    }
    this.version++;
  }

  private async ingestWorld(line: WorldLine): Promise<void> {
    if (line.type === "snapshot") {
      this.snapshot = line;
      this.size = line.size;
      this.palette = line.palette;
      this.paletteId = new Map(line.palette.map((n, i) => [n, i]));
      this.base = await decodeBlocks(line.blocks_b64, line.size);
      this.blocks = this.base.slice();
      this.blocksT = 0;
      this.state0 = null;
      if (line.agents?.length) {
        this.primaryAgent = line.agents[0].id;
        for (const st of this.stepsByAgent.get(this.primaryAgent) ?? []) { this.steps.push(st); this.stepByI.set(st.i, st); }
        for (const m of this.memoryByAgent.get(this.primaryAgent) ?? []) this.memory.push(m);
      }
      this.ready = true;
      this.onReady?.();
      return;
    }
    this.worldByT[line.t] = line;
    if (line.t > this.maxT) this.maxT = line.t;
  }

  private ingestStep(line: StepLine): void {
    if (line.agent != null) {
      const list = this.stepsByAgent.get(line.agent) ?? [];
      list.push(line);
      this.stepsByAgent.set(line.agent, list);
      if (line.agent !== this.primaryAgent) return;
    }
    this.steps.push(line);
    this.stepByI.set(line.i, line);
  }

  private ingestMemory(line: MemoryLine): void {
    if (line.agent != null) {
      const list = this.memoryByAgent.get(line.agent) ?? [];
      list.push(line);
      this.memoryByAgent.set(line.agent, list);
      if (line.agent !== this.primaryAgent) return;
    }
    this.memory.push(line);
  }

  private ingestEvent(line: EventLine): void {
    this.events.push(line);
    if (line.type === "say") this.says.push(line);
  }

  /** Multi-agent: the step an agent was on at world step t (its last step that started by t). */
  agentStepAt(agent: number, t: number): StepLine | undefined {
    const list = this.stepsByAgent.get(agent);
    if (!list) return undefined;
    let best: StepLine | undefined;
    for (const s of list) { if (s.t_start <= t) best = s; else break; }
    return best;
  }

  // ------------------------------------------------------------------ queries

  index(x: number, y: number, z: number): number {
    const [sx, , sz] = this.size;
    return x + z * sx + y * sx * sz;
  }

  blockAt(x: number, y: number, z: number): number {
    const [sx, sy, sz] = this.size;
    if (x < 0 || y < 0 || z < 0 || x >= sx || y >= sy || z >= sz) return 0;
    return this.blocks[this.index(x, y, z)];
  }

  private state0: WorldState | null = null;

  /** World state (agent, creatures, light, day) at world step t. t = 0 is the snapshot.
   *  Returns stored objects, nothing is allocated per call. */
  stateAt(t: number): WorldState | null {
    if (!this.snapshot) return null;
    if (t <= 0) {
      if (!this.state0) {
        const s = this.snapshot;
        this.state0 = { t: 0, i: 0, agent: s.agent, creatures: s.creatures, light: s.light, day: s.day, chests: s.chests,
                        weather: s.weather, bed: s.bed, agents: s.agents };
      }
      return this.state0;
    }
    let line = this.worldByT[t];
    if (!line) {
      // A gap (should not happen). Fall back to the nearest earlier line.
      for (let k = t - 1; k >= 1; k--) { line = this.worldByT[k]; if (line) break; }
      if (!line) return this.stateAt(0);
    }
    return line;
  }

  /** The agent step that world step t belongs to (0 before the first). */
  agentStepIndexAt(t: number): number {
    const line = this.worldByT[t];
    return line ? line.i : 0;
  }

  stepRecord(i: number): StepLine | undefined {
    return this.stepByI.get(i);
  }

  /** Index into this.memory of the version in force after agent step i (-1 if none). */
  memoryIndexAt(i: number, lines: MemoryLine[] = this.memory): number {
    let lo = 0, hi = lines.length - 1, ans = -1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      if (lines[mid].i <= i) { ans = mid; lo = mid + 1; } else hi = mid - 1;
    }
    return ans;
  }

  /** Text of the memory file after agent step i. */
  memoryTextAt(i: number): string {
    const k = this.memoryIndexAt(i);
    return k < 0 ? "" : this.memory[k].text;
  }

  /** Text before memory line k (the last accepted version earlier than it). */
  memoryTextBefore(k: number, lines: MemoryLine[] = this.memory): string {
    for (let j = k - 1; j >= 0; j--) if (lines[j].accepted) return lines[j].text;
    return "";
  }

  /** First world step of agent step i. */
  tOfAgentStep(i: number): number {
    const rec = this.stepByI.get(i);
    if (rec) return rec.t_end;
    for (let t = 1; t <= this.maxT; t++) { const l = this.worldByT[t]; if (l && l.i >= i) return t; }
    return this.maxT;
  }

  nextEventT(after: number): number | null {
    for (const e of this.events) if (e.t > after) return e.t;
    return null;
  }

  prevEventT(before: number): number | null {
    let best: number | null = null;
    for (const e of this.events) { if (e.t < before) best = e.t; else break; }
    return best;
  }

  nextMemoryEditT(after: number): number | null {
    for (const m of this.memory) if (m.i > 0 && m.t >= after) { const t = this.tOfAgentStep(m.i); if (t > after) return t; }
    return null;
  }

  prevMemoryEditT(before: number): number | null {
    let best: number | null = null;
    for (const m of this.memory) { if (m.i === 0) continue; const t = this.tOfAgentStep(m.i); if (t < before) best = t; else break; }
    return best;
  }

  displayName(familiar: string): string {
    return this.snapshot?.display_names?.[familiar] ?? familiar;
  }

  // ------------------------------------------------------------------ block time travel

  /** Move the block grid to world step t, reporting every changed cell through onBlockChange. */
  setBlocksT(t: number): void {
    if (!this.snapshot) return;
    t = Math.max(0, Math.min(t, this.maxT));
    if (t === this.blocksT) return;
    if (t < this.blocksT) {
      // Going back: reset to the snapshot, then roll forward. Block changes are rare, so this is cheap.
      const cb = this.onBlockChange;
      for (let k = 0; k < this.blocks.length; k++) {
        if (this.blocks[k] !== this.base[k]) {
          this.blocks[k] = this.base[k];
          if (cb) { const [sx, , sz] = this.size; const y = Math.floor(k / (sx * sz)); const r = k - y * sx * sz; cb(r % sx, y, Math.floor(r / sx), this.base[k]); }
        }
      }
      this.blocksT = 0;
    }
    for (let k = this.blocksT + 1; k <= t; k++) {
      const line = this.worldByT[k];
      if (!line) continue;
      for (const [x, y, z, name] of line.blocks) {
        const id = this.paletteId.get(name) ?? 0;
        this.blocks[this.index(x, y, z)] = id;
        this.onBlockChange?.(x, y, z, id);
      }
    }
    this.blocksT = t;
  }
}

async function decodeBlocks(b64: string, size: [number, number, number]): Promise<Uint8Array> {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  const ds = new DecompressionStream("deflate");
  const stream = new Blob([bytes]).stream().pipeThrough(ds);
  const buf = new Uint8Array(await new Response(stream).arrayBuffer());
  const n = size[0] * size[1] * size[2];
  if (buf.length !== n) throw new Error(`snapshot has ${buf.length} cells, expected ${n}`);
  return buf;
}
