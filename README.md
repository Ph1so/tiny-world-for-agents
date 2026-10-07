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
