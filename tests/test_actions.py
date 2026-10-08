"""Unit tests for the seven actions and the rules around them."""
from conftest import flat_world, make_world

from tinyworld.sim import text as T
from tinyworld.sim.defs import ID


def give(w, **items):
    for k, v in items.items():
        w._add(k.replace("_", " "), v)


# ------------------------------------------------------------------ move

def test_move_walks_and_costs_real_steps(flat):
    r = flat.step({"name": "move", "dir": "north", "steps": 3})
    assert flat.pos == [32, 10, 29] and r.steps == 3 and r.valid
    assert r.text == "Moved 3 cells north."
    assert len(r.deltas) == 3 and [d["t"] for d in r.deltas] == [1, 2, 3]


def test_move_directions(flat):
    for d, want in [("south", [32, 10, 33]), ("east", [33, 10, 33]), ("west", [32, 10, 33]), ("north", [32, 10, 32])]:
        flat.step({"name": "move", "dir": d, "steps": 1})
        assert flat.pos == want


def test_move_climbs_one_block_and_stops_at_two(flat):
    flat.set_block(32, 10, 31, "stone")
    flat.set_block(32, 10, 29, "stone")
    flat.set_block(32, 11, 29, "stone")
    flat.set_block(32, 12, 29, "stone")
    r = flat.step({"name": "move", "dir": "north", "steps": 5})
    assert flat.pos == [32, 10, 30]          # up onto the block, down again, then the wall
    assert r.steps == 3 and r.text == "Moved 2 cells north. Blocked by stone at (32,10,29) and stone at (32,11,29)."


def test_move_blocked_costs_one_step(flat):
    flat.set_block(32, 11, 31, "stone")
    r = flat.step({"name": "move", "dir": "north", "steps": 4})
    assert flat.pos == [32, 10, 32] and r.steps == 1 and r.valid
    assert r.text == "You did not move. Blocked by stone at (32,11,31)."     # the head cell


def test_blocked_move_names_what_is_in_the_way(flat):
    flat.set_block(32, 10, 31, "dirt")                         # feet cell: a step up, but the head can't clear it
    flat.set_block(32, 12, 32, "stone")
    r = flat.step({"name": "move", "dir": "north", "steps": 1})
    assert r.text == "You did not move. Blocked by dirt at (32,10,31) and stone at (32,12,32)."
    flat.set_block(32, 11, 31, "log")                          # a two-high wall
    r = flat.step({"name": "move", "dir": "north", "steps": 1})
    assert r.text == "You did not move. Blocked by dirt at (32,10,31) and log at (32,11,31)."
    flat.set_block(32, 11, 33, "stone")                        # a walk stopped part way says it too
    flat.set_block(32, 10, 31, "air")
    flat.set_block(32, 11, 31, "air")
    flat.set_block(32, 11, 30, "planks")
    r = flat.step({"name": "move", "dir": "north", "steps": 4})
    assert r.text == "Moved 1 cell north. Blocked by planks at (32,11,30)."
    flat.pos = [10, 10, 10]                                    # far from the stone above
    flat._spawn("sheep", (10, 10, 9))
    flat.cfg.creatures.passive_move_prob = 0.0
    r = flat.step({"name": "move", "dir": "north", "steps": 1})
    assert r.text == "You did not move. Blocked by sheep #1."


def test_move_bad_arguments(flat):
    for a in [{"name": "move", "dir": "north", "steps": 9}, {"name": "move", "dir": "sideways", "steps": 1},
              {"name": "move", "dir": "north", "steps": 0}]:
        r = flat.step(a)
        assert not r.valid and r.steps == 1 and r.text == T.BAD_ARGS


def test_up_and_down_only_in_water(flat):
    assert flat.step({"name": "move", "dir": "up", "steps": 1}).text == T.NOT_MOVED_DRY
    assert flat.step({"name": "move", "dir": "down", "steps": 1}).text == T.NOT_MOVED_DRY
    for y in range(5, 10):
        flat.set_block(32, y, 31, "water")
    flat.step({"name": "move", "dir": "north", "steps": 1})
    assert flat.pos == [32, 9, 31]           # floats in the top water cell
    flat.step({"name": "move", "dir": "down", "steps": 2})
    assert flat.pos == [32, 7, 31] and flat.air == 8
    flat.step({"name": "move", "dir": "up", "steps": 2})
    assert flat.pos == [32, 9, 31] and flat.air == 10
    flat.step({"name": "move", "dir": "south", "steps": 1})
    assert flat.pos == [32, 10, 32]          # climbs out


def test_fall_damage(flat):
    for y in range(4, 10):
        flat.set_block(32, y, 31, "air")
    r = flat.step({"name": "move", "dir": "north", "steps": 1})
    assert flat.pos == [32, 4, 31] and flat.health == 20 - (6 - 3)
    assert any(e["type"] == "hurt" and e["detail"]["cause"] == "fall" for e in r.events)


def test_move_stops_when_a_creature_comes_into_view(flat):
    flat.cfg.creatures.passive_move_prob = 0.0
    for y in (10, 11, 12):
        for x in range(28, 37):
            flat.set_block(x, y, 27, "stone")           # a wall hides the sheep
    flat.set_block(32, 10, 27, "air")
    flat.set_block(32, 11, 27, "air")
    flat._spawn("sheep", (36, 10, 25))
    assert flat.visible_creatures() == []
    r = flat.step({"name": "move", "dir": "north", "steps": 8})
    assert r.steps < 8 and flat.visible_creatures()


# ------------------------------------------------------------------ mine

def test_mine_by_hand_takes_hardness_steps(flat):
    r = flat.step({"name": "mine", "x": 33, "y": 9, "z": 32})
    assert r.text == "Got 1 grass." and r.steps == 2 and flat.inv == {"grass": 1}
    assert flat.block(33, 9, 32) == "air"
    assert r.deltas[-1]["blocks"] == [[33, 9, 32, "air"]] and r.deltas[0]["blocks"] == []
    assert [e["type"] for e in r.events] == ["first_mine"]
    assert flat.step({"name": "mine", "x": 31, "y": 9, "z": 32}).events == []


def test_mine_needs_the_right_tool_and_says_only_what_happened(flat):
    flat.set_block(33, 10, 32, "stone")
    flat.set_block(31, 10, 32, "iron ore")
    r = flat.step({"name": "mine", "x": 33, "y": 10, "z": 32})
    assert r.text == T.NOT_BROKEN and r.steps == 1 and r.valid and flat.block(33, 10, 32) == "stone"
    give(flat, wood_pickaxe=1)
    assert flat.step({"name": "mine", "x": 31, "y": 10, "z": 32}).text == T.NOT_BROKEN
    r = flat.step({"name": "mine", "x": 33, "y": 10, "z": 32})
    assert r.text == "Got 1 stone." and r.steps == 4 and flat.tools["wood pickaxe"] == 29
    give(flat, stone_pickaxe=1)
    r = flat.step({"name": "mine", "x": 31, "y": 10, "z": 32})
    assert r.text == "Got 1 iron ore." and r.steps == 4 and flat.tools["stone pickaxe"] == 59


def test_better_tools_are_faster(flat):
    steps = []
    for pick in ("wood pickaxe", "stone pickaxe", "iron pickaxe"):
        flat.set_block(33, 10, 32, "stone")
        flat._add(pick, 1)
        steps.append(flat.step({"name": "mine", "x": 33, "y": 10, "z": 32}).steps)
    assert steps == [4, 3, 2]


def test_tool_wears_out_and_breaks(flat):
    give(flat, wood_pickaxe=1)
    flat.tools["wood pickaxe"] = 1
    r = flat.step({"name": "mine", "x": 33, "y": 9, "z": 32})
    assert r.text == "Got 1 grass. The wood pickaxe broke."
    assert "wood pickaxe" not in flat.inv and "wood pickaxe" not in flat.tools
    assert any(e["type"] == "tool_broke" for e in r.events)


def test_mine_drops(flat):
    give(flat, iron_pickaxe=1)
    flat.set_block(33, 10, 32, "coal ore")
    flat.set_block(31, 10, 32, "berry bush")
    assert flat.step({"name": "mine", "x": 33, "y": 10, "z": 32}).text == "Got 1 coal."
    assert flat.step({"name": "mine", "x": 31, "y": 10, "z": 32}).text == "Got 2 berries."


def test_mine_invalid_targets(flat):
    assert flat.step({"name": "mine", "x": 36, "y": 10, "z": 32}).text == T.TOO_FAR
    r = flat.step({"name": "mine", "x": 33, "y": 10, "z": 32})
    assert r.text == T.NOTHING_THERE and not r.valid and r.steps == 1
    assert flat.step({"name": "mine", "x": "a", "y": 10, "z": 32}).text == T.BAD_ARGS
    # A block with no open face does not break.
    assert flat.step({"name": "mine", "x": 33, "y": 8, "z": 32}).text == T.NOT_BROKEN
    flat.set_block(33, 10, 32, "water")
    assert flat.step({"name": "mine", "x": 33, "y": 10, "z": 32}).text == T.NOT_BROKEN


def test_berry_bush_regrows(flat):
    flat.set_block(33, 10, 32, "berry bush")
    flat.step({"name": "mine", "x": 33, "y": 10, "z": 32})
    flat.food = 20
    seen = []
    while flat.t < 160:
        flat.food = 20
        r = flat.step({"name": "wait", "steps": 8})
        seen += [d["t"] for d in r.deltas if [33, 10, 32, "berry bush"] in d["blocks"]]
    assert seen == [1 + flat.cfg.bush_regrow] and flat.block(33, 10, 32) == "berry bush"


# ----------------------------------------------------------------- place

def test_place(flat):
    give(flat, planks=2, sticks=1)
    r = flat.step({"name": "place", "item": "planks", "x": 33, "y": 10, "z": 32})
    assert r.text == "Placed planks at (33, 10, 32)." and r.steps == 1
    assert flat.block(33, 10, 32) == "planks" and flat.inv["planks"] == 1
    assert r.deltas[0]["blocks"] == [[33, 10, 32, "planks"]]
    assert [e["type"] for e in r.events] == ["first_place"]
    assert flat.step({"name": "place", "item": "planks", "x": 33, "y": 10, "z": 32}).text == T.NOT_EMPTY
    assert flat.step({"name": "place", "item": "planks", "x": 32, "y": 11, "z": 32}).text == T.NOT_EMPTY
    assert flat.step({"name": "place", "item": "planks", "x": 40, "y": 10, "z": 32}).text == T.TOO_FAR
    assert flat.step({"name": "place", "item": "stone", "x": 31, "y": 10, "z": 32}).text == T.NO_ITEM
    r = flat.step({"name": "place", "item": "sticks", "x": 31, "y": 10, "z": 32})
    assert r.text == "The sticks was not placed." and not r.valid and r.steps == 1
    assert flat.inv == {"planks": 1, "sticks": 1}


def test_names_accept_underscores(flat):
    give(flat, iron_ore=1)
    assert flat.step({"name": "place", "item": "Iron_Ore", "x": 33, "y": 10, "z": 32}).valid


# ------------------------------------------------------------------- eat

def test_eat(flat):
    give(flat, berries=1, raw_meat=1, cooked_meat=1, stone=1)
    flat.food = 5
    r = flat.step({"name": "eat", "item": "berries"})
    assert r.text == "Ate 1 berries." and flat.food == 7 and r.steps == 1
    flat.step({"name": "eat", "item": "raw meat"})
    assert flat.food == 10
    flat.step({"name": "eat", "item": "cooked meat"})
    assert flat.food == 18
    r = flat.step({"name": "eat", "item": "stone"})
    assert r.text == "The stone was not eaten." and flat.inv == {"stone": 1} and r.steps == 1
    r = flat.step({"name": "eat", "item": "berries"})
    assert r.text == T.NO_ITEM and not r.valid and r.steps == 1


# ---------------------------------------------------------------- attack

def test_attack(flat):
    flat.cfg.creatures.passive_move_prob = 0.0
    flat._spawn("sheep", (33, 10, 32))
    cid = flat.creatures[0]["id"]
    assert flat.step({"name": "attack", "id": cid}).text == f"Hit sheep #{cid}."
    flat.step({"name": "attack", "id": cid})
    r = flat.step({"name": "attack", "id": cid})
    assert r.text == f"Hit sheep #{cid}. It is gone. Got 2 raw meat."
    assert flat.inv == {"raw meat": 2} and flat.creatures == []
    assert [e for e in r.events if e["type"] == "kill"][0]["detail"]["kind"] == "sheep"
    r = flat.step({"name": "attack", "id": cid})
    assert not r.valid and r.steps == 1
    flat._spawn("chicken", (36, 10, 32))
    assert not flat.step({"name": "attack", "id": flat.creatures[0]["id"]}).valid


def test_sword_hits_harder_and_wears(flat):
    flat.cfg.creatures.passive_move_prob = 0.0
    give(flat, stone_sword=1)
    flat._spawn("sheep", (33, 10, 32))
    cid = flat.creatures[0]["id"]
    flat.step({"name": "attack", "id": cid})
    assert "Got 2 raw meat" in flat.step({"name": "attack", "id": cid}).text
    assert flat.tools["stone sword"] == 38


# ------------------------------------------------------------------ wait

def test_wait(flat):
    r = flat.step({"name": "wait", "steps": 5})
    assert r.steps == 5 and flat.t == 5 and r.text == "Waited 5 steps."
    assert not flat.step({"name": "wait", "steps": 20}).valid


def test_wait_stops_when_hurt(flat):
    flat.food = 0
    r = flat.step({"name": "wait", "steps": 8})
    assert r.steps == 5 and flat.health == 19


def test_unknown_action_costs_one_step(flat):
    for a in [{"name": "fly"}, {}, {"name": 3}, "nonsense", None]:
        r = flat.step(a)
        assert r.text == T.UNKNOWN_ACTION and not r.valid and r.steps == 1
    assert flat.t == 5


# ---------------------------------------------------------------- vitals

def test_food_drops_and_health_heals(flat):
    flat.health = 10
    for _ in range(15):
        flat.step({"name": "wait", "steps": 1})
    assert flat.food == 19 and flat.health == 11


def test_death_by_hunger_and_respawn(flat):
    flat._add("planks", 3)
    flat.food, flat.health = 0, 1
    flat.pos = [40, 10, 40]
    flat.set_block(33, 10, 32, "planks")
    r = flat.step({"name": "wait", "steps": 8})
    assert r.died == "hunger" and r.steps == 5
    assert flat.pos == [32, 10, 32] and flat.inv == {} and flat.health == 20 and flat.food == 20
    assert flat.block(33, 10, 32) == "planks" and not flat.done
    assert [e["type"] for e in r.events] == ["hurt", "death", "respawn"]
    obs = flat.observe()
    assert "You died. Cause: hunger. You are back at the starting point. Your items are gone." in obs
    flat.step({"name": "wait", "steps": 1})
    assert "You died" not in flat.observe()


def test_wipe_mode_reports_the_death_the_same_way():
    w = flat_world(on_death="respawn_wipe_memory")
    w.food, w.health = 0, 1
    r = w.step({"name": "wait", "steps": 8})
    assert r.died == "hunger" and not w.done and w.pos == [32, 10, 32]


def test_end_run_mode():
    w = flat_world(on_death="end_run")
    w.food, w.health = 0, 1
    r = w.step({"name": "wait", "steps": 8})
    assert r.died == "hunger" and w.done
    assert "You died. Cause: hunger." in w.observe() and "starting point" not in w.observe()
    r = w.step({"name": "wait", "steps": 1})
    assert r.steps == 0 and not r.valid


def test_drowning(flat):
    for y in range(5, 10):
        flat.set_block(32, y, 31, "water")
    flat.step({"name": "move", "dir": "north", "steps": 1})
    flat.step({"name": "move", "dir": "down", "steps": 3})
    died = None
    for _ in range(40):
        died = died or flat.step({"name": "wait", "steps": 1}).died
    assert died == "drowning"


# ------------------------------------------------------- day, night, light

def test_light_levels_and_day_events(flat):
    flat.cfg.creatures.zombie_spawn_prob = 0.0
    seen, events = {}, []
    while flat.t < 300:
        flat.food = 20
        r = flat.step({"name": "wait", "steps": 1})
        seen[flat.t] = r.deltas[0]["light"]
        events += [(e["t"], e["type"]) for e in r.events]
    assert seen[100] == "bright" and seen[190] == "dim" and seen[250] == "dark" and seen[295] == "dim"
    assert events == [(200, "night_start"), (300, "day_start")]
    assert flat.day == 2 and seen[300] == "bright"


def test_cover_and_torch_change_light(flat):
    assert flat.light() == "bright"
    flat.set_block(32, 13, 32, "stone")
    assert flat.light() == "dim"
    flat.t = 250
    assert flat.light() == "dark"
    flat.set_block(34, 10, 32, "torch")
    assert flat.light() == "dim"


# --------------------------------------------------------------- zombies

def night_world():
    w = flat_world()
    w.t = 199
    return w


def test_zombies_come_at_night_far_away_and_leave_at_sunrise():
    w = night_world()
    w.cfg.creatures.zombie_spawn_prob = 1.0
    w.cfg.creatures.zombie_chase_dist = 0
    w.t = 198
    r = w.step({"name": "wait", "steps": 1})
    assert w.creatures == []                                 # t = 199 is still day
    first = []
    for _ in range(12):
        w.health = 20
        r = w.step({"name": "wait", "steps": 1})
        first += [c for c in r.deltas[0]["creatures"] if c["id"] not in [f["id"] for f in first]]
    assert len(w.creatures) == w.cfg.creatures.zombie_max and all(c["kind"] == "zombie" for c in w.creatures)
    assert all(max(abs(c["pos"][0] - 32), abs(c["pos"][2] - 32)) >= 12 for c in first)
    while w.t < 300:
        w.health = w.food = 20
        w.step({"name": "wait", "steps": 1})
    # Zombies are gone. Two sheep and two chickens came with the morning.
    assert sorted(c["kind"] for c in w.creatures) == ["chicken", "chicken", "sheep", "sheep"]


def test_no_zombies_near_a_torch():
    w = night_world()
    w.cfg.creatures.zombie_spawn_prob = 1.0
    w.cfg.creatures.zombie_spawn_min_dist = 0
    w.cfg.creatures.zombie_spawn_max_dist = 5
    w.set_block(32, 10, 33, "torch")
    for _ in range(30):
        w.step({"name": "wait", "steps": 1})
    assert w.creatures == []


def test_zombie_chases_at_half_speed_and_hits():
    w = night_world()
    w.cfg.creatures.zombie_spawn_prob = 0.0
    w.cfg.creatures.zombie_step_every = 2
    w._spawn("zombie", (32, 10, 26))
    w.cfg.vitals.heal_food_min = 99
    hits = []
    for _ in range(20):
        r = w.step({"name": "wait", "steps": 1})
        hits += [e["t"] for e in r.events if e["type"] == "hurt"]
    assert w.creatures[0]["pos"] == [32, 10, 31]             # 5 cells, one every 2 steps
    assert hits and hits[0] == 208 and hits[1] - hits[0] == 2
    assert w.health == 20 - 3 * len(hits)


def test_zombie_moves_on_two_of_every_three_steps():
    w = night_world()
    w.cfg.creatures.zombie_spawn_prob = 0.0
    assert w.cfg.creatures.zombie_step_every == 1.5
    w._spawn("zombie", (32, 10, 14))                          # 18 away: inside the chase range of 20
    for _ in range(9):
        w.step({"name": "wait", "steps": 1})
    assert w.creatures[0]["pos"] == [32, 10, 20]              # 6 cells in 9 steps


def test_armor_takes_off_zombie_damage_and_wears():
    w = night_world()
    w.cfg.creatures.zombie_spawn_prob = 0.0
    w.cfg.vitals.heal_food_min = 99
    give(w, iron_helmet=1, iron_chestplate=1)
    w._spawn("zombie", (32, 10, 31))
    hurt = []
    for _ in range(6):
        r = w.step({"name": "wait", "steps": 1})
        hurt += [e["detail"]["amount"] for e in r.events if e["type"] == "hurt"]
    assert hurt and set(hurt) == {1}                           # 3 - 1 - 2, never below 1
    assert w.tools["iron helmet"] == w.cfg.durability["iron helmet"] - len(hurt)
    assert w.tools["iron chestplate"] == w.cfg.durability["iron chestplate"] - len(hurt)
    w._take("iron chestplate", 1)
    hurt = []
    for _ in range(6):
        r = w.step({"name": "wait", "steps": 1})
        hurt += [e["detail"]["amount"] for e in r.events if e["type"] == "hurt"]
    assert hurt and set(hurt) == {2}


def test_death_cause_uses_shown_names():
    w = flat_world(names="alien")
    w._cause = "zombie"
    w.health = 0
    w._die()
    assert "zombie" not in w._death_notice and w.dn("zombie") in w._death_notice


def test_zombie_does_not_get_through_walls_or_doors():
    w = night_world()
    w.cfg.creatures.zombie_spawn_prob = 0.0
    for dx, dz in ((1, 0), (-1, 0), (0, 1)):
        w.set_block(32 + dx, 10, 32 + dz, "stone")
        w.set_block(32 + dx, 11, 32 + dz, "stone")
    w.set_block(32, 10, 31, "door")           # a doorway for the agent is two doors high
    w.set_block(32, 11, 31, "door")
    w.set_block(32, 12, 32, "stone")
    w._spawn("zombie", (32, 10, 28))
    for _ in range(60):
        w.step({"name": "wait", "steps": 1})
    assert w.health == 20
    r = w.step({"name": "move", "dir": "north", "steps": 1})   # the agent can stand in the door
    assert w.pos == [32, 10, 31]


# ---------------------------------------------------------------- notice

def test_notice_is_shown_once(flat):
    flat.set_notice("Your reply could not be read.")
    flat.step({"name": "wait", "steps": 1})
    assert "Your reply could not be read." in flat.observe()
    assert "Your reply could not be read." in flat.observe()
    flat.step({"name": "wait", "steps": 1})
    assert "Your reply could not be read." not in flat.observe()


def test_valid_actions_are_all_accepted():
    w = make_world(3)
    w._add("planks", 8)
    w._add("berries", 1)
    names = set()
    for a in w.valid_actions():
        w2 = make_world(3)
        w2._add("planks", 8)
        w2._add("berries", 1)
        assert w2.step(a).valid, a
        names.add(a["name"])
    assert {"move", "mine", "place", "craft", "eat", "wait"} <= names


# ------------------------------------------------------- shafts and traps

def dig_shaft(w, x, z, top, bottom):
    """A one-wide hole in column (x, z) from y = top down to y = bottom, stone around it."""
    w.blocks[:top + 1] = ID["stone"]
    for y in range(bottom, top + 1):
        w.set_block(x, y, z, "air")


def test_move_up_out_of_water_says_why(flat):
    r = flat.step({"name": "move", "dir": "up", "steps": 1})
    assert flat.pos == [32, 10, 32] and r.text == T.NOT_MOVED_DRY and r.valid
    r = flat.step({"name": "move", "dir": "down", "steps": 2})
    assert r.text == T.NOT_MOVED_DRY
    flat.set_block(32, 11, 31, "stone")
    assert flat.step({"name": "move", "dir": "north", "steps": 1}).text.startswith(T.NOT_MOVED + " Blocked by")


def test_move_up_blocked_in_water_is_plain_not_moved(flat):
    for y in range(5, 11):
        flat.set_block(32, y, 32, "water")
    flat.set_block(32, 12, 32, "stone")
    assert flat.step({"name": "move", "dir": "up", "steps": 1}).text == T.NOT_MOVED


def test_respawn_does_not_drop_into_a_dug_out_start():
    w = flat_world()
    dig_shaft(w, 32, 32, 9, 2)                     # start column dug down to y = 2, surface at y = 10
    w.pos = [32, 2, 32]
    w._add("stone pickaxe", 1)                     # not trapped, so the run goes on
    w.food, w.health = 0, 1
    r = w.step({"name": "wait", "steps": 8})
    assert r.died == "hunger"
    assert w.pos[1] == 10 and max(abs(w.pos[0] - 32), abs(w.pos[2] - 32)) == 1
    assert w.block(w.pos[0], w.pos[1] - 1, w.pos[2]) == "stone"


def test_respawn_on_a_built_over_start_is_unchanged(flat):
    flat.set_block(32, 10, 32, "planks")
    flat.set_block(32, 11, 32, "planks")
    flat.pos = [40, 10, 40]
    flat.food, flat.health = 0, 1
    flat.step({"name": "wait", "steps": 8})
    assert flat.pos == [32, 12, 32]


def test_trapped_in_stone_with_nothing_ends_the_run():
    w = flat_world()
    dig_shaft(w, 32, 32, 12, 4)
    w.blocks[13:] = ID["stone"]                    # sealed: nothing can be swum or walked out of
    w.pos = [32, 4, 32]
    r = w.step({"name": "move", "dir": "up", "steps": 1})
    assert w.trapped() and w.done and w.stuck
    assert [e["type"] for e in r.events if e["type"] == "stuck"] == ["stuck"]
    assert w.step({"name": "wait", "steps": 1}).steps == 0


def test_open_shaft_without_tools_is_also_trapped():
    w = flat_world()
    dig_shaft(w, 32, 32, 9, 2)                     # stone all round, open sky above, empty hands
    w.pos = [32, 2, 32]
    assert w.trapped()


def test_not_trapped_with_a_pickaxe_a_block_or_soft_walls():
    w = flat_world()
    dig_shaft(w, 32, 32, 9, 2)
    w.pos = [32, 2, 32]
    w._add("stone pickaxe", 1)
    assert not w.trapped()
    w = flat_world()
    dig_shaft(w, 32, 32, 9, 2)
    w.pos = [32, 2, 32]
    w._add("dirt", 1)
    assert not w.trapped()
    w = flat_world()                                # grass walls break by hand
    w.pos = [32, 10, 32]
    w.set_block(32, 9, 32, "air")
    w.pos = [32, 9, 32]
    assert not w.trapped()


def test_on_stuck_continue_only_logs_once():
    w = flat_world(on_stuck="continue")
    dig_shaft(w, 32, 32, 9, 2)
    w.pos = [32, 2, 32]
    kinds = []
    for _ in range(3):
        kinds += [e["type"] for e in w.step({"name": "wait", "steps": 1}).events]
    assert kinds.count("stuck") == 1 and not w.done


# ---------------------------------------------------------------- inventory limit and chests

def test_full_inventory_blocks_mining_and_crafting(flat):
    assert flat.cfg.inventory_slots == 10 and flat.cfg.stack_size == 32
    give(flat, wood_pickaxe=1, stone_sword=1, log=2, sticks=1, coal=1, berries=1, raw_meat=1, sand=1, stone=1,
         dirt=32)
    assert flat.slots(flat.inv) == 10
    r = flat.step({"name": "mine", "x": 33, "y": 9, "z": 32})          # grass would need an 11th slot
    assert r.text == T.NO_ROOM and r.valid and r.steps == 1 and flat.block(33, 9, 32) == "grass"
    r = flat.step({"name": "mine", "x": 32, "y": 9, "z": 33})          # 33 dirt is two stacks
    assert r.text == T.NO_ROOM
    r = flat.step({"name": "craft", "items": {"log": 1}})              # planks need a new slot; one log stays
    assert r.text == T.NO_ROOM and flat.inv["log"] == 2
    flat.step({"name": "drop", "items": {"sand": 1}})
    assert flat.step({"name": "craft", "items": {"log": 1}}).text == "Made 4 planks."


def test_meat_that_does_not_fit_is_lost(flat):
    give(flat, wood_pickaxe=1, stone_sword=1, log=1, sticks=1, coal=1, berries=1, sand=1, stone=1, dirt=1, raw_meat=31)
    flat._spawn("sheep", (33, 10, 32))
    flat.cfg.creatures.passive_move_prob = 0.0
    texts = [flat.step({"name": "attack", "id": 1}).text for _ in range(2)]
    assert texts[-1] == "Hit sheep #1. It is gone. Got 1 raw meat. No room for 1 raw meat."
    assert flat.inv["raw meat"] == 32


def test_drop(flat):
    give(flat, dirt=5)
    r = flat.step({"name": "drop", "items": {"dirt": 2}})
    assert r.text == "Dropped dirt x2." and r.steps == 1 and flat.inv["dirt"] == 3
    assert flat.step({"name": "drop", "items": {"dirt": 9}}).text == "Not enough dirt in inventory."
    assert flat.step({"name": "drop", "items": {"log": 1}}).text == T.NO_ITEM
    assert flat.step({"name": "drop", "items": {}}).text == T.BAD_ARGS


def test_chest_store_take_and_observe(flat):
    give(flat, chest=1, stone=10, coal=3, wood_pickaxe=1)
    assert flat.step({"name": "place", "item": "chest", "x": 33, "y": 10, "z": 32}).valid
    r = flat.step({"name": "store", "x": 33, "y": 10, "z": 32, "items": {"stone": 6, "coal": 3}})
    assert r.text == "Stored stone x6, coal x3." and r.steps == 1
    assert flat.inv == {"stone": 4, "wood pickaxe": 1} and flat.chests[(33, 10, 32)] == {"stone": 6, "coal": 3}
    assert "  chest at (33,10,32) holds: stone x6, coal x3" in flat.observe()
    assert flat.step({"name": "store", "x": 33, "y": 10, "z": 32, "items": {"wood pickaxe": 1}}).text == \
        "The wood pickaxe was not stored."
    assert flat.step({"name": "take", "x": 33, "y": 10, "z": 32, "items": {"coal": 4}}).text == \
        "Not enough coal in the chest."
    r = flat.step({"name": "take", "x": 33, "y": 10, "z": 32, "items": {"coal": 2}})
    assert r.text == "Took coal x2." and flat.inv["coal"] == 2 and flat.chests[(33, 10, 32)] == {"stone": 6, "coal": 1}
    assert flat.step({"name": "take", "x": 34, "y": 10, "z": 32, "items": {"coal": 1}}).text == "No chest at (34, 10, 32)."
    assert flat.step({"name": "take", "x": 40, "y": 10, "z": 32, "items": {"coal": 1}}).text == T.TOO_FAR
    assert flat.step({"name": "store", "x": 33, "y": 10, "z": 32, "items": "coal"}).text == T.BAD_ARGS


def test_chest_full_and_mining(flat):
    flat.cfg.chest_slots = 1
    give(flat, chest=1, stone=40, wood_pickaxe=1)
    flat.step({"name": "place", "item": "chest", "x": 33, "y": 10, "z": 32})
    assert flat.step({"name": "store", "x": 33, "y": 10, "z": 32, "items": {"stone": 33}}).text == "No room in the chest."
    assert flat.step({"name": "store", "x": 33, "y": 10, "z": 32, "items": {"stone": 32}}).valid
    r = flat.step({"name": "mine", "x": 33, "y": 10, "z": 32})
    assert r.text == "The chest is not empty." and flat.block(33, 10, 32) == "chest"
    flat.step({"name": "take", "x": 33, "y": 10, "z": 32, "items": {"stone": 32}})
    for _ in range(4):
        r = flat.step({"name": "mine", "x": 33, "y": 10, "z": 32})
        if r.text.startswith("Got"):
            break
    assert r.text == "Got 1 chest." and (33, 10, 32) not in flat.chests


def test_chest_keeps_items_through_death_and_replays():
    w = flat_world()
    give(w, chest=1, stone=5)
    w.step({"name": "place", "item": "chest", "x": 33, "y": 10, "z": 32})
    w.step({"name": "store", "x": 33, "y": 10, "z": 32, "items": {"stone": 5}})
    w._cause = "hunger"
    w.health = 0
    w._die()
    assert w.inv == {} and w.chests[(33, 10, 32)] == {"stone": 5}
    assert w.snapshot()["chests"] == [[33, 10, 32, {"stone": 5}]]


def test_no_limit_when_slots_is_zero(flat):
    flat.cfg.inventory_slots = 0
    give(flat, dirt=500, wood_pickaxe=1, stone_sword=1, log=1, sticks=1, coal=1, berries=1, raw_meat=1, sand=1)
    assert flat.step({"name": "mine", "x": 33, "y": 9, "z": 32}).text == "Got 1 grass."
    assert flat.observe().split("\n")[3].startswith("inventory: ")
