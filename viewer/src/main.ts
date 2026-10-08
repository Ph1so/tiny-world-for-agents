// Entry point. Routes:
//   /?run=ID              replay a run
//   /?run=ID&live=1       follow a run that is still being written
//   /compare?a=ID&b=ID    two runs side by side with one scrubber
//   /                     run picker
// Extra query keys: t=STEP (start there, paused), cam=orbit|follow|map|pov, names=both (alien names on),
// debug=1 (draw call counter).
import "./style.css";
import { getOptions, listRuns, type RunListEntry } from "./data/source";
import { Player } from "./player";
import { RunView } from "./runview";
import { Controls } from "./ui/controls";
import { button, clear, el } from "./ui/dom";
import type { NameOpts } from "./ui/panels";
import { newRunForm, resumeFromPicker, RunControlBar } from "./ui/runcontrol";

const app = document.getElementById("app")!;
const params = new URLSearchParams(location.search);
const isCompare = location.pathname.replace(/\/$/, "").endsWith("/compare") || params.has("a");
const showDebug = params.has("debug");

async function picker(): Promise<void> {
  const root = el("div", { class: "picker" });
  root.append(el("h1", { text: "tiny world" }), el("p", { class: "muted", text: "pick a run to replay, or follow one live" }));
  app.append(root);
  const opts = await getOptions();
  if (opts.controls) {
    const details = el("details", { class: "new-run-box" }, el("summary", { text: "＋ new run" }), newRunForm(opts));
    root.append(details);
  }
  let runs: RunListEntry[] = [];
  try { runs = await listRuns(); } catch (e) { root.append(el("p", { class: "error", text: `could not list runs: ${(e as Error).message}` })); return; }
  if (runs.length === 0) root.append(el("p", { text: "no runs found. Start the server with --runs pointing at a folder of runs." }));
  const table = el("table", { class: "runs" });
  table.append(el("tr", {}, ...["run", "controller", "model", "memory", "seed", "steps", "state", "", ""].map((h) => el("th", { text: h }))));
  for (const r of runs) {
    const row = el("tr", {},
      el("td", {}, el("a", { href: `/?run=${encodeURIComponent(r.run_id)}`, text: r.run_id })),
      el("td", { text: r.controller ?? "" }),
      el("td", { text: (r.model ?? "–") + (r.lineage ? `  ·  ${r.lineage} g${r.generation ?? "?"}` : "") }),
      el("td", { text: String(r.memory_chars) + (r.longterm_chars ? ` + ${r.longterm_chars}` : "") }),
      el("td", { text: String(r.seed ?? "") }), el("td", { text: `${r.world_steps}${r.max_steps ? " / " + r.max_steps : ""}` }),
      el("td", {}, el("span", { class: "state-badge", "data-state": r.state ?? "", text: r.state ?? "" }),
        r.state === "stopped" && opts.controls ? button("resume", () => void resumeFromPicker(r.run_id), "small") : null),
      el("td", {}, el("a", { href: `/?run=${encodeURIComponent(r.run_id)}&live=1&cam=follow`, text: "live" })),
      el("td", {}, button("compare…", () => {
        const other = prompt("compare with run id:", runs.find((x) => x.run_id !== r.run_id)?.run_id ?? "");
        if (other) location.href = `/compare?a=${encodeURIComponent(r.run_id)}&b=${encodeURIComponent(other)}`;
      }, "small")));
    table.append(row);
  }
  root.append(table);
}

function mount(views: RunView[], player: Player, names: NameOpts, live: boolean): void {
  clear(app);
  player.live = live;
  if (live) player.speed = 5;
  const stageRow = el("div", { class: `stage-row ${views.length > 1 ? "compare" : ""}` }, ...views.map((v) => v.root));
  const first = views[0];
  const controls = new Controls(player, {
    nextEvent: () => { const t = first.run.nextEventT(player.t); if (t != null) player.seek(t); },
    prevEvent: () => { const t = first.run.prevEventT(player.t); if (t != null) player.seek(t); },
    nextMemory: () => { const t = first.run.nextMemoryEditT(player.t); if (t != null) player.seek(t); },
    prevMemory: () => { const t = first.run.prevMemoryEditT(player.t); if (t != null) player.seek(t); },
    setCamera: (m) => views.forEach((v) => v.setCamera(m)),
    toggleRecord: () => first.recorder.toggle(),
    toggleAlien: () => { names.alien = !names.alien; return names.alien; },
    showAlienToggle: true,
    alienOn: names.alien,
    goLive: live ? () => { player.live = true; player.seek(player.maxT); player.play(); } : undefined,
  });
  const header = el("div", { class: "topbar" },
    el("a", { href: "/", class: "home", text: "tiny world" }),
    el("span", { class: "muted", text: views.length > 1 ? `compare: ${views.map((v) => v.run.meta.runId).join("  vs  ")}` : (live ? "live" : "replay") }),
    el("span", { class: "grow" }),
    el("span", { class: "muted small", text: "space play/pause · ←/→ step · e next event · m next memory edit · drag to orbit" }));
  if (views.length === 1) {
    // Pause, resume or stop the run itself (shown only while it is not finished).
    const rc = new RunControlBar(first.run.meta.runId, live);
    rc.onState = (s) => { first.runState = s; };
    controls.root.append(rc.root);
  }
  app.append(header, stageRow, controls.root);
  for (const v of views) v.resize();
  window.addEventListener("resize", () => views.forEach((v) => v.resize()));

  let last = performance.now();
  let started = false;
  const loop = (now: number) => {
    const dt = Math.min(0.1, (now - last) / 1000);
    last = now;
    let maxT = Infinity;
    for (const v of views) maxT = Math.min(maxT, v.run.maxT);
    player.maxT = Math.max(0, maxT);
    if (!started && views.every((v) => v.run.ready) && views.some((v) => v.run.maxT > 0)) {
      started = true;
      if (live) { player.seek(player.maxT); player.play(); }
      else if (params.has("t")) player.seek(Number(params.get("t")));
      else player.play();
    }
    if (live && player.live && player.playing) player.pt = Math.max(player.pt, player.maxT - 1);
    player.tick(dt);
    controls.refresh();
    for (const v of views) v.frame(showDebug);
    requestAnimationFrame(loop);
  };
  requestAnimationFrame(loop);
  views.forEach((v) => v.start());
  const cam = params.get("cam");
  if (cam) controls.root.querySelectorAll<HTMLButtonElement>("button.cam").forEach((b) => { if (b.textContent === cam) b.click(); });
}

(async () => {
  const names: NameOpts = { alien: params.get("names") === "both" };
  const player = new Player();
  if (isCompare) {
    const a = params.get("a"), b = params.get("b");
    if (!a || !b) { app.append(el("p", { class: "error", text: "compare needs ?a=RUN&b=RUN" })); return; }
    mount([new RunView(a, false, player, names), new RunView(b, false, player, names)], player, names, false);
    return;
  }
  const runId = params.get("run");
  if (!runId) { await picker(); return; }
  const live = params.get("live") === "1";
  mount([new RunView(runId, live, player, names)], player, names, live);
})();
