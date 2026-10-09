# Tiny World

A small voxel sandbox with no goal, and an LLM agent that lives in it with a size-limited memory file.

`PLAN.md` is the build plan, `docs/INTERFACES.md` the data formats, `docs/STATUS.md` the honest state of each milestone and what to run first, `docs/DECISIONS.md` the choices made along the way.

## Install and test

```
uv sync                                   # Python 3.11+, all deps
cd viewer && npm install && npm run build && cd ..
uv run pytest -q                          # about 90 s, no network
```

## Play, bots, agent

```
uv run python -m tinyworld.sim.cli --seed 1                                      # type actions by hand (help, move north 3, mine 31 13 23, valid, quit)
uv run python -m tinyworld.runner.run --controller sensible_bot --seed 1 --max-steps 1500 --run-id demo
uv run python -m tinyworld.runner.run --controller llm --model mock --memory-chars 2000 --max-steps 200 --run-id mock_demo   # no network
uv run python -m tinyworld.runner.run --controller llm --model haiku --memory-chars 2000 --max-steps 200 --run-id haiku_demo # real model, a few cents
uv run python -m tinyworld.runner.run --run-config configs/run.yaml [--resume]     # same flags from a file; --resume continues from the last complete step
```

Runs go to `runs/<run_id>/` (six files, see `docs/INTERFACES.md`). Add `--names alien --shuffle-recipes` for alien mode, `--memory-chars 0` to turn the memory file off, `--step-delay 0.3` to slow a bot down so you can watch it live. Model entries (provider, id, prices, thinking) are in `configs/models.yaml`; every entry says whether its price was verified. Keys go in `.env` (copy `.env.example`). `mock` is the sensible bot wrapped in the reply format with memory edits, over-limit edits and unreadable replies thrown in.

## Viewer

```
uv run python -m tinyworld.server --runs runs --runs samples --runs viewer/fixtures --port 8000
```

Open `http://127.0.0.1:8000/` for the run picker (with a "new run" form, and resume for stopped runs), `/?run=<id>` to replay, `/?run=<id>&live=1` to follow a run in progress, `/compare?a=<id>&b=<id>` for two runs side by side. Keys: space, arrows, `e` next event, `m` next memory edit. While a run is going, the bar under the stage pauses, resumes or stops the run itself (not just playback); `--read-only` turns that off. More in `viewer/README.md`; screenshots in `docs/screenshots/`.

## Long-term memory across runs (lineages)

The memory file holds this world (places, plans) and starts empty every run. A long-term file
holds what the agent learned about the game and carries over: each run in a lineage starts from
the file the previous run left, edits it with a `"longterm"` field in its replies, and gets one
last call at the end of the run to edit it before it is saved back to `lineages/<name>/`.

```
uv run python -m tinyworld.runner.run --controller llm --model haiku --lineage haiku_a --longterm-chars 800 --max-steps 300
uv run python -m tinyworld.runner.lineage --lineage haiku_a --model haiku --generations 5     # back to back, seed+1 each
uv run python -m tinyworld.analysis.lineage_report haiku_a [--text]                          # generation by generation
```

The viewer shows the long-term file above the memory panel, and the new run form takes a
lineage. A lineage only runs one generation at a time; an unfinished one holds it until it is
resumed to the end. Off by default, so other runs and their prompts are unchanged.

## Planning (a plan the agent writes when it chooses to)

Off by default. With `planning: action` an agent has a plan slot (a goal and steps, shown every
step) and a `plan` action that costs a turn and asks for the plan in a separate reply. With
`planning: triggers` the plan can also carry conditions the agent sets itself
(`"replan_when": ["steps_since_plan >= 50"]`), and it is asked for a new plan when one turns true.
The harness never decides when to plan or what about (DECISIONS 125).

```
uv run python -m tinyworld.runner.run --controller llm --model haiku --memory-chars 2000 --planning triggers --max-steps 300 --run-id haiku_plan
# multi: add `planning: action` or `planning: triggers` to an agent line in the spec
```

Planning turns are in steps.jsonl under `plan`; summary.json of a multi run has `plans_written` per agent.

## Sweeps and report

```
uv run python -m tinyworld.runner.sweep configs/sweeps/mock.yaml --yes          # 2 mock models x 2 memory sizes x 2 seeds, no network
uv run python -m tinyworld.runner.sweep configs/sweeps/first_real.yaml          # haiku, 2 memory sizes, 2 seeds, 300 steps, budget $2
uv run python -m tinyworld.runner.sweep configs/sweeps/memory_sweep.yaml        # the PLAN.md sweep, stops at budget_usd
uv run python -m tinyworld.analysis.report runs/<sweep>                        # report.html (written at the end of every sweep too)
uv run python -m tinyworld.server --runs runs/<sweep>                          # serve a sweep to the viewer
```

The sweep runner prints the run count and a cost estimate and waits for a yes (`--yes` skips, `--dry-run` only prints). It stops cleanly at `budget_usd`. Run it again to resume: finished runs (with `summary.json`) are skipped, cut-off runs continue.
