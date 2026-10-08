// Where lines come from. Replay fetches the four files once. Live opens the websocket, which
// sends the same lines (history first, then new ones). Both call RunData.ingest.
import { RunData } from "./run";
import type { FileName, StreamMessage } from "./types";

const FILES: FileName[] = ["world", "steps", "memory", "events", "longterm"];

export interface RunListEntry {
  run_id: string;
  controller: string | null;
  model: string | null;
  memory_chars: number;
  seed: number | null;
  names?: string;
  max_steps?: number | null;
  world_steps: number;
  finished: boolean;
  /** finished | running | paused | stopping | stopped (see tinyworld/server/control.py) */
  state?: RunState;
  lineage?: string | null;
  generation?: number | null;
  longterm_chars?: number;
}

export type RunState = "finished" | "running" | "paused" | "stopping" | "stopped";

export async function listRuns(): Promise<RunListEntry[]> {
  const r = await fetch("/api/runs");
  if (!r.ok) throw new Error(`GET /api/runs: ${r.status}`);
  return r.json();
}

export async function getRun(runId: string): Promise<RunListEntry> {
  const r = await fetch(`/api/runs/${encodeURIComponent(runId)}`);
  if (!r.ok) throw new Error(`GET run: ${r.status}`);
  return r.json();
}

// ------------------------------------------------------------------ run control

export interface ModelOption { name: string; provider: string | null; model: string | null; input_per_m: number | null; output_per_m: number | null }
export interface LineageOption { name: string; generations: number; chars: number; longterm_chars: number | null; busy: string | null }
export interface Options { controls: boolean; models: ModelOption[]; worlds: string[]; lineages?: LineageOption[] }

export interface RunSpec {
  controller: string;
  model?: string;
  memory_chars?: number;
  max_steps?: number;
  seed?: number;
  world?: string;
  run_id?: string;
  step_delay?: number;
  lineage?: string;
  longterm_chars?: number;
}

export async function getOptions(): Promise<Options> {
  const r = await fetch("/api/options");
  if (!r.ok) return { controls: false, models: [], worlds: [] };   // an older server
  return r.json();
}

/** POST with the header the server wants for control calls. Throws with the server's message. */
async function post(url: string, body?: unknown): Promise<RunListEntry> {
  const r = await fetch(url, {
    method: "POST",
    headers: { "X-Tinyworld": "1", "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof data.detail === "string" ? data.detail : `${r.status}`);
  return data;
}

export function startRun(spec: RunSpec): Promise<RunListEntry> { return post("/api/runs", spec); }

export function controlRun(runId: string, action: "pause" | "resume" | "stop"): Promise<RunListEntry> {
  return post(`/api/runs/${encodeURIComponent(runId)}/${action}`);
}

async function fetchConfig(run: RunData): Promise<void> {
  const r = await fetch(`/api/runs/${encodeURIComponent(run.meta.runId)}/config.yaml`);
  if (r.ok) run.applyConfigYaml(await r.text());
}

/** Replay mode. Resolves when every file has been ingested. */
export async function loadReplay(run: RunData, onProgress?: (msg: string) => void): Promise<void> {
  await fetchConfig(run);
  for (const file of FILES) {
    onProgress?.(`loading ${file}.jsonl`);
    const r = await fetch(`/api/runs/${encodeURIComponent(run.meta.runId)}/${file}.jsonl`);
    if (!r.ok) {
      if (file === "world") throw new Error(`run ${run.meta.runId}: ${r.status}`);
      continue;
    }
    const text = await r.text();
    let start = 0;
    while (start < text.length) {
      let end = text.indexOf("\n", start);
      if (end < 0) end = text.length;
      const raw = text.slice(start, end).trim();
      start = end + 1;
      if (!raw) continue;
      try {
        await run.ingest(file, JSON.parse(raw));
      } catch (e) {
        console.warn(`bad line in ${file}.jsonl`, e);
      }
    }
  }
  run.historyDone = true;
  run.finished = true;
  run.version++;
}

/** Live mode. Keeps the websocket open and reconnects if it drops. Returns a stop function. */
export function connectLive(run: RunData, onStatus?: (msg: string) => void): () => void {
  let ws: WebSocket | null = null;
  let stopped = false;
  let queue: Promise<void> = Promise.resolve();
  // Lines already ingested per file. After a reconnect the server resends the history, and
  // these counts let us skip what we already have.
  const seen: Record<string, number> = { world: 0, steps: 0, memory: 0, events: 0, longterm: 0 };
  const skip: Record<string, number> = { world: 0, steps: 0, memory: 0, events: 0, longterm: 0 };
  fetchConfig(run).catch(() => undefined);

  const open = () => {
    if (stopped) return;
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/ws/runs/${encodeURIComponent(run.meta.runId)}`);
    onStatus?.("connecting");
    for (const f of Object.keys(seen)) skip[f] = seen[f];
    ws.onopen = () => onStatus?.("live");
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data) as StreamMessage;
      // Keep ingest order even though the snapshot decode is async.
      queue = queue.then(async () => {
        if (msg.file === "status") {
          if (msg.line.history_done) { run.historyDone = true; onStatus?.(run.finished ? "finished" : "live"); }
          if (msg.line.finished) { run.finished = true; onStatus?.("finished"); }
          run.version++;
          return;
        }
        if (skip[msg.file] > 0) { skip[msg.file]--; return; }
        seen[msg.file]++;
        await run.ingest(msg.file, msg.line);
      });
    };
    ws.onclose = () => {
      if (stopped) return;
      onStatus?.("reconnecting");
      setTimeout(open, 1500);
    };
    ws.onerror = () => ws?.close();
  };
  open();
  return () => { stopped = true; ws?.close(); };
}
