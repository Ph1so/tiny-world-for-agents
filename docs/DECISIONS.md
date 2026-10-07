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
16. **Craft** needs the exact amounts of one recipe. A wrong set, wrong amounts, or a missing workbench or furnace all give the same line, "Nothing was made.", cost one step, and count as a valid action with a `craft_fail` event. Naming items that are not in the inventory is an invalid action.
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
42. **The sweep config takes `controller`** as one name or a list (default `llm`), and `shuffle_recipes` (default false). A bot controller ignores `models`, `memory_chars` and `history_window` and gives one run per seed. Every run is a child process of `tinyworld.runner.run` started with `--resume`, so a cut-off run continues from its last complete step. A run with a `summary.json` counts as done and is skipped. The llm flags passed to the child are `--model`, `--memory-chars`, `--history-window`.
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
