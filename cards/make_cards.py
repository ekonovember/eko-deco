"""Lay out 90 x 64 mm (landscape) wetnotes runtime cards as print-ready PDFs.

This is the **layout engine only** — it computes nothing. Feed it numbers from
`deco.cli` and it renders them in the planner convention (V-Planner / MultiDeco
/ slate runtimes): stop depths down the side, RUN = the runtime you leave the
stop, TTS last, contingencies as parallel columns. `README.md` documents that
format and the sources it was verified against; follow it for any new printed
or exported schedule.

Sizes are millimetres, origin bottom-left. TTS is rounded UP, RUN truncated
(`report.runtime_min`) — do that when you produce the numbers, not here.

Usage: build a card spec (see EXAMPLE at the bottom for the shape), then

    save_card(spec, Path("mycard.pdf"))       # one card, exact size, + .png
    save_sheet([spec, spec2], Path("a4.pdf")) # 4x each on A4 with crop marks

Generate the numbers with e.g.

    python -m deco.cli plan --depth D --time T --gas GAS --deco-gas GAS \
        --gf-low LO --gf-high HI --sac 20 --sac-multiplier 1.5 --problem-time 2

re-running per contingency column, and again with `--deco-gas` dropped for the
LOST table and `--divers 2` for the team min-gas / turn figures.
"""
from __future__ import annotations

import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")   # headless: must precede the pyplot import
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

W, H = 90.0, 64.0          # card, mm (90 wide = landscape)
MONO = "DejaVu Sans Mono"
INK = "#111111"
GREY = "#555555"
RULE = "#9a9a9a"
RED = "#a3101a"
LEFT, RIGHT = 2.0, 45.0    # x of the two contingency tables
OUT = Path(__file__).resolve().parent


class Pen:
    """Draws in card-local mm; the origin is where the card sits on the page."""

    def __init__(self, ax, ox=0.0, oy=0.0):
        self.ax, self.ox, self.oy = ax, ox, oy

    def txt(self, x, y, s, size=4.4, weight="normal", color=INK, ha="left", rotation=0):
        self.ax.text(self.ox + x, self.oy + y, s, fontsize=size, fontweight=weight,
                     color=color, ha=ha, va="baseline", family=MONO, rotation=rotation)

    def rule(self, y, x0=2.0, x1=W - 2.0, lw=0.4, color=RULE):
        self.ax.plot([self.ox + x0, self.ox + x1], [self.oy + y, self.oy + y],
                     lw=lw, color=color, solid_capstyle="butt")

    def rect(self, x, y, w, h, **kw):
        self.ax.add_patch(Rectangle((self.ox + x, self.oy + y), w, h, **kw))


LABEL_W = 5.6              # depth-label column, mm
COL_W = 8.7                # one bottom-time column, mm
BAND = "#eeeeee"           # zebra fill, so a row stays trackable across columns


def cell(v):
    """Every cell is exactly 5 characters, so the columns line up on the slash.

    `(leg, run)` renders as `leg/run`, the notation the whole toolchain prints
    (`deco.buhlmann.StopLeg`, DECISIONS.md #17):

    * `run` is the runtime you **leave** that stop on - not when you arrive;
    * `leg` is the ascent to the stop plus the hold, measured from the previous
      stop, so the column adds up to the runtimes beside it.

    Feeding the bare *hold* here instead is the classic error and the card goes
    quietly wrong by one ascent per stop - use `table_from_plans`, which takes
    `deco plan --json` output and cannot get it wrong. A bare number (SUR, TTS)
    is padded to sit under the runtime digits, `None` is a dash.
    """
    if v is None:
        return "  -  "
    if isinstance(v, tuple):
        return f"{v[0]:>2}/{v[1]:>2}"
    return f"   {v:>2}"


#: Vertical room a table has between the header strip and the summary rule.
TABLE_H = 43.0
SIZE_MAX = 7.4             # design type size; short cards do not balloon past it


def fit_size(n_rows, height=TABLE_H, size_max=SIZE_MAX):
    """Largest type size whose rows still fit `height` mm.

    A real deco schedule is six or seven stops, not the three the layout was
    first drawn around, and an overflowing table silently writes the TTS row
    over the summary - on the one artifact that goes underwater. So the type
    shrinks to fit rather than the rows running off the card.
    """
    pitch = height / max(1, n_rows)
    return max(3.6, min(size_max, (pitch - 0.55) / 0.62))


def table(pen, x, y, title, rows, size=None):
    """One contingency table; rows are (label, cells, kind).

    `size` defaults to whatever fits the row count (`fit_size`)."""
    if size is None:
        size = fit_size(len(rows))
    width = LABEL_W + 4 * COL_W
    pitch = size * 0.62 + 0.55          # rows breathe with the type size
    pen.txt(x, y, title, size=4.2, weight="bold", color=GREY)
    y -= pitch * 0.95

    band, y_head, prev = False, y, None
    for label, cells, kind in rows:
        if kind == "sum" and prev == "stop":                 # stops end here
            pen.rule(y + 1.9, x0=x - 0.6, x1=x + width + 0.6, lw=0.35, color=INK)
        if kind == "stop":
            if band:
                pen.rect(x - 0.6, y - 1.4, width + 1.2, pitch, facecolor=BAND,
                         edgecolor="none")
            band = not band
        color = RED if kind == "tts" else INK
        pen.txt(x + LABEL_W - 1.4, y, label, size=size * 0.80, weight="bold",
                color=GREY if kind == "head" else color, ha="right")
        for i, c in enumerate(cells):
            pen.txt(x + LABEL_W + (i + 0.5) * COL_W, y, c if kind == "head" else cell(c),
                    size=size * (0.86 if kind == "head" else 1.0), weight="bold",
                    color=GREY if kind == "head" else color, ha="center")
        if kind == "head":
            y_head = y - 1.9
            pen.rule(y_head, x0=x - 0.6, x1=x + width + 0.6, lw=0.5, color=INK)
            band = True
        y -= pitch
        prev = kind

    y_foot = y + pitch - 1.9
    pen.rule(y_foot, x0=x - 0.6, x1=x + width + 0.6, lw=0.5, color=INK)
    pen.ax.plot([pen.ox + x + LABEL_W - 0.7] * 2,          # depth labels | data
                [pen.oy + y_foot, pen.oy + y_head],
                lw=0.35, color=INK, solid_capstyle="butt")
    return y


def draw_card(pen, spec):
    """Render one card into `pen`'s 90 x 64 mm frame."""
    pen.rect(0, 0, W, H, facecolor="#ffffff", edgecolor="none")
    pen.rect(0.4, 0.4, W - 0.8, H - 0.8, fill=False, lw=0.5, ec=INK)

    pen.rect(0.4, H - 7.0, W - 0.8, 6.6, facecolor=spec["accent"], edgecolor="none")
    pen.txt(2.8, H - 5.0, spec["tag"], size=6.4, weight="bold", color="#ffffff")
    pen.txt(W - 2.8, H - 5.0, spec["subtitle"], size=5.8, weight="bold",
            color="#ffffff", ha="right")

    top = H - 10.4
    # One size for both halves: a diver reads across them, so rows must line up
    # even when one scenario has an extra stop.
    size = fit_size(max(len(spec["left"][1]), len(spec["right"][1])))
    yl = table(pen, LEFT, top, spec["left"][0], spec["left"][1], size)
    table(pen, RIGHT, top, spec["right"][0], spec["right"][1], size)
    y = yl - 0.6

    for s, size, weight, color in spec["extra"]:
        pen.txt(2.8, y, s, size=size, weight=weight, color=color)
        y -= size * 0.64 + 0.6

    pen.rule(6.4)
    pen.txt(2.8, 4.0, spec["summary"], size=4.0, weight="bold")
    pen.txt(2.8, 1.7, spec["footer"], size=3.5, color=spec.get("footer_color", GREY))


def save_card(spec, path):
    """One card, one page, exactly 90 x 64 mm."""
    fig = plt.figure(figsize=(W / 25.4, H / 25.4), dpi=300)
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set_xlim(0, W)
    ax.set_ylim(0, H)
    ax.set_axis_off()
    draw_card(Pen(ax), spec)
    fig.savefig(path, format="pdf")
    fig.savefig(path.with_suffix(".png"), format="png")
    plt.close(fig)


A4_W, A4_H = 210.0, 297.0
COLS, ROWS = 2, 4
GUTTER, VGAP = 8.0, 6.0
MARK = 3.0                 # crop-mark tick length, mm


def save_sheet(specs, path):
    """Both cards, 4x each, at exact size on A4 with crop marks.

    Printers and PDF viewers default to 'fit to page', which scales a 90 x 64 mm
    page up to A4. An A4 page cannot be scaled up, so printing this sheet at
    100% gives cards that are actually 90 x 64 mm - then cut on the borders.
    """
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
            draw_card(Pen(ax, ox, oy), spec)
            for mx in (ox, ox + W):                       # crop marks
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




# --------------------------------------------------------------------------
def table_from_plans(title, plans, mark=0):
    """Build a table `(title, rows)` straight from `deco plan --json` output.

    `plans` is one parsed JSON dict per contingency column, left to right, all
    of the same dive with one thing varied (bottom time, depth, or a lost deco
    gas). `mark` is the index of the planned column, flagged with `*`.

    This exists so the card cannot disagree with the planner. Every number
    comes from the `stops` key, which carries the printed notation already
    resolved - leg and leave-at runtime - so there is no transcription step to
    get wrong and no chance of pasting a raw hold from the segment table.

    Columns need not share a stop list: a depth only some columns reach shows
    `-` in the others, exactly like the GUI's scenario table.
    """
    per = [{s["depth_m"]: (s["leg_min"], s["run_min"]) for s in p["stops"]}
           for p in plans]
    depths = sorted({d for col in per for d in col}, reverse=True)
    head = [("BT" if len(plans) > 1 else "",
             [("--" if i != mark else "--*") for i in range(len(plans))],
             "head")]
    rows = [(f"{d:g}", [col.get(d) for col in per], "stop") for d in depths]
    rows.append(("SUR", [p["input"].get("_", 0) or _run_surface(p)
                         for p in plans], "sum"))
    # TTS is a budget: round UP, the opposite of a runtime (DECISIONS.md #17).
    rows.append(("TTS", [math.ceil(p["tts_min"] - 1e-9) for p in plans], "tts"))
    return (title, head + rows)


def _run_surface(plan):
    """Runtime on surfacing, truncated - the same floor the stops use."""
    return math.floor(plan["total_runtime_min"] + 1e-9)


def gas_line(plan):
    """The gas plan as one short string: bottom mix, then each switch depth.

    The printed card has no room for a per-row GAS column beside four
    contingency columns, so the switches live in the table title - derived from
    the plan rather than typed, so they cannot drift from the schedule. Kept
    terse ("21/35 EAN50@21 O2@6") because the title strip is about 40
    characters wide at the card's type size.
    """
    bottom = plan["input"]["gas"]
    out, seen = [], bottom
    # A switch can happen on the ascent (before the first stop) or at a stop;
    # walk the segments once so each mix is named at the depth it starts, and
    # only once.
    for seg in plan["segments"]:
        if seg["gas"] == seen or seg["kind"] in ("descent", "bottom"):
            continue
        depth = seg["depth_start_m"] if seg["kind"] == "ascent" else seg["depth_end_m"]
        out.append(f"{seg['gas']}@{depth:g}")
        seen = seg["gas"]
    return " ".join([bottom, *out])


# Card spec shape. Placeholder numbers only - NOT a dive plan. Replace the
# tables with real `deco.cli` output before printing anything you dive.
#
# A table row is (label, cells, kind); kind is "head" | "stop" | "sum" | "tts".
# A stop cell is (stop_minutes, runtime_you_leave_on) or None for "not planned";
# sum/tts cells are bare numbers. Columns are the contingency axis - here
# bottom time; `*` marks the planned column.
EXAMPLE_HDR = ("BT", ["--*", "--", "--", "--"], "head")

EXAMPLE = {
    "tag": "EXAMPLE",
    "subtitle": "-- m / -- min   GF --/--",
    "left": ("ON PLAN  <bottom gas> -> <deco gas> @ -- m", [
        EXAMPLE_HDR,
        ("9", [None, None, (1, 0), (1, 0)], "stop"),
        ("6", [(1, 0), (2, 0), (2, 0), (3, 0)], "stop"),
        ("3", [(3, 0), (4, 0), (6, 0), (8, 0)], "stop"),
        ("SUR", [0, 0, 0, 0], "sum"),
        ("TTS", [0, 0, 0, 0], "tts"),
    ]),
    "right": ("LOST <deco gas>  all on <bottom gas>", [
        EXAMPLE_HDR,
        ("9", [(1, 0), (1, 0), (2, 0), (2, 0)], "stop"),
        ("6", [(2, 0), (3, 0), (4, 0), (5, 0)], "stop"),
        ("3", [(8, 0), (11, 0), (14, 0), (18, 0)], "stop"),
        ("SUR", [0, 0, 0, 0], "sum"),
        ("TTS", [0, 0, 0, 0], "tts"),
    ]),
    "extra": [],
    "summary": "MIN GAS -- b (2 div --)   TURN -- b (2 div --)   CNS --%",
    "footer": "depth m | cell = leg min / leave-at runtime | placeholder - not a plan",
    "accent": "#444444",
}


if __name__ == "__main__":
    save_card(EXAMPLE, OUT / "example_card.pdf")
    save_sheet([EXAMPLE, EXAMPLE], OUT / "example_a4.pdf")
    print("wrote example_card.pdf/.png and example_a4.pdf")
