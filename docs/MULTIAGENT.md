# Multi-agent, real-time world: design notes

Status: built (DECISIONS 112). `tinyworld/sim/body.py`, `tinyworld/sim/engine.py`,
`tinyworld/runner/multi.py`, viewer `scene/others.ts`. The goal: the world runs on its own
clock, and several agents act in it independently and in parallel, each at the speed its model
thinks.

    python -m tinyworld.runner.multi --run-id duo --agents 2 --model haiku --max-steps 1200
    python -m tinyworld.runner.multi --run-id mix --agents 1 --bots 2 --clock lockstep

Choices made while building (the open questions below):
- `tick_ms` 1000 by default, fixed. Lockstep (`--clock lockstep`) for fair comparisons.
- Bodies block each other; two agents walking into each other swap.
- Agents can attack each other from the start. `pvp_loot` (off) gives the killer the victim's items.
- Separate memory files. An optional `persona` per agent in a `--spec` yaml.
- An agent observes only once its action has finished, then thinks while its body stands
  still, so nothing is ever cut short in practice (the engine supports it for later).
- Not built yet: offers/accept trades, resuming a stopped multi-agent run, picking which agent
  the viewer follows (it follows the first).

## 1. The core shape: one writer, many proposers

- **The world loop is the only thing that changes world state.** It is single-threaded and
  ticks on a clock (`tick_ms`, for example 500 ms per world step).
- **Agents never touch state.** Each agent is an async task:
  observe → call the model → submit an action → wait for the result → repeat.
  A submitted action goes into that agent's inbox. The world picks it up at the next tick.
- Because there is a single writer, there are no data races and no locks. Every "race"
  that remains is a *game* conflict: two agents want the same thing in the same tick. Those are
  settled by explicit, logged rules (section 3), which is the useful kind of problem.

```
 agent A task ──submit──▶ inbox A ─┐
 agent B task ──submit──▶ inbox B ─┼─▶ world loop: every tick
 agent C task ──submit──▶ inbox C ─┘     1. take new actions from the inboxes
                                         2. advance each agent's current activity one tick (random order)
                                         3. creatures, weather, crops, vitals
                                         4. resolve damage and deaths together
                                         5. log the tick; wake agents whose activity finished
```

## 2. Actions become activities that run over ticks

Today an action is a loop that ticks the world itself (`_move` walks up to 8 cells, calling
`_tick` each time). With a shared clock, an action must instead be an **activity**: something
that does one tick's worth of work each time the world ticks.

The cheapest refactor is to turn each handler into a **generator** that `yield`s where it now
calls `self._tick()`. The world loop then calls `next()` on each agent's activity once per tick.
Most of the existing handler code stays as it is.

- **The body keeps working while the model thinks.** A `move 8` or a 6-step `mine` goes on
  while the next call is in flight. This pipelining is what makes real time work at all.
- **Idle when nothing is queued.** If an activity ends and no new action has arrived, the body
  stands still (an implicit wait). How much an agent idles is a measurement in itself.
- **A new action arriving mid-activity preempts it** at the next tick. The result says "The
  move was cut short after 3 cells." Policy: latest wins, at most one action pending per agent.
- **Stale observations are expected.** The model decided on what it saw at tick t₀, and the
  action lands at t₁. Everything is checked again when the action is applied ("Nothing is
  there.", "No creature #4 within reach."). The result should also give the tick it was applied
  at, so the agent can tell its picture was out of date.

## 3. Conflicts within one tick

Each tick, agents are applied in a **seeded random order** (reshuffled every tick, so no agent
always goes first). Then:

| Conflict | Rule |
|---|---|
| Two agents mine the same block | Mining progress is per (agent, block). The first to finish takes the block. The other gets "Nothing is there." and loses its progress. |
| Two agents step into the same cell | The first in order wins. The other is "Blocked by agent #2." |
| Two agents step into each other's cells | They swap. Otherwise two agents in a 1-wide tunnel are stuck forever. |
| Placing a block where an agent stands | Refused ("The cell is not empty."), as for creatures now. |
| Chest store/take at the same time | Each action is atomic, applied in order. The second sees the updated contents. Fighting over the last iron is a real outcome. |
| `give` | Atomic: taken from the giver and added to the receiver only if the receiver is within reach *and* it fits, otherwise nothing happens. |
| Trades | Two phases with an **expiry**: `offer {to, give, want, ticks}` creates a pending offer; `accept {offer_id}` runs both transfers atomically if both sides still hold the items. Offers lapse after `ticks`, so nothing is ever locked. |
| Agents hitting each other | Damage is collected during the tick and applied at the end, so mutual attacks land together and both agents can die. Turn order gives no edge. |
| Zombies | Chase the nearest agent. Hits go through the same end-of-tick damage step. |

## 4. Deadlocks and stalls

There are no locks, so the classic kind can't happen: the world never waits on an agent. What can happen:

- **Model or API stalls.** Each call has a timeout (60 s), retries with backoff, and a shared
  token bucket across agents to respect rate limits. A stalled agent's body idles; the world goes on.
- **Bodies blocking each other.** Swapping solves face-offs in a tunnel. The existing
  `trapped()` check gets an "agents count as walls" variant so a trapped agent can be logged.
- **Agents waiting on each other** (A waits for B's iron, B waits for A's wood). That is
  emergent behaviour, not a bug. Don't prevent it; detect it (both idle with open offers) and log it.
- **Crash or restart.** Save a world checkpoint every N ticks, plus the action log, and resume
  from both.

## 5. Determinism

When an action arrives depends on API latency, so the same seed won't reproduce a run.
Reproducibility comes from the **action log** instead: every applied action is logged with its
tick, and a replay feeds the log back in, which matches the existing replay contract. For
controlled experiments, keep a **lockstep mode** (`clock: lockstep`). In it, each tick waits
for every agent that is between actions, with a timeout. That gives turn-based, seed-reproducible
runs and fair comparisons between models.

## 6. Time, speed and fairness

- A faster model acts more often. In real time that is part of the experiment ("thinking costs
  time"), but it confounds model comparisons, so use lockstep for those.
- Rough numbers for Haiku: about 3 s per call. With `tick_ms` = 1000 an agent acts every 3 to 4
  ticks, a day of 300 ticks is 5 minutes, and 2400 ticks is about 40 minutes. Cost per agent is
  about what one run costs now, times the number of agents.
- Shared day and night. Sleep skips the night only if every agent is asleep (the Minecraft rule).
  Otherwise it is resting in place until dawn.

## 7. Seeing and talking

- Other agents appear in observations like creatures, as "agent #2 (Ada) at (x,y,z)", maybe
  with what they hold.
- `say {"text": "..."}`: heard by agents within `hear_radius` cells, in their next observation:
  "agent #2 at (x,y,z) said: ...". Messages pile up while an agent is thinking; keep the last N.
- `give`, `offer`, `accept` as in section 3. Chests are shared by default. Ownership (locks)
  can come later, to see whether theft or sharing appears.

## 8. Build order

1. **Bodies.** Move agent state (pos, inv, tools, vitals, bed, made, notices) out of `World` into
   `Agent` objects. Keep a single-agent wrapper so every existing test, bot and run still works.
2. **Activities.** Turn the handlers into generators. In single-agent mode, step them back to back
   so behaviour is identical (the tests prove it).
3. **Clock and loop.** The tick loop, inboxes, random apply order, end-of-tick damage, lockstep mode.
4. **Runner.** One async task per agent, async model client, per-agent `steps`/`memory` files,
   and a `world.jsonl` with an `agents` list.
5. **Viewer.** Several agents, speech bubbles, and a per-agent panel.
6. **Social actions.** `say`, `give`, `offer`/`accept`, then experiments: 2 to 3 plain agents first,
   then personalities and roles as variables.

## Open questions

- `tick_ms`: fixed, or scaled to the slowest model?
- Bodies block each other (enables guarding a door, needs swapping), or pass through (simpler)?
- Can agents attack each other from the start, or only later?
- Separate or shared memory files? (Separate. A shared one is its own experiment.)
