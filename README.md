# Tiny World

A small voxel sandbox with no goal, and an LLM agent that lives in it with a size-limited memory file.

See `PLAN.md` for the build plan and `docs/INTERFACES.md` for the data formats. Build status is tracked in `docs/STATUS.md`.

## Run it

```
uv sync
uv run pytest                                             # all tests
uv run python -m tinyworld.sim.cli --seed 1               # play by hand (try: move north 3, mine 31 13 23, valid, quit)
uv run python -m tinyworld.runner.run --controller sensible_bot --seed 1 --max-steps 1500 --run-id demo
```

Add `--names alien --shuffle-recipes` to either command for alien mode. Runs go to `runs/<run_id>/`. Two sample runs are in `samples/`. Choices made along the way are in `docs/DECISIONS.md`.

## Experiments

Sweeps run every combination of a yaml config in `configs/sweeps/` and put the runs in `runs/<sweep>/`.

```
uv run python -m tinyworld.runner.sweep configs/sweeps/smoke.yaml --yes    # both bots, 2 seeds, 200 steps, no cost
uv run python -m tinyworld.runner.sweep configs/sweeps/memory_sweep.yaml   # the llm sweep from PLAN.md, asks first
uv run python -m tinyworld.analysis.metrics runs/<sweep>/<run>             # summary.json for one run
uv run python -m tinyworld.analysis.report runs/<sweep>                    # report.html for a sweep
uv run python -m tinyworld.server --runs runs/<sweep>                      # serve the sweep to the viewer
```

The sweep runner prints the run count and a cost estimate and waits for a yes (skip with `--yes`, look only with `--dry-run`). It stops cleanly at `budget_usd` and can be started again: runs with a `summary.json` are skipped and cut-off runs continue from their last complete step. `sweep_status.json` in the sweep folder shows what ran and what was spent. The report is written at the end of every sweep and links each run to the viewer.
