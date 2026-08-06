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
from matplotlib.patches import Polygon, Rectangle

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

    def arrow(self, x, y, length, color=INK, lw=0.9):
        """Solid arrow pointing LEFT, its tip at (x, y), `length` mm long.

        Drawn pointing back into the table so it indicates the row it sits
        beside, rather than gesturing off the edge of the card.
        """
        head = min(1.6, length * 0.45)
        self.ax.plot([self.ox + x + head * 0.8, self.ox + x + length],
                     [self.oy + y, self.oy + y],
                     lw=lw, color=color, solid_capstyle="butt")
        self.ax.add_patch(Polygon(
            [(self.ox + x, self.oy + y),
             (self.ox + x + head, self.oy + y + head * 0.62),
             (self.ox + x + head, self.oy + y - head * 0.62)],
            closed=True, facecolor=color, edgecolor="none"))

    def rule(self, y, x0=2.0, x1=W - 2.0, lw=0.4, color=RULE):
        self.ax.plot([self.ox + x0, self.ox + x1], [self.oy + y, self.oy + y],
                     lw=lw, color=color, solid_capstyle="butt")

    def rect(self, x, y, w, h, **kw):
        self.ax.add_patch(Rectangle((self.ox + x, self.oy + y), w, h, **kw))


LABEL_W = 7.0              # depth-label column, mm
MARK_W = 6.0               # gas-switch marker gutter on the right, mm
BAND = "#eeeeee"           # zebra fill, so a row stays trackable across columns
CHAR_W = 0.2124            # DejaVu Sans Mono advance, mm per point of type size

#: Vertical room the table has between the header strip and the summary rule.
TABLE_H = 45.5
SIZE_MAX = 9.5             # design type size; a short card does not balloon past it


def cell(v):
    """A cell as text, for logs and tests — `runtime_table` draws it in two
    separately aligned fields so the columns line up on the card itself."""
    if v is None:
        return "-"
    leg, run = v
    return f"({run})" if leg is None else f"{leg} ({run})"


def cell_fields(v):
    """`(minutes, runtime)` as the two strings a cell is drawn from.

    Brackets hug their digits — `(42)`, `(104)`, never `( 42)`. Alignment comes
    from *where* the fields are drawn, not from padding inside them: both are
    right-aligned on fixed rules, so units sit under units and the closing
    bracket lines up down the column, which is the convention a numeric column
    is read by. The opening bracket is the one thing left ragged, and it is the
    right thing to give up.
    """
    if v is None:
        return ("", "-")
    leg, run = v
    return ("" if leg is None else f"{leg}", f"({run})")


def fit_size(n_rows, height=TABLE_H, size_max=SIZE_MAX):
    """Largest type size whose rows still fit `height` mm."""
    pitch = height / max(1, n_rows)
    return max(3.6, min(size_max, (pitch - 0.55) / 0.62))


def runtime_table(pen, x, y, columns, rows, width, size=None):
    """MultiDeco's compressed runtime table.

    `columns` are the scenario headings (`OK`, `-50`, …); `rows` are
    `(depth_label, cells, switch)` where `switch` is a gas name to flag on that
    row, or None. A switch is drawn as a filled black triangle in the gutter on
    the right, at the row where that mix starts being breathed.
    """
    if size is None:
        size = fit_size(len(rows) + 1)
    pitch = size * 0.62 + 0.55
    col_w = (width - LABEL_W - MARK_W) / len(columns)

    pen.txt(x + LABEL_W + col_w * 0.5, y, columns[0], size=size * 0.82,
            weight="bold", color=GREY, ha="center")
    for i, head in enumerate(columns[1:], start=1):
        pen.txt(x + LABEL_W + (i + 0.5) * col_w, y, head, size=size * 0.82,
                weight="bold", color=GREY, ha="center")
    y_head = y - 1.9
    pen.rule(y_head, x0=x - 0.6, x1=x + width + 0.6, lw=0.5, color=INK)
    y -= pitch

    band = False
    for label, cells, switch in rows:
        if band:
            pen.rect(x - 0.6, y - 1.4, width + 1.2, pitch, facecolor=BAND,
                     edgecolor="none")
        band = not band
        pen.txt(x + LABEL_W - 1.6, y, label, size=size * 0.90, weight="bold",
                ha="right")
        for i, c in enumerate(cells):
            x_col = x + LABEL_W + i * col_w
            mins, run = cell_fields(c)
            # Two fixed rules per column: minutes right-aligned on one, the
            # bracketed runtime right-aligned on the next. Centring the pair as
            # a single string is what left "2 (42)" and "33 (104)" ragged.
            if mins:
                pen.txt(x_col + col_w * 0.42, y, mins, size=size,
                        weight="bold", ha="right")
            pen.txt(x_col + col_w * 0.97, y, run, size=size, weight="bold",
                    ha="right")
        if switch:
            # Arrow in the right gutter, pointing back at the row: this is
            # where you change gas. Marker only - a mix name here either
            # collides with it or steals width from the numbers, and the
            # numbers are the card. Which mix is in the legend, keyed by depth.
            pen.arrow(x + width - MARK_W + 0.8, y + size * 0.10, MARK_W - 1.8)
        y -= pitch

    y_foot = y + pitch - 1.9
    pen.rule(y_foot, x0=x - 0.6, x1=x + width + 0.6, lw=0.5, color=INK)
    pen.ax.plot([pen.ox + x + LABEL_W - 0.9] * 2,
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

    y = runtime_table(pen, 2.4, H - 10.6, spec["columns"], spec["rows"],
                      width=W - 4.8)
    y -= 0.6
    # `warnings` is REQUIRED, not `spec.get(...)`: this card carries no printed
    # disclaimer, so the model's warnings are the only caveat on it, and a
    # renderer that forgets them is a safety regression rather than a cosmetic
    # one (DECISIONS.md #4, #5). A KeyError here is the point — pass [] when
    # the plan really is clean.
    for w in spec["warnings"]:
        pen.txt(2.8, y, f"! {w}", size=3.6, weight="bold", color=RED)
        y -= 2.9
    for s_, size, weight, color in spec.get("extra", []):
        pen.txt(2.8, y, s_, size=size, weight=weight, color=color)
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
def rows_from_scenarios(plans):
    """Compressed runtime rows from several `deco plan --json` results.

    `plans` is one parsed plan per column, left to right — MultiDeco's own
    `utrata gazu` layout is `OK / lost 50 / lost 100 / both`, and the columns
    here are whatever scenarios you pass. Returns rows shaped for
    `runtime_table`.

    The first row is the bottom depth carrying only its runtime, exactly as
    MultiDeco prints `32  (40)`: you do not hold on the bottom, you leave it.
    Gas switches are flagged on the row where that mix is first breathed, taken
    from the planned (first) column.
    """
    per = [{s["depth_m"]: (s["leg_min"], s["run_min"]) for s in p["stops"]}
           for p in plans]
    depths = sorted({d for col in per for d in col}, reverse=True)

    lead = plans[0]
    bottom_depth = lead["input"]["max_depth_m"]
    bottom_run = [_bottom_run(p) for p in plans]
    rows = [(f"{bottom_depth:g}", [(None, r) for r in bottom_run], None)]

    switch_at = _switch_depths(lead)
    for d in depths:
        rows.append((f"{d:g}", [col.get(d) for col in per], switch_at.get(d)))
    return rows


def _bottom_run(plan):
    """Runtime on leaving the bottom phase = total runtime minus TTS."""
    return math.floor(plan["total_runtime_min"] - plan["tts_min"] + 1e-9)


def _switch_depths(plan):
    """{stop depth: mix} for each gas switch, at the row it first applies to.

    A switch made on the ascent (EAN50 at 21 m) has no row of its own in a
    compressed table, so it is flagged on the first stop breathing it — which
    is where the diver acts on it anyway.
    """
    out, seen = {}, plan["input"]["gas"]
    for s in plan["stops"]:
        if s["gas"] != seen:
            out[s["depth_m"]] = s["gas"]
            seen = s["gas"]
    return out


def gas_line(plan):
    """The gas plan as one short string: bottom mix, then each switch depth."""
    bottom = plan["input"]["gas"]
    out, seen = [], bottom
    for seg in plan["segments"]:
        if seg["gas"] == seen or seg["kind"] in ("descent", "bottom"):
            continue
        depth = seg["depth_start_m"] if seg["kind"] == "ascent" else seg["depth_end_m"]
        out.append(f"{seg['gas']}@{depth:g}")
        seen = seg["gas"]
    return " ".join([bottom, *out])


# Card spec shape. Placeholder numbers only - NOT a dive plan. Replace with
# real `deco.cli` output (via rows_from_scenarios) before printing anything you
# dive.
#
# "warnings" is required (see draw_card): the model's ppO2 / ceiling / density
# warnings for THIS plan, as plain strings; [] when the plan is clean.
# "columns" are the scenario headings; "rows" are (depth label, cells, switch)
# from rows_from_scenarios - a cell is (leg_minutes, runtime), (None, runtime)
# for the bottom row, or None where that column never reaches the depth.
EXAMPLE = {
    "tag": "EXAMPLE",
    "subtitle": "-- m / -- min   GF --/--",
    "columns": ["OK", "-50", "-O2", "BOTH"],
    "rows": [
        ("--", [(None, 0)] * 4, None),
        ("9",  [(0, 0), (0, 0), (0, 0), (0, 0)], "<deco gas>"),
        ("6",  [(0, 0), (0, 0), (0, 0), (0, 0)], "<deco gas>"),
        ("3",  [(0, 0), (0, 0), (0, 0), (0, 0)], None),
    ],
    "warnings": ["<the plan's warnings go here - [] only when there are none>"],
    "extra": [],
    "summary": "MIN GAS -- b (2 div --)   TURN -- b (2 div --)   CNS --%",
    "footer": "depth m | cell = min (runtime you leave on) | placeholder - not a plan",
    "accent": "#444444",
}


if __name__ == "__main__":
    save_card(EXAMPLE, OUT / "example_card.pdf")
    save_sheet([EXAMPLE], OUT / "example_a4.pdf")
    print("wrote example_card.pdf/.png and example_a4.pdf")
