"""Text CLI. Type an action as JSON or in short form and read the observation.

    python -m tinyworld.sim.cli --seed 1

Short forms: move north 3 | mine 31 13 23 | place planks 31 14 23 | craft planks 3 sticks 2
             eat berries | attack 7 | wait 4
Other commands: help, obs, valid, hash, quit
"""
from __future__ import annotations

import argparse
import json

from . import World, load_world_config


def parse_action(line: str) -> dict:
    """Turn a typed line into an action dict. Unknown input becomes an unknown action."""
    line = line.strip()
    if line.startswith("{"):
        try:
            a = json.loads(line)
            return a if isinstance(a, dict) else {"name": line}
        except json.JSONDecodeError:
            return {"name": line}
    w = line.split()
    if not w:
        return {"name": ""}
    name, rest = w[0].lower(), w[1:]

    def num(s: str):
        return int(s) if s.lstrip("-").isdigit() else s

    if name == "move":
        return {"name": name, "dir": rest[0].lower() if rest else "", "steps": num(rest[1]) if len(rest) > 1 else 1}
    if name == "mine" and len(rest) == 3:
        return {"name": name, **{k: num(v) for k, v in zip("xyz", rest)}}
    if name == "place" and len(rest) >= 4:
        return {"name": name, "item": " ".join(rest[:-3]), **{k: num(v) for k, v in zip("xyz", rest[-3:])}}
    if name == "craft":
        items, words = {}, []
        for tok in rest:
            if tok.isdigit() and words:
                items[" ".join(words)] = int(tok)
                words = []
            else:
                words.append(tok)
        if words:
            items[" ".join(words)] = 1
        return {"name": name, "items": items}
    if name == "eat":
        return {"name": name, "item": " ".join(rest)}
    if name == "attack":
        return {"name": name, "id": num(rest[0].lstrip("#")) if rest else None}
    if name == "wait":
        return {"name": name, "steps": num(rest[0]) if rest else 1}
    return {"name": name}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--config", default=None)
    ap.add_argument("--names", choices=["familiar", "alien"], default=None)
    ap.add_argument("--shuffle-recipes", action="store_true", default=None)
    ap.add_argument("--on-death", default=None)
    args = ap.parse_args()
    cfg = load_world_config(args.config, names=args.names, shuffle_recipes=args.shuffle_recipes,
                            on_death=args.on_death)
    world = World(cfg, seed=args.seed)
    print(world.observe())
    while not world.done:
        try:
            line = input("\n> ").strip()
        except EOFError:
            break
        if line in ("quit", "exit", "q"):
            break
        if line in ("help", "?"):
            print(__doc__)
        elif line == "obs":
            print(world.observe())
        elif line == "hash":
            print(world.state_hash())
        elif line == "valid":
            for a in world.valid_actions():
                print(json.dumps(a))
        elif line:
            world.step(parse_action(line))
            print(world.observe())


if __name__ == "__main__":
    main()
