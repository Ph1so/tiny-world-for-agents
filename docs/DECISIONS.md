# Decisions

Calls made while building M1 and M2 with nobody to ask. Each one can be changed. Most are one line in `configs/world.yaml` or one small function.

## World rules that PLAN.md left open

1. **The agent is 2 cells tall, creatures are 1.** `position` is the feet cell. The head is one cell up. This is what "head under water" needs.
2. **Water holds the agent up.** In water there is no falling. `move up` and `move down` change depth. Walking into water puts the feet in the top water cell with the head in air, so swimming across a lake costs no air. Only going down uses air.
3. **Falling into water does no damage.**
4. **Creatures never enter water.** Zombies cannot follow the agent into a lake. Simple, and something an agent could find out.
5. **Doors are one cell.** The agent walks through a door cell, creatures cannot, and sight does not pass. A doorway the agent fits through needs two doors, one on top of the other. PLAN.md does not say how tall a door is. This was the least code.
6. **Zombie hit rule.** A zombie hits when its cell touches a face of the agent's feet or head cell. So walls two high on four sides plus a roof block are safe. The 2 step cooldown is shared by all zombies.
7. **Zombies spawn 12 to 24 cells from the agent** (`zombie_spawn_max_dist`), on the top of any column that is not water, with a chance of 0.08 per night step while fewer than 6 exist. PLAN.md gives only the 12. Without an upper limit most zombies would never get near on a 64 wide map. "Dark ground" is read as "any ground at night that is not within 6 cells of a torch".
8. **Zombies outside the chase range wander at random.** Passive animals move with chance 0.25 per step and do not run away when hit.
9. **Light.** bright for steps 0 to 179 of the day, dim for 180 to 199, dark for 200 to 279, dim for 280 to 299. A block above the head (leaves do not count) lowers it one level. A torch within 6 cells lifts dark to dim.
10. **Mining needs an open face.** A block with full blocks on all six sides does not break. This stops digging blind for blocks the agent was never shown. Mining does not need line of sight beyond that.
11. **Mining progress is not kept.** If the agent is hurt before the last step, the block stays whole.
12. **Tool wear.** One use per block broken (the best pickaxe wears on every block, dirt too) and one per sword hit. A failed mine costs no wear.
13. **Berry bushes.** Breaking a bush gives 2 berries and removes the block. It comes back in the same cell after 150 steps. There is no berry bush item and no coal ore item (coal ore gives coal). So "every minable block as an item" has these two exceptions.
14. **Grass gives a grass item**, not dirt.
15. **Place** works into an air or water cell within 3 cells, with no need for a block next to it.
16. **Craft** needs the exact amounts of one recipe. A wrong set, wrong amounts, or a missing workbench or furnace all give the same line, "Nothing was made." (with `rule_notes` off; see 109), cost one step, and count as a valid action with a `craft_fail` event. Naming items that are not in the inventory is an invalid action.
17. **Eating something that is not food** costs one step, keeps the item, and is a valid action.
18. **Distances are box distances** (the largest of the x, y, z differences) from the feet cell, for reach, attack, "nearby", "close", and "in view".
19. **Respawn** resets health, food, and air to full. If the start cell has been built over, the agent appears on top.
20. **Multi-step moves** report how many cells were really moved. A move that goes nowhere costs one step.
21. **Numbers I had to invent** (all in `world.yaml`): block hardness, tool speed, durability (30, 60, 150 for pickaxes, 40, 100 for swords), hand damage 2, sword damage 4 and 6, creature health (sheep 6, chicken 4, zombie 10), meat drops (sheep 2, chicken 1), animal counts (6 and 6 at the start, 2 of each back every morning up to 8).

## Observations

22. **Line of sight** is a straight line from the eye (1.5 cells above the feet) to the nearest point of the target cell, sampled 72 times. It is blocked by any cell that is not air, water, or a torch, and where it would slip between two blocks that only touch at an edge. It is close to exact but not exact.
23. **Water can be seen through.** Only water cells that touch air are listed, so a lake shows its surface, not its volume.
24. **To stay under about 600 tokens** the close list shows the 4 nearest cells of each block type plus a count, the far list shows a count and the nearest cell, and at most 8 creatures are listed. The longest observation in five 1500 step sensible bot runs was 1108 characters.
25. **"open air above you"** is printed when nothing is above the head. Otherwise the first block above is named with its position.
26. **The death line and the notice line** come right after the "last action" line.
27. **All sentences live in `tinyworld/sim/text.py`** so the banned word test has one place to look.

## Name modes

28. **Alien words** are 2 or 3 consonant-vowel syllables with an optional last consonant. No alien word contains any familiar word or any banned word. They come from a second generator seeded with the same seed, so terrain does not depend on the name mode. Rule 2 of PLAN.md says one generator. This is the one exception and the names and the recipe shuffle are still fully set by the seed.
29. **"air" keeps its name in alien mode.** It is the name of a vital and appears in "open air above you". Air is never listed as a block. The alien test skips this one word.
30. **In alien mode only alien names are accepted in actions.** Otherwise typing "planks" would work and prior knowledge would leak back in.
31. **Recipe shuffle.** Tiers are: no station, workbench, furnace. Inside a tier the input sets are dealt out again to the outputs. Outputs, amounts, and stations stay. A shuffle is thrown away and redrawn if any recipe would need its own output or could not be reached from bare hands. Because of that only a few shuffles exist for the first tier.

## Runner and logs

32. **Agent steps `i` start at 1.** `i` 0 is the state before the first step. This is now written in docs/INTERFACES.md.
33. **`max_steps` can be overshot by up to 7 world steps** because the last action is not cut short.
34. **Resume replays the logged actions** through a fresh world. No controller decisions are made for those steps. Bots re-run their own `act` in `replay` to bring their private state forward.
35. **Extra keys** added to the formats: `spawn` in the snapshot, `agent.tools` in every world line, `died` in steps.jsonl, `shuffle_recipes` in config.yaml.

## Bots and balance

36. **The random bot picks an action type at random, then an action of that type.** Picking from the flat list would be almost all mining because so many blocks are in reach.
37. **The sensible bot reads the world directly** (block grid, recipe table, creature list). It looks recipes up by output, so it also works with shuffled recipes. At step 165 of each day it stops, walls itself in with whatever blocks it holds (digging a few if it has none), waits for morning, and takes the walls back.
38. **No tuning of the vitals was needed.** With the PLAN.md defaults the random bot died within 600 steps on 9 of 10 seeds (seeds 1 to 10) and the sensible bot lived 1500 steps with no death on 10 of 10. The sensible bot with its shelter turned off died on 5 of 10 seeds (4 of those to zombies), so nights do matter.
39. **"Every recipe is reachable" is tested two ways.** A flood fill from the start checks that enough logs, stone, coal ore, iron ore, bushes, and animals can be walked to on seeds 1 to 20. And the sensible bot, starting with nothing, crafts all 13 outputs on each of those seeds.

## Analysis

Calls made while building M6 (metrics, sweep runner, report). Nobody was around to ask.

40. **Run folders of a sweep are `runs/<sweep>/<model>_m<memory>_k<K>_s<seed>/`** and the `run_id` in config.yaml is that folder name without the sweep part. The server refuses run ids with a slash and lists only the direct children of a runs directory, so a sweep is served with `python -m tinyworld.server --runs runs/<sweep>`. For bot runs the controller name stands in for the model and memory and K are 0, for example `sensible_bot_m0_k0_s1`. Model ids are made safe for folder names by swapping anything that is not a letter, digit, dot or underscore for a dash (`openai/gpt-4o` becomes `openai-gpt-4o`).
41. **The report links each run as `http://localhost:8000/?run=<run_id>`.** That URL shape was not agreed with the viewer. If the viewer reads a different query key, change `runs_table` in `tinyworld/analysis/report.py` or pass `--viewer`.
42. **The sweep config takes `controller`** as one name or a list (default `llm`), and `shuffle_recipes` (default false). A bot controller ignores `models`, `memory_chars` and `history_window` and gives one run per seed. Every run is a child process of `tinyworld.runner.run` started with `--resume`, so a cut-off run continues from its last complete step. A run with a `summary.json` counts as done and is skipped. The llm flags passed to the child are `--model`, `--memory-chars`, `--history-window`, checked against the runner after M4 landed. `configs/sweeps/mock.yaml` runs the M6 acceptance sweep with the mock adapter and no network.
43. **Cost estimate.** Model calls per run are `max_steps / 2` (the sample bot runs used 2.3 and 3.2 world steps per agent step, a model that waits less will be nearer 2). Each call is taken as 900 input tokens plus `memory_chars / 4` for the memory file, and 150 output tokens. Prices come from `configs/models.yaml` when it exists; the loader accepts a mapping of models or a list, and any numeric key with "input" or "output" in its name that is not a cache price. A model with no price counts as $0 and the plan says so. Bots cost $0.
44. **Spend is read from `cost_usd` in every steps.jsonl of the sweep** every quarter second, new bytes only. When it reaches `budget_usd` no new run starts and the running ones get SIGTERM. The runner writes the steps.jsonl line last, so a killed run is at a complete step and resumes cleanly. `budget_usd: 0` means no limit.
45. **Activity share is measured in world steps** (`share_<action>`), because that is time in the world. An `agent_share_<action>` in agent steps is also written. Entropy uses action names over windows of 50 agent steps, mean over all windows, in bits.
46. **A placed block** is a cell that went from air or water to a block during a `place` action aimed at that cell. Berry bushes growing back are not placed blocks. `blocks_placed` counts placements. `largest_placed_group` is the largest group of placed blocks that touch face to face (6 neighbours, the 3D form of 4-connected), tracked over the whole run while blocks are placed and taken back, so the sensible bot's shelter counts even though it removes it each morning. Four wall blocks around the agent do not touch face to face, so `largest_placed_group_26` also counts edge and corner contact. Placed blocks that are mined again leave the group.
47. **Night steps** are world steps with `t mod 300 >= 200`. "Enclosed" means all four horizontal neighbours of the feet cell and of the head cell are solid and the cell above the head is solid. Solid is anything but air, water and torch, so doors count. "Near a torch" means a torch within `torch_light` (6) cells by box distance, checked on the replayed grid, and only counts when not enclosed. Everything else is "open".
48. **Memory line survival** treats a line as born when it first appears in a memory version and dead at the first later version without it, measured in agent steps. `memory_line_survival_mean` averages the lines that died; `memory_line_survival_mean_censored` also counts lines still alive at the end as living until the last step. Characters changed is the difflib edit distance between versions (chars removed plus chars added).
49. **Wall clock.** steps.jsonl has model latency but no timestamps. The sweep runner measures each child's real time and passes it into `summary.json` as `wall_clock_s`. When metrics are computed by hand, `wall_clock_s` falls back to the sum of latencies.
50. **`finished`** is true when the last `t_end` is at or past `max_steps`, or `on_death` is `end_run` and a death was logged.
51. **Report colours** follow the dataviz skill palette: models and actions use the fixed categorical order, memory sizes use the blue ramp because they are ordered. The plotly charts render on a light surface even in dark mode (plotly colours cannot follow CSS variables); the page around them does switch. Every chart has a one or two sentence caption. The report embeds plotly.js so it is one file of about 5 MB.

## Viewer

Calls made while building M3 and M5 (server, viewer, memory visualiser, compare view). Nobody was around to ask.

52. **`websockets` was added to pyproject.toml.** uvicorn needs a websocket library to serve `WS /ws/runs/{run_id}` and the environment had none. One line in the dependency list.
53. **The websocket sends two extra status messages** that are not in docs/INTERFACES.md: `{"file":"status","line":{"history_done":true,"finished":bool}}` after every existing line has been sent, and `{"file":"status","line":{"finished":true}}` when `summary.json` appears while tailing. The viewer uses them to show "live" against "finished". A client that ignores unknown `file` values sees exactly the contract. The history is sent file by file in the order world, steps, memory, events, so the snapshot is always the first message. New lines are polled every quarter second and only complete lines (ending in a newline) are sent. The connection stays open until the client closes it.
54. **A run's id is its folder name**, not the `run_id` in config.yaml, so a copied folder is served under its new name and `/api/runs/{id}/...` always matches `/api/runs`. `--runs` can be repeated; the first directory holding the id wins. The built viewer is served at `/` when `viewer/dist` exists, with `/compare` mapped to the same `index.html`.
55. **Playback speed.** 1x is 2 world steps per second, so 50x is 100 steps per second and a 1500 step run plays in 15 seconds. PLAN.md gives speeds but not what 1x means.
56. **Interpolation is between world steps, not agent steps.** Each world line has all positions, so the agent and the creatures slide from the state at `floor(pt)` to the state at `floor(pt) + 1`. Block changes apply at `floor(pt)`. A creature that is absent from the next step just stops.
57. **The sky follows the step within the day**, computed from `t mod day_length` with `day_length`, `night_start` and `dim_steps` read from config.yaml (defaults 300, 200, 20). The `light` field in world.jsonl is the agent's local light (it drops under a roof and rises near a torch), so it is only used as a nudge: `dark` caps the daylight at 0.15 and `bright` keeps it at 0.6 or more. Dusk colours are blended in around the fade.
58. **Scrubbing backwards rebuilds the block grid from the snapshot** and replays the deltas forward, marking every touched chunk dirty. Block changes are rare (a few hundred cells in 1500 steps) so this is cheap and keeps one code path. Chunks are 16 x 32 x 16, two meshes each (opaque and water), so the terrain is at most 32 draw calls; creatures are one instanced mesh per kind and the agent one mesh. A 64 x 32 x 64 world measured 45 to 55 draw calls and 100 to 170 k triangles.
59. **Torches are small sticks with a bright tip** inside the cell, treated as see-through by the mesher, with an additive glow sprite each and a point light for the first six. Doors are drawn as a slightly inset block with a handle; the sim has no door orientation.
60. **The memory panel shows the version in force after the current agent step** and highlights the most recent edit as a diff against the accepted version before it, even if that edit was several steps ago (the header then says "unchanged since"). A rejected edit shows the unchanged file plus the refused ops in red. The diff is a line LCS with a word LCS inside paired changed lines, computed in the browser. The timeline's x axis is agent steps because that is when edits happen; clicking a mark seeks to the `t_end` of that agent step.
61. **Compare view is two full `RunView`s** (scene plus panels) sharing one `Player`, so the scrubbers cannot drift. The scrubber range is the shorter of the two runs. Event and memory jumps use the left run.
62. **Alien mode.** Panels take names from world.jsonl (always familiar) and, when the toggle is on, append the shown name from the snapshot's `display_names` as "log (bunuv)". The observation, thought, action and events are shown as logged, so in alien mode the observation is in alien words either way. The toggle only affects runs where names differ.
63. **Fixtures.** `viewer/fixtures/make_memdemo.py` wraps the sensible bot with scripted memory ops and writes `memdemo` (familiar) and `aliendemo` (alien, shuffled recipes) through the real `RunLogger`, so the files are in the documented formats. The bot runs in `samples/` have an empty memory file and never place torches, which is why these exist. The folders are committed (about 2 MB).
64. **Screenshots** come from `viewer/scripts/screenshot.mjs` with Playwright's Chromium on SwiftShader. Frame rate was not measured in that setup (software GL); the 60 fps claim rests on draw calls and triangle counts and on the frame loop allocating nothing.

## Agent

65. **The system prompt is PLAN.md section 7 to the letter.** A test reads the block out of PLAN.md and compares it with the rendered prompt, so the two cannot drift. With memory size 0 the memory paragraph and the memory field are left out as PLAN.md says, and the words "your memory file, " are also dropped from the "Each step you are shown" sentence, because the file is not shown then and the sentence would be false.
66. **Action lines are built from the world**, not fixed strings: reach and attack reach come from `world.yaml`, and the item names in the `place`, `eat`, and `craft` examples come from `world.dn`, so alien mode shows alien words. The craft example is `{"dirt": 2, "sand": 1}`, which is not a recipe, so the example gives nothing away. The lines say only the key names and ranges. They do not say what up and down do or when a mine fails.
67. **User message layout.** `memory file (812 of 2000 characters used)`, the file, a blank line, `last 3 actions:` with numbered `action -> result` lines (the action is the exact JSON that went to `world.step`), a blank line, `observation:`, and the observation. With memory size 0 the memory block is left out. The thought is never shown back.
68. **Memory ops.** `append` puts a newline before the text when the file is not empty. `replace` changes the first occurrence. A malformed op (not a dict, unknown op, missing field, empty `old`, `old` not found) is skipped on its own; the other ops of the same edit still apply. Only the character limit rejects a whole edit. With memory size 0, ops are ignored and nothing is written to memory.jsonl.
69. **A wipe on death is recorded in the next step's memory line** as a first op `{"op": "wipe", "reason": "death"}` in front of whatever the agent sent that step. The wipe itself happens in `on_result`, after the step's line is already decided, and the loop writes one memory line per step. `text` is always the file after the step, so a reader that follows `text` needs no special case.
70. **Parse failure** means no JSON object with an `action` dict that has a string `name`. Everything else is tolerated: code fences, text before or after, an object before the real one. Unknown action names reach the simulation and come back as the one step "Unknown action." error, which is an invalid action, not a parse failure.
71. **Token and cost accounting.** `input_tokens` in steps.jsonl is every billed input token, cache reads and writes included. Cache reads and writes are priced with `cache_read_per_m` and `cache_write_per_m` from models.yaml when set, else at the input price. Thinking tokens are output tokens. The SDKs' own retries are turned off so the backoff in `tinyworld/llm/base.py` is the only one: up to 6 tries, 1 s doubling to 60 s, with jitter, on 429, 5xx, timeouts and connection errors.
72. **`model` in config.yaml is the models.yaml entry name**, which is what `--model` and sweep configs take. The provider id is next to it as `model_id`, with `provider`, `max_tokens`, `llm_settings` (thinking, reasoning, sampling, base_url) and `prices_per_m`. Sampling is left at provider defaults unless the entry sets `sampling`.
73. **The mock that plays.** `SensibleMockClient` wraps the sensible bot in the reply format, appends a memory line every 5 steps, sends an over limit edit every 29 steps and an unreadable reply every 37 steps, so a mock run goes through the memory, rejection and parse failure code for real. It needs the world, which no LLM gets: the controller hands it over only to a client that sets `needs_world = True`, and calls `client.replay` on resume so the bot's private state comes forward.
74. **Prices in models.yaml are not verified against the official pages.** The docs pages of Anthropic and OpenAI could not be fetched from the build sandbox. The model ids match the literal lists shipped in the installed SDKs and the prices come from third party pages dated May and August 2026. Every entry carries a `note` saying so. Check them before a paid sweep.

## Review

Independent review on 2026-10-07. Every acceptance check in PLAN.md section 12 was run by hand from a clean install (`rm -rf .venv viewer/node_modules viewer/dist`). What was found and changed:

75. **`--resume` on the command line now keeps the stored `max_steps`.** `run.py` took the CLI default of 1500 over the run's own config, so resuming a 200 step run carried on to 1500. The stored value wins unless `--max-steps` is given. Resuming a truncated mock run now gives files identical to the uninterrupted run. The sweep runner always passes `--max-steps`, so sweeps were not affected.
76. **`--step-delay SECONDS`** was added to `tinyworld.runner.run` so a bot run can be watched live; without it a 1500 step bot run is over in a few seconds. Live mode was checked with it: the viewer followed the run from step 279 to 376 while it was written.
77. **Stars were not visible at night.** The star dome ended a little above the horizon and the camera looks down from above the world, so the sky it sees is the band near the horizon. The dome now reaches slightly under the horizon with 1800 stars instead of 500, and the point size is 3.
78. **Report over-time charts use adaptive bins.** 100 step bins over 200 step runs gave two or three points, and the planned length was taken from `world_steps`, so the overshoot of the last action made a nearly empty last bin that dropped the activity share to zero and faked a flat tail in the memory chart. Bins are now `time_bin(max_t)`, about 15 per sweep (100 for 1500 step runs, 10 for 200 step runs), and the length comes from `max_steps` in summary.json. The activity legend moved under the panels (it sat on a subplot title), rows got more space, and the entropy chart title no longer collides with its legend.
79. **Samples and fixtures carry a `summary.json`.** They are complete runs, and the server reports them as finished. The server test was asserting the opposite from before `write_summary` landed in the runner.
80. **`help` in the text CLI** prints the short forms. Before, a human typing `help` got "Unknown action." and a wasted step.
81. **`configs/models.yaml` was verified** against platform.claude.com (models overview, pricing, deprecations) and developers.openai.com (models, pricing) on 2026-10-07. The current Anthropic ids are `claude-haiku-5-5`, `claude-sonnet-5-5`, `claude-opus-5-5`; the older `claude-haiku-4-5-20251001`, `claude-sonnet-4-6`, `claude-opus-4-7` are still active and kept as `haiku45`, `sonnet46`, `opus47` for "only the model changes" runs. The entry names `haiku`, `sonnet`, `opus` now point at the 5.5 models. OpenAI's pages list `gpt-6-luna`, `gpt-6.1-sol`, `gpt-6-astra`; `gpt-5.4` and `gpt-5-mini` are no longer on them, so `gpt54` and `gpt5_mini` were dropped and `gpt54_mini` stays marked unverified. `haiku` ($0.10 / $0.50 per million) is the cheap default used in the README and `configs/sweeps/first_real.yaml`. Haiku 5.5 has a higher price tier for prompts over 100k tokens, which this project never reaches.
82. **`configs/sweeps/memory_sweep.yaml`** had the placeholder model names from PLAN.md (`model_a`, `model_b`). It now names `haiku` and `sonnet`. Its estimate ($89) is over its $25 budget on purpose: the cost guard stops it. `first_real.yaml` is the small real sweep to run first (about $0.11 estimated).
83. **Not measured: 60 fps.** Headless Chromium here runs on SwiftShader (software GL), so the frame time it reports (40 to 100 ms per frame) says nothing about a laptop GPU. The claim still rests on draw calls (40 to 52) and triangle counts (120 to 160 k), which is well within what a laptop draws at 60 fps. The owner should check once on real hardware with `?debug=1`.
84. **Not run: a 200 step run with a real model.** No API key in the review sandbox. The exact command is in `docs/STATUS.md`. The network error path was checked: a missing key fails at once with "ANTHROPIC_API_KEY is not set. Put it in .env (see .env.example)."

## Memory coercion (after the first real Haiku run)

85. The first real run (Haiku, 200 steps) wrote its memory as `"memory": ["line", "line"]`,
    a list of plain strings, every step. The documented schema is a list of op dicts
    ({"op":"append"...}), so the old code silently dropped every edit: the memory file stayed
    empty for the whole run and the model never saw its own notes. That defeats the point of the
    experiment, so `parser.normalize_memory` now coerces the common real-model shapes into
    documented ops. Judgment call: a list where every item is a string is read as a single
    `rewrite` to those lines joined by newlines, because the model emits its full intended notes
    each step (a snapshot), not deltas. A mixed list keeps op dicts and treats bare strings as
    appends. A bare string is a rewrite. This keeps logs conformant to INTERFACES.md and never
    silently loses an edit. Revisit if a model turns out to emit append-deltas as bare strings;
    for that model a rewrite would wrongly discard its history. The system prompt was left exactly
    as PLAN.md section 7 (a test pins it), so the fix lives entirely in the parser.
86. metrics.memory_metrics now ignores non-dict ops defensively, so a stray op shape can never
    crash summary.json again.

## Hard mode (fog, lethal nights, scarcity)

A second world preset, `configs/world_hard.yaml`, turns on three pressures so an LLM agent has
to keep a real plan in its memory file instead of re-deriving everything from each observation.
Every knob is a config field with a default that reproduces the old world, so the default
`configs/world.yaml`, all prior tests, and the samples are unchanged. Three existing fields were
renamed to the names the pressures use; the renames keep their old default values, and
`configs/world.yaml` was updated in the same commit (`food_drop_every` -> `food_drain_every`,
`zombie_move_every` -> `zombie_step_every`, `torch_no_spawn` -> `torch_radius`). The committed
sample/fixture `config.yaml` snapshots still carry the old field names; they are frozen run
records, read by the server and viewer as loose yaml and never re-validated, so they are left
as-is.

87. **FOG is just `view_radius`** (already a field, default 12). Hard mode sets it to 4: the "in
    view" block only reaches 4 cells, so the agent learns the wider map only from its own memory.
    The "close within 3 cells" block and line of sight are unchanged (no x-ray). The viewer renders
    the god-view from world.jsonl and never reads `view_radius`, so fog lives only in the text
    observation.
88. **Zombie block breaking.** New knobs `zombie_breaks` (list of block names, default `[]` = off)
    and `zombie_break_steps` (default 4). A chasing zombie that is blocked by a breakable block in
    its path toward the agent grinds that one feet-level block; after `zombie_break_steps` adjacent
    steps the block becomes air. Progress is per zombie and resets if it turns to a different cell.
    Blocks not in the list stop it, so stone, workbench, furnace and door are safe and zombies
    still cannot open doors. Net effect in hard mode (`[dirt, sand, grass, leaves, planks]`): a
    dirt hut fails, a stone box with a door is safe. With the default empty list the whole branch
    is skipped and the state hash is identical to before, so determinism and the old world hold.
89. **Other zombie knobs:** `zombie_max` 6->10, `zombie_step_every` 2->1 (zombies move at the
    agent's speed, so they cannot be outrun), `zombie_damage` 3->4. `torch_radius` (the spawn-
    suppression distance, formerly `torch_no_spawn`) 6->3, so torches protect a smaller area;
    `torch_light` (the dark->dim light lift, used by the viewer and metrics) is left at 6.
90. **Scarcity.** `vitals.food_drain_every` (hunger interval), `terrain.berry_density_mult` and
    `creatures.animal_count_mult` (both 1.0 by default). The multipliers scale berry-bush spawn
    rate and minimum count, and sheep+chicken start counts, max, and morning respawn. They are
    applied so that a value of 1.0 draws from the seeded generator exactly as before (no rng
    consumed differently), so the default world is byte-identical.
91. **Final hard-mode values and tuning.** view_radius 4; zombies max 10, step_every 1, damage 4,
    breaks `[dirt, sand, grass, leaves, planks]`, break_steps 4, torch_radius 3; food_drain_every
    6; berry_density_mult 0.5; animal_count_mult 0.5. Only `food_drain_every` was tuned away from
    the first guess: at 9 (with everything else as above) the upgraded sensible bot survived 10/10
    seeds at 600 steps (too easy). Lowering it stepwise gave 9/10 at 7 and 6/10 at 6, so 6 is the
    final value. The deaths it produces are mostly "caught at night with a half-built shelter"
    (food is scarce enough that balancing foraging against gathering a night's worth of stone
    sometimes runs the agent out of daylight) plus some starvation, which is the middle ground the
    experiment wants: planning required, but clearly possible.
92. **Measured survival, seeds 1-10 at 600 steps, hard mode.** random_bot: 0/10 survive, all 10
    die in the first night (first death t 124-237); it never shelters. sensible_bot (upgraded):
    6/10 survive the full 600 steps; the four deaths are 5 zombie + 1 hunger across the losing
    seeds. So random dies early and often, sensible survives on roughly half.
93. **Every recipe is reachable in hard mode.** Checked two ways, both on seeds 1-10 with the
    hard world: `recipes.all_reachable(BASE)` (the recipe graph, world-independent) holds, and a
    flood fill of walkable cells from spawn reaches at least one cell of log, stone, coal ore,
    iron ore, berry bush and water within reach, with animals present, on every seed. So every
    recipe's raw inputs are obtainable. The hard world only changes vitals, zombie behaviour, the
    view radius, and halves berry/animal density; it removes no resource type. (The survival-first
    sensible bot does not speed-run all 13 crafts within 600 steps because it spends its time
    sheltering and eating under the pressures; that is expected and is not what "reachable" means
    here.)
94. **Upgraded sensible bot.** All new behaviour is gated behind a non-empty `zombie_breaks`, so
    easy mode is untouched (the easy balance tests still pass and it still crafts all 13 on seeds
    1-20). In hard mode it (a) keeps a reserve of stone on hand for the night and crafts one door
    during the day (`_hard_prep`), (b) builds its night shelter out of blocks a zombie cannot
    break (stone), with one door for the entrance (`_wall_choice`), falling back to cutting fresh
    stone if it runs short, and (c) reclaims the stone walls and the door each morning
    (`_leave`). It reads the world directly, so fog does not affect it.
95. **Runner `world:` key.** A run config (`configs/run_hard.yaml`) and a sweep config
    (`configs/sweeps/hard_mem.yaml`) can now name a world yaml with a `world:` key
    (`world_hard`, `world_hard.yaml`, or a path; resolved against `configs/`). `run.py` reads it
    when `--config` is not given on the command line; the sweep passes it to each child as
    `--config`. The resolved world is stored in `config.yaml` as before, so resume and the viewer
    are unaffected. Determinism in hard mode was confirmed identical across two fresh processes;
    alien mode and the banned-words check both still pass in hard mode.
96. **Respawn never drops into a dug-out start.** The haiku_night sample dug a one-wide shaft
    straight down from the start point, starved at the bottom, and respawned at the start, which
    put it back at the bottom with empty hands in stone, unable to leave for its last 200 steps.
    Respawn still climbs on top of anything built over the start. If that cell would be more than
    one below the start height, the agent instead goes to the nearest column (rings outward)
    with a dry cell it can stand in at or above start height minus one, taking the lowest such
    cell so it lands under a tree canopy rather than on it.
97. **"Up and down only work in water."** A failed `move up` or `move down` out of water now
    returns "You did not move. Up and down only work in water." The same sample tried `move up`
    about 200 times against a bare "You did not move." This is the one template that states a
    rule rather than only what happened; it describes the mechanic, not what to do about it. A
    blocked move in water still gets the plain text.
98. **Stuck runs end.** After each action the world checks `trapped()`: the agent holds nothing
    it could place or that any recipe uses, and from every cell it can walk or swim to (up to
    256), no block within reach breaks with its tools. Creatures are ignored. When this first
    becomes true a `stuck` event is logged and, with `on_stuck: end_run` (the default), the run
    ends. `on_stuck: continue` only logs the event. A digging escape needs a pickaxe in stone,
    and placing a block in one's own cell is not allowed, so with empty hands in stone nothing can
    ever change.
99. **Livelier nights, more ore, armor.** The haiku_live_night run showed six zombies that never
    came near the agent: they spawned 12-24 cells away but only chased within 10, so they
    wandered. Normal mode now: `zombie_chase_dist` 10->20 (covers most of the spawn ring),
    `zombie_step_every` 2->1.5 (a zombie moves on 2 of every 3 steps; the field is now a float
    and 2 still means every other step), `zombie_max` 6->9, `zombie_spawn_prob` 0.08->0.12. Ore:
    `coal_rate` 0.03->0.05, `iron_rate` 0.02->0.035, `surface_coal`/`surface_iron` 8->14. Hard
    mode takes the same chase range, spawn chance and ore numbers and keeps its own faster,
    larger zombie pack. New items: wood sword (2 planks + 1 stick, damage 3, 20 uses), iron
    helmet (3 iron ingot) and iron chestplate (5 iron ingot), all at a workbench. Armor works
    from the inventory like swords: each piece held takes its points (helmet 1, chestplate 2)
    off a zombie hit, at least 1 always gets through, and every piece held wears once per hit
    (30 and 40 uses). Armor only stops zombie damage. The sensible bot's goals include the new
    items, armor last, so it still makes all 16 things on seeds 1-20. Death notices now show the
    cause through the display names, which closed a leak of "zombie" in alien mode that only
    appeared once zombies reached the agent. Earlier samples keep their stored world config.
100. **Long-term file and lineages.** A second memory file for what carries over between runs
    (lessons about the game), next to the memory file for this world. Each run in a lineage
    starts from the long-term file the previous one left. Choices: (a) off unless
    `longterm_chars` > 0, and then the prompt only gains a paragraph that states the mechanics
    ("carries over to your later runs, which may take place in a different world") with no
    advice on what to keep; (b) the agent may edit it every step with a `"longterm"` field, plus
    one reflection call when the run ends, because most runs end on max_steps with no chance to
    sum up; (c) reproducibility: the run folder stores the starting text (config.yaml and
    longterm.jsonl line 0), so a lineage run replays from its folder alone; (d) generations are
    sequential, an unfinished run holds the lineage; (e) a stored text longer than the limit is
    refused rather than truncated, since every edit to it would be rejected; (f) on a death in
    `respawn_wipe_memory` mode only the memory file is wiped. The lineage `haiku_4nights` was
    seeded by hand from runs/haiku_4nights (no long-term file in that run): its game rules,
    recipes and lessons, including ones from earlier memory versions that the agent later
    overwrote, every one checked against the game, without coordinates or plans.
100. **Blocked moves name the blocker; "above" means above the head.** In the two Haiku runs, 47
    of 54 failed sideways moves were stopped by the head cell alone: the model dug out the cell
    at its feet, saw it empty, and could not tell why it still could not walk in. It also tried
    to roof its shelter inside its own head because "open air above you" was checked from the
    cell above the head. A blocked sideways move now ends with " Blocked by stone at (x,y,z)."
    (the head cell for a level step; the feet cell plus whatever stops a step up; or "sheep #3"
    when a creature stands there), also after a walk that stopped part way. The above line now
    reads "open air above your head, from (x,y+2,z) up" or "stone above your head at (...)".
    Both only report what is there, so the wording rule holds. The prompt is unchanged: the
    agent still has to work out that it is two cells tall.
101. **Inventory limit and chests.** The inventory has 10 slots (`inventory_slots`; 0 turns the
    limit off). A slot holds one tool or armor piece, or up to 32 (`stack_size`) of anything
    else. A pickup that does not fit fails whole and costs a step: mining leaves the block
    standing, crafting uses nothing up ("No room in inventory."). Meat from a kill fills what
    room there is and the rest is lost ("No room for 1 raw meat."). The observation shows
    "inventory (7 of 10 slots): ...". A chest (8 planks at a workbench, hardness 4, no
    pickaxe needed) holds 20 slots (`chest_slots`). Three actions were added: `store` and
    `take` (a chest within reach, items with counts, all or nothing) and `drop` (items gone for
    good). `drop` exists so a full inventory can never lock the agent out of food: placing
    only empties placeable blocks, and sticks, coal or spare tools could otherwise pile up
    with no way out. Tools and armor cannot be stored, because wear is tracked per held tool
    and storing would let a worn one come back fresh. A chest that holds anything does not
    break ("The chest is not empty."). Chests keep their contents through death, which is the
    reason to build one near the start. Chests within reach list their contents in the
    observation. world.jsonl carries a `chests` list in the snapshot and every step line.
    The sensible bot now drops spare or outdone tools and junk past fixed keep amounts when
    under two slots are free, drops a whole junk stack (never what the failed action used)
    after a "No room", skips a goal it cannot reach instead of waiting on it, and cuts a
    staircase out when it is stuck deep or hungry with no food in reach. It still makes all 17
    things on seeds 1-20. It does not use chests.
101. **Long-term plain text appends; edit ops spelled out.** In runs/haiku_4nights_g2 the agent
    wiped its long-term file at agent step 241: it sent only the line it wanted to add, as a list
    of strings, and the memory coercion (a list of strings is the whole file, right for the
    memory file because Haiku resends it every step) turned that into a rewrite. Every recipe and
    lesson the lineage had was gone, and the run starved soon after. Now "longterm" plain text
    (a string or strings in the list) is always appended; replacing the whole file needs an
    explicit rewrite op, and a model that resends the whole file as lines gets an over-limit
    rejection rather than duplicates. With the long-term file on, the prompt now spells out the
    three ops and says a death does not end a run (the agent had called each respawn a new run).
    Runs without a long-term file keep the PLAN.md prompt word for word. Haiku's max_tokens went
    from 2048 to 4096: 7% of that run's replies were cut off while rewriting both files. The run
    was resumed from world step 808 with its long-term file restored to the version after agent
    step 240; the restore is a line marked "manual" in its longterm.jsonl and its config.yaml has
    a note, so the change mid-run is on record.
102. **Chase range 20 -> 15.** With zombies spawning 12-24 cells away, a range of 20 put about
    60% of them on the agent the moment they appeared, so a night felt like one wave. At 15
    about 20% chase from the start and the rest wander until they come close. Hard mode
    follows. Still well above the original 10, where none ever arrived.
103. **Long-term rejections say how to make room; the reflection gets a second try.** In
    runs/haiku_4nights_g2, after the fix in 101, the agent only ever added lines: its long-term
    file sat at the 1200 limit and 182 edits were rejected. Its end-of-run reflection resent
    the whole file plus a lesson, was rejected, and left nothing new. A long-term rejection now
    adds, when under a quarter of the file is free, how many characters are free and that
    append makes the file longer while replace with shorter text or rewrite can make it
    shorter (mechanical wording only). A rejected reflection gets one more call with that
    notice; its longterm.jsonl line keeps both replies (`attempts`, `first_raw_reply`). The
    lineage haiku_4nights was also edited by hand before generation 3: the line "FOOD IS THE
    KILLER (runs 1-12 starved)" was wrong (7 of 8 deaths were zombies at night), and
    per-life notes were folded in, 1200 -> 947 characters. The edit is recorded in
    lineages/haiku_4nights/manual_edits.jsonl.
104. **The agent's head is shown; placing into itself and being hit say so.** In
    runs/haiku_4nights_g2 the agent sealed the four cells beside its feet, tried to place a
    block in its own head cell, got "The cell is not empty.", took that as a solid roof, and
    was killed by a zombie standing beside its head (agent steps 398 and 543). 19 of its 26
    "not empty" placements were into its own body. Nothing it saw said it is two cells tall.
    Three changes, all facts about what happened, no advice: the position line now reads
    "position (x, y, z), head at (x, y+1, z)" (PLAN.md section 6 showed the position alone);
    placing into the agent's own cells answers "You are in that cell."; and every zombie hit
    adds " Zombie #N at (x, y, z) hit you." to that step's result, so a wait cut short or a
    death says what did it and from where.
105. **Memory lines accumulate with step stamps; the observation shows health and food
    earlier.** In runs/haiku_4nights_g2, 846 of 866 memory edits were whole-file rewrites (the
    snapshot coercion of 85) and a memory line lived 1.6 steps on average, while the file used
    377 of 2000 characters. Each step the agent re-summarised the screen, so nothing built up
    and it never saw food fall (1 per 15 steps) in time to act on it. Three changes:
    `memory_plain: append` (the new default; `rewrite` keeps 85) reads plain "memory" text as
    added lines, like "longterm"; a line that is already in the file is skipped, so a model that
    resends its notes does not double them; and each added line starts with "[step t] ", the
    world step it was written at. The prompt in append mode spells out the three ops and the
    stamp (rewrite mode with no long-term file is still PLAN.md section 7 word for word). A
    memory rejection with under a quarter free also says how much is free and what shortens the
    file, as for the long-term file (103). The observation's vitals line now reads "health
    20/20 (20 at step 820) | food 12/20 (16 at step 820) | air 10/10": the values
    `vitals_lookback` (60) world steps ago, or at the last respawn if that is later. Configs
    without `memory_plain` (runs started before this) resume in append mode.
106. **Jump action.** `{"name": "jump", "item": "dirt"}` moves the agent up one cell and puts
    the item in the cell its feet left, so it stands on it: repeated, it builds a pillar to
    climb. Before this, going up on land meant cutting stairs; "move up" only works in water.
    It takes one world step like place. It needs the item in the inventory, an item that can
    be stood on (not a torch: "The torch was not placed."), and the cell above the head free
    of blocks and creatures ("You did not move. Blocked by stone at (x,y,z)."). The result is
    "Moved up 1 cell. Placed dirt at (x, y, z)." A chest placed this way is a chest. It counts
    as a placement in metrics (blocks_placed, first_place) and has its own share_jump.
    valid_actions offers it, so the random bot uses it; the sensible bot does not.
107. **Under a roof it is dark at any hour; zombies spawn in the dark.** Before this, zombies
    came only at night, only on the surface and 12-24 cells away, while a torch only stopped
    spawns within 6 cells of itself, so a torch could never matter and no Haiku run ever tried
    coal + sticks. Now a cell with a block above the head (solid, not leaves) is dark day and
    night unless a torch is within torch_light, and the agent's light line says so. Each step,
    with zombie_dark_spawn_prob (0.05), a zombie can appear in a covered, unlit open cell (two
    free cells over a floor) 5 to 24 cells away sideways (zombie_dark_min_dist), at any hour;
    in practice those are the agent's own tunnels and shafts, since the terrain has no caves.
    A torch within max(torch_radius, torch_light) of the cell stops it. By day, zombies out
    under the open sky are removed every step (before, all zombies went at dawn); covered ones
    stay. The night surface spawns are unchanged. Sensible bot, seeds 1-6, 1200 steps: zombie
    hits 1 -> 4, no deaths either way.
108. **Sky reading, open cells touching the body, fewer dark spawns.** From
    runs/haiku_fresh_s2_v2 (the first run under 107): (a) inside a roofed shelter the light
    read "dark" all day and the agent, using light as its clock, waited about 550 daytime world
    steps for a daylight that never came. The header now also gives the sky by time of day:
    "step 1641 | day 6 | light dark | sky bright". (b) Three of its five deaths were zombies
    beside its head while it believed it was sealed in, even with "head at" and "hit you"
    lines. A new line names every non-solid cell a zombie could hit it from (four sides at feet
    level and at head level, and above the head): "open cells touching you: head north
    (19,15,46)", or "all 9 (...)" in the open, or "none" when sealed. (c) 99 of its 159
    zombies came from covered cells, 71 by day: zombie_dark_spawn_prob 0.05 -> 0.015. The
    alien-shuffle bot test on seed 4 now needs 2100 steps instead of 1500 to make all 17
    things (no deaths; the changed spawn draws shift its world).
109. **rule_notes: why a craft failed, why health is flat, and what was made.** From
    runs/haiku_fresh_s2_v3 (seed 2, about 1000 steps in): (a) health sat at exactly 10 for about
    450 steps while food stayed 5 to 14, under heal_food_min 15; the agent kept "resting to
    regenerate" and noted the flat health without ever linking it to food. (b) Every failed craft
    read "Nothing was made.", so it concluded "crafts need a workbench nearby" when the real cause
    was the amounts (log x2 instead of log x1), and it guessed distance only by luck. (c) It found
    the wood and stone pickaxe items once each, never wrote them down, lost the iron smelting line
    to its own memory rewrites, and after dying redid every trial. `rule_notes` (on by default,
    one flag in world.yaml) breaks the wording rule in three places, as NOT_MOVED_DRY does:
    a craft that matches nothing reads "Nothing was made. Nothing is made from exactly these items
    and amounts."; one that matches but lacks its station reads "Nothing was made. No workbench
    within 2 cells." (this does tell the agent the set was right); and while health is under max
    and food under heal_food_min the observation adds "health does not rise while food is under
    15". The observation also lists, after the inventory, each thing made so far with the items
    it was first made from: "things you have made: log -> 4 planks; 3 planks + 2 sticks -> wood
    pickaxe". This is a record of what happened, not of anything unseen, and it survives death
    like the memory file (it is cleared with respawn_wipe_memory). With all 17 things made the
    line is about 500 characters, so the observation size test measures it on its own. Set
    `rule_notes: false` to compare with runs before this.
110. **recipe_book: the whole craft table in the system prompt (off by default).** In
    runs/haiku_4nights the agent tried to craft only 34 times in 1200 steps, every attempt a
    Minecraft recipe, and never made an ingot, a sword or armor. `recipe_book: true` adds one
    line per craft after the action lines: "3 iron ingot -> 1 iron helmet (with a workbench
    within 2 cells)", with "1 coal or planks" for fuel. It is built from world.recipes and the
    display names, so it is correct with alien names and shuffled recipes. It says how each
    thing is made, never what it does (sword damage, armor, food values stay unlisted), so in
    alien mode the agent still has to find out which word is armor. It sits in the system
    prompt, not the observation, because it never changes within a run and stays cached.
    Off, the prompt is the PLAN.md text word for word. The header avoids the word "recipe".
111. **Farming, a bed, and weather: reasons to stay in one place and build.** In
    runs/haiku_book_s3 the agent had full iron gear by world step 485 and spent most of the rest
    waiting. Three additions give a base a purpose. All numbers are in world.yaml; each has its
    own seeded random stream, so terrain and creature draws are unchanged.
    (a) Farming. Mining grass gives 1 seeds a quarter of the time. Seeds are planted with
    `place` into an empty cell with dirt or grass under it and water within 4 cells sideways,
    level with the soil or up to 2 below (lake water sits about 2 below the shore; with 1 below
    there were almost no plots). The block is a `sprout`; after 300 steps (rain on it counts
    double) it becomes `wheat`. Mining wheat gives 2 wheat and 1-2 seeds; a sprout gives its
    seeds back. 3 wheat make bread (food 6, no station). A plot of about six crops feeds one
    agent, so food stops depending on roaming for bushes and animals.
    (b) Bed. Sheep also drop 1 wool. 3 wool + 3 planks at a workbench make a bed. New action
    `sleep`: with a bed within reach, from dusk to dawn by the clock (not a storm's darkness),
    and no zombie within 8 cells, the world runs on until dawn or until the agent is hurt (so
    an open bed is a risk), healing 1 health per 5 steps while food is above 0. The bed becomes
    the respawn point, shown as "respawn point: bed at (x,y,z)", until it is broken.
    (c) Weather. Every 100 steps a new weather is drawn: clear, rain (25%) or storm (10%); the
    first 100 steps are clear. Rain or a storm with no solid block anywhere above the head
    (leaves do not count) drains food twice as fast and stops healing; a storm also hails
    1 damage every 6 steps, is dark (zombies spawn and do not burn by day), and sky reads
    "dark". The header gains "| weather rain", and the observation says "rain is falling on
    you" (or "rain and hail"). With rule_notes on it adds the rule, another break of the
    wording rule like OBS_NO_HEAL: "while rain falls on you, food drops 2 times as fast and
    health does not rise". A roof is the whole fix, so a shelter is worth building by day too.
    Bread and bed stay out of the recipe shuffle (UNSHUFFLED): wheat or wool swapped onto
    planks or a pickaxe held up everything after it. The sensible bot plants when it holds
    seeds, harvests ripe wheat, bakes bread, makes a bed (it never sleeps), shelters in storms,
    roofs with anything but leaves, digs toward buried ore when none is in the open, and jumps
    up on a held block when it cannot break out of a pit. Its tests now run 2100 steps (2400
    for alien and shuffled): a crop needs time to ripen.
112. **Several agents in one world, on a shared clock.** Design in docs/MULTIAGENT.md. Agent
    state moved from World into Body objects (`world.bodies`, `world.me`); World forwards the
    old attribute names to `world.me`, so the action code is unchanged. Every action handler is
    now a generator that yields where it used to tick the world, and World.step() drives it with
    a tick per yield, so a single agent behaves exactly as before (all tests unchanged, plus a
    test that one agent through the Engine matches World.step() step for step). The Engine
    steps every agent's action once per shared world step in a seeded random order; only the
    world thread changes state, so there are no locks in the simulation and no deadlocks.
    Rules between agents: bodies block each other and swap when walking into each other;
    attacks on agents land at the end of the step (mutual kills possible; armor counts);
    zombies chase the nearest agent; zombie spawns are placed around a random agent; "say"
    reaches agents within hear_radius (16) once; "give" moves items (tools keep their wear)
    only if the receiver is within reach and they fit; end_run takes one agent out and the run
    ends when all are out. Weather and seed drops keep their own streams; one agent alone
    draws no extra random numbers. The runner gives each LLM agent a thread; its controller
    reads the world through a WorldView that holds a re-entrant world lock and points
    world.me at its body. Real time (1 s per step by default) lets a slow model lose time; lockstep
    waits for every thinker before each step and is reproducible with bots. Multi-agent prompts
    replace the first line with a fact about time and other agents and add say/give lines.
113. **Multi-agent: a zombie hit per agent decision, not per cooldown.** In runs/haiku_trio_s5
    (3 Haiku agents, real time, 1 s per step) each decision took about 3 s, so an agent stood
    still for 2 to 5 world steps between actions, and a zombie beside it hit every 2 steps: 293
    hits, 34 deaths (32 at night), result lines like "Got 1 dirt. Zombie #43 hit you." four times
    over. Solo runs never had this, because the world waits for the agent. Now, with
    `zombie_hits_per_decision` (on), zombies can hit an agent at most once per action it starts
    (Body.decisions, counted by the engine), on top of the step cooldown. A hit already cuts a
    running action short, so this only bites while the agent is thinking. It applies only in a
    multi-agent world, so single-agent runs are unchanged.
114. **Run anything from the viewer.** The new-run form on the run picker now takes a list of
    agents (name; model agent, sensible bot or random bot; model; memory size; an optional
    persona paragraph), world steps, seed (with a dice button), base world, run id, the clock
    and seconds per step when there are several agents, and 32 world settings in groups
    (rules, weather, zombies, food and survival, resources, multi-agent) filled with the base
    world's values. Only changed settings are sent; the server (tinyworld/server/settings.py)
    writes them into a copy of the base world, checks it against WorldConfig before anything
    starts, and the run gets it as world.custom.yaml, so its config.yaml records every value.
    One agent goes to the single-agent runner (lineages and bot step delay still work, and
    --persona is new there), more to the multi-agent runner (spec.yaml in the run folder).
    The form shows a rough time and cost (from past Haiku runs: about $0.00043 and 3 s per
    decision, about 2 world steps per action). Stopped multi-agent runs cannot be resumed yet;
    the server says so.
115. **Farming made findable: wild wheat, a growing line in the book, more seeds.** In
    runs/3agents_20261008_213436 (3 Haiku agents, recipe book on) only one agent ever got seeds
    (2, from 10 grass blocks), it tried to eat them while starving, and nobody planted: the book
    listed "3 wheat -> 1 bread" but nothing said where wheat comes from, and grass is worth
    mining for nothing else. Now (a) every new map gets `farming.wild_patches` (3) patches of up
    to `wild_per_patch` (4) ripe wheat on open soil by water, from their own random stream, so
    terrain, creatures and every later draw are unchanged (tested: the wheat cells are the only
    difference); (b) the recipe book gains a "What grows:" line: seeds placed on dirt or grass
    with water near become wheat after grow_steps, mining wheat gives wheat and seeds, mining
    grass sometimes gives seeds; (c) `seed_chance` 0.25 -> 0.5. The flat test arena turns seed
    drops off. The bot finds wild wheat and bakes bread much earlier, but the extra detours put
    some seeds past 2100 steps, so its tests now run 2400.
116. **The growing line names the sprout.** In runs/3agents_farm_s153 all three planted crops
    ripened (steps 639, 663, 855) and nobody harvested: the book said seeds become "wheat"
    after 300 steps, but the world shows a "sprout" first, so Ada took "wheat" for the young
    plant and kept noting "avoid the unripe wheat" while starving beside ripe wild wheat for
    about 200 steps. The line now reads: seeds placed in an empty cell on dirt or grass with
    water near become a sprout; a sprout turns into wheat after grow_steps; a wheat block is
    ripe and mining it gives wheat and seeds; mining a sprout gives its seeds back.
117. **Multi-agent runs can be resumed and extended.** `python -m tinyworld.runner.multi
    --run-id NAME --resume --max-steps N` continues a stopped run or extends a finished one to N
    world steps, appending to its files and recording the extension under `extended` in its
    config. The world is rebuilt by applying every logged action at the world step it started on;
    with the engine's seeded order and separate random streams that reproduces the run exactly
    (tested against the logged results and world lines). Actions still under way when a run ends
    are now saved to inflight.json and put back on resume; runs from before that lose those last
    few actions. Each agent's memory file, last K action/results, step count and costs are
    restored; death notices and heard lines piled up by the replay are dropped (the agents saw
    them at the time). First used to extend runs/3agents_scarce_s153 from 2400 to 4800.
118. **Ore in one corner, a starting kit, bigger memory.** To give exploring and farming a reason:
    `terrain.hill_place: corner` puts the stone hill (and with it the ore seen on bare stone) in
    the corner of the land on the side the seeded draw fell, and `terrain.ore_radius` (> 0) keeps
    all coal and iron ore within that many cells of the hill, at `ore_boost` (2x) the usual rate.
    With corner + 14 on seed 153 the ore sits around (47,47), about 22 cells from the start, out
    of sight. `start_items` gives every new agent items (e.g. seeds and bread), not again on
    respawn. The form gains these plus animal respawn, berry regrowth, wheat per crop and bread
    value, and its default memory file is 4000 characters (agents in runs/3agents_scarce_s153
    hit the 2000 limit often: Ada had 18 rejected edits).
119. **Reasons for a base, without saying "build a base".** In runs/3agents_economy_s153 the
    agents farmed but never built around their fields, used a chest, or slept in a bed, and
    every zombie death threw their seeds, wheat and bread away; after respawning they went for
    remembered berry bushes rather than their own crops. Three changes, none an instruction:
    (a) the recipe book gains "What some things do:" with facts the book had left out: a bed
    sets where you come back after a death, a chest's contents stay when you die and a chest
    with items will not break, creatures cannot pass a door, no zombies appear near a torch,
    and (with weather) rain falls where nothing shuts out the sky; (b) with rule_notes, the
    observation lists "things you have placed": the agent's standing workbenches, furnaces,
    chests (with contents), beds, doors, torches and crops (shown as sprout or, once ripe,
    wheat), so a death no longer erases where home is; (c) two crop threats a wall answers,
    both off by default and in the form: `farming.zombies_trample` (a chasing zombie that
    steps onto a crop crushes it) and `farming.animal_eat_prob` (a sheep or chicken beside a
    crop may eat it). New events crop_trampled and crop_eaten.
120. **The death notice says what a death does not take.** Through day 8 of
    runs/3agents_base_s153 no agent used, built or even mentioned a chest, while deaths took
    an iron pickaxe, bread and seeds; the chest line in the recipe book was one of about thirty.
    With rule_notes on, the respawn notice now ends "Your items are gone. What is in a chest is
    not lost." (DIED_CHEST_NOTE), the fact placed where the loss is read, like the other rule notes.
121. **Beds within reach, rooms instead of boxes, food that never dies out.** In
    runs/3agents_base_s153 the six sheep (no respawn) gave 5 wool all run, so the 3-wool bed was
    nearly impossible, and every shelter was a 1-cell box: the observation lists "open cells
    touching you", and sealing exactly those cells is the best answer to it. (a) A straw bed: 3
    wheat + 3 planks at a workbench also makes a bed (wool is scarce, wheat is farmed). (b) After a
    death with no bed to come back to, the notice adds "Sleeping at a bed makes you come back beside
    it." (c) With rule_notes, when the cells a creature could pass through around the agent close
    off within 200 cells (doors, leaves and solid blocks count as closed, a roof is needed), the
    observation says "you are in a closed space of N floor cells: no open path for creatures leads
    outside", so a room reads as safe as a box. (d) `creatures.passive_respawn` may be a fraction,
    a chance per morning (0.5 is about one sheep and one chicken every other day; whole numbers draw
    nothing extra), so animals thin out without dying out; slow berries are a long bush_regrow.
122. **Doors are two cells high; doors are not openings.** In runs/3agents_base_s153 Cy placed
    the run's first door. A one-cell door at foot level leaves the cell above open, and a blocked
    zombie steps up onto the door (it can be stood on) and over it, so a one-cell door kept nothing
    out. Placing a door now also fills the cell above it with door if that cell is empty; breaking
    either half removes both and gives one door back; with a block already above, a one-cell door
    is enough. The book line says so. Also, "open cells touching you" is meant as the cells a
    zombie could reach the agent from, but it listed every cell the agent could enter, doors
    included (Cy's own door showed as "feet north (9,17,27)"); it now lists only cells a creature
    can stand in (air, torch), so doors and water are no longer reported as openings.
123. **Planting aimed at the soil, food arithmetic in the book, faster crops.** In
    runs/4agents_varied_base_s153_r2, 10 of 46 plantings worked; 27 failed with "The cell is not
    empty." because the agent gave the dirt block itself, not the air cell above it ("plant a seed
    on the dirt at (62,12,57)"). The 4 starting seeds each were all lost that way, and no sprout
    stood before step 976. And one crop (200 steps, 3 wheat, 1 bread = 6 food) did not cover the 13
    to 26 food lost meanwhile, so no agent ever had more than one sprout. (a) With rule_notes on,
    seeds placed into a dirt or grass block say "The cell is not empty: (x, y, z) is dirt. seeds go
    in the empty cell above the dirt, (x, y+1, z)." (NOT_EMPTY_SOIL). (b) The book's grow line says
    "(the cell one higher than that block)" and that sprouts grow side by side, and a food line
    gives what eating restores and how fast food drops (rain included). (c) Defaults go from
    grow_steps 300 and wheat_per_crop 2 to 120 and 3 (world.yaml, world_varied.yaml; world_hard.yaml
    keeps its scarcity), so one crop is one bread (6 food against 8 lost in 120 dry steps): two
    sprouts per agent keep it fed, in rain too (rain doubles both the food drain and the growing).
124. **A memory file whose lessons outlast a rewrite (memory_layout: sections).** In
    runs/4agents_varied_base_s153_r2 (4 Haiku agents, 4000 character files) about three quarters of
    every file was state: the map, the agent's own health, food and inventory (which the observation
    already shows), and plans. Real lessons did appear ("craft needs exact counts", "wheat/seeds NOT
    food") but each agent rewrote its whole file about every 25 steps, from about 1500 to 600
    characters, never near the limit, and a lesson sentence lived 4 to 5 versions. Of 21 repeated
    "nothing is made from exactly these items" failures, 17 came while the lesson was out of the
    file; none of 18 tries to eat seeds or wheat came while "not food" was in it. So the lessons
    worked when kept and were not kept. Opt-in `memory_layout: sections` (agent spec key, run flag
    `--memory-layout`, a "lessons" box in the form; default `plain` leaves the prompt word for word)
    makes the file three parts: GOAL (one line, at most 200 characters, set with {"op": "goal"}),
    LESSONS (added with {"op": "lesson"} or an appended "LESSON: ..." line, changed or removed only
    by replace) and NOTES (append and rewrite work here; a rewrite that sends the whole file back
    keeps every lesson and adds new ones). The prompt names the parts, says health, food, inventory
    and surroundings are shown every step so the file does not need them, and asks for a lesson when
    something fails or surprises. Unlike most prompt text this is advice, not a fact about the world;
    it is off by default so runs with it can be compared against runs without.
125. **A plan the agent writes when it chooses to (planning: action | triggers).** In
    runs/4agents_varied_base_s153_32d (4 Haiku agents, 32 days) the agents wrote what they needed
    ("plant seeds by water", "eat early") and did not hold to it: the subject of an agent's
    thought changed about every 2 decisions, and 49 of 50 hunger deaths came after the "eat early"
    lesson was in the file. One call per step does the planning, the bookkeeping and the acting,
    and nothing keeps a goal in place between calls. The fix must not do the agent's strategy for
    it, so the rule is: the harness gives the means to plan and never says when or what about. A
    test for any piece of it: would this code still make sense in a different game? "Plan again
    when food is under 8" or "at dawn" fails that; a slot that holds a goal until the agent
    changes it passes. Two opt-in levels (agent spec key `planning`, run flag `--planning`; default
    `off` leaves prompts and replies word for word):
    - `action`: a plan slot (goal and steps, at most `plan_chars` 1000 characters) shown every step
      after the memory file, and a `plan` action. Choosing it costs the turn: the world gets a wait
      of `plan_wait` steps (default 1; in real time the second call's latency adds itself) and the
      agent is asked for the plan in a separate reply. The plan changes in no other way, so a memory
      rewrite cannot lose it. A plan over the limit, with no goal, or unreadable leaves the old one.
    - `triggers`: the same, and the plan may carry up to 5 conditions under "replan_when", each a
      name, a comparison and a number. The names are the numbers the observation shows (taken from
      world.vitals()), the counters step, steps_since_plan and deaths, and any item name (how many
      held). On the step a condition turns from false to true the agent's turn is the planner call
      alone, told which condition fired. A condition that is true when written waits until it has
      been false once, or a plan could set itself off for ever. No condition is built in, and the
      prompt's one example ("steps_since_plan >= 50") names a counter, not anything in the world.
    What is still ours: that a plan exists, its goal-and-steps shape, the 1000 characters (600 was tried first and cut off a real Haiku plan by 25), and the
    list of names (listing food next to step says both can be watched; it does not say which
    matters). Not built on purpose, kept for later rungs to compare against: a forced plan every N
    decisions, and plans forced on events we pick (death, dawn, low health). Each planning turn is
    in steps.jsonl under `plan` (cause, fired, accepted, goal, steps, replan_when, the plan before,
    the reply and its cost) with a `plan` event, and summary.json counts `plans_written` per agent.
    If an agent never chooses the plan action, that is a result, not a fault of the run.
126. **Replies that follow the format: a reply tool for the models that need it, and one more
    shape the parser reads.** In runs/sonnet_plan_s153_200 (4 Sonnet agents, 200 steps) 39 of 107
    replies were unreadable. Asked for one bare JSON object, Sonnet often wrote function-call markup
    with the action's name as the tag (`<invoke name="move"> <parameter name="dir">west</parameter>
    ... </invoke>`), sometimes repeating an empty tag until the token cap (2048 output tokens, one
    call of 61 s). Each became a 1-step wait, so a third of the turns were lost. Two changes.
    (a) Model entry key `reply_tool: true` (anthropic): the call offers one tool, `reply`, whose
    input is the reply's JSON object, and the adapter hands back the tool's input as the reply
    text (the plain text when the model did not use the tool). The model that wants to make a call
    then has a real one to make. On the 39 observations that had failed, 39 of 39 came back
    readable through the tool, each with a thought and memory edits, and 6 of 6 planner replies
    did too. The tool is offered, not forced: `tool_choice` of type tool is refused by
    claude-sonnet-5-5 and by any model with thinking on. Also tried and refused by the API:
    prefilling the reply with `{` (not supported by these models) and `output_config` with a JSON
    schema (every object must list its keys, and an action's `items` is a map of item names). It
    is on for sonnet, opus and sonnet_thinking and off for haiku, so Haiku runs stay comparable
    with the earlier ones (Haiku's rate was 98 of 7235); the system prompt is the same either way.
    (b) The parser reads `<invoke name="ACTION">` with its parameter tags as that action, when the
    name is an action and the tag says something (19 of the 39). A tag with nothing in it stays
    unreadable, since it carries no action. A JSON object whose "action" has no name no longer
    hides a readable action elsewhere in the reply. `say` and `give` are now among the names the
    salvage paths know.
127. **A plan asked for on a count of turns (plan_every), the comparison rung.** With `planning`
    on and nothing forcing it, agents did not plan: Haiku 0 plans in 331 decisions
    (runs/smoke_plan_triggers_s153), Sonnet 1 in 274 over two 200-step runs
    (runs/sonnet_plan_s153_200, _v2). So whether a plan helps could not be seen at all. Agent spec
    key `plan_every: N` (run flag `--plan-every`, needs planning action or triggers, default 0 =
    never) makes the agent's turn a planning turn on its first turn and whenever N of its turns have
    gone by since its last planning turn of any cause; choosing the plan action or a fired
    condition restarts the count. The count is of the agent's own turns and knows nothing about the
    world, which keeps to the rule of 125. It is more of our doing than rungs 1 and 2, since the
    agent no longer decides when, and a run with it shows what a plan does, not whether an agent
    would make one. The prompt adds one sentence saying so, and the request says how many turns it
    has been. The step's `plan.cause` is `interval`.
128. **The condition example is a form, not a condition.** The triggers paragraph showed
    "steps_since_plan >= 50" as its example, picked because it names a counter and nothing in the
    world. It still steered: in runs/sonnet_plan_every20_s153_400 Sonnet wrote that exact condition
    23 times and most replans were that timer; Haiku wrote steps_since_plan >= 40 or 20. The
    paragraph now gives the form with placeholders ("NAME < NUMBER") and the list of names, and no
    real condition. (125 and 127 describe the old example.)
129. **A plan that does not cost the turn (plan_inline) and conditions that wait (plan_cooldown).**
    In runs/haiku_plan_every20_s153_10d (4 Haiku agents, triggers with plan_every 20, stopped at
    step 1937) planning made things worse than no planning over the same 1835 steps: 20 deaths
    against 12, zombie deaths 13 against 2, 6 seeds planted against 17. Two causes, both from how
    often conditions fired. (a) A fired condition took the whole turn, so the agent stood still.
    All 13 zombie deaths followed a planning turn and 10 ended on two or more in a row: the agents
    write several health conditions (health < 10, < 8, < 5) and in a fight each fires in turn. A
    zombie hit the agent on 12% of planning turns against 3% of other turns. (b) A plan lived a
    median of 5 ordinary decisions before it was replaced, 23 of 253 were replaced before any
    action, and only 21 of 249 were near copies of the one before. Step 1 of a plan was mostly
    followed; a farming step sat about 70% of the way down the list and was never reached. Two
    opt-in agent spec keys (run flags `--plan-inline`, `--plan-cooldown`), neither knowing anything
    about the world: `plan_inline: true` asks for the plan in the same reply as the next action
    when a condition fires or plan_every comes up, so it takes no turn (the plan action the agent
    chooses still takes one, and such a step's `plan` has `inline: true` and no cost of its own);
    `plan_cooldown: K` leaves conditions unchecked until K of the agent's turns have gone by since
    its last planning turn (a condition that turned true meanwhile fires then). Not done, on
    purpose: "do not plan with a zombie near", which is knowledge of the game. What it costs: with
    plan_inline planning is no longer a separate act with a price, and one call again does both
    jobs on those turns.
130. **Longer actions the agent aims itself: goto and repeat (long_actions).** On an easier world
    (berries regrow, animals respawn, 3 zombies at most; runs/haiku_easy_plan_s153_5d and
    haiku_easy_base_s153_5d) agents still died of hunger with food in reach. All 32 animals were
    alive at almost every death. Hungry with an animal in view, an agent attacked it on 13 of 101
    turns (2 of 36 without planning), a sword in hand on 63 of them. Holding seeds with water within
    3 cells, it planted on 60 of 571 turns. Where a thing sits in the observation was not the cause:
    creatures are listed last and a zombie in view is in the thought on 79 to 89% of turns, a sheep
    on 10 to 19%. Getting food is a chain of small decisions (walk, walk, walk, hit, hit, hit, eat)
    and at each one the agent can turn to something else. World key `long_actions: true` (default
    false: the actions are unknown and the prompt is unchanged) adds two things that shorten the
    chain without choosing the target. `goto` with x, y, z or with a creature's or agent's id walks,
    one world step per cell, until the agent is beside it (within 1 cell sideways, and within reach
    up or down): a shortest path over level steps, steps up one cell and safe falls, found again
    every step. It ends when beside the target, hurt, a creature other than the target comes within
    close_radius (at first it ended, as move does, when anything new came into view: with animals
    about that cut 132 of 346 gotos short), another body is in the way, there is no way on foot (it first walks to the nearest cell it can
    reach), the creature is gone, or after `goto_max_steps` (30). It never mines or builds.
    `"repeat": 2 to 8` on any action does it that many times in a row and stops after a try that
    fails or once the agent is hurt; the result is the last try that worked, with the count. Left
    out on purpose: "hunt", "plant all my seeds", anything that names what to go after. What is
    still ours: that walking somewhere is not a decision worth the agent's turns (finding the path
    is taken to be no part of strategy).
