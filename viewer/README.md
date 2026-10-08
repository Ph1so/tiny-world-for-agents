# Viewer

A Three.js app that replays run folders and follows live runs. It reads only the files in
`docs/INTERFACES.md`, served by `tinyworld.server`.

## Run it

Built (one process serves the API and the viewer):

```
cd viewer && npm install && npm run build && cd ..
uv run python -m tinyworld.server --runs runs --runs samples --runs viewer/fixtures --port 8000
# open http://127.0.0.1:8000/
```

Development (Vite with hot reload, API calls are proxied to the Python server on port 8000):

```
uv run python -m tinyworld.server --runs runs --runs samples --runs viewer/fixtures --port 8000
cd viewer && npm run dev      # open http://127.0.0.1:5173/
```

`--runs` can be given several times. The first directory that holds a run id wins.

## Routes

| URL | What |
|---|---|
| `/` | run picker |
| `/?run=ID` | replay |
| `/?run=ID&live=1` | live mode, websocket, follows the newest step |
| `/compare?a=ID&b=ID` | two runs side by side, one scrubber |

Extra query keys: `t=STEP` starts paused at that world step, `cam=orbit|follow|map|pov` (pov is first person at eye height, facing the last move, with fog at the run's `view_radius`), `names=both`
turns the alien name toggle on, `debug=1` shows draw calls and triangles.

Keys: space play/pause, left/right one step (shift for 50), `e` next event, `m` next memory edit.
Drag to orbit, wheel to zoom, right drag to pan.

## Panels

- Status: run id, controller, model, day, world step, step within the day, light, agent step,
  vitals bars, inventory with tool uses left.
- Agent: thought, action, result, and the observation exactly as logged for the current agent step.
- Memory: the file after the current agent step with a usage bar. The last edit is shown as a diff
  against the version before it (additions green, removals red, word level inside changed lines).
  A rejected edit shows the unchanged file and the ops that were refused.
- Memory timeline: characters used over agent steps, a green dot per accepted edit, a red cross per
  rejected one, the limit as a dashed line. Click a mark to scrub to that step.
- Events: the feed from `events.jsonl`. Click a row to scrub to it. Future events are faded.

Scrubbing to world step `t` shows agent step `i` of the world line at `t`, its observation (taken
at `t_start`), and the memory file after that step's ops.

## Recording

The record button captures the canvas with `MediaRecorder` and downloads a `.webm` when stopped.
The log files are the real recording; this is for sharing clips.

## Fixtures

`fixtures/memdemo` and `fixtures/aliendemo` are small bot runs with scripted memory edits (append,
replace, rewrite, and a few rejected edits) and placed torches, for testing the memory panel and
the alien name toggle. Regenerate with `uv run python viewer/fixtures/make_memdemo.py`.

## Screenshots

With the server running on port 8000 and the viewer built:

```
node scripts/screenshot.mjs "http://127.0.0.1:8000/?run=sensible_seed1&t=700" ../docs/screenshots/viewer.png
node scripts/screenshot.mjs "http://127.0.0.1:8000/?run=memdemo&t=93" ../docs/screenshots/memory.png 1500 900 ".panel.memory"
```

Uses the Chromium that Playwright already installed (`PLAYWRIGHT_BROWSERS_PATH`) or `CHROME_PATH`.

## How it is built

- `src/data/run.ts` is the one data model. Replay (`loadReplay`) and live (`connectLive`) both
  feed it the same lines. The block grid is moved to any step by replaying deltas from the
  snapshot; going backwards resets and rolls forward, which is cheap because block changes are rare.
- `src/scene/terrain.ts` builds 16 x 32 x 16 chunks as merged meshes (one opaque, one water per
  chunk) with hidden faces removed. Only chunks touched by a change are rebuilt.
- `src/scene/creatures.ts` builds each creature kind as one vertex coloured geometry and draws all
  of a kind with one `InstancedMesh`. The agent is one mesh.
- The whole 64 x 32 x 64 world is about 45 to 55 draw calls and 100 to 170 k triangles. The frame
  loop allocates nothing: positions are interpolated into reused vectors and instance matrices.
