"""Run several generations of one lineage back to back.

    python -m tinyworld.runner.lineage --lineage haiku_a --model haiku --generations 5 --max-steps 300
    python -m tinyworld.runner.lineage --lineage haiku_a --model haiku --generations 3 --same-seed

Each generation is a normal run (runs/<lineage>_g<N>) that starts from the long-term file the
previous one left. Seeds go seed, seed+1, ... so every generation meets a new world, unless
--same-seed keeps the world fixed (then any gain can come from remembered places too, not only
from lessons). An unfinished generation is resumed first. Stops at the first error.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from tinyworld.agent.lineage import Lineage
from tinyworld.runner.run import resolve_world_path, run
from tinyworld.sim import load_world_config


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Run generations of a lineage, each handing its long-term file on.")
    ap.add_argument("--lineage", required=True)
    ap.add_argument("--model", required=True, help="entry name in configs/models.yaml")
    ap.add_argument("--generations", type=int, default=3, help="how many more generations to run")
    ap.add_argument("--max-steps", type=int, default=300, help="world steps per generation")
    ap.add_argument("--seed", type=int, default=1, help="seed of the first new generation")
    ap.add_argument("--same-seed", action="store_true", help="every generation gets the same world")
    ap.add_argument("--memory-chars", type=int, default=2000)
    ap.add_argument("--longterm-chars", type=int, default=None,
                    help="long-term file limit, default the lineage's last one, or 800 for a new lineage")
    ap.add_argument("--history-window", type=int, default=3)
    ap.add_argument("--config", default=None, help="world yaml or name, e.g. world_hard")
    ap.add_argument("--runs-dir", default="runs")
    ap.add_argument("--lineages-dir", default=None)
    args = ap.parse_args(argv)

    lin = Lineage(args.lineage, args.lineages_dir)
    if args.longterm_chars is None:
        past = [h.get("longterm_chars") for h in lin.history() if h.get("longterm_chars")]
        args.longterm_chars = past[-1] if past else 800
    held = lin.holder()
    if held:
        print(f"resuming unfinished generation {held['run_id']}")
        run_dir = Path(held["run_dir"])
        run(run_dir.name, "llm", max_steps=0, runs_dir=run_dir.parent, resume=True)

    cfg = load_world_config(resolve_world_path(args.config))
    for k in range(args.generations):
        gen = lin.next_generation
        seed = args.seed if args.same_seed else args.seed + k
        run_id = f"{args.lineage}_g{gen}"
        extra = {"model": args.model, "memory_chars": args.memory_chars, "history_window": args.history_window,
                 "longterm_chars": args.longterm_chars, "lineage": args.lineage, "lineages_dir": args.lineages_dir}
        world = run(run_id, "llm", seed, args.max_steps, cfg, args.runs_dir, extra_config=extra)
        h = lin.history()[-1]
        print(f"generation {gen} ({run_id}, seed {seed}): world steps {world.t}, deaths {world.deaths}, "
              f"crafted {len(world.firsts['craft'])}, long-term {h['start_chars']} -> {h['end_chars']} chars, "
              f"${h.get('cost_usd_total', 0):.3f}")
    print(f"\nlong-term file of {args.lineage} now:\n{lin.text()}")


if __name__ == "__main__":
    main()
