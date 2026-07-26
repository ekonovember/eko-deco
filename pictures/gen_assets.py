"""Regenerate the branding assets: icon.png, icon.ico, social_preview.png.

The window/taskbar icons are package data and are written into
``src/deco/assets/`` so they ship in the wheel; ``social_preview.png`` stays in
``pictures/`` with the README artwork.

Dev-only (needs matplotlib + Pillow, which are NOT runtime deps of the app);
run from the repo root: python pictures/gen_assets.py. The generated files are
committed, so this only needs re-running when the branding changes.
"""
import io

import matplotlib
import numpy as np

matplotlib.use("Agg")
from matplotlib.colors import to_rgb
from matplotlib.figure import Figure
from matplotlib.patches import FancyBboxPatch
from PIL import Image

BLUE = "#0a84ff"
DARK = "#1e1e1e"
GRAD_TOP = "#3a9dff"      # brighter near the surface
GRAD_BOT = "#0257c9"      # deeper blue at the bottom — a touch of water depth


def _draw_mark(ax, color, lw, zorder, dx=0.0, dy=0.0,
               cx=0.5, cy=0.5, scale=1.0, aspect=1.0):
    """The <//> mark as clean vector strokes (round caps/joins, even weight)
    instead of a rendered monospace glyph — so spacing and stroke are exact.

    Geometry is authored in the unit square (icon defaults cx=cy=0.5, scale=1,
    aspect=1). cx/cy re-centre it, scale resizes it, and aspect stretches y to
    undo a non-square figure (the 2:1 social card uses aspect=2 so the mark
    keeps the same shape as on the icon). dx/dy add a soft drop-shadow offset."""
    strokes = [
        [(0.30, 0.70), (0.13, 0.50), (0.30, 0.30)],   # left chevron  <
        [(0.375, 0.30), (0.475, 0.70)],               # slash /
        [(0.525, 0.30), (0.625, 0.70)],               # slash /
        [(0.70, 0.70), (0.87, 0.50), (0.70, 0.30)],   # right chevron >
    ]
    for pts in strokes:
        xs = [cx + (x - 0.5) * scale + dx for x, _ in pts]
        ys = [cy + (y - 0.5) * scale * aspect + dy for _, y in pts]
        ax.plot(xs, ys, color=color, lw=lw, solid_capstyle="round",
                solid_joinstyle="round", zorder=zorder)


# ---- app icon: gradient blue rounded tile + white <//> mark ----
# Every .ico frame is rendered NATIVELY at its own pixel size (not one big
# master shrunk with LANCZOS) so the small taskbar / title-bar sizes stay
# sharp. figsize is fixed at 1 inch and dpi = the target pixel size, which
# makes a fixed point linewidth a constant *fraction* of the icon at every
# size — so the stroke weight scales automatically and nothing is downsampled.
ICON_LW = 5.5            # points → ~7.6% of the width; stays separate at 24 px
TOP, BOT = np.array(to_rgb(GRAD_TOP)), np.array(to_rgb(GRAD_BOT))
_GRAD = (BOT + (TOP - BOT) * np.linspace(0, 1, 256)[:, None])[:, None, :] \
    .repeat(2, axis=1)


def render_icon(px: int) -> Image.Image:
    """Render the icon natively at px×px (crisp at every size, no downsampling)."""
    fig = Figure(figsize=(1, 1), dpi=px)
    fig.patch.set_alpha(0.0)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_axis_off()
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    tile = FancyBboxPatch(
        (0.04, 0.04), 0.92, 0.92,
        boxstyle="round,pad=0,rounding_size=0.20",
        facecolor="none", edgecolor="none", mutation_aspect=1)
    ax.add_patch(tile)
    im = ax.imshow(_GRAD, extent=(0, 1, 0, 1), origin="lower",
                   aspect="auto", zorder=0)
    im.set_clip_path(tile)
    # No drop shadow: it muddies the small sizes. High-contrast white on blue
    # is what keeps the mark legible when shrunk to the taskbar.
    _draw_mark(ax, color="white", lw=ICON_LW, zorder=2)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", transparent=True)
    buf.seek(0)
    return Image.open(buf).convert("RGBA")


render_icon(512).save("src/deco/assets/icon.png")
# Assemble the .ico from natively-rendered frames, largest first (the ICO plugin
# keeps each appended image at its own native size — a small base image would
# otherwise clamp every frame down to its size).
_ico_sizes = [256, 128, 64, 48, 32, 24, 16]
_frames = [render_icon(s) for s in _ico_sizes]
_frames[0].save("src/deco/assets/icon.ico", format="ICO", append_images=_frames[1:])

# ---- GitHub social preview (1280x640) ----
fig = Figure(figsize=(12.8, 6.4), dpi=100)
fig.patch.set_facecolor(DARK)
ax = fig.add_axes([0, 0, 1, 1])
ax.set_axis_off()
ax.set_xlim(0, 1)
ax.set_ylim(0, 1)
ax.set_facecolor(DARK)

_draw_mark(ax, color=BLUE, lw=15, zorder=2,
           cx=0.205, cy=0.62, scale=0.42, aspect=2.0)
ax.text(0.40, 0.62, "eko-deco", ha="left", va="center", fontsize=88,
        fontweight="bold", color="white", family="sans-serif")
ax.text(0.5, 0.41, "Bühlmann ZHL-16C + gradient factors + rock bottom",
        ha="center", va="center", fontsize=28, color="#d0d0d0",
        family="sans-serif")
ax.text(0.5, 0.33, "dive-deco planner in pure Python — "
                   "cross-checked against Subsurface and Baker's GFDECO",
        ha="center", va="center", fontsize=17, color="#8a8a8a",
        family="sans-serif")

# decorative dive profile + dashed ceiling along the bottom, like the app chart
prof_t = [0, 0.06, 0.30, 0.34, 0.52, 0.55, 0.62, 0.65, 0.78, 0.80, 0.97]
prof_d = [0, 0.75, 0.75, 0.95, 0.95, 0.55, 0.55, 0.35, 0.35, 0.20, 0]
ceil_t = [0.18, 0.30, 0.45, 0.60, 0.75, 0.90, 0.97]
ceil_d = [0.05, 0.22, 0.38, 0.42, 0.30, 0.12, 0]
y0, h = 0.03, 0.20                       # strip at the bottom of the card
def to_y(d):
    return y0 + (1 - d) * h

ax.plot([t * 0.92 + 0.04 for t in prof_t], [to_y(d) for d in prof_d],
        color=BLUE, linewidth=3, solid_capstyle="round")
ax.plot([t * 0.92 + 0.04 for t in ceil_t], [to_y(d) for d in ceil_d],
        color="#ff6b5e", linewidth=2, linestyle="--")
fig.savefig("pictures/social_preview.png", facecolor=DARK)
print("done")
