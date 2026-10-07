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

## LLM agent

The agent is a controller for the same run loop. It gets the fixed system prompt from `PLAN.md` section 7, and each step its memory file, the last K action/result pairs, and the observation. Model entries (provider, id, prices, thinking settings) live in `configs/models.yaml`. Keys go in `.env` (copy `.env.example`).

```
uv run python -m tinyworld.runner.run --controller llm --model mock --memory-chars 2000 --history-window 3 --max-steps 200 --run-id mock_demo
uv run python -m tinyworld.runner.run --controller llm --model sonnet --memory-chars 2000 --history-window 3 --max-steps 200 --run-id sonnet_demo
uv run python -m tinyworld.runner.run --run-config configs/run.yaml                        # same keys from a file, flags win
uv run python -m tinyworld.runner.run --run-config configs/run.yaml --resume                # continue from the last complete step
```

The first command needs no network: `mock` is the sensible bot wrapped in the reply format, with memory edits, a few over limit edits and a few unreadable replies thrown in. The second is the M4 acceptance check with a real model; it needs `ANTHROPIC_API_KEY` in `.env` and costs a few cents. Swap `sonnet` for any entry in `configs/models.yaml` (`haiku`, `opus`, `gpt54_mini`, `ollama_example`, ...). `--memory-chars 0` turns the memory file off. Prices in `models.yaml` were not checked against the official pricing pages, see `docs/DECISIONS.md` 74.

## Experiments

Sweeps run every combination of a yaml config in `configs/sweeps/` and put the runs in `runs/<sweep>/`.

```
uv run python -m tinyworld.runner.sweep configs/sweeps/smoke.yaml --yes    # both bots, 2 seeds, 200 steps, no cost
uv run python -m tinyworld.runner.sweep configs/sweeps/mock.yaml --yes     # 2 mock models x 2 memory sizes x 2 seeds, no network
uv run python -m tinyworld.runner.sweep configs/sweeps/memory_sweep.yaml   # the llm sweep from PLAN.md, asks first
uv run python -m tinyworld.analysis.metrics runs/<sweep>/<run>             # summary.json for one run
uv run python -m tinyworld.analysis.report runs/<sweep>                    # report.html for a sweep
uv run python -m tinyworld.server --runs runs/<sweep>                      # serve the sweep to the viewer
```

The sweep runner prints the run count and a cost estimate and waits for a yes (skip with `--yes`, look only with `--dry-run`). It stops cleanly at `budget_usd` and can be started again: runs with a `summary.json` are skipped and cut-off runs continue from their last complete step. `sweep_status.json` in the sweep folder shows what ran and what was spent. The report is written at the end of every sweep and links each run to the viewer.

## Viewer

The viewer replays run folders and follows live runs. Build it once, then one server serves the API and the page.

```
cd viewer && npm install && npm run build && cd ..
uv run python -m tinyworld.server --runs runs --runs samples --runs viewer/fixtures --port 8000
```

Open `http://127.0.0.1:8000/` for the run picker, `/?run=<run_id>` to replay, `/?run=<run_id>&live=1` to follow a run that is still being written, and `/compare?a=<run>&b=<run>` for two runs side by side. For development run the server as above and `cd viewer && npm run dev`, which serves the page on port 5173 and proxies `/api` and `/ws` to port 8000. Details, keys and fixtures are in `viewer/README.md`. Screenshots are in `docs/screenshots/`.
