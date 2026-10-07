# Tiny World

A small voxel sandbox with no goal, and an LLM agent that lives in it with a size-limited memory file.

This file is the build plan. Build the milestones in section 12 in order. After each milestone, run its acceptance checks and stop for review before starting the next one.

## 1. What this project is for

It is a research prototype. It should answer three questions.

1. What does an LLM agent do in a world that gives it no goal?
2. How does behaviour change when only the model changes?
3. How does behaviour change when only the memory size changes?

The game is a measuring tool. Clean, comparable runs matter more than game features.

## 2. Rules that protect the experiment

These are not negotiable. Ask before changing any of them.

1. **The simulation is headless.** It never imports the renderer or the agent. The viewer and the agent are both clients of the simulation.
2. **The simulation is deterministic.** The same seed and the same list of actions always give the same world. All randomness comes from one seeded generator.
3. **The world waits for the agent.** Time only moves when the agent acts. A slow model and a fast model get the same world.
4. **The agent is told no goals and no tips.** The prompt text in section 7 is fixed. Do not add advice, recipes, warnings, or hints about what is good or bad.
5. **Feedback says what happened, never why or what to do next.** "The block did not break" is fine. "You need a pickaxe" is not.
6. **Memory size is counted in characters.** Tokens differ between models, characters do not.
7. **Everything is logged.** Every run can be replayed step by step from its log files with no model calls.
8. **Conditions share seeds.** Every model and memory size in a sweep runs on the same set of world seeds.

## 3. Stack

| Part | Choice |
|---|---|
| Simulation, agent, runner | Python 3.11+, numpy, pydantic for configs |
| Live server | FastAPI with a WebSocket |
| Viewer | TypeScript, Three.js, Vite |
| Analysis | pandas, plotly |
| Tests | pytest |
| Env | uv |

API keys are read from a `.env` file that is gitignored.

## 4. Repo layout

```
tinyworld/
  sim/          world, blocks, items, recipes, creatures, vitals, actions, observations
  agent/        loop, prompt, memory, response parser
  llm/          adapters (anthropic, openai_compatible, mock)
  bots/         random_bot, sensible_bot (no LLM)
  runner/       single run, sweep, cost guard
  server/       FastAPI app for live view and replay files
  analysis/     metrics, report
viewer/         Three.js app
configs/        world.yaml, run.yaml, sweeps/*.yaml
runs/           one folder per run (gitignored)
tests/
```

## 5. The world

### Size and terrain

- 64 x 64 wide, 32 tall. x is east, z is south, y is up. Sea level is y = 12.
- Generated from a seed with simple height noise.
- Must contain grass plains, forest patches, at least one lake, sandy shores, and hills with exposed stone, coal, and iron.
- The map edge is deep water.

### Blocks

grass, dirt, sand, stone, water, log, leaves, berry bush, coal ore, iron ore, planks, workbench, furnace, torch, door.

### Items

Every minable block as an item, plus sticks, coal, iron ingot, berries, raw meat, cooked meat, wood pickaxe, stone pickaxe, iron pickaxe, stone sword, iron sword.

### Recipes

The agent is never shown this table. It finds recipes by trying combinations.

| Inputs | Output | Needs nearby |
|---|---|---|
| 1 log | 4 planks | |
| 2 planks | 4 sticks | |
| 4 planks | workbench | |
| 6 planks | door | workbench |
| 3 planks + 2 sticks | wood pickaxe | workbench |
| 3 stone + 2 sticks | stone pickaxe | workbench |
| 2 stone + 1 stick | stone sword | workbench |
| 8 stone | furnace | workbench |
| 1 coal + 1 stick | 4 torches | |
| 1 raw meat + 1 fuel | cooked meat | furnace |
| 1 iron ore + 1 fuel | iron ingot | furnace |
| 3 iron ingot + 2 sticks | iron pickaxe | workbench |
| 2 iron ingot + 1 stick | iron sword | workbench |

Fuel is coal or planks. "Nearby" means within 2 cells.

A failed craft keeps the items and still costs one step.

### Mining rules

- By hand you can break grass, dirt, sand, leaves, log, planks, berry bush, and placed blocks.
- Stone and coal ore need any pickaxe.
- Iron ore needs a stone or iron pickaxe.
- Better tools break blocks in fewer steps.
- Tools wear out after a set number of uses.
- The best tool in the inventory is used automatically. There is no equip action.

### Creatures

- **Sheep and chickens.** Passive. They wander. They drop raw meat. A few respawn each morning.
- **Zombies.** They appear at night on dark ground at least 12 cells from the agent, up to 6 at once. They chase the agent when within 10 cells. They move one cell every 2 steps, so the agent can outrun them. They cannot break blocks or open doors. They are removed at sunrise. They do not appear within 6 cells of a torch.

### Vitals

All values live in `configs/world.yaml`. Starting defaults are below. Tune them in milestone 2.

| Thing | Default |
|---|---|
| Health | max 20 |
| Food | max 20, drops 1 every 15 steps |
| Starving | at 0 food, lose 1 health every 5 steps |
| Healing | at 15+ food, gain 1 health every 10 steps |
| Air | max 10, lose 1 per step with head under water, then 2 health per step |
| Fall damage | 1 health per block fallen beyond 3 |
| Zombie hit | 3 health, at most once every 2 steps |
| Berries / raw meat / cooked meat | +2 / +3 / +8 food |
| Berry bush | regrows after 150 steps |

### Day and night

One day is 300 steps. Steps 0 to 199 are day. Steps 200 to 299 are night. The agent sees a light level of bright, dim, or dark. It is not told what night means.

### Death

Config option `on_death`.

- `respawn_keep_memory` (default). Back to the start point, inventory gone, world unchanged, memory file kept.
- `respawn_wipe_memory`. Same but the memory file is emptied.
- `end_run`. The run stops.

The next observation says "You died. Cause: hunger. You are back at the starting point. Your items are gone." and nothing more.

### Name modes

LLMs already know Minecraft. To separate real discovery from recall, support two modes in config.

- `familiar`. Normal names like log, stone, zombie.
- `alien`. Every block, item, and creature name is swapped for a made-up word chosen from the seed. Option `shuffle_recipes` also reassigns recipe inputs within the same tier so prior knowledge of Minecraft recipes does not help.

The viewer always shows the normal look and can show both names.

## 6. Actions and observations

### Actions

| Action | Effect |
|---|---|
| `move(dir, steps)` | dir is north, south, east, west, up, or down. steps is 1 to 8. Climbs one block automatically. Up and down only work in water. Stops early if blocked, hurt, or a new creature comes into view. |
| `mine(x, y, z)` | Try to break a block within 3 cells. Repeats until it breaks, fails, or the agent is hurt. |
| `place(item, x, y, z)` | Put a block from the inventory into an empty cell within 3 cells. |
| `craft(items)` | Combine a set of inventory items, for example `{"planks": 3, "sticks": 2}`. |
| `eat(item)` | Try to eat an inventory item. |
| `attack(id)` | Hit a creature within 2 cells. |
| `wait(steps)` | Do nothing for 1 to 8 steps. Stops early if hurt. |

Each action costs at least one step. Multi-step actions cost their real number of steps.

An invalid action costs one step and returns a plain error such as "No such item in inventory."

### Observations

Plain text, under about 600 tokens. Example.

```
step 412 | day 2 | light dim
position (31, 14, 22)
health 17/20 | food 9/20 | air 10/10
inventory: stone pickaxe (41 uses left), planks x6, sticks x2, berries x3
last action: mine (31, 13, 23). Result: got 1 stone.

close (within 3 cells):
  stone: (31,13,24) (32,13,23) (30,13,23)
  dirt: (31,13,21) (32,13,22)
  open air above you
in view (within 12 cells):
  log: 9 seen, nearest (35,14,20)
  water: nearest (40,12,22)
  berry bush: 2 seen, nearest (27,14,18)
creatures:
  sheep #7 at (28,14,25)
```

Rules for observations.

- Only list blocks the agent could see from where it stands. No x-ray.
- Give absolute coordinates so the agent can write places into memory.
- Never add adjectives or judgments such as "dangerous" or "useful".

## 7. Agent loop, prompt, and memory

### One step

1. Build the user message from the memory file, the last K steps, and the current observation.
2. Call the model.
3. Parse the reply.
4. Apply the memory edit.
5. Apply the action to the simulation.
6. Log everything.

### System prompt

Use this text exactly. Only fill in the values in braces.

```
You are in a world. The world moves forward each time you act.

Each step you are shown your memory file, your last {K} actions with their results, and what you can observe right now. You do not remember anything else from earlier steps.

Your memory file holds at most {N} characters. You may edit it every step. An edit that would go over the limit is rejected and the file stays as it was.

Actions:
{one line per action with its arguments, mechanical wording only}

Reply with one JSON object and nothing else:
{"thought": "...", "memory": [...], "action": {...}}
```

When the memory size is 0, leave out the memory paragraph and the memory field.

There is no sentence about surviving, exploring, building, or doing well. Add a test that fails if the prompt or any observation template contains words like goal, should, try to, survive, danger, tip, hint, or recipe.

### Reply format

```json
{
  "thought": "free text, logged for the human, never shown back to the agent",
  "memory": [
    {"op": "append", "text": "..."},
    {"op": "replace", "old": "...", "new": "..."},
    {"op": "rewrite", "text": "..."}
  ],
  "action": {"name": "move", "dir": "north", "steps": 3}
}
```

- `memory` may be empty.
- Memory ops are applied in order before the action.
- If the result is over the limit, none of the ops are applied. The next observation includes "Memory edit rejected. It was {n} characters over the limit."
- If the reply cannot be parsed, the agent does a 1 step wait and the next observation says "Your reply could not be read." Count these.

### Memory file

- Starts empty.
- Shown every step with a line such as "memory file (812 of 2000 characters used)".
- Every version is saved with the step number.

### History window

`history_window` K is how many past steps are shown as one-line "action then result" pairs. Default 3. This must stay small or the context window becomes the real memory and the file stops mattering. K is a sweep knob too.

## 8. Model adapters

One small interface.

```python
class LLMClient:
    def complete(self, system: str, user: str, max_tokens: int) -> Reply:
        ...  # Reply has text, input_tokens, output_tokens, latency_s
```

Adapters to build.

- `anthropic` using the official SDK.
- `openai_compatible` with a configurable base URL, so it covers OpenAI, OpenRouter, and local models through Ollama.
- `mock` that returns scripted replies for tests.

Other requirements.

- Model ids, prices per million tokens, and any reasoning settings live in `configs/models.yaml`. Do not hardcode model ids. Look up current ids and prices in each provider's docs when filling this in.
- Leave sampling settings at provider defaults unless the config says otherwise. Record what was used.
- Retry with backoff on rate limits and server errors.
- Use prompt caching for the system prompt where the provider supports it.

## 9. Logging

Each run writes to `runs/<run_id>/`.

| File | Contents |
|---|---|
| `config.yaml` | Full resolved config, seed, model id, git commit |
| `steps.jsonl` | One line per agent step with the observation, raw reply, parsed action, result, vitals, tokens, latency, cost |
| `world.jsonl` | Per step block changes and creature positions, enough for the viewer to replay with no simulation |
| `memory.jsonl` | Every memory version with step number, ops, full text, and characters used |
| `events.jsonl` | Firsts and notable moments (first time each block is mined, each item crafted, each death with cause, each zombie killed) |
| `summary.json` | Final metrics from section 11 |

Runs must be resumable from the last complete step.

## 10. Viewer

A browser app with two modes. Live mode connects by WebSocket to a running run. Replay mode loads a run folder.

### Look

- Low poly and cute. Flat shaded blocks, soft pastel colours, soft shadows.
- The agent is a small blocky character with a simple face.
- Sheep, chickens, and zombies are small and rounded with a gentle idle bob. Zombies should look goofy, not scary.
- The sky fades from day to dusk to night with stars. Torches glow.
- Movement between steps is smoothly interpolated so it does not look like teleporting.
- Build the terrain as merged chunk meshes with hidden faces removed. Rebuild only the chunk that changed.

### Camera

Orbit camera, follow camera, and a top-down map view.

### Panels

- Vitals bars, inventory, day and step counter.
- The current observation as the agent saw it.
- The agent's thought and chosen action.
- **Memory panel.** The current memory file with a usage bar. The last edit is highlighted with additions in green and removals in red.
- **Memory timeline.** A chart of memory size over steps with a mark at every edit and every rejected edit. Clicking a point shows the file at that step and the diff from the version before.
- Event feed from `events.jsonl`.

### Replay controls

Play, pause, speed from 1x to 50x, a scrubber over the full run, and jump to next event or next memory edit.

### Compare view

Load two runs side by side with synced scrubbers, so two models or two memory sizes on the same seed can be watched together.

### Recording

The log files are the recording. Also add a button that saves the canvas to a video file with the browser MediaRecorder.

## 11. Experiments and analysis

### Sweep config

```yaml
name: memory_sweep
seeds: [1, 2, 3]
max_steps: 1500
models: [model_a, model_b]
memory_chars: [0, 500, 2000, 8000, 32000]
history_window: [3]
names: familiar
on_death: respawn_keep_memory
budget_usd: 25
parallel_runs: 4
```

The runner expands this into every combination and runs them.

### Cost guard

- Before a sweep starts, print the number of runs, an estimate of model calls and cost, and ask for confirmation.
- Track spend during the sweep and stop cleanly when `budget_usd` is reached.

### Baselines

- `random_bot` picks valid actions at random.
- `sensible_bot` is hand-coded to gather food, make tools, and wall itself in at night.
- Memory size 0.

### Metrics per run

Survival.
- Steps survived per life, number of deaths, cause of each death.

Progress.
- Distinct blocks mined, distinct items crafted, recipes found, deepest tool tier reached, failed craft attempts.

What it chose to do.
- Share of steps spent on each activity (moving, mining, placing, crafting, eating, fighting, waiting).
- Map cells visited.
- Blocks placed, and the size of the largest connected group of placed blocks.
- Where it was at night (enclosed, in the open, near a torch).

Stuck or looping.
- Longest streak of the same action.
- Action entropy over a sliding window of 50 steps.
- Count of unreadable replies and invalid actions.

Memory.
- Characters used over time, number of edits by op type, rejected edits, characters changed per step.
- How long a line of memory survives before being changed or removed.

Cost.
- Tokens, dollars, and wall-clock time.

### Report

`python -m tinyworld.analysis.report runs/<sweep>` writes one `report.html` with these charts.

- Each metric by model and memory size, averaged over seeds, with the spread shown.
- Activity share over time for each condition.
- Memory size over time for each condition.
- A table linking every run to its replay in the viewer.

## 12. Milestones

### M1. Simulation core

Build `sim/` with terrain, blocks, items, recipes, creatures, vitals, day and night, death, actions, and observations.

Acceptance.
- Unit tests for every action and every recipe.
- A determinism test where the same seed and actions give an identical world hash.
- A text CLI where a human can type actions and read observations.

### M2. Bots and balance

Build `random_bot` and `sensible_bot`. Tune `world.yaml`.

Acceptance.
- Over 10 seeds, the random bot usually dies within 2 days.
- Over 10 seeds, the sensible bot usually survives 5 days.
- Every recipe is reachable on every seed from 1 to 20.

### M3. Viewer

Build live and replay modes with the look from section 10, driven by bot runs.

Acceptance.
- A bot run can be watched live and then replayed from its folder with identical results.
- Holds 60 fps on a laptop.

### M4. Agent, adapters, memory

Build `llm/` and `agent/`.

Acceptance.
- A full run with the mock adapter passes with no network.
- The banned-words test on the prompt and observation templates passes.
- A 200 step run with one real model completes and logs every file in section 9.
- Over-limit memory edits are rejected and logged.

### M5. Memory visualiser

Add the memory panel, memory timeline, diff view, and event feed to the viewer.

Acceptance.
- Scrubbing to any step shows the exact memory file and observation from that step.

### M6. Sweeps and report

Build the sweep runner, cost guard, metrics, and report.

Acceptance.
- A small sweep of 2 models x 2 memory sizes x 2 seeds x 200 steps runs end to end and produces `report.html`.
- A stopped sweep resumes without redoing finished runs.

### M7. Alien mode

Add alien names and recipe shuffling. Add the compare view.

Acceptance.
- The same seed in familiar and alien mode gives the same terrain.
- No familiar name appears anywhere in an alien mode observation.

## 13. Later ideas

Not part of the prototype.

- Two agents in one world with a `say` action.
- Image observations in place of text.
- A second pass where a model labels each memory line by type (map note, recipe, rule, plan) to chart what the agent chooses to keep.
- Ask the agent at the end of a run what it was trying to do, and compare that with what it did.
