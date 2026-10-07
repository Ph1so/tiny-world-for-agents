// Line formats from docs/INTERFACES.md. Replay and live mode feed the same lines.

export type Vec3 = [number, number, number];

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
}

export type WorldLine = SnapshotLine | WorldStepLine;

export interface StepLine {
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
  i: number;
  t: number;
  ops: MemoryOp[];
  accepted: boolean;
  over_by: number;
  text: string;
  chars: number;
  limit: number;
}

export interface EventLine {
  t: number;
  i: number;
  type: string;
  detail: Record<string, unknown>;
}

export type FileName = "world" | "steps" | "memory" | "events";

export interface StreamMessage {
  file: FileName | "status";
  line: Record<string, unknown>;
}
