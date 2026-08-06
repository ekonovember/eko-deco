"""Build the two printed cards for the `examples/scenario_2` dive.

32 m / 40 min on EAN28, GF 5/50, EAN50 + O2 as deco gases — planned at
eko-deco's own defaults (sea-level salt water), which is the pairing that lands
on MultiDeco's runtime (`tests/test_multideco_scenarios.py`).

Every number comes from `deco.cli plan --json`, so a cell cannot drift from the
schedule. `make_cards.py` is the layout engine; this file is the dive.

    python cards/make_scenario2.py

Writes, into `cards/` (all gitignored — cards are remade per dive):

* `scenario2.pdf/.png` + `scenario2_a4.pdf` — lost-gas columns (OK/-50/-O2/BOTH)
* `scenario2_multideco.pdf/.png` + `scenario2_multideco_a4.pdf` — MultiDeco's
  own layout: ON PLAN and LOST EAN50 side by side over bottom-time columns
"""
from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from make_cards import (
    BAND,
    GREY,
    INK,
    LEFT,
    MONO,
    RED,
    RIGHT,
    H,
    Pen,
    W,
    gas_line,
    plt,
    rows_from_scenarios,
    save_card,
    save_sheet,
)

OUT = Path(__file__).resolve().parent
REPO = OUT.parent
ACCENT = "#1f3350"

DEPTH, BOTTOM_TIME = 32, 40
BOTTOM = "28@24@232"
EAN50, O2 = "50@11@200", "100@11@200"
GF = ("0.05", "0.50")
#: The export states both rates; SAC/multiplier/problem time are the planner's.
RATES = ["--descent-rate", "8", "--ascent-rate", "9"]
GAS_PLAN = ["--sac", "20", "--sac-multiplier", "1.5", "--problem-time", "2"]
#: Bottom-time contingency columns, on the 3 min grid. `*` marks the plan.
BOTTOM_TIMES = (34, 37, 40, 43)


def plan(time_min=BOTTOM_TIME, decos=(EAN50, O2), divers=1):
    """One `deco plan --json`, parsed."""
    cmd = [sys.executable, "-m", "deco.cli", "plan",
           "--depth", str(DEPTH), "--time", str(time_min), "--gas", BOTTOM,
           "--gf-low", GF[0], "--gf-high", GF[1],
           *RATES, *GAS_PLAN, "--divers", str(divers), "--json"]
    for g in decos:
        cmd += ["--deco-gas", g]
    env = {"PYTHONPATH": str(REPO / "src"), "PATH": "/usr/bin:/bin"}
    out = subprocess.run(cmd, capture_output=True, text=True, check=True,
                         cwd=REPO, env=env).stdout
    return json.loads(out)


# ------------------------------------------------------------ card B layout ---
# Two tables side by side sharing one set of bottom-time columns. The engine's
# `runtime_table` draws one full-width table in `min (runtime)` form; this card
# is denser — `leg/run` in one field, plus SUR and TTS summary rows — so it
# draws its own grid on the same Pen.
SUB_Y = H - 9.6            # the "ON PLAN … " strip
HEAD_Y = H - 13.4          # column headings
ROW0_Y = H - 17.0
PITCH = 4.55
LABEL_W = 7.2
TABLE_W = 41.0
SIZE = 5.6


def grid_table(pen, x, title, columns, rows, surface, tts, mark):
    """One `leg/run` table: heading strip, banded depth rows, SUR and TTS."""
    col_w = (TABLE_W - LABEL_W) / len(columns)
    pen.txt(x, SUB_Y, title, size=3.6, weight="bold", color=GREY)

    pen.txt(x + LABEL_W - 1.6, HEAD_Y, "BT", size=SIZE * 0.86, weight="bold",
            color=INK, ha="right")
    for i, head in enumerate(columns):
        label = f"{head}*" if head == mark else f"{head}"
        pen.txt(x + LABEL_W + (i + 0.94) * col_w, HEAD_Y, label,
                size=SIZE * 0.86, weight="bold", color=GREY, ha="right")
    pen.rule(HEAD_Y - 1.9, x0=x - 0.4, x1=x + TABLE_W + 0.4, lw=0.5, color=INK)

    y = ROW0_Y
    for band, (label, cells) in enumerate(rows):
        if band % 2 == 0:
            pen.rect(x - 0.4, y - 1.4, TABLE_W + 0.8, PITCH, facecolor=BAND,
                     edgecolor="none")
        pen.txt(x + LABEL_W - 1.6, y, label, size=SIZE * 0.92, weight="bold",
                ha="right")
        for i, c in enumerate(cells):
            pen.txt(x + LABEL_W + (i + 0.94) * col_w, y, c, size=SIZE,
                    weight="bold", ha="right")
        y -= PITCH

    pen.rule(y + PITCH - 1.9, x0=x - 0.4, x1=x + TABLE_W + 0.4, lw=0.5, color=INK)
    for label, values, color in (("SUR", surface, INK), ("TTS", tts, RED)):
        pen.txt(x + LABEL_W - 1.6, y, label, size=SIZE * 0.82, weight="bold",
                color=color, ha="right")
        for i, v in enumerate(values):
            pen.txt(x + LABEL_W + (i + 0.94) * col_w, y, v, size=SIZE,
                    weight="bold", color=color, ha="right")
        y -= PITCH
    # the vertical rule between the label column and the numbers
    pen.ax.plot([pen.ox + x + LABEL_W - 0.9] * 2,
                [pen.oy + y + PITCH - 1.9, pen.oy + HEAD_Y - 1.9],
                lw=0.35, color=INK, solid_capstyle="butt")


def draw_two_table_card(pen, spec):
    pen.rect(0, 0, W, H, facecolor="#ffffff", edgecolor="none")
    pen.rect(0.4, 0.4, W - 0.8, H - 0.8, fill=False, lw=0.5, ec=INK)
    pen.rect(0.4, H - 7.0, W - 0.8, 6.6, facecolor=spec["accent"], edgecolor="none")
    pen.txt(2.8, H - 5.0, spec["tag"], size=6.4, weight="bold", color="#ffffff")
    pen.txt(W - 2.8, H - 5.0, spec["subtitle"], size=5.8, weight="bold",
            color="#ffffff", ha="right")

    for x, table in ((LEFT + 0.4, spec["left"]), (RIGHT + 0.4, spec["right"])):
        grid_table(pen, x, table["title"], spec["columns"], table["rows"],
                   table["surface"], table["tts"], spec["mark"])

    pen.rule(6.4)
    pen.txt(2.8, 4.0, spec["summary"], size=4.0, weight="bold")
    pen.txt(2.8, 1.7, spec["footer"], size=3.5, color=GREY)


def save_two_table(spec, path):
    fig = plt.figure(figsize=(W / 25.4, H / 25.4), dpi=300)
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set_xlim(0, W)
    ax.set_ylim(0, H)
    ax.set_axis_off()
    draw_two_table_card(Pen(ax), spec)
    fig.savefig(path, format="pdf")
    fig.savefig(path.with_suffix(".png"), format="png")
    plt.close(fig)


# ----------------------------------------------------------------- numbers ---
def bar(liters, tank_l):
    """Cylinder pressure a volume needs, rounded UP: reserves never round down."""
    return math.ceil(liters / tank_l - 1e-9)


def summary_line(planned, team):
    """MIN GAS / TURN for one and two divers, plus the CNS clock."""
    def figures(p):
        g = p["gas"]
        tank = next(c["tank_l"] for c in g["cylinders"] if c["role"] == "Bottom")
        fill = next(c["pressure_bar"] for c in g["cylinders"] if c["role"] == "Bottom")
        rb = bar(g["rock_bottom_l"], tank)
        return rb, math.floor(fill - (fill - rb) / 2)

    solo_gas, solo_turn = figures(planned)
    team_gas, team_turn = figures(team)
    return (f"MIN GAS {solo_gas} b (2 div {team_gas} b)   "
            f"TURN {solo_turn} b (2 div {team_turn} b)   "
            f"CNS {round(planned['cns_pct'])}%")


def bottom_time_table(decos):
    """`{depth: [leg/run per bottom time]}` plus the SUR and TTS rows."""
    plans = [plan(time_min=t, decos=decos) for t in BOTTOM_TIMES]
    per = [{s["depth_m"]: f"{s['leg_min']}/{s['run_min']}" for s in p["stops"]}
           for p in plans]
    depths = sorted({d for col in per for d in col}, reverse=True)
    rows = [(f"{d:g}", [col.get(d, "-") for col in per]) for d in depths]
    surface = [f"{math.floor(p['total_runtime_min'])}" for p in plans]
    tts = [f"{math.ceil(p['tts_min'] - 1e-9)}" for p in plans]
    return rows, surface, tts, plans[0]


def main():
    planned = plan()
    team = plan(divers=2)
    gf_lo, gf_hi = (round(float(g) * 100) for g in GF)
    subtitle = f"{DEPTH} m / {BOTTOM_TIME} min   GF {gf_lo}/{gf_hi}"
    summary = summary_line(planned, team)

    # ---- card A: the lost-gas columns MultiDeco's own scenario table uses ----
    columns = [("OK", (EAN50, O2)), ("-50", (O2,)), ("-O2", (EAN50,)), ("BOTH", ())]
    plans = [plan(decos=d) for _label, d in columns]
    switches = " · ".join(f"{d:g}m {mix}" for d, mix in
                          sorted(_switch_rows(plans[0]).items(), reverse=True))
    spec_a = {
        "tag": f"{DEPTH}m EAN28",
        "subtitle": subtitle,
        "columns": [label for label, _ in columns],
        "rows": rows_from_scenarios(plans),
        # straight from `deco plan --json`, so the card cannot disagree with the
        # planner about what is wrong with the dive (DECISIONS.md #4)
        "warnings": planned["warnings"],
        "extra": [],
        "summary": summary,
        "footer": (f"← switch: {switches}  |  cell = min (runtime you leave on)"
                   "  |  EAN28 24L@232 · stages 11L@200"),
        "accent": ACCENT,
    }
    save_card(spec_a, OUT / "scenario2.pdf")

    # ---- card B: ON PLAN / LOST EAN50 over bottom-time columns --------------
    on_rows, on_sur, on_tts, on_lead = bottom_time_table((EAN50, O2))
    lost_rows, lost_sur, lost_tts, lost_lead = bottom_time_table((O2,))
    spec_b = {
        "tag": f"{DEPTH}m EAN28",
        "subtitle": subtitle,
        "columns": BOTTOM_TIMES,
        "mark": BOTTOM_TIME,
        "left": {"title": f"ON PLAN  {gas_line(on_lead)}",
                 "rows": on_rows, "surface": on_sur, "tts": on_tts},
        "right": {"title": f"LOST EAN50  {gas_line(lost_lead)}",
                  "rows": lost_rows, "surface": lost_sur, "tts": lost_tts},
        "warnings": planned["warnings"],
        "summary": summary,
        "footer": ("depth m | cell = leg min / leave-at runtime | "
                   "EAN28 24L@232 · EAN50 11L@200 · O2 11L@200"),
        "accent": ACCENT,
    }
    save_two_table(spec_b, OUT / "scenario2_multideco.pdf")

    # ---- A4 imposition: 4x each card, exact size, crop marks ----------------
    save_sheet([spec_a], OUT / "scenario2_a4.pdf")
    _save_two_table_sheet(spec_b, OUT / "scenario2_multideco_a4.pdf")
    print("wrote scenario2.pdf/.png, scenario2_a4.pdf, "
          "scenario2_multideco.pdf/.png, scenario2_multideco_a4.pdf")


def _switch_rows(plan_json):
    out, seen = {}, plan_json["input"]["gas"]
    for s in plan_json["stops"]:
        if s["gas"] != seen:
            out[s["depth_m"]] = s["gas"]
            seen = s["gas"]
    return out


def _save_two_table_sheet(spec, path):
    """The A4 imposition of card B — same geometry as `make_cards.save_sheet`."""
    from make_cards import A4_H, A4_W, COLS, GUTTER, MARK, ROWS, VGAP, Rectangle

    fig = plt.figure(figsize=(A4_W / 25.4, A4_H / 25.4), dpi=300)
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set_xlim(0, A4_W)
    ax.set_ylim(0, A4_H)
    ax.set_axis_off()
    ax.add_patch(Rectangle((0, 0), A4_W, A4_H, facecolor="#ffffff", edgecolor="none"))

    x0 = (A4_W - COLS * W - (COLS - 1) * GUTTER) / 2
    y0 = (A4_H - ROWS * H - (ROWS - 1) * VGAP) / 2
    for r in range(ROWS):
        for c in range(COLS):
            ox = x0 + c * (W + GUTTER)
            oy = y0 + (ROWS - 1 - r) * (H + VGAP)
            draw_two_table_card(Pen(ax, ox, oy), spec)
            for mx in (ox, ox + W):
                for my in (oy, oy + H):
                    sx = -1 if mx == ox else 1
                    sy = -1 if my == oy else 1
                    ax.plot([mx + sx * 1.0, mx + sx * (1.0 + MARK)], [my, my],
                            lw=0.25, color="#888888")
                    ax.plot([mx, mx], [my + sy * 1.0, my + sy * (1.0 + MARK)],
                            lw=0.25, color="#888888")
    ax.text(4.5, A4_H / 2, "PRINT AT 100% / ACTUAL SIZE - DO NOT FIT TO PAGE. "
            "Each card is 90 x 64 mm; cut on the border.",
            fontsize=4.4, color="#888888", family=MONO, rotation=90,
            ha="center", va="center")
    fig.savefig(path, format="pdf")
    plt.close(fig)


if __name__ == "__main__":
    main()
