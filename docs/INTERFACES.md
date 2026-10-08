# Interfaces

These formats are the contract between the simulation, the agent, the runner, the viewer, and the analysis code. Each part lives in its own folder and only talks to the others through what is written here. Do not change this file without updating every reader and writer.

## Python API of the simulation

```python
from tinyworld.sim import World, WorldConfig, load_world_config

cfg = load_world_config("configs/world.yaml")      # pydantic model. Path is optional. Keyword overrides: names="alien", shuffle_recipes=True, on_death="end_run"
world = World(cfg, seed=1)                          # names="familiar" | "alien" lives in cfg
obs: str = world.observe()                          # text the agent sees (section 6 of PLAN.md)
result = world.step(action: dict)                   # action is the parsed JSON "action" object
# result.text        one plain sentence, what happened
# result.steps       world steps used (>= 1)
# result.valid       False for an invalid action
# result.died        cause string or None
# result.deltas      list of per-world-step delta dicts (see world.jsonl)
# result.events      list of event dicts (see events.jsonl)
world.snapshot() -> dict                            # full state for world.jsonl line 0
world.state_hash() -> str                           # sha256 of full state, for determinism tests
world.vitals() -> dict                              # {"health":..,"food":..,"air":..}
world.t                                             # world step counter
world.done                                          # True when on_death == end_run and agent died
world.valid_actions() -> list[dict]                 # used by bots only, never shown to the agent
world.set_notice(text)                              # extra line shown once in the next observation
world.deaths                                        # number of deaths so far
world.display                                       # dict familiar name -> shown name (same as snapshot display_names)
world.dn(name) / world.internal(shown)              # convert one name each way (internal gives None if unknown)
```

Notes on the API.

- `result` is a `StepResult` dataclass. Its deltas have no `i` key. The run logger adds it.
- `step()` on a world that is `done` changes nothing and returns `steps` 0 and `valid` False.
- `observe()` does not change the world. A death line stays in the observation until the next `step()`. A notice is dropped by the first `step()` that comes after an `observe()` has shown it, so it can be set either before or after the step it belongs to.
- In alien mode the `item` and `items` names in an action must be the shown names. Familiar names are answered with "No such item in inventory." `valid_actions()` already returns shown names.
- A death is reported in `result.died` and as a `death` event. The sim does not touch agent memory. Wiping it in `respawn_wipe_memory` mode is the agent loop's job.

`tinyworld/sim` imports nothing from agent, llm, runner, server, analysis.

## Action JSON

```json
{"name": "move",   "dir": "north", "steps": 3}
{"name": "mine",   "x": 31, "y": 13, "z": 23}
{"name": "place",  "item": "planks", "x": 31, "y": 14, "z": 23}
{"name": "craft",  "items": {"planks": 3, "sticks": 2}}
{"name": "eat",    "item": "berries"}
{"name": "attack", "id": 7}
{"name": "wait",   "steps": 4}
```

north is -z, south is +z, east is +x, west is -x, up is +y.
Item and block names use spaces in text ("berry bush"). Parsing accepts spaces or underscores.

## Run folder `runs/<run_id>/`

Two clocks. `t` is the world step. `i` is the agent step (one model call or one bot decision). One agent step can use several world steps.

### config.yaml
Full resolved config. Keys include `run_id`, `seed`, `controller` (`llm` | `random_bot` | `sensible_bot`), `model` (id or null), `memory_chars`, `history_window`, `names`, `on_death`, `max_steps` (world steps), `git_commit`, `world` (full world config).

### world.jsonl
Line 0 is the snapshot.

```json
{"type":"snapshot","t":0,"size":[64,32,64],"sea_level":12,
 "palette":["air","grass","dirt", "..."],
 "blocks_b64":"<base64 of zlib-compressed uint8 array, index = x + z*64 + y*64*64>",
 "agent":{"pos":[31,14,22],"health":20,"food":20,"air":10,"inventory":{"planks":6}},
 "creatures":[{"id":7,"kind":"sheep","pos":[28,14,25]}],
 "light":"bright","day":1,
 "display_names":{"log":"log"},"spawn":[31,14,22]}
```

The snapshot also has `agent.tools` (see below) and `spawn` `[x,y,z]`, the starting point.

`palette` always uses the familiar names. `display_names` maps familiar name to what the agent is shown (differs only in alien mode).

Every later line is one world step.

```json
{"type":"step","t":413,"i":120,
 "blocks":[[31,13,23,"air"]],
 "agent":{"pos":[31,14,22],"health":17,"food":9,"air":10,"inventory":{"stone":1}},
 "creatures":[{"id":7,"kind":"sheep","pos":[28,14,25]}],
 "light":"dim","day":2}
```

`i` is the agent step this world step belongs to. Agent steps are numbered from 1. `i` 0 means the state before the first agent step (the snapshot, and the empty memory line).

`blocks` lists only cells that changed this step. `creatures` is the full list each step. `inventory` maps item name to count. Tools appear as `"stone pickaxe": 1` and their wear is in `agent.tools`: `{"stone pickaxe": 41}` (uses left, for the one in use). `agent.tools` is in every step line and in the snapshot.

Block, item, and creature names in world.jsonl are always familiar names.

### steps.jsonl
One line per agent step.

```json
{"i":120,"t_start":412,"t_end":413,"observation":"...","raw_reply":"...",
 "thought":"...","action":{"name":"mine","x":31,"y":13,"z":23},
 "result":"got 1 stone.","valid":true,"parse_ok":true,
 "vitals":{"health":17,"food":9,"air":10},
 "memory_chars_used":812,"memory_rejected":false,
 "input_tokens":900,"output_tokens":120,"latency_s":1.2,"cost_usd":0.004}
```

Bots write `raw_reply` "" and `thought` "" and zero tokens and cost.

Each line also has `died`, the cause string if the agent died during this step, else null. `i` starts at 1. `action` is exactly what was passed to `world.step` (shown names in alien mode). `vitals` are the values after the step. `max_steps` is checked before each agent step, so the last action can run up to 7 world steps past it.

A step is complete when its steps.jsonl line is on disk. That line is written last. Resume drops anything in the other files with a higher `i`.

### memory.jsonl
One line per agent step where the agent sent at least one memory op, plus one line at `i` 0 with the empty file.

```json
{"i":120,"t":412,"ops":[{"op":"append","text":"..."}],"accepted":true,
 "over_by":0,"text":"<full file after this step>","chars":812,"limit":2000}
```

When `accepted` is false, `text` is the unchanged file and `over_by` is how many characters over.

### events.jsonl

```json
{"t":413,"i":120,"type":"first_mine","detail":{"block":"stone"}}
```

Types: `first_mine`, `first_craft`, `craft_fail`, `first_place`, `first_eat`, `death` (detail.cause is one of hunger, drowning, fall, zombie), `respawn`, `kill` (detail.kind), `hurt` (detail.cause), `night_start`, `day_start`, `tool_broke`, `memory_rejected`, `parse_fail`, `stuck`. Names in `detail` are familiar names.

`detail` by type. `first_mine` `{block}`. `first_place` `{block}`. `first_craft` `{item}`. `first_eat` `{item}`. `craft_fail` `{items: {name: count}}`. `death` `{cause, pos}`. `respawn` `{pos}`. `stuck` `{pos}`. `kill` `{kind, id}`. `hurt` `{cause, amount}`. `night_start` and `day_start` `{day}`. `tool_broke` `{tool}`. `memory_rejected` and `parse_fail` come from the agent loop.

### summary.json
Written at the end of a run by `tinyworld.analysis.metrics`. Flat keys for the metrics in section 11 of PLAN.md, plus `run_id`, `seed`, `controller`, `model`, `memory_chars`, `history_window`, `names`, `world_steps`, `agent_steps`, `finished`.

## Controller interface of the run loop

`tinyworld/runner/run.py` has `run_loop(world, controller, logger, max_steps, on_step=None)` and the wrapper `run(run_id, controller_name, seed, max_steps, world_cfg, runs_dir, resume, controller=None, extra_config=None)`.

A controller is any object with `act(observation: str, world) -> dict`. It returns either a bare action dict, or a dict with an `action` key plus any of these optional keys.

- `raw_reply`, `thought`, `parse_ok`, `input_tokens`, `output_tokens`, `latency_s`, `cost_usd`, `memory_chars_used`, `memory_rejected`. Copied into the steps.jsonl line. Missing keys get the bot defaults.
- `memory`. A dict `{ops, accepted, over_by, text, chars, limit}`. Written to memory.jsonl with `i` and `t` added. Leave it out on steps with no memory op.
- `events`. A list of `{type, detail}` such as `parse_fail` or `memory_rejected`. Written to events.jsonl with `t` and `i` added.

Optional members of the controller.

- `on_result(result, world)`. Called right after every `world.step`. The place to record history, wipe memory when `result.died` is set, and call `world.set_notice`.
- `replay(observation, world, step_record, memory_record_or_None)`. Called on resume in place of `act` for every step already in the log, so the controller can rebuild its own state with no model calls. `on_result` is still called.
- `memory_limit`. Read once for the `limit` of the memory line at `i` 0.

`extra_config` is merged into config.yaml (`model`, `memory_chars`, `history_window`, and so on). config.yaml also has `shuffle_recipes`.

## Live server

`python -m tinyworld.server --runs runs --port 8000`

- `GET /api/runs` gives a list of `{run_id, controller, model, memory_chars, seed, world_steps, finished}`.
- `GET /api/runs/{run_id}/{file}` serves any of the files above.
- `WS /ws/runs/{run_id}` sends every existing line of world, steps, memory, and events as `{"file":"world","line":{...}}`, then keeps sending new lines as they are written.

The viewer needs nothing else. Live mode and replay mode read the same lines.
