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
