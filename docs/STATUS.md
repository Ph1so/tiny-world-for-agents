# Status

Reviewed 2026-10-07 from a clean install. Every check below was run by hand, not read off a test. `uv run pytest -q`: 220 passed, 0 failed, about 90 s. `npm run build`: clean.

Hard mode added 2026-10-08 (see below). `uv run pytest -q`: 241 passed, 0 failed, about 100 s.

## Hard mode

An optional world preset with three pressures, so an LLM agent has to keep a plan in its memory
file instead of re-deriving it each step. All knobs are config fields, OFF by default: the
default `configs/world.yaml`, every prior test, and the samples are unchanged. Full rationale,
knob list and renames are in docs/DECISIONS.md under "Hard mode".

- **The three pressures.** Fog (`view_radius` 12->4, the "in view" block only; the viewer is
  untouched). Lethal nights (`zombie_max` 10, `zombie_step_every` 1, `zombie_damage` 4, zombies
  break soft blocks via `zombie_breaks`/`zombie_break_steps` but never stone/workbench/furnace/
  door, `torch_radius` 3). Scarcity (`food_drain_every` 6, `berry_density_mult` 0.5,
  `animal_count_mult` 0.5).
- **Final tuned value:** only `food_drain_every` was tuned (9 gave 10/10 sensible survival = too
  easy; 6 gives the middle ground).
- **Measured, seeds 1-10 at 600 steps (hard):** random_bot 0/10 survive, all die in the first
  night; sensible_bot (upgraded) 6/10 survive (losing seeds: 5 zombie + 1 hunger). Every recipe
  reachable on seeds 1-10 (recipe graph + a spawn flood fill reaching log/stone/coal/iron/berry/
  water with animals present). Determinism holds across two processes; alien mode and the
  banned-words check both pass in hard mode. Numbers are reproducible from the seeded sim.
- **Configs:** `configs/world_hard.yaml`, `configs/run_hard.yaml`, `configs/sweeps/hard_mem.yaml`.
  A run or sweep config now names a world with a `world:` key.

Run a hard-mode LLM run (the owner runs the real model; no API key was used in the build):

```
uv run python -m tinyworld.runner.run --run-config configs/run_hard.yaml --run-id haiku_hard
#   haiku, memory 2000, K 3, on_death respawn_keep_memory, world_hard, 600 steps
uv run python -m tinyworld.runner.sweep configs/sweeps/hard_mem.yaml
#   haiku x memory [0, 500, 2000] x seeds [1, 2] x 600 steps, world_hard, estimate ~$0.33, budget $3
```

## Milestones

| Milestone | Status | Evidence |
|---|---|---|
| M1 simulation core | done | Text CLI played by hand (move, mine, craft, a bad command gives "Unknown action." and costs a step). Same seed and bot in two separate processes gave the same world hash after 800 steps. 220 unit tests cover every action and recipe. |
| M2 bots and balance | done | Seeds 1 to 10, 1500 steps. Random bot: first death at steps 124 to 649, within 2 days (600 steps) on 9 of 10 seeds, 2 to 5 deaths per run (hunger, zombie, drowning). Sensible bot: 0 deaths on 10 of 10 seeds. Every recipe reachable on seeds 1 to 20 (test). |
| M3 viewer | done with a caveat | Replay, live mode (followed a slow bot run while it was written), orbit, follow and map cameras, compare view, no console errors in headless Chromium. Stars at night were missing and are fixed. 60 fps was not measured: the sandbox has only software GL. Draw calls 40 to 52, 120 to 160 k triangles. Check once on a laptop with `?debug=1`. |
| M4 agent, adapters, memory | done with a caveat | 200 step mock run writes all six files in the documented formats. Over-limit edits are rejected, logged in memory.jsonl and events.jsonl, and the next observation says "Memory edit rejected. It was 2 characters over the limit." Unreadable replies become a 1 step wait with "Your reply could not be read." Banned-words test passes. Resume of a truncated run gives byte-identical logs (a resume bug was fixed, see DECISIONS 75). Not run: 200 steps with a real model, no API key here. |
| M5 memory visualiser | done | Scrubbed with the memory buttons, the timeline canvas, and the arrow keys over 30 positions on two runs: the memory panel and observation panel matched memory.jsonl and steps.jsonl exactly every time (`viewer/scripts/check_scrub.mjs`). A rejected edit shows the unchanged file and the refused ops in red. |
| M6 sweeps and report | done | `configs/sweeps/mock.yaml` (2 models x 2 memory x 2 seeds x 200 steps) ran in 10 s and wrote report.html. Charts are labelled and readable (time charts were rebinned, see DECISIONS 78). Deleting one summary.json and running the sweep again redid only that run, with its finished steps kept. |
| M7 alien mode | done | Seed 7 in familiar and alien mode gives the same block array and spawn. No familiar block, item or creature name appears in any alien observation or result (checked by grep over the whole run). Compare view shows both side by side. |

Rule check (PLAN.md rules 4 and 5): the system prompt matches PLAN.md section 7 word for word (test). All result sentences live in `tinyworld/sim/text.py`; every distinct result over four runs was listed and read: "Got 1 stone.", "The block did not break.", "Nothing was made.", "You did not move.", "Too far." and so on. Nothing says why or what to do next.

## Run tomorrow morning

```
git clone <origin> tiny-world-for-agents && cd tiny-world-for-agents
uv sync
cd viewer && npm install && npm run build && cd ..
uv run pytest -q                                                 # 220 passed

cp .env.example .env                                             # put ANTHROPIC_API_KEY in it
uv run python -m tinyworld.runner.run --controller llm --model haiku --memory-chars 2000 --history-window 3 --max-steps 200 --run-id haiku_demo
#   first real run, about 100 model calls, roughly 2 to 5 cents. This is the M4 check that was not run here.

uv run python -m tinyworld.server --runs runs --runs samples --runs viewer/fixtures --port 8000
#   open http://127.0.0.1:8000/?run=haiku_demo and read the thoughts and the memory panel

uv run python -m tinyworld.runner.sweep configs/sweeps/first_real.yaml
#   haiku x memory [0, 2000] x seeds [1, 2] x 300 steps, estimate $0.11, budget $2, asks for a yes
uv run python -m tinyworld.server --runs runs/first_real          # the report links each run here
```

The report is at `runs/first_real/report.html`. Look at it in a browser; it is one self-contained file.

## Known issues

- The cost estimate in the sweep planner assumes 900 input tokens plus memory_chars/4 per call, 150 output tokens, and 2 world steps per call. Real runs can differ by a factor of 2 or so. Claude 4.7 and later tokenise about 30% more tokens for the same text (per the pricing page). The budget guard uses real spend, so the estimate only matters for planning.
- `configs/sweeps/memory_sweep.yaml` (the PLAN.md example) is estimated at about $89 with haiku and sonnet and has a $25 budget, so it stops partway. Raise `budget_usd` or trim `memory_chars` before running it.
- 60 fps on a laptop was not measured (software GL only here).
- `gpt54_mini`, `openrouter_example` and `ollama_example` in `configs/models.yaml` are unverified; all other entries were checked against the providers' pages on 2026-10-07.
- Prompt caching is requested on the system prompt. The prompt is short (a few hundred tokens), so some providers will not cache it. Costs are still right; the cache columns in steps.jsonl will just read zero.
- A run started with a missing API key leaves an empty `runs/<id>/` folder behind. Delete it or reuse the id.
- The viewer's `record` button uses MediaRecorder and was not tested in headless Chromium.

## First three experiments

Estimates come from the sweep planner (`--dry-run`) with the verified prices. Real cost may be about double, see above.

1. **Does memory matter at all, cheapest model.** `first_real.yaml`: haiku, memory 0 vs 2000, seeds 1 and 2, 300 steps. 4 runs, about $0.11. Read the thoughts and the memory file by hand in the viewer before trusting any metric. Then widen to memory [0, 500, 2000, 8000], seeds 1 to 3, 1500 steps: 12 runs, about $2.10.
2. **Only the model changes.** Memory 2000, seeds 1 to 3, 1500 steps, models haiku, sonnet, gpt6_luna (and sonnet46 or haiku45 for an older generation). The planner puts 3 seeds x 4 models at about $25 (haiku and gpt6_luna runs are cents, each sonnet run is about $3.50). Compare survival, recipes found, activity share and action entropy on the same seeds.
3. **Recall or discovery.** Same as 1 but `names: alien` and `shuffle_recipes: true` (copy `first_real.yaml`, change those two keys). Same cost as 1. If recipes found and tool tier fall a lot in alien mode, the familiar results were mostly Minecraft recall.
