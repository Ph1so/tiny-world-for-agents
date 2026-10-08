// Which agent action is on screen at a fractional world step, how far through it is, what it is
// aimed at, and the short texts the viewer shows for it.
import type { RunData } from "../data/run";
import type { StepLine, Vec3 } from "../data/types";

export interface ActionNow {
  rec: StepLine;
  name: string;
  /** 0 at the step's t_start, 1 at its t_end. */
  p: number;
  /** World steps the action took. */
  dur: number;
  done: boolean;
  /** The cell a mine, place, store or take is aimed at. */
  target: Vec3 | null;
  creatureId: number | null;
  /** Item named by place or eat, as the agent typed it. */
  item: string | null;
}

const num = (v: unknown): number | null => {
  if (typeof v === "number" && Number.isFinite(v)) return Math.round(v);
  if (typeof v === "string" && v.trim() !== "" && Number.isFinite(Number(v))) return Math.round(Number(v));
  return null;
};

/** The action in progress at pt. Between steps that is the action leading to the next world
 *  step; exactly on a step (paused) it is the one that produced it, as the agent panel shows. */
export function actionAt(run: RunData, pt: number): ActionNow | null {
  const t0 = Math.floor(pt);
  const t = pt > t0 ? Math.min(run.maxT, t0 + 1) : t0;
  const i = run.agentStepIndexAt(t);
  const rec = i > 0 ? run.stepRecord(i) : undefined;
  if (!rec) return null;
  const a = (rec.action && typeof rec.action === "object" ? rec.action : {}) as Record<string, unknown>;
  const name = typeof a.name === "string" ? a.name : "";
  const dur = Math.max(1, rec.t_end - rec.t_start);
  const p = Math.min(1, Math.max(0, (pt - rec.t_start) / dur));
  const x = num(a.x), y = num(a.y), z = num(a.z);
  return {
    rec, name, p, dur, done: p >= 1,
    target: ["mine", "place", "store", "take"].includes(name) && x !== null && y !== null && z !== null ? [x, y, z] : null,
    creatureId: name === "attack" ? num(a.id) : null,
    item: typeof a.item === "string" ? a.item : firstItem(a.items),
  };
}

/** The first item named in an "items" object (store, take, drop, craft). */
function firstItem(items: unknown): string | null {
  if (!items || typeof items !== "object") return null;
  const k = Object.keys(items as object)[0];
  return k ?? null;
}

/** "log x3 + dirt x2" from an "items" object. */
function itemsText(items: unknown): string {
  if (!items || typeof items !== "object") return "";
  return Object.entries(items as Record<string, unknown>).map(([k, v]) => `${k} x${v}`).join(" + ");
}

export const ACTION_ICON: Record<string, string> = {
  move: "🚶", mine: "⛏", place: "🧱", craft: "🔨", eat: "🍽", attack: "⚔", wait: "⏳",
  store: "📦", take: "📦", drop: "🗑",
};

/** What the agent is doing, e.g. "⛏ mining stone". blockName is the block at the target now. */
export function actionVerb(act: ActionNow, blockName: string | null, creatureKind: string | null): string {
  const a = act.rec.action as Record<string, unknown>;
  const icon = ACTION_ICON[act.name] ?? "❓";
  switch (act.name) {
    case "move": return `${icon} walking ${String(a.dir ?? "")}`;
    case "mine": return `${icon} mining ${blockName && blockName !== "air" ? blockName : "block"}`;
    case "place": return `${icon} placing ${act.item ?? "block"}`;
    case "craft": {
      const items = a.items && typeof a.items === "object" ? Object.keys(a.items as object).join(" + ") : "";
      return `${icon} crafting${items ? " " + items : ""}`;
    }
    case "eat": return `${icon} eating ${act.item ?? ""}`;
    case "attack": return `${icon} attacking ${creatureKind ?? "creature"}${act.creatureId !== null ? " #" + act.creatureId : ""}`;
    case "wait": return `${icon} waiting`;
    case "store": return `${icon} storing ${itemsText(a.items)} in chest`;
    case "take": return `${icon} taking ${itemsText(a.items)} from chest`;
    case "drop": return `${icon} dropping ${itemsText(a.items)}`;
    default: return `${icon} ${act.name || "unreadable reply"}`;
  }
}

/** Short text that floats up when an action finishes, or null for nothing. ok is false for a miss. */
export function resultFloat(result: string): { text: string; ok: boolean } | null {
  let m: RegExpMatchArray | null;
  // Inventory limit: a pickup with no room left says so, even after "Got ...".
  if (/^No room in inventory/.test(result) || / No room for /.test(result)) return { text: "✖ inventory full", ok: false };
  if (/^No room in the /.test(result)) return { text: "✖ chest full", ok: false };
  if (/ is not empty\./.test(result)) return { text: "✖ chest not empty", ok: false };
  if (/^Not enough .+ in the /.test(result)) return { text: "✖ not in chest", ok: false };
  if (/was not stored/.test(result)) return { text: "✖ can't store that", ok: false };
  if (/^No \S.* at \(/.test(result)) return { text: "✖ no chest there", ok: false };
  if ((m = result.match(/^Stored (.+)\.$/))) return { text: `📦 ${m[1]}`, ok: true };
  if ((m = result.match(/^Took (.+)\.$/))) return { text: `+${m[1]}`, ok: true };
  if ((m = result.match(/^Dropped (.+)\.$/))) return { text: `🗑 ${m[1]}`, ok: true };
  if ((m = result.match(/^Got (\d+) (.+?)\./))) return { text: `+${m[1]} ${m[2]}`, ok: true };
  if ((m = result.match(/^Made (\d+) (.+?)\./))) return { text: `+${m[1]} ${m[2]}`, ok: true };
  if ((m = result.match(/^Ate 1 (.+?)\./))) return { text: `ate ${m[1]}`, ok: true };
  if ((m = result.match(/^Placed (.+?) at/))) return { text: `−1 ${m[1]}`, ok: true };
  if (/It is gone\./.test(result)) return { text: "defeated!", ok: true };
  if (/^Hit /.test(result)) return { text: "hit!", ok: true };
  if (/^You did not move/.test(result)) return { text: "✖ blocked", ok: false };
  if (/did not break/.test(result)) return { text: "✖ won't break", ok: false };
  if (/^Nothing was made/.test(result)) return { text: "✖ nothing made", ok: false };
  if (/^Nothing is there/.test(result)) return { text: "✖ nothing there", ok: false };
  if (/not empty/.test(result)) return { text: "✖ cell taken", ok: false };
  if (/^Too far/.test(result)) return { text: "✖ too far", ok: false };
  if (/^No such item|^Not enough/.test(result)) return { text: "✖ don't have it", ok: false };
  if (/was not (placed|eaten)/.test(result)) return { text: "✖ can't", ok: false };
  if (/^No creature/.test(result)) return { text: "✖ missed", ok: false };
  if (/^(Unknown action|Bad arguments)/.test(result)) return { text: "✖ invalid", ok: false };
  return null;
}
