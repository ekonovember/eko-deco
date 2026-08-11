"""The two Hermanice cards, in the handwritten wetnotes runtime convention.

Sources — both kept verbatim in `examples/hermanice_dive/`, both printed here
exactly as the planner that produced them printed them:

* **TRAINING** — MultiDeco 4.24 export, `training_dive/multideco_training_runtime.txt`:
  32 m / 40 min on EAN32, GF **5/50**, fresh water at 150 m (surface 1.000 bar),
  rates 8/9 m/min. The deliberately over-conservative practice profile.
* **ACTUAL** — Shearwater **Perdix** on-unit planner, photographed 2026-08-08
  (`actual_plan/`): 33 m / 40 min on EAN32, GF **40/85**, last stop 3 m, RMV 20.

The layout is the one transcribed in
`examples/hermanice_dive/runtime_convention/card.md` — the
hand-written card that copies `examples/scenario_2`: a direction glyph per
row (down / level / up), the depth, the leg, the leave-at runtime in brackets,
and a filled **triangle** pointing at every gas-switch row. `README.md` is the
reference for why the columns are those columns; this file only adds the
direction glyph and the switch triangle to it.

**These cards print another planner's schedule, not ours.** Every depth,
minute and runtime on them comes from the source above. Every row carries its
minutes, as the hand-written card does; a transit's minutes are set grey and
its row is marked with an arrow, so nothing on the card can be misread as time
held at a depth. What this file computes is only what the sources do not print:
min gas, turn pressure and the plan's warnings, all from `deco.cli`. Where
eko-deco disagrees with a source about the schedule itself, that is reported on
stdout and in `examples/hermanice_dive/README.md` — never silently merged into
the card.

    python cards/make_hermanice.py          # both cards + the A4 sheet
    python cards/make_hermanice.py training # just one

Writes `hermanice_training.pdf/.png`, `hermanice_actual.pdf/.png` and
`hermanice_a4.pdf` into `cards/` (all gitignored — cards are remade per dive).
"""
from __future__ import annotations

import itertools
import json
import math
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from make_cards import (
    A4_H,
    A4_W,
    BAND,
    COLS,
    GREY,
    GUTTER,
    INK,
    MARK,
    MONO,
    RED,
    ROWS,
    RULE,
    VGAP,
    H,
    Pen,
    Polygon,
    Rectangle,
    W,
    plt,
)

OUT = Path(__file__).resolve().parent
REPO = OUT.parent

#: The cylinders actually carried, as (litres, fill bar).
BOTTOM_TANK, STAGE_TANK = (24.0, 220.0), (11.3, 130.0)
SAC = 20.0                 # the Perdix's own RMV, used for both cards

DOWN, LEVEL, UP = "descent", "level", "ascent"


# --------------------------------------------------------------- the sources ---
# rows: (kind, depth_m, run_min, gas) — `run` is the runtime the diver LEAVES
# that row on, exactly as the source prints it. Leg minutes are NEVER stored:
# they are run differences (DECISIONS #17), so the two columns cannot disagree.
TRAINING = {
    "tag": "TRAINING  32m",
    "subtitle": "GF 5/50   MultiDeco",
    "accent": "#5a2d5a",
    "source": "MultiDeco 4.24 - 32m/40min EAN32, fresh 150m, 8/9 - 21m is a switch stop",
    "rows": [
        (DOWN,  32, 4,  "EAN32"),
        (LEVEL, 32, 40, "EAN32"),
        (UP,    21, 41, "EAN32"),
        (LEVEL, 21, 44, "EAN50"),
        (LEVEL, 18, 45, "EAN50"),
        (LEVEL, 15, 46, "EAN50"),
        (LEVEL, 12, 47, "EAN50"),
        (LEVEL,  9, 49, "EAN50"),
        (LEVEL,  6, 54, "O2"),
        (LEVEL,  3, 63, "O2"),
    ],
    "surface_run": 63,
    "cns": 38.9,
    # The export's printed ppO2s pin the environment below: EAN32 at 32 m is
    # 1.31 and O2 at 6 m is 1.58 only at surface 1.000 bar + 10 1/3 m/bar.
    "plan": ["--depth", "32", "--time", "40", "--gf-low", "0.05", "--gf-high", "0.50",
             "--descent-rate", "8", "--ascent-rate", "9",
             "--water", "fresh", "--surface-p", "1.0"],
}

ACTUAL = {
    "tag": "ACTUAL  33m",
    "subtitle": "GF 40/85   Perdix",
    "accent": "#1f3350",
    "source": "Shearwater Perdix planner 2026-08-08, fresh water @ 267 m",
    "rows": [
        (LEVEL, 33, 40, "EAN32"),
        (UP,    21, 42, "EAN32"),
        (UP,     9, 44, "EAN50"),
        (LEVEL,  9, 45, "EAN50"),
        (LEVEL,  6, 48, "O2"),
        (LEVEL,  3, 53, "O2"),
    ],
    "surface_run": 53,
    "cns": 31,
    # Environment stated by the diver: fresh water, 267 m at the time of the
    # plan. The six printed Qty values had already fixed it to 0.980-0.984 bar
    # and 10.29-10.31 m/bar before it was confirmed — see the folder README.
    # The descent rate is the one thing left over: the bottom row needs a 2.0
    # min descent, and 10 m/min is out by 40 L (also in the README).
    "plan": ["--depth", "33", "--time", "40", "--gf-low", "0.40", "--gf-high", "0.85",
             "--descent-rate", "16.2", "--ascent-rate", "10",
             "--water", "fresh", "--altitude", "267"],
}

CARDS = {"training": TRAINING, "actual": ACTUAL}


# ------------------------------------------------------------------ numbers ---
def plan_json(card, divers=1):
    """eko-deco's own plan of the same dive, at the source's stated settings."""
    cmd = [sys.executable, "-m", "deco.cli", "plan", *card["plan"],
           "--gas", f"32@{BOTTOM_TANK[0]:g}@{BOTTOM_TANK[1]:g}",
           "--deco-gas", f"50@{STAGE_TANK[0]:g}@{STAGE_TANK[1]:g}",
           "--deco-gas", f"100@{STAGE_TANK[0]:g}@{STAGE_TANK[1]:g}",
           "--sac", f"{SAC:g}", "--sac-multiplier", "1.5", "--problem-time", "2",
           "--divers", str(divers), "--json"]
    env = {"PYTHONPATH": str(REPO / "src"), "PATH": "/usr/bin:/bin"}
    out = subprocess.run(cmd, capture_output=True, text=True, check=True,
                         cwd=REPO, env=env).stdout
    return json.loads(out)


def legs(card):
    """Leg minutes per row: the run difference, which is what a leg IS."""
    runs = [r[2] for r in card["rows"]]
    return [runs[0], *[b - a for a, b in itertools.pairwise(runs)]]


def bar_up(liters, tank):
    """Bar a volume needs, rounded UP — a reserve never rounds down."""
    return math.ceil(liters / tank - 1e-9)


def summary_line(card):
    """MIN GAS / TURN, plus the source's CNS.

    **Solo figures only.** The two-diver reserve was on the card and came off
    it: this dive is planned with one set of cylinders, and a second bold number
    beside each of these is a number to pick the wrong one of at 33 m. Plan
    `--divers 2` when the dive is a team dive and reprint the card.
    """
    solo = plan_json(card)
    rb = bar_up(solo["gas"]["rock_bottom_l"], BOTTOM_TANK[0])
    turn = math.floor(solo["gas"]["turn_pressure_bar"])
    return (f"MIN GAS {rb} b   TURN {turn} b   "
            f"CNS {round(card['cns'])}%"), solo


# ------------------------------------------------------------------- layout ---
# No pressure column: the only pressures on this card are MIN GAS and TURN, on
# the summary line. A per-row SPG figure is a number to read in the water that
# nothing in the water can act on — you act on the turn pressure.
GLYPH_W = 5.0              # direction-glyph gutter, mm
LABEL_W = 12.0             # depth column
LEG_W = 15.0               # leg minutes / bot / asc
RUN_W = 18.0               # (runtime)
MARK_W = 7.0               # switch-triangle gutter
TABLE_W = GLYPH_W + LABEL_W + LEG_W + RUN_W + MARK_W
TABLE_TOP = H - 10.4
TABLE_BOT = 12.0           # leaves room for the switch/need line above the rule
INFO_Y = 9.4               # the one line of switch + gas plan
SUMMARY_RULE = 7.2


#: Where a row's optical middle sits above its text baseline, per mm of type
#: size: half the cap height of DejaVu Sans Mono (0.73 em) in mm per point.
MID = 0.73 / 2 * 0.3528


def row_mid(y, size):
    """The row's optical centre line — every mark in a row aligns to this."""
    return y + size * MID


def triangle(pen, x, y, size, color=INK):
    """The switch marker: a filled triangle with one vertex pointing LEFT, into
    the row it marks, its apex on the row's centre line.

    Pointing at the row rather than merely sitting beside it is what makes the
    marker unambiguous once there are two of them on a card: the apex names the
    row, so a triangle can never read as belonging to the line above or below.
    """
    pen.ax.add_patch(Polygon(
        [(pen.ox + x, pen.oy + y),
         (pen.ox + x + size, pen.oy + y + size * 0.62),
         (pen.ox + x + size, pen.oy + y - size * 0.62)],
        closed=True, facecolor=color, edgecolor="none"))


def glyph(pen, kind, x, y, size):
    """Down arrow / level dash / up arrow, drawn rather than typed.

    A glyph font would do it, but the card is set in DejaVu Sans Mono and its
    arrows are half the weight of the digits beside them; these read at 7 pt
    through a mask, which is the whole point of the column.

    All three are the same length and share one centre line (`y`, the row's
    optical middle) and one x, so the column reads as a column: a dash sits
    exactly where the shaft of the arrows is, and the two arrows are mirror
    images rather than one being taller than the other.
    """
    half = min(1.35, size * 0.22)          # half the glyph's length, mm
    if kind == LEVEL:
        pen.ax.plot([pen.ox + x - half, pen.ox + x + half], [pen.oy + y] * 2,
                    lw=1.0, color=INK, solid_capstyle="butt")
        return
    up = kind == UP
    tip = pen.oy + y + (half if up else -half)
    tail = pen.oy + y - (half if up else -half)
    head = min(1.0, half * 0.85)           # arrowhead length, mm
    base = tip - (head if up else -head)
    pen.ax.plot([pen.ox + x] * 2, [tail, base], lw=0.9, color=INK,
                solid_capstyle="butt")
    w = head * 0.55
    pen.ax.add_patch(Polygon(
        [(pen.ox + x, tip), (pen.ox + x - w, base), (pen.ox + x + w, base)],
        closed=True, facecolor=INK, edgecolor="none"))


def draw_runtime_card(pen, spec):
    """One 90 x 64 mm card in the hand-written runtime convention."""
    pen.rect(0, 0, W, H, facecolor="#ffffff", edgecolor="none")
    pen.rect(0.4, 0.4, W - 0.8, H - 0.8, fill=False, lw=0.5, ec=INK)
    pen.rect(0.4, H - 7.0, W - 0.8, 6.6, facecolor=spec["accent"], edgecolor="none")
    pen.txt(2.8, H - 5.0, spec["tag"], size=6.4, weight="bold", color="#ffffff")
    pen.txt(W - 2.8, H - 5.0, spec["subtitle"], size=5.8, weight="bold",
            color="#ffffff", ha="right")

    rows = spec["table"]
    x = (W - TABLE_W) / 2                 # the block is centred on the card
    x_right = x + TABLE_W
    x_leg = x + GLYPH_W + LABEL_W + LEG_W
    x_run = x_leg + RUN_W
    x_mark = x_run + MARK_W * 0.25

    # Row pitch follows the row count, so the 6-row Perdix card sets its
    # schedule half again as large as the 10-row MultiDeco one instead of
    # leaving the space blank. The schedule numbers get the space (README).
    n = len(rows) + 1                                   # + the SURF row
    # Warnings are drawn between the table and the info line, so they take
    # their space FROM the table rather than writing over the line below it.
    bottom = TABLE_BOT + 2.9 * len(spec["warnings"])
    pitch = min(5.6, (TABLE_TOP - bottom) / n)
    size = max(4.4, min(8.6, (pitch - 0.55) / 0.62))

    y = TABLE_TOP
    pen.txt(x + GLYPH_W + LABEL_W - 1.4, y, "m", size=size * 0.72, weight="bold",
            color=GREY, ha="right")
    pen.txt(x_leg - 1.0, y, "min", size=size * 0.72, weight="bold", color=GREY,
            ha="right")
    pen.txt(x_run - 1.0, y, "run", size=size * 0.72, weight="bold", color=GREY,
            ha="right")
    pen.rule(y - 1.9, x0=x - 0.6, x1=x_right, lw=0.5, color=INK)

    y -= pitch
    for i, (kind, depth, leg, run, switch) in enumerate(rows):
        if i % 2:
            pen.rect(x - 0.6, y - 1.4, TABLE_W + 0.6, pitch, facecolor=BAND,
                     edgecolor="none")
        mid = row_mid(y, size)
        glyph(pen, kind, x + GLYPH_W * 0.5, mid, size)
        pen.txt(x + GLYPH_W + LABEL_W - 1.4, y, f"{depth:g}", size=size,
                weight="bold", ha="right")
        # Every row carries its minutes — the hand-written convention. A
        # TRANSIT's minutes are set grey and a shade smaller so the column
        # cannot be misread as a stop: the arrow says it is a transit and the
        # weight says it again. Only bold black numbers are time held.
        transit = kind in (DOWN, UP)
        pen.txt(x_leg - 1.0, y, leg, size=size * (0.86 if transit else 1.0),
                weight="bold", color=GREY if transit else INK, ha="right")
        pen.txt(x_run - 1.0, y, f"({run:g})", size=size, weight="bold", ha="right")
        if switch:
            triangle(pen, x_mark, mid, size=min(2.1, size * 0.30))
        y -= pitch

    pen.rule(y + pitch - 1.9, x0=x - 0.6, x1=x_right, lw=0.5, color=INK)
    pen.txt(x + GLYPH_W + LABEL_W - 1.4, y, "SURF", size=size * 0.82, weight="bold",
            ha="right")
    pen.txt(x_run - 1.0, y, f"({spec['surface_run']:g})", size=size, weight="bold",
            ha="right")
    pen.txt(x_run + 1.4, y, f"TTS {spec['tts']:g}'", size=size * 0.82, weight="bold",
            color=RED)

    # the vertical rule that separates the depth label from the numbers
    pen.ax.plot([pen.ox + x + GLYPH_W + LABEL_W - 0.7] * 2,
                [pen.oy + y - 1.9, pen.oy + TABLE_TOP - 1.9],
                lw=0.35, color=RULE, solid_capstyle="butt")

    y -= pitch * 0.7
    # Required, never optional: this card carries no printed disclaimer, so the
    # planner's warnings are the only caveat on it (DECISIONS #4, #5).
    for w in spec["warnings"]:
        pen.txt(2.8, y, f"! {w}", size=3.6, weight="bold", color=RED)
        y -= 2.9

    pen.txt(2.8, INFO_Y, spec["info"], size=3.5, weight="bold", color=INK)
    pen.rule(SUMMARY_RULE)
    pen.txt(2.8, 4.6, spec["summary"], size=4.0, weight="bold")
    pen.txt(2.8, 2.7, spec["footer"], size=3.2, color=GREY)
    pen.txt(2.8, 1.0, spec["source"], size=3.2, color=GREY)


def build(name):
    """Assemble one card spec from its source rows."""
    card = CARDS[name]
    summary, solo = summary_line(card)
    leg_min = legs(card)

    # A switch is marked on the row that ENDS at the depth the diver changes
    # gas at, which is not always the row the new mix first appears on. The
    # Perdix bills the whole 21 -> 9 m ascent to EAN50, so that mix is taken at
    # 21 m and the triangle belongs on the row arriving at 21 m, not on the one
    # arriving at 9 m. On a stop row the two coincide. This is what puts both
    # cards' triangles at 21 m and 6 m, as the hand-written card has them.
    table, seen = [], card["rows"][0][3]
    marked, switches = set(), []
    for i, (kind, _depth, _run, gas) in enumerate(card["rows"]):
        if gas == seen:
            continue
        row = i - 1 if kind in (DOWN, UP) else i
        marked.add(row)
        switches.append(f"{card['rows'][row][1]:g}m {gas}")
        seen = gas
    for i, ((kind, depth, run, _gas), leg) in enumerate(
            zip(card["rows"], leg_min, strict=True)):
        table.append((kind, depth, f"{leg:g}", run, i in marked))

    tts = card["surface_run"] - card["rows"][0][2] if name == "actual" else \
        card["surface_run"] - 40
    spec = {
        "tag": card["tag"],
        "subtitle": card["subtitle"],
        "accent": card["accent"],
        "table": table,
        "surface_run": card["surface_run"],
        "tts": tts,
        # straight from `deco plan --json` for the same dive, so the card cannot
        # disagree with the planner about what is wrong with it
        "warnings": solo["warnings"],
        "summary": summary,
        # No glyph name in the legend: the triangles point AT their rows and
        # those rows are named here by depth, so "(v)" was describing a marker
        # that no longer points that way and told the reader nothing either way.
        "info": f"SWITCH {' · '.join(switches)}",
        "footer": ("min = minutes on that row, grey = transit not a stop · "
                   "run = the runtime you LEAVE that row on"),
        "source": (f"EAN32 {BOTTOM_TANK[0]:g}L@{BOTTOM_TANK[1]:g} · stages "
                   f"{STAGE_TANK[0]:g}L@{STAGE_TANK[1]:g}  |  schedule: "
                   f"{card['source']}"),
    }
    return spec, solo


def save_card(spec, path):
    fig = plt.figure(figsize=(W / 25.4, H / 25.4), dpi=300)
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set_xlim(0, W)
    ax.set_ylim(0, H)
    ax.set_axis_off()
    draw_runtime_card(Pen(ax), spec)
    fig.savefig(path, format="pdf")
    fig.savefig(path.with_suffix(".png"), format="png")
    plt.close(fig)


def save_sheet(specs, path):
    """4 rows x the given cards, exact size on A4, with crop marks."""
    fig = plt.figure(figsize=(A4_W / 25.4, A4_H / 25.4), dpi=300)
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set_xlim(0, A4_W)
    ax.set_ylim(0, A4_H)
    ax.set_axis_off()
    ax.add_patch(Rectangle((0, 0), A4_W, A4_H, facecolor="#ffffff", edgecolor="none"))

    x0 = (A4_W - COLS * W - (COLS - 1) * GUTTER) / 2
    y0 = (A4_H - ROWS * H - (ROWS - 1) * VGAP) / 2
    for r in range(ROWS):
        for c, spec in enumerate(specs):
            ox = x0 + c * (W + GUTTER)
            oy = y0 + (ROWS - 1 - r) * (H + VGAP)
            draw_runtime_card(Pen(ax, ox, oy), spec)
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


def compare(name, spec, ours):
    """One line per stop: what the source printed against what we plan."""
    src = {d: (leg, run) for _k, d, leg, run, _s in spec["table"]
           if _k == LEVEL and d != spec["table"][0][1]}
    mine = {s["depth_m"]: (s["leg_min"], s["run_min"]) for s in ours["stops"]}
    print(f"\n{name}: source vs eko-deco")
    print(f"  {'depth':>6} {'source':>12} {'eko-deco':>12}")
    for d in sorted(set(src) | set(mine), reverse=True):
        s = f"{src[d][0]}' @{src[d][1]:g}" if d in src else "-"
        m = f"{mine[d][0]:g}' @{mine[d][1]:g}" if d in mine else "-"
        print(f"  {d:>6g} {s:>12} {m:>12}")
    print(f"  {'run':>6} {spec['surface_run']:>12g} "
          f"{math.floor(ours['total_runtime_min']):>12g}")
    print(f"  {'CNS':>6} {round(CARDS[name]['cns']):>11}% "
          f"{round(ours['cns_pct']):>11}%")


def main():
    which = sys.argv[1:] or list(CARDS)
    specs = []
    for name in which:
        spec, ours = build(name)
        save_card(spec, OUT / f"hermanice_{name}.pdf")
        specs.append(spec)
        warned = f" ({len(spec['warnings'])} warning(s))" if spec["warnings"] else ""
        print(f"wrote hermanice_{name}.pdf/.png{warned}")
        compare(name, spec, ours)
    save_sheet(specs, OUT / "hermanice_a4.pdf")
    print(f"\nwrote hermanice_a4.pdf ({len(specs)} card(s) x {ROWS} rows)")


if __name__ == "__main__":
    main()
