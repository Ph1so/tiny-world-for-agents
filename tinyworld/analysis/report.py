"""One self-contained report.html for a sweep folder.

    python -m tinyworld.analysis.report runs/<sweep> [--out runs/<sweep>/report.html] [--viewer http://localhost:8000]

Reads every <sweep>/<run>/summary.json (written by tinyworld.analysis.metrics; runs without one are
computed on the fly) plus steps.jsonl and events.jsonl for the over-time charts. Charts:

    1. every metric by model and memory size, mean over seeds with the spread (bars, std error bars,
       one dot per seed)
    2. activity share over time per condition (stacked areas, 100 world step bins)
    3. memory size over time per condition
    4. survival: share of runs with no death yet, over world steps
    5. a table with one row per run and a link to its replay in the viewer

Colour rules follow the dataviz skill: a fixed categorical order for models and for actions,
a single blue ramp for memory sizes (an ordered quantity), text never in a series colour.
"""
from __future__ import annotations

import argparse
import html
import json
import sys
import warnings
from pathlib import Path
from urllib.parse import quote

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from tinyworld.analysis.metrics import ACTIONS, compute_metrics
from tinyworld.analysis.replay import read_jsonl

VIEWER_URL = "http://localhost:8000"
TIME_BIN = 100                      # world steps per bin in the over-time charts, for runs of 1500 steps or more


def time_bin(max_t: int) -> int:
    """Bin width for the over-time charts: TIME_BIN for long runs, else about 15 bins (a 200 step
    run gets 10 step bins). Always a multiple of 10 so the tick labels stay round."""
    return max(10, min(TIME_BIN, int(round(max_t / 15 / 10)) * 10))

# Palette from the dataviz skill (references/palette.md), light mode.
CATEGORICAL = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948", "#8a5a2b", "#5f6b7a", "#0f9bb0", "#b8409a"]
SEQUENTIAL = ["#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#104281", "#0d366b"]   # ordinal, steps 250..700
SURFACE, PAGE = "#fcfcfb", "#f9f9f7"
INK, INK2, MUTED, GRID, AXIS = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'

# (key, title, caption) for chart 1. Shown in this order, only the ones present in the summaries.
METRICS = [
    ("deaths", "Deaths", "How many times the agent died in the run. Lower means it kept itself alive."),
    ("life_steps_mean", "Steps survived per life", "World steps between deaths, averaged over the lives in a run."),
    ("recipes_found", "Recipes found", "Distinct items crafted at least once. 13 is every recipe in the game."),
    ("blocks_mined_distinct", "Distinct blocks mined", "How many kinds of block were broken at least once."),
    ("deepest_tool_tier", "Deepest tool tier", "0 none, 1 wood, 2 stone, 3 iron. Which tools it managed to make."),
    ("craft_fails", "Failed craft attempts", "Craft actions that made nothing. Trying combinations costs steps."),
    ("cells_visited", "Map cells visited", "Distinct (x, z) columns the agent stood on. A measure of exploration."),
    ("blocks_placed", "Blocks placed", "How many blocks the agent put down."),
    ("largest_placed_group", "Largest built structure", "Largest group of placed blocks that touch face to face."),
    ("night_enclosed_share", "Night steps enclosed", "Share of night steps spent walled in on all sides with a roof."),
    ("night_torch_share", "Night steps near a torch", "Share of night steps in the open but within torch light."),
    ("night_open_share", "Night steps in the open", "Share of night steps with no walls and no torch nearby."),
    ("longest_same_action_streak", "Longest same action streak", "Most agent steps in a row with the same action name. High means looping."),
    ("action_entropy_50", "Action entropy", "Mean entropy in bits of action names over a sliding window of 50 agent steps. Low means repetitive."),
    ("invalid_actions", "Invalid actions", "Actions the world refused (bad arguments, missing items)."),
    ("unreadable_replies", "Unreadable replies", "Replies that could not be parsed. Each one costs a step of waiting."),
    ("memory_chars_mean", "Memory characters used", "Mean size of the memory file over the run."),
    ("memory_edits", "Memory edits", "Steps with an accepted memory edit."),
    ("memory_rejected", "Rejected memory edits", "Edits that would have gone over the limit."),
    ("memory_chars_changed_per_step", "Memory characters changed per step", "How much of the file changed each agent step, on average."),
    ("memory_line_survival_mean", "Memory line survival", "Agent steps a memory line lasted before it was changed or removed (lines that died)."),
    ("memory_lines_created", "Memory lines written", "Distinct lines that ever appeared in the memory file."),
    ("tokens_total", "Tokens", "Input plus output tokens over the run."),
    ("cost_usd_total", "Cost (USD)", "Dollars spent on model calls."),
    ("wall_clock_s", "Wall clock (s)", "Seconds the run took."),
    ("agent_steps", "Agent steps", "Model calls or bot decisions. One agent step can move the world several steps."),
]


# ---------------------------------------------------------------- loading


def load_summaries(sweep_dir: Path) -> pd.DataFrame:
    rows = []
    for d in sorted(p for p in sweep_dir.iterdir() if p.is_dir()):
        if not (d / "config.yaml").exists():
            continue
        p = d / "summary.json"
        try:
            s = json.loads(p.read_text()) if p.exists() else compute_metrics(d)
        except Exception as exc:         # one bad folder should not block the report
            print(f"skip {d}: {exc}", file=sys.stderr)
            continue
        s["_dir"] = str(d)
        s["_name"] = d.name
        rows.append(s)
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["model"] = df["model"].where(df["model"].notna(), df["controller"]).astype(str)
    df["memory_chars"] = df["memory_chars"].fillna(0).astype(int)
    df["history_window"] = df["history_window"].fillna(0).astype(int)
    df["condition"] = df["model"] + " / m" + df["memory_chars"].astype(str)
    if df["history_window"].nunique() > 1:
        df["condition"] += " / k" + df["history_window"].astype(str)
    return df


def model_colors(models: list[str]) -> dict[str, str]:
    return {m: CATEGORICAL[i % len(CATEGORICAL)] for i, m in enumerate(models)}


def memory_colors(sizes: list[int]) -> dict[int, str]:
    sizes = sorted(sizes)
    if len(sizes) == 1:
        return {sizes[0]: SEQUENTIAL[2]}
    idx = np.linspace(0, len(SEQUENTIAL) - 1, len(sizes)).round().astype(int)
    return {s: SEQUENTIAL[i] for s, i in zip(sizes, idx)}


def base_layout(**kw) -> dict:
    lay = dict(paper_bgcolor=SURFACE, plot_bgcolor=SURFACE, font=dict(family=FONT, color=INK2, size=12),
               margin=dict(l=48, r=16, t=44, b=48), hovermode="closest",
               # Top right, on the title line, so it never sits on the x axis title.
               legend=dict(orientation="h", y=1.0, yanchor="bottom", x=1, xanchor="right", font=dict(color=INK2)),
               xaxis=dict(gridcolor=GRID, zerolinecolor=AXIS, linecolor=AXIS, tickfont=dict(color=MUTED)),
               yaxis=dict(gridcolor=GRID, zerolinecolor=AXIS, linecolor=AXIS, tickfont=dict(color=MUTED)))
    lay.update(kw)
    return lay


def style_axes(fig: go.Figure) -> None:
    fig.update_xaxes(gridcolor=GRID, zerolinecolor=AXIS, linecolor=AXIS, tickfont=dict(color=MUTED), showline=True)
    fig.update_yaxes(gridcolor=GRID, zerolinecolor=AXIS, linecolor=AXIS, tickfont=dict(color=MUTED))


# ---------------------------------------------------------------- chart 1: metrics


def metric_figure(df: pd.DataFrame, key: str, title: str, colors: dict[str, str]) -> go.Figure:
    """Grouped bars (mean over seeds) with std error bars and one dot per seed, on a numeric x axis
    so the dots can sit on their own bar."""
    models = list(colors)
    mems = sorted(df["memory_chars"].unique())
    xcats = [f"{m:,}" for m in mems]
    fig = go.Figure()
    n = len(models)
    width = min(0.8 / n, 0.3)
    for j, model in enumerate(models):
        sub = df[df["model"] == model]
        offset = (j - (n - 1) / 2) * width
        xs, means, stds, px, py, pt = [], [], [], [], [], []
        for mi, m in enumerate(mems):
            rows = sub[sub["memory_chars"] == m]
            vals = pd.to_numeric(rows[key], errors="coerce").dropna()
            if vals.empty:
                continue
            xs.append(mi + offset)
            means.append(float(vals.mean()))
            stds.append(float(vals.std(ddof=0)) if len(vals) > 1 else 0.0)
            for seed, v in zip(rows.loc[vals.index, "seed"], vals):
                px.append(mi + offset)
                py.append(float(v))
                pt.append(f"{model}, memory {xcats[mi]}, seed {seed}")
        if not xs:
            continue
        fig.add_bar(name=model, x=xs, y=means, width=width - 0.04, legendgroup=model,
                    marker=dict(color=colors[model], line=dict(width=0)),
                    error_y=dict(type="data", array=stds, visible=True, color=INK2, thickness=1, width=4),
                    customdata=[xcats[mems.index(m)] for m in mems if not sub[sub["memory_chars"] == m].empty],
                    hovertemplate=f"{model}<br>memory %{{customdata}}<br>mean %{{y:.3g}} ± %{{error_y.array:.2g}}<extra></extra>")
        fig.add_scatter(name=f"{model} seeds", x=px, y=py, mode="markers", showlegend=False, legendgroup=model,
                        marker=dict(color=colors[model], size=8, line=dict(color=SURFACE, width=2)),
                        text=pt, hovertemplate="%{text}: %{y:.3g}<extra></extra>")
    fig.update_layout(**base_layout(title=dict(text=title, font=dict(color=INK, size=14), x=0, xanchor="left"),
                                    barmode="overlay", height=300, showlegend=len(models) > 1))
    fig.update_xaxes(title=dict(text="memory characters", font=dict(color=MUTED)), tickmode="array",
                     tickvals=list(range(len(xcats))), ticktext=xcats, range=[-0.6, len(xcats) - 0.4],
                     zeroline=False)   # x is categorical in spirit, a line at "0" means nothing
    fig.update_yaxes(rangemode="tozero")
    style_axes(fig)
    return fig


# ---------------------------------------------------------------- over-time data


def activity_over_time(run_dir: Path, max_t: int, tb: int = TIME_BIN) -> np.ndarray:
    """Share of world steps per action per bin of tb world steps. Shape (bins, len(ACTIONS))."""
    steps = read_jsonl(run_dir / "steps.jsonl")
    nb = max(1, int(np.ceil(max_t / tb)))
    counts = np.zeros((nb, len(ACTIONS)))
    for s in steps:
        name = (s.get("action") or {}).get("name")
        if name not in ACTIONS:
            continue
        a = ACTIONS.index(name)
        for t in range(s["t_start"], max(s["t_end"], s["t_start"] + 1)):
            b = min(t // tb, nb - 1)
            counts[b, a] += 1
    tot = counts.sum(axis=1, keepdims=True)
    return np.divide(counts, tot, out=np.full_like(counts, np.nan), where=tot > 0)


def memory_over_time(run_dir: Path, max_t: int, tb: int = TIME_BIN) -> np.ndarray:
    """Memory characters used at the end of each bin of tb world steps (last value seen, carried forward)."""
    steps = read_jsonl(run_dir / "steps.jsonl")
    nb = max(1, int(np.ceil(max_t / tb)))
    out = np.full(nb, np.nan)
    last = 0.0
    for s in steps:
        last = float(s.get("memory_chars_used") or 0)
        out[min(s["t_end"] // tb, nb - 1)] = last
    for b in range(1, nb):
        if np.isnan(out[b]):
            out[b] = out[b - 1]
    return out


def first_death(run_dir: Path) -> int | None:
    for e in read_jsonl(run_dir / "events.jsonl"):
        if e.get("type") == "death":
            return int(e["t"])
    return None


def activity_figure(df: pd.DataFrame, max_t: int) -> go.Figure:
    conds = list(dict.fromkeys(df.sort_values(["model", "memory_chars"])["condition"]))
    ncol = min(3, len(conds))
    nrow = int(np.ceil(len(conds) / ncol))
    fig = make_subplots(rows=nrow, cols=ncol, subplot_titles=conds, shared_yaxes=True,
                        horizontal_spacing=0.05, vertical_spacing=0.3 / max(1, nrow))
    tb = time_bin(max_t)
    xs = [(b + 0.5) * tb for b in range(int(np.ceil(max_t / tb)))]
    for ci, cond in enumerate(conds):
        arrs = [activity_over_time(Path(d), max_t, tb) for d in df.loc[df["condition"] == cond, "_dir"]]
        if not arrs:
            continue
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)       # a bin with no steps is all nan
            mean = np.nanmean(np.stack(arrs), axis=0)
        r, c = ci // ncol + 1, ci % ncol + 1
        for a, action in enumerate(ACTIONS):
            ys = np.nan_to_num(mean[:, a])
            fig.add_scatter(x=xs, y=ys, name=action, mode="lines", stackgroup=f"g{ci}", legendgroup=action,
                            showlegend=ci == 0, line=dict(width=0.5, color=CATEGORICAL[a]),
                            fillcolor=CATEGORICAL[a], hovertemplate=f"{action}: %{{y:.0%}} at step %{{x}}<extra></extra>",
                            row=r, col=c)
    # The legend goes under the panels: with three panels per row it would sit on a subplot title.
    fig.update_layout(**base_layout(height=max(300, 290 * nrow), showlegend=True, hovermode="x unified",
                                    legend=dict(orientation="h", y=-0.22 / max(1, nrow), yanchor="top", x=0, xanchor="left", font=dict(color=INK2)),
                                    margin=dict(l=48, r=16, t=44, b=72)))
    fig.update_yaxes(range=[0, 1], tickformat=".0%")
    fig.update_xaxes(title=dict(text="world step", font=dict(color=MUTED)), row=nrow)
    style_axes(fig)
    for ann in fig.layout.annotations:
        ann.font = dict(color=INK, size=12)
    return fig


def memory_figure(df: pd.DataFrame, max_t: int, mem_colors: dict[int, str]) -> go.Figure:
    models = list(dict.fromkeys(df["model"]))
    fig = make_subplots(rows=1, cols=len(models), subplot_titles=models, shared_yaxes=True, horizontal_spacing=0.05)
    tb = time_bin(max_t)
    xs = [(b + 1) * tb for b in range(int(np.ceil(max_t / tb)))]
    for mi, model in enumerate(models):
        sub = df[df["model"] == model]
        for mem in sorted(sub["memory_chars"].unique()):
            runs = sub[sub["memory_chars"] == mem]
            arrs = [memory_over_time(Path(d), max_t, tb) for d in runs["_dir"]]
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                mean = np.nanmean(np.stack(arrs), axis=0)
                lo, hi = np.nanmin(np.stack(arrs), axis=0), np.nanmax(np.stack(arrs), axis=0)
            col = mem_colors[int(mem)]
            name = f"m{mem:,}"
            if len(arrs) > 1:
                fig.add_scatter(x=xs + xs[::-1], y=list(hi) + list(lo[::-1]), fill="toself", mode="lines",
                                line=dict(width=0), fillcolor=col, opacity=0.12, showlegend=False,
                                hoverinfo="skip", legendgroup=name, row=1, col=mi + 1)
            fig.add_scatter(x=xs, y=mean, mode="lines", name=name, legendgroup=name, showlegend=mi == 0,
                            line=dict(width=2, color=col, shape="spline", smoothing=0.3),
                            hovertemplate=f"{model} {name}: %{{y:,.0f}} chars at step %{{x}}<extra></extra>",
                            row=1, col=mi + 1)
    fig.update_layout(**base_layout(height=320, showlegend=True, hovermode="x unified"))
    fig.update_xaxes(title=dict(text="world step", font=dict(color=MUTED)))
    fig.update_yaxes(title=dict(text="characters", font=dict(color=MUTED)), col=1)
    style_axes(fig)
    for ann in fig.layout.annotations:
        ann.font = dict(color=INK, size=12)
    return fig


def survival_figure(df: pd.DataFrame, max_t: int, mem_colors: dict[int, str]) -> go.Figure:
    models = list(dict.fromkeys(df["model"]))
    fig = make_subplots(rows=1, cols=len(models), subplot_titles=models, shared_yaxes=True, horizontal_spacing=0.05)
    xs = list(range(0, max_t + 1, max(1, max_t // 300)))
    for mi, model in enumerate(models):
        sub = df[df["model"] == model]
        for mem in sorted(sub["memory_chars"].unique()):
            runs = sub[sub["memory_chars"] == mem]
            deaths = [first_death(Path(d)) for d in runs["_dir"]]
            alive = [sum(1 for d in deaths if d is None or d > t) / len(deaths) for t in xs]
            name = f"m{mem:,}"
            fig.add_scatter(x=xs, y=alive, mode="lines", name=name, legendgroup=name, showlegend=mi == 0,
                            line=dict(width=2, color=mem_colors[int(mem)], shape="hv"),
                            hovertemplate=f"{model} {name}: %{{y:.0%}} alive at step %{{x}}<extra></extra>",
                            row=1, col=mi + 1)
    fig.update_layout(**base_layout(height=300, showlegend=True, hovermode="x unified"))
    fig.update_yaxes(range=[0, 1.05], tickformat=".0%")
    fig.update_yaxes(title=dict(text="runs with no death yet", font=dict(color=MUTED)), col=1)
    fig.update_xaxes(title=dict(text="world step", font=dict(color=MUTED)))
    style_axes(fig)
    for ann in fig.layout.annotations:
        ann.font = dict(color=INK, size=12)
    return fig


# ---------------------------------------------------------------- page


CSS = """
:root { color-scheme: light dark;
  --page:#f9f9f7; --surface:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e; --muted:#898781; --grid:#e1e0d9; --axis:#c3c2b7; --link:#2a78d6; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --page:#0d0d0d; --surface:#1a1a19; --ink:#fff; --ink2:#c3c2b7; --muted:#898781; --grid:#2c2c2a; --axis:#383835; --link:#3987e5; } }
:root[data-theme="dark"] { --page:#0d0d0d; --surface:#1a1a19; --ink:#fff; --ink2:#c3c2b7; --muted:#898781; --grid:#2c2c2a; --axis:#383835; --link:#3987e5; }
* { box-sizing: border-box; }
body { margin:0; padding:24px 16px 64px; background:var(--page); color:var(--ink); font-family:system-ui,-apple-system,"Segoe UI",sans-serif; font-size:15px; line-height:1.45; }
main { max-width:1200px; margin:0 auto; }
h1 { font-size:24px; margin:0 0 4px; } h2 { font-size:18px; margin:40px 0 4px; } h1+p, h2+p { color:var(--ink2); margin:0 0 16px; }
.tiles { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; margin:16px 0; }
.tile { background:var(--surface); border:1px solid var(--grid); border-radius:8px; padding:12px 14px; }
.tile .label { color:var(--muted); font-size:12px; } .tile .value { font-size:24px; font-weight:600; }
.grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(360px,1fr)); gap:16px; }
.card { background:#fcfcfb; border:1px solid var(--grid); border-radius:8px; padding:8px 8px 10px; overflow:hidden; }
.card.wide { grid-column:1/-1; }
.caption { color:#52514e; font-size:13px; margin:4px 8px 0; }
table { border-collapse:collapse; width:100%; font-size:13px; background:var(--surface); }
th, td { text-align:left; padding:6px 8px; border-bottom:1px solid var(--grid); white-space:nowrap; }
th { color:var(--muted); font-weight:500; } td.num { text-align:right; font-variant-numeric:tabular-nums; }
a { color:var(--link); }
.note { color:var(--muted); font-size:13px; }
@media (max-width:600px) { .grid { grid-template-columns:1fr; } body { padding:16px 16px 48px; } }
"""


def tile(label: str, value) -> str:
    return f'<div class="tile"><div class="label">{html.escape(label)}</div><div class="value">{html.escape(str(value))}</div></div>'


def fig_html(fig: go.Figure, first: bool) -> str:
    return fig.to_html(full_html=False, include_plotlyjs=first, config={"displayModeBar": False, "responsive": True})


def card(fig: go.Figure, caption: str, first: bool, wide: bool = False) -> str:
    return (f'<div class="card{" wide" if wide else ""}">{fig_html(fig, first)}'
            f'<p class="caption">{html.escape(caption)}</p></div>')


def runs_table(df: pd.DataFrame, viewer: str) -> str:
    cols = [("_name", "run", False), ("model", "model", False), ("memory_chars", "memory", True),
            ("history_window", "K", True), ("seed", "seed", True), ("world_steps", "world steps", True),
            ("agent_steps", "agent steps", True), ("deaths", "deaths", True), ("recipes_found", "recipes", True),
            ("cells_visited", "cells", True), ("invalid_actions", "invalid", True), ("cost_usd_total", "cost $", True),
            ("finished", "finished", False)]
    cols = [c for c in cols if c[0] in df.columns]
    head = "".join(f"<th>{html.escape(t)}</th>" for _, t, _ in cols) + "<th>replay</th>"
    rows = []
    for _, r in df.sort_values(["model", "memory_chars", "history_window", "seed"]).iterrows():
        cells = []
        for key, _, num in cols:
            v = r[key]
            if isinstance(v, float):
                v = f"{v:,.4f}" if key == "cost_usd_total" else f"{v:,.3g}"
            cells.append(f'<td class="{"num" if num else ""}">{html.escape(str(v))}</td>')
        url = f"{viewer.rstrip('/')}/?run={quote(str(r['run_id']), safe='')}"
        cells.append(f'<td><a href="{html.escape(url)}">open</a></td>')
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


def build_report(sweep_dir: str | Path, viewer: str = VIEWER_URL) -> str:
    sweep_dir = Path(sweep_dir)
    df = load_summaries(sweep_dir)
    name = sweep_dir.name
    parts = [f"<main><h1>Sweep report: {html.escape(name)}</h1>"]
    if df.empty:
        parts.append("<p>No runs with a config.yaml found in this folder.</p></main>")
        return f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><title>Sweep report {html.escape(name)}</title><style>{CSS}</style></head><body>{''.join(parts)}</body></html>"
    models = list(dict.fromkeys(sorted(df["model"].unique())))
    mcolors = model_colors(models)
    mem_colors = memory_colors([int(m) for m in df["memory_chars"].unique()])
    # The planned length, not the real one: the last action may overshoot max_steps by a few
    # world steps and those would otherwise make a nearly empty last bin.
    max_t = int(max(1, df["max_steps"].max() if "max_steps" in df else df["world_steps"].max()))
    n_seeds = df["seed"].nunique()
    status_p = sweep_dir / "sweep_status.json"
    status = json.loads(status_p.read_text()) if status_p.exists() else {}
    parts.append(f"<p>{len(df)} runs, {len(models)} model{'s' if len(models) != 1 else ''}, "
                 f"{df['memory_chars'].nunique()} memory size{'s' if df['memory_chars'].nunique() != 1 else ''}, "
                 f"{n_seeds} seed{'s' if n_seeds != 1 else ''}. Bars show the mean over seeds, the thin line on each bar "
                 f"is one standard deviation, and each dot is one seed.</p>")
    parts.append('<div class="tiles">' + tile("runs", len(df)) + tile("finished", int(df["finished"].sum()))
                 + tile("total deaths", int(df["deaths"].sum())) + tile("spent", f"${df['cost_usd_total'].sum():,.2f}")
                 + tile("tokens", f"{int(df['tokens_total'].sum()):,}")
                 + (tile("stopped", status["stopped"]) if status.get("stopped") else "") + "</div>")

    first = True
    parts.append("<h2>Metrics by model and memory size</h2><p>Each chart is one metric from summary.json. "
                 "x is the memory limit in characters, colour is the model (or bot).</p>")
    parts.append('<div class="grid">')
    for key, title, caption in METRICS:
        if key not in df.columns or pd.to_numeric(df[key], errors="coerce").isna().all():
            continue
        parts.append(card(metric_figure(df, key, title, mcolors), caption, first))
        first = False
    parts.append("</div>")

    parts.append("<h2>Activity share over time</h2><p>What the agent spent its world steps on, per condition, "
                 f"averaged over seeds in bins of {time_bin(max_t)} world steps.</p>")
    parts.append(card(activity_figure(df, max_t),
                      "Stacked shares of world steps per action. A flat band of one colour over a long stretch means "
                      "the agent kept doing the same thing. Nights are steps 200 to 299 of each 300 step day.", first, wide=True))
    first = False

    parts.append("<h2>Memory size over time</h2><p>Characters in the memory file, one line per memory limit, "
                 "one panel per model. The shaded band is the range over seeds.</p>")
    if (df["memory_chars"] > 0).any():
        parts.append(card(memory_figure(df, max_t, mem_colors),
                          "How full the memory file was as the run went on. A line that reaches its limit early and stays "
                          "there means the agent filled the file and then had to replace lines to add anything.", first, wide=True))
    else:
        parts.append('<p class="note">Every run in this sweep had memory size 0, so there is nothing to plot.</p>')

    parts.append("<h2>Survival</h2><p>Share of runs in each condition that had not died yet at each world step.</p>")
    parts.append(card(survival_figure(df, max_t, mem_colors),
                      "Each line starts at 100% and drops when a run has its first death. A line that stays high means "
                      "that condition kept itself alive. Later deaths after a respawn are not shown here, see the deaths chart.",
                      first, wide=True))

    parts.append(f"<h2>Runs</h2><p>One row per run. The replay link opens the run in the viewer at {html.escape(viewer)}. "
                 f"Start the server on this sweep folder first: <code>python -m tinyworld.server --runs {html.escape(str(sweep_dir))}</code>.</p>")
    parts.append(runs_table(df, viewer))
    parts.append("</main>")
    # The first charts are drawn while the page is still loading, before the grid has settled,
    # so they keep the full page width and get clipped. Resize every plot once the page is in.
    parts.append("<script>window.addEventListener('load',function(){document.querySelectorAll('.js-plotly-plot')"
                 ".forEach(function(p){Plotly.Plots.resize(p);});});</script>")
    body = "".join(parts)
    return (f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>"
            f"<title>Sweep report {html.escape(name)}</title><style>{CSS}</style></head><body>{body}</body></html>")


def write_report(sweep_dir: str | Path, out: str | Path | None = None, viewer: str = VIEWER_URL) -> Path:
    sweep_dir = Path(sweep_dir)
    out = Path(out) if out else sweep_dir / "report.html"
    out.write_text(build_report(sweep_dir, viewer))
    return out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Write report.html for a sweep folder.")
    ap.add_argument("sweep", help="runs/<sweep>")
    ap.add_argument("--out", default=None)
    ap.add_argument("--viewer", default=VIEWER_URL, help="base URL of the viewer for the replay links")
    args = ap.parse_args(argv)
    out = write_report(args.sweep, args.out, args.viewer)
    print(f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main(sys.argv[1:])
