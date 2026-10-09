"""Several agents in one world, each acting at its own pace. Logs to runs/<run_id>/.

    python -m tinyworld.runner.multi --run-id duo --agents 2 --model haiku --max-steps 1200
    python -m tinyworld.runner.multi --run-id mix --spec configs/multi_example.yaml

Threads. The world thread owns the World and the Engine and is the only one that changes them.
Each LLM agent has a thread that waits for an observation, calls its model (no lock held), and
puts the reply on a shared queue. The agent's controller sees the world through a WorldView,
which takes the world lock and points the world at that agent's body for every access. Bots
act inline on the world thread, with no delay.

An agent observes once its action has finished, then thinks; its body stands still meanwhile.

Clocks:
  realtime  the world ticks every tick_ms whatever the agents are doing; a slow thinker loses
            time, as in real life.
  lockstep  before each tick the world waits until no agent is thinking, so speed does not
            matter and a run with bots only is reproducible from its seed.

Files: config.yaml, world.jsonl (snapshot with "agents", then one line per world step),
steps.jsonl and memory.jsonl (one line per agent step, with "agent"), events.jsonl (agent
events carry detail.agent), summary.json. See docs/MULTIAGENT.md.
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import threading
import time
from pathlib import Path

import yaml

from tinyworld.agent.parser import WAIT_ONE
from tinyworld.agent.prompt import INTRO_LOCKSTEP, INTRO_REALTIME
from tinyworld.sim import World, WorldConfig, load_world_config
from tinyworld.sim.engine import Engine

from .run import PAUSE_FILE, PID_FILE, STEP_DEFAULTS, STOP_FILE, git_commit, make_bot, resolve_world_path, write_prompts

FILES = ["world", "steps", "memory", "events"]
INFLIGHT_FILE = "inflight.json"      # actions under way when the run ended, for resuming exactly


class WorldView:
    """The world as one agent's controller may see it from another thread: every attribute read
    and method call happens under the world lock with world.me set to that agent's body."""

    def __init__(self, world: World, body, lock):
        object.__setattr__(self, "_w", world)
        object.__setattr__(self, "_body", body)
        object.__setattr__(self, "_lock", lock)

    def __getattr__(self, name):
        with self._lock:
            self._w.me = self._body
            val = getattr(self._w, name)
        if not callable(val):
            return val

        def call(*args, **kwargs):
            with self._lock:
                self._w.me = self._body
                return val(*args, **kwargs)
        return call

    def observe(self) -> str:
        """The observation without its side effects (heard lines and notices stay for the agent)."""
        from tinyworld.sim.observe import render
        with self._lock:
            self._w.me = self._body
            return render(self._w)


class _Thinker(threading.Thread):
    """One LLM agent: observation in, reply out."""

    def __init__(self, aid: int, controller, view: WorldView, replies: queue.Queue):
        super().__init__(daemon=True, name=f"agent-{aid}")
        self.aid, self.controller, self.view, self.replies = aid, controller, view, replies
        self.inbox: queue.Queue = queue.Queue()

    def run(self) -> None:
        while True:
            item = self.inbox.get()
            if item is None:
                return
            obs, t_obs = item
            started = time.monotonic()
            try:
                out = self.controller.act(obs, self.view)
            except Exception as e:                   # the model call failed for good: stand still
                out = {"action": dict(WAIT_ONE), "events": [{"type": "agent_error", "detail": {"error": repr(e)[:300]}}]}
            self.replies.put((self.aid, obs, t_obs, out, time.monotonic() - started))


def _make_controller(spec: dict, seed: int, aid: int, world_cfg: WorldConfig, clock: str):
    kind = spec.get("controller", "llm")
    if kind != "llm":
        return make_bot(kind, seed + aid)
    from tinyworld.agent.controller import make_llm_controller
    return make_llm_controller(
        spec["model"], spec.get("memory_chars", 2000), spec.get("history_window", 3), world_cfg.on_death,
        seed + aid, spec.get("models_file"), spec.get("max_tokens"),
        memory_plain=spec.get("memory_plain", "append"), memory_layout=spec.get("memory_layout", "plain"),
        intro=INTRO_REALTIME if clock == "realtime" else INTRO_LOCKSTEP, persona=spec.get("persona"),
        planning=spec.get("planning", "off"), plan_chars=spec.get("plan_chars"), plan_wait=spec.get("plan_wait"),
        plan_every=spec.get("plan_every"), plan_inline=spec.get("plan_inline"), plan_cooldown=spec.get("plan_cooldown"))


def run_multi(run_id: str, agents: list[dict] | None = None, seed: int = 1, max_steps: int = 1200,
              world_cfg: WorldConfig | None = None, runs_dir: str | Path = "runs", clock: str = "realtime",
              tick_ms: int = 1000, clients: dict | None = None, resume: bool = False) -> World:
    """agents: one dict per agent: name, controller (llm | sensible_bot | random_bot), and for llm
    model, memory_chars, history_window, max_tokens, persona. clients maps an agent's index to a
    ready LLM client (tests).

    resume=True continues an existing run folder up to max_steps (a stopped run, or a finished
    one being extended): agents, seed, clock and world come from its config.yaml, the world is
    rebuilt by applying every logged action at the world step it started on (the world is
    deterministic given those), the actions still under way when it ended (inflight.json) are put
    back, each agent's memory file, recent history and costs are restored, and the files are
    appended to."""
    run_dir = Path(runs_dir) / run_id
    old_cfg: dict = {}
    if resume:
        old_cfg = yaml.safe_load((run_dir / "config.yaml").read_text())
        agents = [{k: v for k, v in a.items() if k in ("name", "controller", "model", "memory_chars", "history_window",
                                                         "max_tokens", "persona", "memory_plain", "memory_layout",
                                                         "models_file", "planning", "plan_chars", "plan_wait",
                                                         "plan_every", "plan_inline", "plan_cooldown")}
                  for a in old_cfg["agents"]]
        seed, clock, tick_ms = old_cfg["seed"], old_cfg.get("clock", "realtime"), old_cfg.get("tick_ms", 1000)
        world_cfg = WorldConfig.model_validate(old_cfg["world"])
        (run_dir / "summary.json").unlink(missing_ok=True)
    if clock not in ("realtime", "lockstep"):
        raise ValueError("clock must be realtime or lockstep")
    world_cfg = world_cfg or load_world_config()
    run_dir.mkdir(parents=True, exist_ok=True)
    fh = {n: open(run_dir / f"{n}.jsonl", "a" if resume else "w") for n in FILES}

    def write(name: str, row: dict) -> None:
        fh[name].write(json.dumps(row) + "\n")

    world = World(world_cfg, seed=seed)
    eng = Engine(world)
    lock = threading.RLock()                     # re-entrant: on_result may read through a view
    replies: queue.Queue = queue.Queue()
    ctl, thinkers, views, kinds = {}, {}, {}, {}
    for n, spec in enumerate(agents):
        aid = eng.add_agent(spec.get("name") or f"agent{n + 1}")
        kinds[aid] = spec.get("controller", "llm")
        c = _make_controller(spec, seed, n, world_cfg, clock)
        if clients and n in clients and kinds[aid] == "llm":
            c.client = clients[n]
        ctl[aid] = c
        views[aid] = WorldView(world, world.body(aid), lock)
        if kinds[aid] == "llm":
            thinkers[aid] = _Thinker(aid, c, views[aid], replies)

    if resume:
        if [a["id"] for a in old_cfg["agents"]] != list(ctl):
            raise RuntimeError(f"agent ids {list(ctl)} do not match the run's {[a['id'] for a in old_cfg['agents']]}")
    config = {"run_id": run_id, "mode": "multi", "seed": seed, "clock": clock, "tick_ms": tick_ms,
              "max_steps": max_steps, "names": world_cfg.names, "on_death": world_cfg.on_death,
              "git_commit": git_commit(), "agents": []}
    for (aid, c), spec in zip(ctl.items(), agents):
        entry = {"id": aid, "name": world.body(aid).name, "controller": kinds[aid], **{k: v for k, v in spec.items() if k not in ("name",)}}
        if hasattr(c, "config_extras"):
            entry.update(c.config_extras())
        config["agents"].append(entry)
    config["world"] = world_cfg.model_dump(mode="json")
    if resume:
        config = {**old_cfg, "max_steps": max_steps,
                  "extended": old_cfg.get("extended", []) + [{"from": old_cfg["max_steps"], "to": max_steps,
                                                              "git_commit": git_commit()}]}
    (run_dir / "config.yaml").write_text(yaml.safe_dump(config, sort_keys=False))
    llms = {aid: c for aid, c in ctl.items() if hasattr(c, "system_prompt")}
    if llms and not resume:
        system = {}
        for aid, c in llms.items():
            world.me = world.body(aid)
            system[str(aid)] = c.system_prompt(world)
        write_prompts(run_dir, system, next(iter(llms.values())))
    if not resume:
        write("world", world.snapshot())
        for aid, c in ctl.items():
            write("memory", {"agent": aid, "i": 0, "t": 0, "ops": [], "accepted": True, "over_by": 0, "text": "",
                             "chars": 0, "limit": int(getattr(c, "memory_limit", 0) or 0)})

    i_of = {aid: 0 for aid in ctl}                    # agent steps so far, per agent
    first = next(iter(ctl))
    pending: dict[int, tuple] = {}                    # aid -> (obs, t_obs, controller output, think seconds)
    if resume:
        _replay(run_dir, world, eng, ctl, i_of, pending)
    thinking: set[int] = set()
    started = time.monotonic()
    for name in (PAUSE_FILE, STOP_FILE):
        (run_dir / name).unlink(missing_ok=True)
    (run_dir / PID_FILE).write_text(str(os.getpid()))

    def give_turn(aid: int) -> None:
        """World thread, lock held: show the agent the world; a bot answers on the spot."""
        obs, t_obs = eng.observe(aid), world.t
        if kinds[aid] == "llm":
            thinking.add(aid)
            thinkers[aid].inbox.put((obs, t_obs))
        else:
            world.me = world.body(aid)
            take_reply(aid, obs, t_obs, ctl[aid].act(obs, world), 0.0)

    def take_reply(aid: int, obs: str, t_obs: int, out, secs: float) -> None:
        out = out if isinstance(out, dict) and "action" in out else {"action": out}
        pending[aid] = (obs, t_obs, out, secs)
        thinking.discard(aid)
        eng.submit(aid, out["action"])

    for t in thinkers.values():
        t.start()
    stopped = False
    try:
        with lock:
            for aid in eng.alive():
                if aid not in pending:                # a resumed in-flight action is still running
                    give_turn(aid)
        deadline = time.monotonic()
        while world.t < max_steps and not world.done:
            if (run_dir / STOP_FILE).exists():
                stopped = True
                break
            if (run_dir / PAUSE_FILE).exists():
                time.sleep(0.2)
                deadline = time.monotonic()
                continue
            # Collect replies: all of them in lockstep, whatever has arrived in real time.
            while True:
                block = clock == "lockstep" and bool(thinking)
                try:
                    aid, obs, t_obs, out, secs = replies.get(timeout=1.0) if block else replies.get_nowait()
                except queue.Empty:
                    if block:
                        if (run_dir / STOP_FILE).exists():
                            break
                        continue
                    break
                with lock:
                    take_reply(aid, obs, t_obs, out, secs)
            if (run_dir / STOP_FILE).exists():
                continue
            with lock:
                results, deltas, events = eng.tick()
                tick_i = i_of[first] + 1          # the followed (first) agent's step under way, as the viewer reads i
                for d in deltas:
                    write("world", {"type": d["type"], "t": d["t"], "i": tick_i,
                                    **{k: v for k, v in d.items() if k not in ("type", "t")}})
                for e in events:
                    write("events", {"t": e["t"], "i": tick_i, "type": e["type"], "detail": e.get("detail", {})})
                for r in results:
                    obs, t_obs, out, secs = pending.pop(r.agent)
                    c = ctl[r.agent]
                    world.me = world.body(r.agent)
                    if hasattr(c, "on_result"):
                        c.on_result(r, views[r.agent])
                    i_of[r.agent] += 1
                    i = i_of[r.agent]
                    b = world.body(r.agent)
                    rec = {"agent": r.agent, "i": i, "t_obs": t_obs, "t_start": r.t_start, "t_end": r.t_end,
                           "observation": obs, "raw_reply": out.get("raw_reply", ""), "thought": out.get("thought", ""),
                           "action": r.action, "result": r.text, "valid": r.valid,
                           "parse_ok": out.get("parse_ok", True), "died": r.died,
                           "vitals": {"health": b.health, "food": b.food, "air": b.air}, "think_s": round(secs, 3)}
                    for key in ("memory_chars_used", "memory_rejected", "input_tokens", "output_tokens",
                                "latency_s", "cost_usd"):
                        rec[key] = out.get(key, STEP_DEFAULTS[key])
                    if out.get("plan") is not None:
                        rec["plan"] = out["plan"]
                    for e in out.get("events", []):
                        write("events", {"t": t_obs, "i": tick_i, "type": e["type"],
                                         "detail": {**e.get("detail", {}), "agent": r.agent}})
                    if out.get("memory") is not None:
                        write("memory", {"agent": r.agent, "i": i, "t": r.t_start, **out["memory"]})
                    write("steps", rec)
                    if b.alive:
                        give_turn(r.agent)
                for f in fh.values():
                    f.flush()
            if clock == "realtime":
                deadline += tick_ms / 1000
                time.sleep(max(0.0, deadline - time.monotonic()))
    finally:
        # Actions still under way, so a later resume can finish and log them exactly.
        inflight = {}
        for aid, (obs, t_obs, out, secs) in pending.items():
            slot = eng.slots[aid]
            if slot.activity is not None or slot.inbox is not None:
                inflight[str(aid)] = {"obs": obs, "t_obs": t_obs, "out": out, "secs": secs,
                                      "t_start": slot.t0 if slot.activity is not None else world.t}
        (run_dir / INFLIGHT_FILE).write_text(json.dumps({"t": world.t, "agents": inflight}))
        for t in thinkers.values():
            t.inbox.put(None)
        for f in fh.values():
            f.close()
        (run_dir / PID_FILE).unlink(missing_ok=True)
        (run_dir / STOP_FILE).unlink(missing_ok=True)
    if not stopped:
        _write_summary(run_dir, world, ctl, i_of, time.monotonic() - started)
    return world


def _replay(run_dir: Path, world: World, eng: Engine, ctl: dict, i_of: dict, pending: dict) -> None:
    """Rebuild a run's world and its agents' state from its logs (see run_multi resume)."""
    from tinyworld.agent.prompt import describe_action
    steps = [json.loads(l) for l in (run_dir / "steps.jsonl").read_text().splitlines() if l]
    mems = [json.loads(l) for l in (run_dir / "memory.jsonl").read_text().splitlines() if l]
    last_world = None
    with open(run_dir / "world.jsonl") as f:
        for line in f:
            if line.strip():
                last_world = line
    end_t = json.loads(last_world)["t"]
    flight = {}
    if (run_dir / INFLIGHT_FILE).exists():
        data = json.loads((run_dir / INFLIGHT_FILE).read_text())
        if data.get("t") == end_t:
            flight = {int(k): v for k, v in data["agents"].items()}
    starts: dict[int, list] = {}
    for s in steps:
        starts.setdefault(s["t_start"], []).append((s["agent"], s["action"]))
    for aid, v in flight.items():
        starts.setdefault(v["t_start"], []).append((aid, v["out"]["action"]))
    deltas: list = []
    while world.t < end_t:
        for aid, action in starts.get(world.t, []):
            eng.submit(aid, action)
        _, deltas, _ = eng.tick()
    for aid, action in starts.get(end_t, []):           # submitted at the very end, not started yet
        eng.submit(aid, action)
    # Death notices and heard lines are cleared when an agent looks; the replay never looks, so
    # drop the ones it piled up (the agents saw them at the time).
    for b in world.bodies:
        b._death_notice, b.heard, b._notice, b._notice_shown = None, [], None, False
    # The rebuilt world should be the logged one. (Compared line to line: a world line is taken
    # inside the step, before running actions resume, so agents mid-walk are one cell behind.)
    logged = {a["id"]: a for a in json.loads(last_world).get("agents", [])}
    rebuilt = {a["id"]: a for a in (deltas[-1].get("agents", []) if deltas else [])}
    off = [rebuilt[i]["name"] for i in logged if i in rebuilt and any(
        rebuilt[i][k] != logged[i][k] for k in ("pos", "inventory", "health", "food"))]
    if off:
        print(f"resume: rebuilt state differs from the log for {off} (actions under way at the end were not saved)")
    for aid, c in ctl.items():
        mine = [s for s in steps if s["agent"] == aid]
        i_of[aid] = len(mine)
        if not hasattr(c, "history"):
            continue
        pair = getattr(c, "history_pair", lambda a, r, p: (describe_action(a), r))
        c.history = [pair(s["action"], s["result"], s.get("plan")) for s in mine]
        c.i = len(mine) + (aid in flight)
        c.deaths = sum(1 for s in mine if s.get("died"))
        c.parse_fails = sum(1 for s in mine if not s.get("parse_ok", True))
        c.total_cost_usd = sum(float(s.get("cost_usd") or 0) for s in mine)
        c.total_input_tokens = sum(int(s.get("input_tokens") or 0) for s in mine)
        c.total_output_tokens = sum(int(s.get("output_tokens") or 0) for s in mine)
        mem = [m for m in mems if m.get("agent") == aid]
        text = mem[-1]["text"] if mem else ""
        if aid in flight:
            out = flight[aid]["out"]
            c.total_cost_usd += float(out.get("cost_usd") or 0)
            if out.get("memory"):
                text = out["memory"]["text"]
            c._last_action = out["action"]
        elif mine:
            c._last_action = mine[-1]["action"]
        if c.memory_on:
            c.memory.set(text, c.i)
        if getattr(c, "planning_on", False):
            world.me = world.body(aid)
            for s in mine + ([flight[aid]["out"]] if aid in flight else []):
                c.replay_plan(s, world)
            if aid not in flight:
                c._plan_turn = None                 # only an action still under way waits for its result
    for aid, v in flight.items():
        pending[aid] = (v["obs"], v["t_obs"], v["out"], v["secs"])


def _write_summary(run_dir: Path, world: World, ctl: dict, i_of: dict, wall_s: float) -> None:
    agents = []
    for aid, c in ctl.items():
        b = world.body(aid)
        agents.append({"id": aid, "name": b.name, "alive": b.alive, "agent_steps": i_of[aid], "deaths": b.deaths,
                       "items_crafted": list(b.firsts["craft"]), "cost_usd": round(getattr(c, "total_cost_usd", 0.0), 6),
                       **({"plans_written": c.plans_written} if getattr(c, "planning_on", False) else {})})
    summary = {"mode": "multi", "world_steps": world.t, "wall_clock_s": round(wall_s, 1), "agents": agents,
               "cost_usd_total": round(sum(a["cost_usd"] for a in agents), 6)}
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2))


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--spec", default=None, help="yaml with an agents list (and any of the options below)")
    ap.add_argument("--agents", type=int, default=2, help="how many LLM agents, without --spec")
    ap.add_argument("--model", default="haiku")
    ap.add_argument("--bots", type=int, default=0, help="sensible bots added next to the LLM agents")
    ap.add_argument("--memory-chars", type=int, default=4000)
    ap.add_argument("--history-window", type=int, default=3)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--max-steps", type=int, default=None)
    ap.add_argument("--clock", choices=["realtime", "lockstep"], default=None)
    ap.add_argument("--tick-ms", type=int, default=None)
    ap.add_argument("--config", default=None, help="world yaml, default configs/world.yaml")
    ap.add_argument("--recipe-book", action="store_true", default=None, help="list every craft in the system prompt")
    ap.add_argument("--runs-dir", default="runs")
    ap.add_argument("--resume", action="store_true", help="continue the run folder up to --max-steps")
    args = ap.parse_args(argv)
    if args.resume:
        if args.max_steps is None:
            ap.error("--resume needs --max-steps (the new total)")
        w = run_multi(args.run_id, max_steps=args.max_steps, runs_dir=args.runs_dir, resume=True)
        print(f"{args.run_id}: world steps {w.t}, agents alive {[b.name for b in w.bodies if b.alive]}")
        return

    spec = (yaml.safe_load(Path(args.spec).read_text()) if args.spec else None) or {}
    agents = spec.get("agents") or (
        [{"name": f"agent{n + 1}", "controller": "llm", "model": args.model, "memory_chars": args.memory_chars,
          "history_window": args.history_window} for n in range(args.agents)]
        + [{"name": f"bot{n + 1}", "controller": "sensible_bot"} for n in range(args.bots)])
    pick = lambda flag, key, default: flag if flag is not None else spec.get(key, default)
    cfg = load_world_config(resolve_world_path(args.config or spec.get("world")),
                            recipe_book=pick(args.recipe_book, "recipe_book", None))
    w = run_multi(args.run_id, agents, seed=pick(args.seed, "seed", 1), max_steps=pick(args.max_steps, "max_steps", 1200),
                  world_cfg=cfg, runs_dir=args.runs_dir, clock=pick(args.clock, "clock", "realtime"),
                  tick_ms=pick(args.tick_ms, "tick_ms", 1000))
    alive = [b.name for b in w.bodies if b.alive]
    print(f"{args.run_id}: world steps {w.t}, agents alive {alive}, folder {Path(args.runs_dir) / args.run_id}")


if __name__ == "__main__":
    main()
