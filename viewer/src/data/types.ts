// Line formats from docs/INTERFACES.md. Replay and live mode feed the same lines.

export type Vec3 = [number, number, number];

/** A chest and what it holds: [x, y, z, {item: count}]. Lines without chests leave the key out. */
export type ChestEntry = [number, number, number, Record<string, number>];

export interface AgentState {
  pos: Vec3;
  health: number;
  food: number;
  air: number;
  inventory: Record<string, number>;
  tools?: Record<string, number>;
}

export interface Creature {
  id: number;
  kind: string; // sheep | chicken | zombie
  pos: Vec3;
}

/** Multi-agent runs: one entry per agent in the snapshot and every step line. */
export interface AgentEntry extends AgentState {
  id: number;
  name: string | null;
  alive: boolean;
  bed: Vec3 | null;
}

export interface SnapshotLine {
  type: "snapshot";
  t: 0;
  size: Vec3;
  sea_level: number;
  palette: string[];
  blocks_b64: string;
  agent: AgentState;
  creatures: Creature[];
  light: string;
  day: number;
  display_names: Record<string, string>;
  spawn: Vec3;
  chests?: ChestEntry[];
  /** clear | rain | storm. Runs from before weather leave it out. */
  weather?: string;
  /** The respawn bed once slept in, else null. */
  bed?: Vec3 | null;
  agents?: AgentEntry[];
}

export interface WorldStepLine {
  type: "step";
  t: number;
  i: number;
  blocks: [number, number, number, string][];
  agent: AgentState;
  creatures: Creature[];
  light: string;
  day: number;
  chests?: ChestEntry[];
  weather?: string;
  bed?: Vec3 | null;
  agents?: AgentEntry[];
}

export type WorldLine = SnapshotLine | WorldStepLine;

export interface StepLine {
  /** Multi-agent runs: whose step this is, and the world step its observation was taken at. */
  agent?: number;
  t_obs?: number;
  i: number;
  t_start: number;
  t_end: number;
  observation: string;
  raw_reply: string;
  thought: string;
  action: Record<string, unknown> & { name: string };
  result: string;
  valid: boolean;
  parse_ok: boolean;
  died: string | null;
  vitals: { health: number; food: number; air: number };
  memory_chars_used: number;
  memory_rejected: boolean;
  input_tokens: number;
  output_tokens: number;
  latency_s: number;
  cost_usd: number;
}

export interface MemoryOp {
  op: "append" | "replace" | "rewrite";
  text?: string;
  old?: string;
  new?: string;
}

export interface MemoryLine {
  agent?: number;
  i: number;
  t: number;
  ops: MemoryOp[];
  accepted: boolean;
  over_by: number;
  text: string;
  chars: number;
  limit: number;
  /** longterm.jsonl only: the end of run reflection line (i = last agent step + 1). */
  reflection?: boolean;
  thought?: string;
}

export interface EventLine {
  t: number;
  i: number;
  type: string;
  detail: Record<string, unknown>;
}

export type FileName = "world" | "steps" | "memory" | "events" | "longterm";

export interface StreamMessage {
  file: FileName | "status";
  line: Record<string, unknown>;
}
