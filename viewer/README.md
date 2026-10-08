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

## Run control

The picker has a "new run" form (LLM agent with any model in `configs/models.yaml`, or a bot with
a step delay; memory size, world steps, seed, normal or hard world, run id). Starting a run opens
it live. In a run view, while the run is not finished, the transport bar shows its state and
pause / resume / stop buttons. These control the runner process, not playback: pause waits
before the next agent step, stop ends it after the current step without a summary so it can be
resumed later. Stopped runs also have a resume button in the picker. The action chip says
"run paused" or "run stopped" when live playback catches up. See "Run control" in
`docs/INTERFACES.md` for the endpoints and the control files.

## Panels

- Status: run id, controller, model, day, world step, step within the day, light, agent step,
  vitals bars, inventory with tool uses left and slots used (when the world limits them), and
  every chest with what it holds at this step.
- Agent: thought, action, result, and the observation exactly as logged for the current agent step.
- Memory: the file after the current agent step with a usage bar. The last edit is shown as a diff
  against the version before it (additions green, removals red, word level inside changed lines).
  A rejected edit shows the unchanged file and the ops that were refused.
- Memory timeline: characters used over agent steps, a green dot per accepted edit, a red cross per
  rejected one, the limit as a dashed line. Click a mark to scrub to that step.
- Events: the feed from `events.jsonl`. Click a row to scrub to it. Future events are faded.

Scrubbing to world step `t` shows agent step `i` of the world line at `t`, its observation (taken
at `t_start`), and the memory file after that step's ops.

## Action animations

The agent is animated for the action in progress, read from `steps.jsonl`: legs and arms swing
when walking, it chops with its pickaxe at the block it mines (cracks spread over the block as the
steps pass, chips fly, the block bursts and the item flies to the agent), reaches out to place
(an outline settles on the new block), works with both hands to craft (sparkles on success),
lifts food to its mouth to eat, and swings at a creature it attacks. With chests it reaches into
the chest it stores in or takes from (the lid opens toward it, item cubes fly in or out), and a
drop scatters the items at its feet. It turns to face what it
works on, and POV looks at that block. A hurt flashes the agent red.

A chip at the top left of the stage says what the agent is doing, with a bar for actions that
take several world steps and the result once done. Results also float up over the agent
("+1 log", "✖ blocked"). In live mode, while the model is still answering, the chip says
"thinking…" and the agent rests a hand on its chin. Effects only fire when playback moves forward
a few steps at a time, so scrubbing does not set them off. Short actions hold their pose for a
moment so they can be seen at high speeds.

Code: `src/scene/action.ts` (which action is on screen, labels), `src/scene/agent.ts` (jointed
agent and poses), `src/scene/fx.ts` (particles, cracks, outlines, flying items, floating text).

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
