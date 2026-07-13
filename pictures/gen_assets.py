"""Regenerate the branding assets: icon.png, icon.ico, social_preview.png.

Dev-only (needs matplotlib + Pillow, which are NOT runtime deps of the app);
run from the repo root: python pictures/gen_assets.py. The generated files are
committed, so this only needs re-running when the branding changes.
"""
import io

import matplotlib
matplotlib.use("Agg")
from matplotlib.figure import Figure
from matplotlib.patches import FancyBboxPatch
from PIL import Image

BLUE = "#0a84ff"
DARK = "#1e1e1e"
MARK = "<//>"

# ---- app icon: solid blue rounded tile + white logo mark (512x512) ----
fig = Figure(figsize=(4, 4), dpi=128)
fig.patch.set_alpha(0.0)
ax = fig.add_axes([0, 0, 1, 1])
ax.set_axis_off()
ax.set_xlim(0, 1)
ax.set_ylim(0, 1)
ax.add_patch(FancyBboxPatch(
    (0.05, 0.05), 0.90, 0.90,
    boxstyle="round,pad=0,rounding_size=0.18",
    facecolor=BLUE, edgecolor="none", mutation_aspect=1))
ax.text(0.5, 0.54, MARK, ha="center", va="center", fontsize=92,
        fontweight="bold", color="white", family="monospace")
buf = io.BytesIO()
fig.savefig(buf, format="png", transparent=True)
buf.seek(0)
master = Image.open(buf).convert("RGBA")
master.save("pictures/icon.png")
master.save("pictures/icon.ico",
            sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
                   (128, 128), (256, 256)])

# ---- GitHub social preview (1280x640) ----
fig = Figure(figsize=(12.8, 6.4), dpi=100)
fig.patch.set_facecolor(DARK)
ax = fig.add_axes([0, 0, 1, 1])
ax.set_axis_off()
ax.set_xlim(0, 1)
ax.set_ylim(0, 1)
ax.set_facecolor(DARK)

ax.text(0.24, 0.62, MARK, ha="center", va="center", fontsize=96,
        fontweight="bold", color=BLUE, family="monospace")
ax.text(0.40, 0.62, "eko-deco", ha="left", va="center", fontsize=88,
        fontweight="bold", color="white", family="sans-serif")
ax.text(0.5, 0.41, "Bühlmann ZHL-16C + gradient factors + rock bottom",
        ha="center", va="center", fontsize=28, color="#d0d0d0",
        family="sans-serif")
ax.text(0.5, 0.33, "educational dive-deco planner in pure Python — "
                   "cross-checked against Subsurface and Baker's GFDECO",
        ha="center", va="center", fontsize=17, color="#8a8a8a",
        family="sans-serif")

# decorative dive profile + dashed ceiling along the bottom, like the app chart
prof_t = [0, 0.06, 0.30, 0.34, 0.52, 0.55, 0.62, 0.65, 0.78, 0.80, 0.97]
prof_d = [0, 0.75, 0.75, 0.95, 0.95, 0.55, 0.55, 0.35, 0.35, 0.20, 0]
ceil_t = [0.18, 0.30, 0.45, 0.60, 0.75, 0.90, 0.97]
ceil_d = [0.05, 0.22, 0.38, 0.42, 0.30, 0.12, 0]
y0, h = 0.03, 0.20                       # strip at the bottom of the card
to_y = lambda d: y0 + (1 - d) * h
ax.plot([t * 0.92 + 0.04 for t in prof_t], [to_y(d) for d in prof_d],
        color=BLUE, linewidth=3, solid_capstyle="round")
ax.plot([t * 0.92 + 0.04 for t in ceil_t], [to_y(d) for d in ceil_d],
        color="#ff6b5e", linewidth=2, linestyle="--")
fig.savefig("pictures/social_preview.png", facecolor=DARK)
print("done")
