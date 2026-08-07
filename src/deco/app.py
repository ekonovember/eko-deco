"""eko-deco — interactive dive-profile visualizer for the Bühlmann ZHL-16C + GF model.

Left panel: dive settings (depth, bottom time, gradient factors, a fully editable
gas list where every mix — bottom / travel / deco — has its own O2, He and tank,
plus SAC, an emergency SAC multiplier and a one-or-two-diver team size). The rest
of the window is a notebook: **Results** (schedule, TTS, per-cylinder gas + rock
bottom, lost-deco-gas scenarios), a printable **Runtime** wetnotes card, and
**Profile** (the depth-vs-time chart with the deco-ceiling overlay).

The dive is loaded from and saved to ``dive_plan.json`` (see
:mod:`deco.dive_config`), the same file the console planner reads/writes — so
``deco plan --save`` shows up here on Reload, and vice-versa.

Run::

    deco-gui              # or: python -m deco.app
"""

from __future__ import annotations

import contextlib
import json
import math
import os
import re
import sys
import textwrap
import tkinter as tk
from dataclasses import dataclass, replace
from tkinter import ttk
from typing import Any, Literal

import matplotlib

matplotlib.use("TkAgg")                    # must precede the backend imports
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from deco import buhlmann as b
from deco import dive_config as dc
from deco import report as rp

# The GUI ascends at a fixed rate; keep it in step with the CLI DivePlan default
# (10 m/min) so the same inputs give the same schedule in both.
ASCENT_RATE = 10.0


@dataclass
class _RowLevel:
    """A level row exactly as typed, before it is validated into a
    ``buhlmann.Level``. Kept unvalidated so a field blanked mid-edit (depth or
    runtime 0) can still be persisted without tripping ``Level``'s invariants.
    Levels are pure depth/time periods — gas is chosen automatically by role."""
    depth: float
    runtime: float

# Branding: the eko-deco wordmark and its "<//>" logo mark.
APP_NAME = "eko-deco"
LOGO_MARK = "<//>"
LOGO_COLOR = "#0a84ff"
_ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
ICON_PNG = os.path.join(_ASSETS, "icon.png")
ICON_ICO = os.path.join(_ASSETS, "icon.ico")

# UI preferences (dark mode, window geometry) live in their own file, per user,
# so they never mix with the dive itself: dive_plan.json stays shareable
# between CLI/GUI and machines, and it is the dive you hand a buddy.
UI_SETTINGS_PATH = os.path.join(
    os.path.dirname(dc.user_config_path()), "ui_settings.json")

# Widget + chart palettes for the clam ttk theme.
LIGHT = {"bg": "#dcdad5", "fg": "#000000", "field": "#ffffff",
         "trough": "#c8c6c1", "border": "#9e9a91", "active": "#eeebe7",
         "chart_bg": "#ffffff", "chart_fg": "#000000", "grid": "#b0b0b0",
         "ceiling": "#c0392b"}
DARK = {"bg": "#2b2b2b", "fg": "#e6e6e6", "field": "#3c3f41",
        "trough": "#1f1f1f", "border": "#555555", "active": "#3a3d3f",
        "chart_bg": "#1e1e1e", "chart_fg": "#d0d0d0", "grid": "#666666",
        "ceiling": "#ff6b5e"}


def _monitor_workareas(root) -> list[tuple[int, int, int, int]]:
    """Per-monitor work areas as ``(left, top, right, bottom)``, primary first. On
    Windows these are the *real* rectangles of each attached monitor (honouring
    monitors placed left of / above the primary, i.e. negative coords, and the
    taskbar); elsewhere a single primary-screen rect. The bounding box of every
    monitor can contain gaps not covered by any screen (offset/mismatched
    monitors), which is why we track each rect and not just the overall span."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            class MONITORINFO(ctypes.Structure):
                _fields_ = [("cbSize", wintypes.DWORD),
                            ("rcMonitor", wintypes.RECT),
                            ("rcWork", wintypes.RECT),
                            ("dwFlags", wintypes.DWORD)]

            mons: list[tuple[int, int, int, int]] = []
            primary: list[tuple[int, int, int, int]] = []
            proc = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_ulong,
                                      ctypes.c_ulong,
                                      ctypes.POINTER(wintypes.RECT),
                                      ctypes.c_double)

            def _cb(h_mon, _hdc, _lprc, _data):
                mi = MONITORINFO()
                mi.cbSize = ctypes.sizeof(MONITORINFO)
                ctypes.windll.user32.GetMonitorInfoW(h_mon, ctypes.byref(mi))
                wk = mi.rcWork
                rect = (wk.left, wk.top, wk.right, wk.bottom)
                (primary if mi.dwFlags & 1 else mons).append(rect)
                return 1

            ctypes.windll.user32.EnumDisplayMonitors(0, 0, proc(_cb), 0)
            rects = primary + mons
            if rects:
                return rects
        except Exception:
            pass
    return [(0, 0, root.winfo_screenwidth(), root.winfo_screenheight())]


def _overlap_area(a: tuple[int, int, int, int],
                  b: tuple[int, int, int, int]) -> int:
    """Area of the intersection of two ``(l, t, r, b)`` rectangles (0 if disjoint)."""
    l, t = max(a[0], b[0]), max(a[1], b[1])
    r, btm = min(a[2], b[2]), min(a[3], b[3])
    return max(0, r - l) * max(0, btm - t)


def clamp_geometry(root, geom: str) -> str:
    """Keep a restored ``WxH+X+Y`` on a real, attached monitor, so a window saved
    on a screen that is gone (or that falls in a gap between offset monitors)
    can't reopen with its title bar unreachable. The window is snapped onto the
    monitor it most overlaps — or, if it overlaps none, the nearest one — and
    clamped inside that monitor's work area. Size-only or unparseable strings
    pass through untouched."""
    m = re.fullmatch(r"(\d+)x(\d+)([+-])(-?\d+)([+-])(-?\d+)", geom.strip())
    if not m:
        return geom
    w, h = int(m.group(1)), int(m.group(2))
    sx, xv, sy, yv = m.group(3), int(m.group(4)), m.group(5), int(m.group(6))
    mons = _monitor_workareas(root)
    maxr = max(r for _l, _t, r, _b in mons)
    maxb = max(b for _l, _t, _r, b in mons)
    # Tk offsets carry a gravity sign: '+' = from the left/top (value may itself
    # be negative, e.g. Tk's own "+-2557"), '-' = from the right/bottom of the
    # whole desktop. Resolve to an absolute top-left first.
    x = xv if sx == "+" else (maxr - w - xv)
    y = yv if sy == "+" else (maxb - h - yv)
    # Pick the monitor the window most overlaps; if it touches none (its monitor
    # was detached, or it landed in a gap between offset monitors) fall back to
    # the monitor nearest the window's centre, so the title bar is always on a
    # real screen.
    want = (x, y, x + w, y + h)
    best = max(mons, key=lambda mo: _overlap_area(want, mo))
    if _overlap_area(want, best) == 0:
        cx, cy = x + w / 2, y + h / 2
        best = min(mons, key=lambda mo: (max(mo[0] - cx, 0, cx - mo[2]) ** 2 +
                                         max(mo[1] - cy, 0, cy - mo[3]) ** 2))
    ml, mt, mr, mb = best
    w, h = min(w, mr - ml), min(h, mb - mt)
    x = min(max(x, ml), mr - w)
    y = min(max(y, mt), mb - h)
    return f"{w}x{h}+{x}+{y}"


def load_ui_settings() -> dict:
    try:
        with open(UI_SETTINGS_PATH, encoding="utf-8") as f:
            return dict(json.load(f))
    except (OSError, ValueError):
        return {}


def save_ui_settings(settings: dict) -> None:
    try:
        os.makedirs(os.path.dirname(UI_SETTINGS_PATH), exist_ok=True)
        with open(UI_SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
            f.write("\n")
    except OSError:
        pass                                   # cosmetic preference; never fatal


def build_profile_points(segs) -> tuple[list[float], list[float]]:
    """Concatenate segment endpoints into a (time, depth) polyline."""
    t, d, run = [0.0], [0.0], 0.0
    for s in segs:
        run += s.duration
        t.append(run)
        d.append(s.depth_end)
    return t, d


def format_card(title_lines: list[str], rows: list[list[str]],
                headers: list[str] | None = None,
                footer_lines: list[str] | None = None,
                aligns: list[str] | None = None,
                widen: int = -1) -> list[str]:
    """Render a monospace box-drawing "slate" and return its lines. Every section
    is optional: full-width ``title_lines`` on top, an optional column ``headers``
    row, the ``rows`` grid, then optional full-width ``footer_lines`` — all framed
    to one width so columns line up in the Tk card and the exported PNG alike.

    ``aligns`` gives ``"<"`` / ``">"`` / ``"^"`` per grid column (default: first
    column left, the rest right). ``widen`` is the column that absorbs any extra
    width a long title/footer line forces: the last by default; pick a
    left-aligned one to keep right-aligned number columns snug."""
    title_lines = list(title_lines or [])
    footer_lines = list(footer_lines or [])
    grid_rows = [[str(c) for c in row] for row in rows]
    cols = len(headers) if headers else (len(grid_rows[0]) if grid_rows else 1)
    aligns = aligns or (["<"] + [">"] * (cols - 1))
    widths = [len(str(headers[i])) if headers else 0 for i in range(cols)]
    for row in grid_rows:
        for i in range(cols):
            widths[i] = max(widths[i], len(row[i]))

    # Inner width spanned by the column grid: each cell is padded by a space on
    # both sides (w + 2) and columns are joined by a single divider.
    inner = sum(w + 2 for w in widths) + (cols - 1)
    longest = max((len(s) for s in title_lines + footer_lines), default=0)
    if longest > inner - 2:                        # widen a column to fit the text
        widths[widen] += longest - (inner - 2)
        inner = sum(w + 2 for w in widths) + (cols - 1)

    def full(s: str) -> str:                       # a full-width (spanning) row
        return "│ " + f"{s:<{inner - 2}}" + " │"

    def grid(cells: list[str]) -> str:
        return "│ " + " │ ".join(
            f"{cells[i]:{aligns[i]}{widths[i]}}" for i in range(cols)) + " │"

    def cols_rule(left: str, mid: str, right: str) -> str:
        return left + mid.join("─" * (w + 2) for w in widths) + right

    def flat_rule(left: str, right: str) -> str:
        return left + "─" * inner + right

    out = [flat_rule("┌", "┐") if title_lines else cols_rule("┌", "┬", "┐")]
    out += [full(s) for s in title_lines]
    if title_lines:
        out.append(cols_rule("├", "┬", "┤"))
    if headers:
        out.append(grid([str(h) for h in headers]))
        out.append(cols_rule("├", "┼", "┤"))
    out += [grid(row) for row in grid_rows]
    if footer_lines:
        out.append(cols_rule("├", "┴", "┤"))
        out += [full(s) for s in footer_lines]
        out.append(flat_rule("└", "┘"))
    else:
        out.append(cols_rule("└", "┴", "┘"))
    return out


# matplotlib renders the Unicode box-drawing glyphs (U+2500 family) from a
# proportional fallback font even under family="monospace", which ragged-aligns
# any framed card in a PNG export (the on-screen Tk Text widget is fine). Fold
# them to ASCII so every cell stays exactly one fixed-width character wide.
_BOX_TO_ASCII = str.maketrans({
    **dict.fromkeys("─", "-"),
    **dict.fromkeys("│", "|"),
    **dict.fromkeys("┌┐└┘├┤┬┴┼", "+"),
})


class DecoApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title(f"{APP_NAME} — Bühlmann ZHL-16C + gradient factors "
                   "+ rock bottom")
        self._ui_settings = load_ui_settings()
        try:                       # last session's size/position (ui_settings)
            geom = str(self._ui_settings.get("geometry") or "1500x900")
            root.geometry(clamp_geometry(root, geom))
        except tk.TclError:
            root.geometry("1500x900")
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._set_window_icon()

        self._building = True
        self._base_cfg = dc.default_config()
        self._plan_ok = False        # True only when a valid plan is on screen
        self._build_layout()
        self._apply_theme()
        # A missing config is a normal first launch; a *broken* one must not
        # silently morph into the default dive — flag it in the status label.
        cfg_note = None
        try:
            cfg = dc.load(strict=True)
        except FileNotFoundError:
            cfg = dc.default_config()
        except (OSError, ValueError):
            cfg = dc.default_config()
            cfg_note = "⚠ config unreadable — defaults"
        self._apply_config(cfg)
        if cfg_note:
            self.cfg_status.config(text=cfg_note)
        self._building = False
        self.recompute()

    # ---------------------------------------------------------------- UI ----

    def _set_window_icon(self) -> None:
        """Use the <//> tile (pictures/icon.png) as the window + taskbar icon."""
        try:
            if sys.platform == "win32":
                # The taskbar groups Tk windows under python.exe and shows ITS
                # icon unless the process claims its own AppUserModelID; the
                # .ico carries crisp pre-rendered small sizes (16/24/32/48…).
                import ctypes
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                    "eko.deco")
                self.root.iconbitmap(default=ICON_ICO)
                # Do NOT also set iconphoto here: iconphoto's images would come
                # from PhotoImage.subsample (nearest-neighbour decimation, no
                # antialiasing) and Windows lets WM_SETICON override the crisp
                # .ico — that is exactly the fuzzy taskbar icon. The .ico alone
                # is sharp at every size.
                return
            master = tk.PhotoImage(file=ICON_PNG)
            # Several sizes so the taskbar picks the closest instead of scaling
            # one down to a mush at 32 px. Keep every image ≤128 px: Tk 8.6's
            # X11 backend silently writes an EMPTY _NET_WM_ICON when the total
            # icon data gets bigger (a 256 px image already trips it) — that is
            # precisely "no icon in the taskbar" with no error anywhere.
            self._icons = tuple(master.subsample(k) for k in (4, 8, 16))
            self.root.iconphoto(True, *self._icons)
        except Exception:
            # A missing icon must never stop the app from opening.
            pass

    def _build_layout(self) -> None:
        main = ttk.Frame(self.root, padding=6)
        main.pack(fill=tk.BOTH, expand=True)

        left = ttk.LabelFrame(main, text="Dive", padding=8)
        left.pack(side=tk.LEFT, fill=tk.Y)

        # Everything but the settings lives in a notebook so the chart has its
        # own tab instead of a permanent slice of the window: tab 1 is the
        # output panel (MultiDeco-style results + wetnotes), tab 2 the profile.
        self.notebook = ttk.Notebook(main)
        self.notebook.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(6, 0))
        results_tab = ttk.Frame(self.notebook, padding=4)
        profile_tab = ttk.Frame(self.notebook, padding=4)
        self.notebook.add(results_tab, text="Results")
        self.notebook.add(profile_tab, text="Profile")

        results = ttk.LabelFrame(results_tab, text="Results", padding=6)
        runtime_frame = ttk.LabelFrame(results_tab,
                                       text="Runtime — wetnotes (printable)",
                                       padding=6)
        runtime_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(6, 0))
        results.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        # --- model settings first: they apply to the whole dive ---
        self._add_gf_row(left)

        # Strip the theme's vertical padding so the ✕ matches the row height;
        # keep some horizontal padding and center the glyph so it isn't clipped.
        ttk.Style().configure("GasDel.TButton", padding=(4, 0), anchor="center")
        # A bare checkbox still carries the theme's label padding, which pushes
        # the indicator off-centre in its column; drop it.
        ttk.Style().configure("GasUse.TCheckbutton", padding=0)

        # --- levels: the dive profile, deepest first (runtime is cumulative) ---
        levels = ttk.LabelFrame(left, text="Levels", padding=6)
        levels.pack(fill=tk.X, pady=(8, 0))

        # Repetitive dives. Only the PROFILE repeats — gases, GF, SAC and the
        # environment are shared across the day, because that is how a day's
        # diving is actually planned (DECISIONS.md #26). The level rows below
        # always show the selected dive; the others are parked in
        # `_dive_profiles` until switched back to.
        series = ttk.Frame(levels)
        series.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(series, text="Dive").pack(side=tk.LEFT)
        self.dive_pick = ttk.Combobox(series, width=4, state="readonly",
                                      values=["1"])
        self.dive_pick.set("1")
        self.dive_pick.pack(side=tk.LEFT, padx=(3, 6))
        self.dive_pick.bind("<<ComboboxSelected>>",
                            lambda _e: self._select_dive(
                                int(self.dive_pick.get()) - 1))
        ttk.Button(series, text="+ dive", width=7,
                   command=self._add_dive).pack(side=tk.LEFT)
        ttk.Button(series, text="− dive", width=7,
                   command=self._remove_dive).pack(side=tk.LEFT, padx=(2, 6))
        self.surface_interval = tk.StringVar(value="60")
        self.si_label = ttk.Label(series, text="SI")
        self.si_entry = ttk.Spinbox(series, from_=0, to=2880, width=5,
                                    textvariable=self.surface_interval)
        self.si_unit = ttk.Label(series, text="min before")
        self.surface_interval.trace_add(
            "write", lambda *_: None if self._building else self.recompute())
        #: Profiles of every dive in the day. Index 0 is the one on screen at
        #: start; each entry is {"surface_interval_min": float, "levels": [...]}
        #: in the config's own shape, so stashing and saving are the same act.
        self._dive_profiles: list[dict] = [
            {"surface_interval_min": 0.0, "levels": []}]
        self._dive_idx = 0

        self.level_list = ttk.Frame(levels)
        self.level_list.pack(fill=tk.X)
        for col, text in enumerate(("depth m", "runtime", "")):
            ttk.Label(self.level_list, text=text, anchor="w").grid(
                row=0, column=col, padx=1, sticky="w")
        self.level_rows: list[dict] = []
        ttk.Button(levels, text="+ Add level", command=self._add_level_row).pack(
            anchor="w", pady=(4, 0))

        # --- gases (bottom / travel / deco, each with O2/He + tank) ---
        gases = ttk.LabelFrame(left, text="Gases", padding=6)
        gases.pack(fill=tk.X, pady=(8, 0))
        self.gas_list = ttk.Frame(gases)
        self.gas_list.pack(fill=tk.X)
        for col, text in enumerate(("role", "O₂%", "He%", "tank L", "bar", "use")):
            ttk.Label(self.gas_list, text=text,
                      anchor="center" if col == self.GAS_USE_COL else "w").grid(
                row=0, column=col, padx=1, sticky=self.GAS_STICKY[col])
        self.gas_rows: list[dict] = []
        ttk.Button(gases, text="+ Add gas", command=self._add_gas_row).pack(
            anchor="w", pady=(4, 0))

        # --- gas planning (SAC + emergency multiplier; 1–2 divers) ---
        gp = ttk.LabelFrame(left, text="Gas planning (rock bottom)", padding=6)
        gp.pack(fill=tk.X, pady=(8, 0))
        sacrow = ttk.Frame(gp)
        sacrow.pack(fill=tk.X, pady=2)
        self.sac = self._add_spin(sacrow, "SAC", 1, 99, 0.5, 20,
                                  fmt="%.1f", unit="L/min", label_width=7,
                                  unit_width=5)
        self.sac_mult = self._add_spin(sacrow, "Emergency ×", 1.0, 9.0, 0.05, 2.0,
                                       fmt="%.2f")
        # Deco SAC: 0 = "same as the bottom SAC" (the whole-dive single rate).
        # Hanging on a stop is not working the bottom, and MultiDeco/Shearwater
        # plan the two rates apart — see DECISIONS.md #16.
        decorow = ttk.Frame(gp)
        decorow.pack(fill=tk.X, pady=2)
        self.sac_deco = self._add_spin(decorow, "Deco SAC", 0, 99, 0.5, 0,
                                       fmt="%.1f", unit="L/min", label_width=7,
                                       unit_width=5)
        ttk.Label(decorow, text="0 = same as SAC").pack(side=tk.LEFT)
        emrow = ttk.Frame(gp)
        emrow.pack(fill=tk.X, pady=2)
        self.problem_min = self._add_spin(emrow, "Problem", 0, 30, 0.5, 1,
                                          fmt="%.1f", unit="min", label_width=7,
                                          unit_width=5)
        # Buddy out of gas: share the supply until the first gas switch
        self.two_divers = tk.BooleanVar(value=False)
        ttk.Checkbutton(emrow, text="2 divers",
                        variable=self.two_divers).pack(side=tk.LEFT)
        self.two_divers.trace_add(
            "write", lambda *_: None if self._building else self.recompute())

        self._add_algorithm_panel(left)

        # --- contingency cut tables (bottom-timer backup matrix) ---
        cont = ttk.LabelFrame(left, text="Contingency (cut table)", padding=6)
        cont.pack(fill=tk.X, pady=(8, 0))
        self.cont_tb = tk.IntVar(value=1)
        self.cont_ta = tk.IntVar(value=1)
        self.cont_db = tk.IntVar(value=1)
        self.cont_da = tk.IntVar(value=1)
        # Step counts on the fixed 3 min × 3 m grid, one slider per direction.
        # Classic tk.Scale (ttk has no labelled slider); themed in _apply_theme.
        self._cont_scales = tuple(
            tk.Scale(cont, from_=0, to=4, resolution=1, orient=tk.HORIZONTAL,
                     label=label, variable=var)
            for label, var in (("− time (×3 min)", self.cont_tb),
                               ("+ time (×3 min)", self.cont_ta),
                               ("− depth (×3 m)", self.cont_db),
                               ("+ depth (×3 m)", self.cont_da)))
        for i, scale in enumerate(self._cont_scales):
            scale.configure(command=lambda _v: None if self._building
                            else self.recompute())
            scale.grid(row=i // 2, column=i % 2, sticky="ew", padx=2)
        cont.columnconfigure(0, weight=1)
        cont.columnconfigure(1, weight=1)

        # --- Settings menu: dark mode (ui_settings.json, not the dive plan) ---
        self.dark = tk.BooleanVar(value=bool(self._ui_settings.get("dark_mode")))
        self.dark.trace_add("write", self._on_dark_toggle)
        menubar = tk.Menu(self.root)
        settings_menu = tk.Menu(menubar, tearoff=0)
        settings_menu.add_checkbutton(label="Dark mode", variable=self.dark)
        menubar.add_cascade(label="Settings", menu=settings_menu)
        self.root.config(menu=menubar)

        # --- config file save / reload ---
        cfgrow = ttk.Frame(left)
        cfgrow.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(cfgrow, text="Save", command=self._save_config).pack(side=tk.LEFT)
        ttk.Button(cfgrow, text="Reload", command=self._reload_config).pack(
            side=tk.LEFT, padx=4)
        self.cfg_status = ttk.Label(cfgrow, text=os.path.basename(dc.default_path()))
        self.cfg_status.pack(side=tk.LEFT, padx=4)

        # --- results panel (scrollable) ---
        self.readout = tk.Text(results, width=58, height=28, wrap="none",
                               font=("Consolas", 10),
                               relief="flat", bg=self.root.cget("bg"))
        scroll = ttk.Scrollbar(results, command=self.readout.yview)
        xscroll = ttk.Scrollbar(results, orient="horizontal",
                                command=self.readout.xview)
        self.readout.configure(yscrollcommand=scroll.set,
                               xscrollcommand=xscroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        xscroll.pack(side=tk.BOTTOM, fill=tk.X)
        self.readout.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # --- runtime "wetnotes" card (bottom-right, printable) ---
        rt_body = ttk.Frame(runtime_frame)
        rt_body.pack(fill=tk.BOTH, expand=True)
        self.runtime_text = tk.Text(rt_body, width=66, height=18, wrap="none",
                                    font=("Consolas", 9), relief="flat",
                                    bg=self.root.cget("bg"))
        rt_scroll = ttk.Scrollbar(rt_body, command=self.runtime_text.yview)
        rt_xscroll = ttk.Scrollbar(rt_body, orient="horizontal",
                                   command=self.runtime_text.xview)
        self.runtime_text.configure(yscrollcommand=rt_scroll.set,
                                    xscrollcommand=rt_xscroll.set)
        rt_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        rt_xscroll.pack(side=tk.BOTTOM, fill=tk.X)
        self.runtime_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        rt_btns = ttk.Frame(runtime_frame)
        rt_btns.pack(fill=tk.X, pady=(4, 0))
        ttk.Button(rt_btns, text="Export PNG",
                   command=self._export_runtime).pack(side=tk.LEFT)
        ttk.Button(rt_btns, text="Copy",
                   command=self._copy_runtime).pack(side=tk.LEFT, padx=4)
        self.runtime_status = ttk.Label(rt_btns, text="")
        self.runtime_status.pack(side=tk.LEFT, padx=4)

        # --- chart (Profile tab) ---
        self.fig = Figure(figsize=(5.4, 5.2), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.fig, master=profile_tab)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        # A TkAgg canvas drawn while its tab is unmapped can come up blank on
        # first reveal; repaint whenever the tab changes.
        self.notebook.bind("<<NotebookTabChanged>>",
                           lambda _e: self.canvas.draw_idle())

    # ------------------------------------------------------------- theme ----

    @property
    def _pal(self) -> dict:
        return DARK if self.dark.get() else LIGHT

    def _apply_theme(self) -> None:
        p = self._pal
        style = ttk.Style()
        style.configure(".", background=p["bg"], foreground=p["fg"],
                        fieldbackground=p["field"], troughcolor=p["trough"],
                        bordercolor=p["border"], lightcolor=p["bg"],
                        darkcolor=p["bg"], insertcolor=p["fg"],
                        arrowcolor=p["fg"])
        for w in ("TCombobox", "TSpinbox"):
            style.map(w, fieldbackground=[("readonly", p["field"])],
                      foreground=[("readonly", p["fg"])])
        style.map("TButton", background=[("active", p["active"])])
        style.map("TCheckbutton", background=[("active", p["bg"])])
        # Notebook tabs need explicit state maps under clam or the selected tab
        # keeps the theme's light default.
        style.configure("TNotebook", background=p["bg"], bordercolor=p["border"])
        style.configure("TNotebook.Tab", background=p["trough"],
                        foreground=p["fg"], padding=(10, 4))
        style.map("TNotebook.Tab",
                  background=[("selected", p["bg"]), ("active", p["active"])],
                  foreground=[("selected", p["fg"])])
        # A scrollbar with nothing to scroll (e.g. the runtime card when it
        # fits) is in the "disabled" state; clam paints that thumb with its
        # light default, so map every state back onto the palette.
        for bar in ("Vertical.TScrollbar", "Horizontal.TScrollbar"):
            style.map(bar,
                      background=[("disabled", p["bg"]), ("active", p["active"])],
                      arrowcolor=[("disabled", p["fg"])])
        # The combobox dropdown is a plain Tk listbox; option_add styles it on
        # creation (existing popdowns keep their colors until reopened).
        self.root.option_add("*TCombobox*Listbox.background", p["field"])
        self.root.option_add("*TCombobox*Listbox.foreground", p["fg"])
        self.root.configure(bg=p["bg"])
        for txt in (self.readout, self.runtime_text):
            txt.configure(bg=p["bg"], fg=p["fg"], insertbackground=p["fg"])
        # tk.Scale is a classic (non-ttk) widget: style it by hand like the Texts.
        for scale in self._cont_scales:
            scale.configure(bg=p["bg"], fg=p["fg"], troughcolor=p["trough"],
                            activebackground=p["active"], highlightthickness=0)

    def _on_close(self) -> None:
        # Window size/position is a UI preference like dark mode: it goes to
        # ui_settings.json on close, never into the shareable dive config.
        # An unmapped/iconified window reports 1x1+0+0 — don't persist that,
        # it would shrink the next launch to nothing.
        geom = self.root.geometry()
        try:
            w, h = (int(v) for v in geom.split("+", 1)[0].split("x"))
            if w >= 200 and h >= 200:
                self._ui_settings["geometry"] = geom
                save_ui_settings(self._ui_settings)
        except ValueError:
            pass
        self.root.destroy()

    def _on_dark_toggle(self, *_) -> None:
        self._apply_theme()
        self._ui_settings["dark_mode"] = bool(self.dark.get())
        save_ui_settings(self._ui_settings)
        if not self._building:
            self.recompute()               # restyle the chart with the new palette

    def _add_spin(self, row, label, lo, hi, increment, init,
                  width: int = 5, fmt: str | None = None, unit: str = "",
                  label_width: int | Literal[""] = "",
                  unit_width: int | Literal[""] = "") -> tk.StringVar:
        """Labelled numeric up/down packed onto `row` (several fit one line).
        `unit` goes after the input; `label_width`/`unit_width` align the
        inputs and whatever follows them across rows (Tk's own "unset" for a
        width is the empty string, not 0)."""
        ttk.Label(row, text=label, width=label_width).pack(side=tk.LEFT)
        var = tk.StringVar(value=(fmt % init) if fmt else f"{init:g}")
        kwargs: dict[str, Any] = {"format": fmt} if fmt else {}
        ttk.Spinbox(row, from_=lo, to=hi, increment=increment, width=width,
                    textvariable=var, **kwargs).pack(
            side=tk.LEFT, padx=(4, 2 if unit else 10))
        if unit:
            ttk.Label(row, text=unit, width=unit_width).pack(
                side=tk.LEFT, padx=(0, 10))
        # Recompute from a variable trace, not the Spinbox command, so a
        # programmatic var.set() (loading dive_plan.json) refreshes too.
        var.trace_add("write",
                      lambda *_: None if self._building else self.recompute())
        return var

    def _num(self, var, default: float, lo: float | None = None) -> float:
        """Float value of a spinbox var; `default` while the entry is mid-edit."""
        try:
            v = float(var.get())
        except (ValueError, tk.TclError):
            return default
        return v if lo is None else max(lo, v)

    def _add_gf_row(self, parent) -> None:
        row = ttk.Frame(parent)
        row.pack(fill=tk.X, pady=2)
        ttk.Label(row, text="GF low / high (%)").pack(side=tk.LEFT)
        self.gf_hi = tk.StringVar(value="70")
        self.gf_lo = tk.StringVar(value="30")
        ttk.Spinbox(row, from_=5, to=100, width=4, textvariable=self.gf_lo).pack(
            side=tk.LEFT, padx=(6, 1))
        ttk.Label(row, text="/").pack(side=tk.LEFT)
        ttk.Spinbox(row, from_=5, to=100, width=4, textvariable=self.gf_hi).pack(
            side=tk.LEFT, padx=1)
        # Shearwater/MultiDeco-style shallowest stop: off = 3 m, on = 6 m
        self.last_stop6 = tk.BooleanVar(value=False)
        ttk.Checkbutton(row, text="Last stop 6 m",
                        variable=self.last_stop6).pack(side=tk.LEFT, padx=(10, 0))
        for v in (self.gf_lo, self.gf_hi, self.last_stop6):
            v.trace_add("write", lambda *_: None if self._building else self.recompute())
        self._add_water_row(parent)

    def _add_water_row(self, parent) -> None:
        """Environment: water type, altitude and surface pressure. All of them
        move every pressure the plan derives (schedule, ppO₂, MOD, density, gas
        volumes), so they sit with the GF row at the top rather than in a
        preferences dialog.

        ``msw_per_bar`` and ``surface_p`` are the stored truth; the dropdown and
        the altitude box are just convenient ways of typing them, and both stay
        editable so a constant taken from another planner (MultiDeco's 1.0 bar
        surface, say) can go in directly."""
        row = ttk.Frame(parent)
        row.pack(fill=tk.X, pady=2)
        ttk.Label(row, text="Water").pack(side=tk.LEFT)
        self.water = tk.StringVar(value="salt")
        ttk.Combobox(row, textvariable=self.water, width=7, state="readonly",
                     values=[*sorted(b.WATER_TYPES), "custom"]).pack(
            side=tk.LEFT, padx=(6, 8))
        self.msw_per_bar = self._add_spin(row, "m/bar", 5.0, 15.0, 0.1,
                                          b.MSW_PER_BAR, fmt="%.6g", width=8)
        alt = ttk.Frame(parent)
        alt.pack(fill=tk.X, pady=2)
        self.altitude = self._add_spin(alt, "Altitude", 0, 5000, 50, 0,
                                       fmt="%.0f", unit="m", label_width=7,
                                       unit_width=5)
        self.surface_p = self._add_spin(alt, "surface", 0.4, 1.2, 0.005, b.P_ATM,
                                        fmt="%.6g", unit="bar", width=8)
        self.water.trace_add("write", self._on_water_type)
        self.altitude.trace_add("write", self._on_altitude)

    def _add_algorithm_panel(self, parent) -> None:
        """Every remaining planner input, in one collapsed-by-default block.

        These were config-file-only before: the GUI read them from
        ``dive_plan.json`` and wrote them back untouched, so a dive planned in
        the app silently used whatever was in the file and there was no way to
        see or change it. Every input to the algorithm is now reachable from
        all three front ends (DECISIONS.md #19), and `test_input_coverage`
        fails if a new one is added without a widget.

        Collapsed by default because these are not per-dive knobs — the
        defaults are the agencies' — but visible, not hidden."""
        box = ttk.LabelFrame(parent, text="Algorithm & rates", padding=6)
        box.pack(fill=tk.X, pady=(8, 0))
        self.algo_open = tk.BooleanVar(value=False)
        body = ttk.Frame(box)
        ttk.Checkbutton(box, text="show", variable=self.algo_open,
                        command=lambda: body.pack(fill=tk.X)
                        if self.algo_open.get() else body.pack_forget()).pack(
            anchor="w")

        rates = ttk.Frame(body)
        rates.pack(fill=tk.X, pady=2)
        self.descent_rate = self._add_spin(rates, "Descent", 1, 60, 1, 18.0,
                                           fmt="%g", unit="m/min",
                                           label_width=8, unit_width=6)
        self.ascent_rate = self._add_spin(rates, "ascent", 1, 30, 1, 10.0,
                                          fmt="%g", unit="m/min", unit_width=6)
        stops = ttk.Frame(body)
        stops.pack(fill=tk.X, pady=2)
        self.stop_interval = self._add_spin(stops, "Stops", 1, 10, 1, 3.0,
                                            fmt="%g", unit="m apart",
                                            label_width=8, unit_width=7)
        # Free value; the "Last stop 6 m" switch by the GF row is the common
        # case and writes this box, but 9 m (say) is now expressible.
        self.last_stop = self._add_spin(stops, "last", 0, 12, 3, 3.0,
                                        fmt="%g", unit="m", unit_width=6)
        pp = ttk.Frame(body)
        pp.pack(fill=tk.X, pady=2)
        self.ppo2_bottom = self._add_spin(pp, "ppO₂", 0.5, 2.0, 0.05, 1.4,
                                          fmt="%.2f", unit="bottom",
                                          label_width=8, unit_width=7)
        self.ppo2_deco = self._add_spin(pp, "", 0.5, 2.0, 0.05, 1.6,
                                        fmt="%.2f", unit="deco", unit_width=6)
        pp2 = ttk.Frame(body)
        pp2.pack(fill=tk.X, pady=2)
        self.ppo2_min = self._add_spin(pp2, "", 0.0, 0.5, 0.01, 0.18,
                                       fmt="%.2f", unit="min", label_width=8,
                                       unit_width=7)
        self.ppo2_switch_tol = self._add_spin(pp2, "", 0.0, 0.5, 0.01, 0.05,
                                              fmt="%.2f", unit="switch tol",
                                              unit_width=10)
        sw = ttk.Frame(body)
        sw.pack(fill=tk.X, pady=2)
        ttk.Label(sw, text="Gas switch", width=8).pack(side=tk.LEFT)
        self.gas_switch_policy = tk.StringVar(value="at-mod")
        ttk.Combobox(sw, textvariable=self.gas_switch_policy, width=13,
                     state="readonly",
                     values=sorted(b.GAS_SWITCH_POLICIES)).pack(side=tk.LEFT)
        ttk.Label(sw, text="at-first-stop holds the switch until you stop"
                  ).pack(side=tk.LEFT, padx=(6, 0))
        self.gas_switch_policy.trace_add(
            "write", lambda *_: self.recompute())
        grid = ttk.Frame(body)
        grid.pack(fill=tk.X, pady=2)
        self.min_stop_time = self._add_spin(grid, "Stop grid", 0.1, 10.0, 0.1,
                                            1.0, fmt="%g", unit="min",
                                            label_width=8, unit_width=6)
        ttk.Label(grid, text="runtime rounds onto this").pack(side=tk.LEFT)
        model = ttk.Frame(body)
        model.pack(fill=tk.X, pady=2)
        self.p_h2o = self._add_spin(model, "P H₂O", 0.0001, 0.2, 0.001,
                                    b.P_H2O, fmt="%.4f", unit="bar",
                                    label_width=8, unit_width=6, width=7)
        ttk.Label(model, text="0.0627 Bühlmann · 0.0567 Schreiner").pack(
            side=tk.LEFT)
        # Keep the shorthand switch and the free field in step.
        self.last_stop6.trace_add(
            "write", lambda *_: None if self._building else
            self.last_stop.set("6" if self.last_stop6.get() else "3"))

    def _on_water_type(self, *_) -> None:
        """Water dropdown → msw/bar. Setting the spinbox var fires its own
        trace, so the recompute happens there; don't kick off a second one.
        'custom' is a label for a hand-typed value, not a preset — selecting it
        changes nothing."""
        mpb = b.WATER_TYPES.get(self.water.get())
        if mpb is not None:
            self.msw_per_bar.set(f"{mpb:.6g}")

    def _on_altitude(self, *_) -> None:
        """Altitude → surface pressure by the standard atmosphere. One-way: the
        pressure box stays hand-editable (a planner's constant may not
        correspond to any altitude), and typing there does not rewrite the
        altitude, which would fight the user mid-edit."""
        if self._building:
            return
        self.surface_p.set(
            f"{b.surface_p_at_altitude(self._num(self.altitude, 0.0, lo=0.0)):.6g}")

    def _add_level_row(self, depth: float = 30, runtime: float = 40,
                       recompute: bool = True) -> None:
        depth_var = tk.StringVar(value=f"{depth:g}")
        run_var = tk.StringVar(value=f"{runtime:g}")

        # Columns: depth · runtime · delete. "runtime" is cumulative minutes
        # since the surface at the END of the level, transit included — levels
        # are contiguous, exactly as MultiDeco/GFDECO/Subsurface define them.
        widgets: list[tk.Widget] = [
            ttk.Spinbox(self.level_list, from_=1, to=300, width=5,
                        textvariable=depth_var),
            ttk.Spinbox(self.level_list, from_=1, to=999, width=5,
                        textvariable=run_var),
        ]
        row = {"widgets": widgets, "depth": depth_var, "runtime": run_var}
        widgets.append(ttk.Button(self.level_list, text="✕", width=2,
                                  style="GasDel.TButton",
                                  command=lambda: self._remove_level_row(row)))
        for var in (depth_var, run_var):
            var.trace_add(
                "write", lambda *_: None if self._building else self.recompute())
        self.level_rows.append(row)
        self._regrid_level_rows()
        if recompute and not self._building:
            self.recompute()

    def _regrid_level_rows(self) -> None:
        for i, row in enumerate(self.level_rows, start=1):
            for col, w in enumerate(row["widgets"]):
                w.grid(row=i, column=col, padx=1, pady=1, sticky="w")

    def _remove_level_row(self, row) -> None:
        if len(self.level_rows) <= 1:       # a dive needs at least one level
            return
        if row in self.level_rows:
            self.level_rows.remove(row)
            for w in row["widgets"]:
                w.destroy()
            self._regrid_level_rows()
            if not self._building:
                self.recompute()

    # ------------------------------------------------------- dive series ----

    def _stash_dive(self) -> None:
        """Park the level rows on screen back into the selected dive.

        Uses `_row_levels`, not `_levels`: a field blanked mid-edit must survive
        switching dives, exactly as it survives saving."""
        self._dive_profiles[self._dive_idx]["levels"] = [
            self._level_row_dict(rl) for rl in self._row_levels()]
        if self._dive_idx:
            self._dive_profiles[self._dive_idx]["surface_interval_min"] = (
                self._num(self.surface_interval, 60.0, lo=0.0))

    def _show_dive(self, idx: int) -> None:
        """Rebuild the level rows from dive `idx`. Caller has already stashed."""
        self._dive_idx = idx
        was_building, self._building = self._building, True
        try:
            for row in list(self.level_rows):
                for w in row["widgets"]:
                    w.destroy()
            self.level_rows.clear()
            for lv in self._dive_profiles[idx]["levels"] or [
                    {"depth_m": 30.0, "runtime_min": 40.0}]:
                self._add_level_row(lv["depth_m"], lv["runtime_min"],
                                    recompute=False)
            self.dive_pick.configure(
                values=[str(i + 1) for i in range(len(self._dive_profiles))])
            self.dive_pick.set(str(idx + 1))
            self.surface_interval.set(
                f"{self._dive_profiles[idx]['surface_interval_min']:g}")
            # Dive 1 starts on clean tissues: there is no interval in front of
            # it, so the field is hidden rather than shown reading zero.
            for w in (self.si_label, self.si_entry, self.si_unit):
                w.pack_forget()
            if idx:
                self.si_label.pack(side=tk.LEFT)
                self.si_entry.pack(side=tk.LEFT, padx=2)
                self.si_unit.pack(side=tk.LEFT)
        finally:
            self._building = was_building

    def _select_dive(self, idx: int) -> None:
        self._stash_dive()
        self._show_dive(idx)
        self.recompute()

    def _add_dive(self) -> None:
        """A new dive after the current last one, seeded from the one on screen —
        a second dive on the same site is the common case, and an empty profile
        would only have to be retyped."""
        self._stash_dive()
        self._dive_profiles.append({
            "surface_interval_min": 60.0,
            "levels": [dict(lv) for lv in
                       self._dive_profiles[self._dive_idx]["levels"]]})
        self._show_dive(len(self._dive_profiles) - 1)
        self.recompute()

    def _remove_dive(self) -> None:
        if len(self._dive_profiles) <= 1:      # a day needs at least one dive
            return
        self._stash_dive()
        self._dive_profiles.pop(self._dive_idx)
        self._show_dive(min(self._dive_idx, len(self._dive_profiles) - 1))
        self.recompute()

    def _series(self) -> list[tuple[float, list[b.Level]]]:
        """The whole day as `(surface_interval, levels)`, plannable rows only.

        Mirrors `_levels()` rather than `_row_levels()`: a half-typed row is
        skipped so the plan does not blow up mid-keystroke. A dive left with no
        plannable level at all is dropped from the series — it cannot be planned
        and must not silently shift the residual loading of the dives after it."""
        self._stash_dive()
        out: list[tuple[float, list[b.Level]]] = []
        for i, prof in enumerate(self._dive_profiles):
            levels = [b.Level(lv["depth_m"], lv["runtime_min"])
                      for lv in prof["levels"]
                      if lv["depth_m"] > 0 and lv["runtime_min"] > 0]
            if levels:
                out.append((0.0 if not i else prof["surface_interval_min"],
                            levels))
        return out

    def _row_levels(self) -> list[_RowLevel]:
        """Every level row exactly as typed — never drops one. This is what gets
        saved: a field left blank mid-edit must not silently delete the level."""
        return [_RowLevel(self._num(row["depth"], 0.0, lo=0.0),
                          self._num(row["runtime"], 0.0, lo=0.0))
                for row in self.level_rows]

    @staticmethod
    def _level_row_dict(rl: _RowLevel) -> dict:
        """Serialize a row to the config shape."""
        return {"depth_m": rl.depth, "runtime_min": rl.runtime}

    def _levels(self) -> list[b.Level]:
        """The rows that can actually be planned — a row being edited (blank or
        zero depth/runtime) is skipped so the plan doesn't blow up mid-keystroke.
        Use `_row_levels` when persisting, so nothing is lost."""
        return [b.Level(r.depth, r.runtime)
                for r in self._row_levels() if r.depth > 0 and r.runtime > 0]

    # The bare "use" checkbox is much narrower than its header, so left-aligning
    # both (like every other column) leaves it visibly adrift under the label.
    # Centre that one column — header and box — so they line up.
    GAS_USE_COL = 5
    GAS_STICKY = ("w", "w", "w", "w", "w", "", "w")   # role..bar, use, ✕

    def _add_gas_row(self, role: str = "Deco", fo2: float = 50, fhe: float = 0,
                     tank: float = 11, pressure: float = 232,
                     enabled: bool = True, recompute: bool = True) -> None:
        role_var = tk.StringVar(value=role)
        fo2_var = tk.StringVar(value=str(int(fo2)))
        fhe_var = tk.StringVar(value=str(int(fhe)))
        tank_var = tk.StringVar(value=str(int(tank)))
        press_var = tk.StringVar(value=str(int(pressure)))
        use_var = tk.BooleanVar(value=enabled)     # unticked = don't count

        widgets: list[tk.Widget] = [
            ttk.Combobox(self.gas_list, textvariable=role_var, width=6,
                         state="readonly", values=dc.ROLES),
            ttk.Spinbox(self.gas_list, from_=5, to=100, width=4, textvariable=fo2_var),
            ttk.Spinbox(self.gas_list, from_=0, to=95, width=4, textvariable=fhe_var),
            ttk.Spinbox(self.gas_list, from_=0, to=30, width=5, textvariable=tank_var),
            ttk.Spinbox(self.gas_list, from_=0, to=300, width=4, textvariable=press_var),
        ]

        row = {"widgets": widgets, "role": role_var, "fo2": fo2_var,
               "fhe": fhe_var, "tank": tank_var, "pressure": press_var,
               "use": use_var}
        widgets.append(ttk.Checkbutton(self.gas_list, variable=use_var,
                                       style="GasUse.TCheckbutton"))
        widgets.append(ttk.Button(self.gas_list, text="✕", width=2,
                                  style="GasDel.TButton",
                                  command=lambda: self._remove_gas_row(row)))
        for var in (role_var, fo2_var, fhe_var, tank_var, press_var, use_var):
            var.trace_add("write",
                          lambda *_: None if self._building else self.recompute())
        self.gas_rows.append(row)
        self._regrid_gas_rows()
        if recompute and not self._building:
            self.recompute()

    def _regrid_gas_rows(self) -> None:
        # Shares columns with the header (row 0) so labels line up over the
        # fields regardless of each widget's own decoration width (spin
        # arrows, combobox dropdown) — a plain pack() can't guarantee that.
        for i, row in enumerate(self.gas_rows, start=1):
            for col, w in enumerate(row["widgets"]):
                w.grid(row=i, column=col, padx=1, pady=1,
                       sticky=self.GAS_STICKY[col])

    def _remove_gas_row(self, row) -> None:
        if row in self.gas_rows:
            self.gas_rows.remove(row)
            for w in row["widgets"]:
                w.destroy()
            self._regrid_gas_rows()
            if not self._building:
                self.recompute()

    def _row_gas(self, row):
        if not row["use"].get():               # unticked: gas doesn't count
            return None
        try:
            fo2 = float(row["fo2"].get()) / 100.0
            fhe = float(row["fhe"].get() or 0) / 100.0
        except (ValueError, tk.TclError):
            return None
        if not (0.0 < fo2 <= 1.0) or not (0.0 <= fhe < 1.0) or fo2 + fhe > 1.0 + 1e-9:
            return None
        return b.Gas(fo2, fhe)

    def _row_tank(self, row) -> float:
        try:
            return float(row["tank"].get())
        except (ValueError, tk.TclError):
            return 0.0

    def _row_pressure(self, row) -> float:
        try:
            return float(row["pressure"].get())
        except (ValueError, tk.TclError):
            return 0.0

    def _pct(self, var, default: float) -> float:
        try:
            return max(1.0, min(100.0, float(var.get()))) / 100.0
        except (ValueError, tk.TclError):
            return default

    def _gas_rows_raw(self) -> list[tuple[str, b.Gas, float, float]]:
        """(role, Gas, tank_l, pressure_bar) for every valid gas row — the raw
        input the shared report layer (`rp.gas_report` / `rp.aggregate_banks`)
        consumes. Keyed downstream by the frozen ``Gas`` value, never its rounded
        display label — two mixes that render the same (e.g. 20.6% and 21.4%
        both 'AIR') keep separate accounting."""
        return [(row["role"].get(), g, self._row_tank(row),
                 self._row_pressure(row))
                for row in self.gas_rows
                for g in (self._row_gas(row),) if g is not None]

    def _banks_by_gas(self) -> dict:
        """{Gas: rp.Bank} across the gas rows, same-mix cylinders aggregated
        into one manifolded bank (`report.aggregate_banks`)."""
        return {bank.gas: bank
                for bank in rp.aggregate_banks(self._gas_rows_raw())}

    def _gas_plan(self) -> b.GasPlan:
        """Consumption inputs (SAC, deco SAC, emergency multiplier, problem
        minutes, team size) from the UI as a ``buhlmann.GasPlan``."""
        deco = self._num(self.sac_deco, 0.0, lo=0.0)
        return b.GasPlan(sac=self._num(self.sac, 20.0, lo=1.0),
                         sac_deco=deco if deco > 0 else None,
                         sac_multiplier=self._num(self.sac_mult, 2.0, lo=1.0),
                         problem_minutes=self._num(self.problem_min, 1.0, lo=0.0),
                         divers=2 if self.two_divers.get() else 1)

    # ----------------------------------------------------------- compute ----

    def _bottom_gas(self) -> b.Gas:
        for row in self.gas_rows:
            if row["role"].get() == "Bottom":
                g = self._row_gas(row)
                if g is not None:
                    return g
        for row in self.gas_rows:            # fallback: first valid gas
            g = self._row_gas(row)
            if g is not None:
                return g
        return b.AIR

    def _make_plan(self) -> b.DivePlan:
        travel: list[b.Gas] = []
        deco: list[b.Gas] = []
        for row in self.gas_rows:
            g = self._row_gas(row)
            role = row["role"].get()
            if g is None or role == "Bottom":
                continue
            (travel if role == "Travel" else deco).append(g)
        # Every field below comes from a widget now — nothing is read straight
        # from the config any more (DECISIONS.md #19).
        return b.DivePlan(
            gf_low=self._pct(self.gf_lo, 0.30),
            gf_high=self._pct(self.gf_hi, 0.70),
            ascent_rate=self._num(self.ascent_rate, ASCENT_RATE, lo=0.5),
            descent_rate=self._num(self.descent_rate, 18.0, lo=0.5),
            stop_interval=self._num(self.stop_interval, 3.0, lo=0.5),
            last_stop_depth=self._num(self.last_stop, 3.0, lo=0.0),
            ppo2_bottom=self._num(self.ppo2_bottom, 1.4, lo=0.1),
            ppo2_deco=self._num(self.ppo2_deco, 1.6, lo=0.1),
            ppo2_min=self._num(self.ppo2_min, 0.18, lo=0.0),
            ppo2_switch_tol=self._num(self.ppo2_switch_tol, 0.05, lo=0.0),
            gas_switch_policy=self.gas_switch_policy.get(),
            min_stop_time=self._num(self.min_stop_time, 1.0, lo=0.01),
            p_h2o=self._num(self.p_h2o, b.P_H2O, lo=0.0001),
            surface_p=self._num(self.surface_p, b.P_ATM, lo=0.1),
            msw_per_bar=self._num(self.msw_per_bar, b.MSW_PER_BAR, lo=1.0),
            deco_gases=tuple(deco),
            travel_gases=tuple(travel),
        )

    def recompute(self) -> None:
        series = self._series()
        if not series:                      # every row mid-edit / emptied
            self._error("⚠ profile incomplete — add a level with a depth and "
                        "runtime")
            return
        gas = self._bottom_gas()

        try:
            plan = self._make_plan()        # validates the gradient factors
            # ONE PlanResult per dive, exactly as cmd_plan builds them: every
            # figure the readout prints is read off it rather than re-derived
            # here. The GUI used to call plan_multilevel itself and then
            # recompute density, CNS/OTU, END, the final ceiling and the whole
            # gas accounting inline — at sea-level salt and with no deco stack,
            # so an altitude or deco-SAC dive showed different numbers from the
            # CLI on the same config (DECISIONS.md #24).
            results = rp.compute_series_result(series, gas, plan,
                                               self._gas_plan(),
                                               self._gas_rows_raw())
        except (ValueError, RuntimeError) as e:
            self._error(f"Plan error: {e}")
            return

        # A dive with no plannable level is dropped from the series, so the
        # selected index can outrun the results; show the last one rather than
        # crash mid-keystroke.
        res = results[min(self._dive_idx, len(results) - 1)]
        levels = res.levels
        scenarios = self._lost_gas_scenarios(levels, gas, plan, res.segments,
                                             res.bailout)
        self._draw(res.segments, res.max_depth_m, levels[-1].runtime,
                   b.ceiling_profile(res.segments, plan), levels)
        self._write_readout(res, scenarios, results)
        self._write_runtime(res, scenarios)
        self._plan_ok = True                # a valid plan is now on every surface

    def _lost_gas_scenarios(self, levels, gas, plan, segs,
                            bailout=None) -> list[tuple[str, list]]:
        """Contingency schedules for losing deco gas, MultiDeco-style: the normal
        dive ("OK"), then one re-plan per deco gas without it, and — with two or
        more deco gases — an "all" worst case with every deco gas gone. Only
        Deco-role gases can be lost; bottom and travel gases always stay. Works
        for any number of deco gases (nothing assumes two).

        A lost gas is simply dropped from the deco stack; levels never name a
        gas (selection is automatic by role), so nothing else needs rewriting.

        Losing the BOTTOM gas is a different question and gets a different
        answer: the bottom phase already happened, so it is not re-planned —
        only the ascent is re-flown on what is left (`buhlmann.bailout_schedule`).
        Its column appears only when that is actually survivable, which on most
        deep dives it is not: with the back gas gone and every stage above its
        MOD there is no schedule to print, and a column that quietly showed one
        anyway would be the most dangerous cell on the card."""
        scenarios: list[tuple[str, list]] = [("OK", segs)]
        deco = plan.deco_gases
        losses = [(repr(g), (g,)) for g in deco]        # (label, gases lost)
        if len(deco) > 1:
            losses.append(("all", tuple(deco)))
        for label, lost in losses:
            remaining = tuple(d for d in deco if d not in lost)
            try:
                lost_segs, _ = b.plan_multilevel(
                    levels, gas, replace(plan, deco_gases=remaining))
            except (ValueError, RuntimeError):
                continue       # a scenario that can't be planned (e.g. hypoxic
                               # gap) just drops its column
            scenarios.append((label, lost_segs))
        if bailout is not None:
            scenarios.append(("bottom gas", bailout))
        return scenarios

    @staticmethod
    def _stops_by_depth(segs) -> tuple[dict, float]:
        """{stop depth (m): (leg minutes, runtime leaving)} + total RT.

        Keyed on the stop's own depth, not on `round(depth)`: with a 0.5 m
        stop interval — which the settings panel allows — 6.0 m and 6.5 m
        would round to the same key and one of the two stops would vanish
        from the table without a trace.

        Both numbers are `buhlmann.StopLeg`'s, the same notation the runtime
        card and the cut table print: the runtime is when you **leave** that
        depth (truncated to whole minutes), and the minutes are the **leg** —
        the ascent to the stop plus the hold, measured from the previous stop
        (from leaving the bottom for the first) — so the column adds up to the
        runtimes beside it."""
        legs = b.stop_legs(segs)
        at = {leg.depth: (leg.leg, leg.run) for leg in legs}
        return at, b.total_runtime(segs)

    # -------------------------------------------------------------- draw ----

    def _draw(self, segs, bottom_depth: float, bottom_time: float,
              ceil_pts=None, levels=None) -> None:
        t, d = build_profile_points(segs)
        p = self._pal
        self.ax.clear()

        self.ax.plot(t, d, color="#1f77b4", linewidth=2, label="Bühlmann GF")
        self.ax.fill_between(t, d, max(d) * 1.05 + 1, color="#1f77b4", alpha=0.10)
        x_max = max(t)

        # Deco ceiling, planner-style: a dashed line with a translucent curtain
        # hanging from the surface (the y-axis is inverted below). NaN-mask the
        # deco-free stretches so no line hugs depth 0 between them.
        if ceil_pts and any(c > 0.05 for _, c in ceil_pts):
            ct = [q[0] for q in ceil_pts]
            cd = [q[1] for q in ceil_pts]
            self.ax.plot(ct, [c if c > 0.05 else float("nan") for c in cd],
                         color=p["ceiling"], linewidth=1.4, linestyle="--",
                         label="ceiling")
            self.ax.fill_between(ct, 0.0, cd, where=[c > 0.05 for c in cd],
                                 color=p["ceiling"], alpha=0.12, linewidth=0)
            leg = self.ax.legend(loc="lower right", fontsize=8,
                                 facecolor=p["chart_bg"], edgecolor=p["grid"])
            for text in leg.get_texts():
                text.set_color(p["chart_fg"])

        run_t, prev = 0.0, None
        for s in segs:
            if s.kind == "stop" and s.duration > 0:
                self.ax.plot([run_t, run_t + s.duration], [s.depth_start, s.depth_end],
                             color="#d62728", linewidth=3)
                self.ax.annotate(
                    f"{round(s.duration)}′ @ {s.depth_start:.0f} m",
                    xy=(run_t + s.duration / 2, s.depth_start),
                    xytext=(0, -14), textcoords="offset points",
                    ha="center", fontsize=8, color="#d62728")
            # By value, not by printed label — two mixes can share one (#8).
            if prev is not None and s.gas != prev:
                self.ax.plot([run_t], [s.depth_start], marker="o",
                             color="#2ca02c", markersize=5, zorder=5)
                self.ax.annotate(repr(s.gas), xy=(run_t, s.depth_start),
                                 xytext=(4, 7), textcoords="offset points",
                                 fontsize=7, color="#2ca02c")
            prev = s.gas
            run_t += s.duration

        self.fig.patch.set_facecolor(p["chart_bg"])
        self.ax.set_facecolor(p["chart_bg"])
        self.ax.tick_params(colors=p["chart_fg"])
        for spine in self.ax.spines.values():
            spine.set_color(p["chart_fg"])
        self.ax.set_xlabel("Runtime (min)", color=p["chart_fg"])
        self.ax.set_ylabel("Depth (m)", color=p["chart_fg"])
        # On a multi-level dive "bottom X m for Y min" misdescribes the profile;
        # spell the levels out (same depth@runtime shorthand as the wetnotes).
        if levels and len(levels) > 1:
            what = " → ".join(f"{l.depth:.0f}m@{l.runtime:.0f}" for l in levels)
        else:
            what = f"bottom {bottom_depth:.0f} m for {bottom_time:.0f} min"
        self.ax.set_title(
            f"Profile  —  {what} "
            f"(total {sum(s.duration for s in segs):.0f} min)",
            color=p["chart_fg"])
        self.ax.invert_yaxis()
        self.ax.grid(True, alpha=0.3, color=p["grid"])
        self.ax.set_xlim(0, x_max * 1.02 + 1)
        self.ax.set_ylim(max(d) * 1.10 + 2, 0)
        self.fig.tight_layout()
        self.canvas.draw_idle()

    # ----------------------------------------------------------- readout ----

    def _write_readout(self, res: rp.PlanResult, scenarios=None,
                       series=None) -> None:
        """Assemble the Results tab from one `PlanResult`.

        Each card is built by its own small method taking `res` and returning
        lines. This method decides the ORDER of the cards and nothing else — it
        holds no arithmetic, which is what keeps DECISIONS #8 and #24 true by
        construction rather than by everyone remembering. It was a single
        252-line block with nine parameters, and every number it derived inline
        was eventually derived wrongly.
        """
        cards: list[list[str]] = [
            self._card_header(res, scenarios),
            *self._cards_warnings(res),
            *self._card_series(series),
            *self._cards_stops(res, scenarios),
            self._card_gas(res),
            *self._card_gas_stack(res),
            self._card_dive(res),
            *self._card_environment(res),
            self._card_gas_plan(res),
        ]
        lines: list[str] = []
        for i, card in enumerate(cards):
            if i:
                lines.append("")
            lines += card
        self.readout.delete("1.0", tk.END)
        self.readout.insert(tk.END, "\n".join(lines))

    def _card_header(self, res: rp.PlanResult, scenarios) -> list[str]:
        """The dive in one line, MultiDeco-style."""
        levels, depth = res.levels, res.max_depth_m
        suffix = (" with unusable deco mix scenario"
                  if scenarios and len(scenarios) > 1 else "")
        if len(levels) > 1:
            profile = " → ".join(f"{l.depth:.0f} m @ {l.runtime:.0f}"
                                 for l in levels)
            return [f"Dive {profile} min{suffix}",
                    f"max {depth:.0f} m · average "
                    f"{b.average_depth(res.segments):.1f} m"]
        return [f"Dive {depth:.0f} m / {levels[-1].runtime:.0f} min{suffix}"]

    def _cards_warnings(self, res: rp.PlanResult) -> list[list[str]]:
        """The model's warnings, then the notices about what the GUI itself
        papered over. One ⚠ card each, in the report layer's own wording so the
        two front ends can never phrase a warning differently."""
        cards = [[f"⚠  {w}"] for w in res.warnings]
        if not any(r["role"].get() == "Bottom" and self._row_gas(r) is not None
                   for r in self.gas_rows):
            cards.append([f"⚠  no Bottom gas in the list — planning on "
                          f"{res.bottom_gas!r}"])
        for i, row in enumerate(self.gas_rows, start=1):
            if not row["use"].get():
                continue
            try:      # mid-edit (unparseable) rows stay quiet; bad *mixes* don't
                fo2 = float(row["fo2"].get())
                fhe = float(row["fhe"].get() or 0)
            except (ValueError, tk.TclError):
                continue
            if self._row_gas(row) is None:
                cards.append([f"⚠  gas row {i} ({fo2:g}/{fhe:g}) is not a "
                              "valid mix — left out of the plan"])
        return cards

    def _card_gas(self, res: rp.PlanResult) -> list[str]:
        depth, gas, plan = res.max_depth_m, res.bottom_gas, res.plan
        env = (plan.surface_p, plan.msw_per_bar)
        # Every ppO₂-derived depth on this card is measured in the dive's own
        # environment: at 1500 m in fresh water the card used to print a
        # sea-level density ABOVE the 6.2 g/L ceiling while the ⚠ density
        # warning — which was environment-aware — stayed silent.
        hypoxic_below = gas.min_depth(plan.ppo2_min, *env)

        gas_rows = [
            ["fractions", f"O₂ {gas.fO2*100:.0f}% · He {gas.fHe*100:.0f}%"
                          f" · N₂ {gas.fN2*100:.0f}%"],
            [f"ppO₂ @ {depth:.0f} m", f"{gas.ppo2(depth, *env):.2f} bar"],
            # A MOD is a limit, so it is truncated, never rounded: EAN30 at
            # ppO2 1.4 is 36.5 m, and printing "37 m" invents half a metre of
            # margin that does not exist.
            [f"MOD @ {plan.ppo2_bottom:g}",
             f"{math.floor(gas.mod(plan.ppo2_bottom, *env)):.0f} m"],
            [f"END @ {depth:.0f} m", f"{res.end_m:.0f} m (O₂ narcotic)"],
            [f"density @ {depth:.0f} m", f"{res.density_g_l:.1f} g/L"],
        ]
        if hypoxic_below > 0:
            note = "" if plan.travel_gases else " (need travel gas!)"
            gas_rows.append(["hypoxic below", f"{hypoxic_below:.0f} m{note}"])
        if plan.travel_gases:
            gas_rows.append(["travel gas",
                             ", ".join(repr(g) for g in plan.travel_gases)])
        if plan.deco_gases:
            gas_rows.append(["deco gas",
                             ", ".join(repr(g) for g in plan.deco_gases)])
        return format_card([f"GAS · {gas!r}"], gas_rows, aligns=["<", "<"])

    def _card_series(self, series) -> list[list[str]]:
        """The day at a glance, on every dive's readout. Empty for a single
        dive. Dive 2 is not dive 1 repeated — its deco is longer for the same
        profile, and seeing the whole series is the only way that reads as a
        consequence of the surface interval rather than a mistake."""
        if not series or len(series) < 2:
            return []
        rows = []
        for i, r in enumerate(series, start=1):
            mark = "▶" if r is series[self._dive_idx] else " "
            rows.append([f"{mark} dive {i}",
                         f"{r.max_depth_m:.0f} m / "
                         f"{r.levels[-1].runtime:.0f} min",
                         f"TTS {r.tts_min:.0f}",
                         f"RT {rp.runtime_min(r.total_runtime_min):d}",
                         f"surfGF {r.surf_gf*100:.0f}%"])
        return [format_card(["DIVE SERIES"], rows,
                            aligns=["<", "<", ">", ">", ">"])]

    def _card_gas_stack(self, res: rp.PlanResult) -> list[list[str]]:
        """Every mix quoted at its OWN MOD — the deepest it would ever be
        breathed. The GAS card above answers "what am I breathing at the
        bottom"; this answers "is each mix in the stack safe where it is
        actually planned for", which for a deco cylinder is a different depth
        entirely. Empty when the stack is one gas: the GAS card already said it."""
        if len(res.gas_stack) < 2:
            return []
        rows = [[r.gas.__repr__(), r.role, f"{r.mod_m:.0f}", f"{r.end_m:.0f}",
                 f"{r.ead_m:.0f}", f"{r.density_g_l:.1f}"
                                   + (" ⚠" if r.dense else "")]
                for r in res.gas_stack]
        return [format_card(["GAS STACK · at each mix's own MOD"], rows,
                            headers=["gas", "role", "MOD", "END", "EAD", "ρ"],
                            aligns=["<", "<", ">", ">", ">", ">"])]

    def _card_dive(self, res: rp.PlanResult) -> list[str]:
        """Rates and the ppO₂ window are shown because a hand-edited
        `ascent_rate` reshapes every schedule, and a setting the readout stays
        silent about is one nobody can check."""
        depth, gas, plan = res.max_depth_m, res.bottom_gas, res.plan
        stops = [s for s in res.segments if s.kind == "stop" and s.duration > 0]
        ndl_min = b.ndl(depth, gas, plan)
        ndl_label = ">10 h" if ndl_min is None else f"{ndl_min} min"
        return format_card(["DIVE"], [
            ["GF low / high", f"{plan.gf_low*100:.0f} / {plan.gf_high*100:.0f}"],
            [f"NDL @ {depth:.0f} m", f"{ndl_label} (square, fresh tissues)"],
            ["bottom time", f"{res.levels[-1].runtime:.0f} min"],
            ["runtime", f"{rp.runtime_min(res.total_runtime_min):d} min"],
            ["TTS", f"{res.tts_min:.0f} min"],
            ["deco total", f"{sum(s.duration for s in stops):.0f} min"
                           f" · {len(stops)} stops"],
            ["CNS / OTU", f"{res.cns_pct:.0f}% / {res.otu:.0f}"],
            ["final ceiling", f"{res.surface_ceiling_m:.2f} m"],
            # GF-High is the budget; SurfGF is what the schedule actually spends.
            # Baker's whole-minute padding usually surfaces the diver under it,
            # and that headroom is the number worth having when a plan changes.
            ["SurfGF", f"{res.surf_gf*100:.0f}% (of {plan.gf_high*100:.0f} "
                       f"allowed)"],
            ["rates", f"down {plan.descent_rate:g} · up {plan.ascent_rate:g}"
                      f" m/min · stops {plan.stop_interval:g} m"],
            ["ppO₂ limits", f"{plan.ppo2_bottom:g} bottom · {plan.ppo2_deco:g}"
                            f" deco · {plan.ppo2_min:g} min"],
            # The environment moves every pressure below it, so it cannot be
            # the one setting the readout stays silent about — least of all
            # once the panel above makes it editable.
            ["water", f"{rp.water_name(plan.msw_per_bar)}"
                      f" · {plan.msw_per_bar:.4g} m/bar"],
            ["surface", f"{plan.surface_p:g} bar"
                        + (f" · ~{alt:.0f} m alt"
                           if (alt := b.altitude_at_surface_p(plan.surface_p))
                           >= 50 else "")],
        ], aligns=["<", "<"])

    def _card_environment(self, res: rp.PlanResult) -> list[list[str]]:
        """Empty at the defaults. A non-default environment means the schedule
        no longer matches a planner set to sea-level salt, said where the
        schedule is read."""
        if not (env_note := rp.environment_note(res.plan)):
            return []
        return [format_card(["⚠ ENVIRONMENT"],
                            [[line] for line in textwrap.wrap(env_note, 46)],
                            aligns=["<"])]

    def _card_gas_plan(self, res: rp.PlanResult) -> list[str]:
        # --- GAS PLAN (per-cylinder + rock bottom) — every litre/bar/SHORT/turn
        # figure comes from the shared report layer, the SAME accounting the CLI
        # renders, so the two front ends can't diverge on the numbers. ---
        gp = self._gas_plan()
        sac, sac_mult = gp.sac, gp.sac_multiplier
        gas = res.bottom_gas
        rep = res.gas
        assert rep is not None       # recompute always passes a GasPlan
        plan_rows: list[list[str]] = []
        for c in rep.cylinders:
            if c.tank_l <= 0:
                need, have = f"{c.liters:.0f} L", "set tank"
                emrg = f"{c.liters_emergency:.0f} L"
            elif c.pressure_bar > 0:
                need = f"{c.bar_used:.0f} bar" + (" SHORT!" if c.short else "")
                have = f"{c.pressure_bar:.0f} bar"
                emrg = (f"{c.bar_used_emergency:.0f} bar"
                        + (" SHORT!" if c.short_emergency else ""))
            else:
                need, have = f"{c.bar_used:.0f} bar", f"{c.tank_l:.0f} L"
                emrg = f"{c.bar_used_emergency:.0f} bar"
            plan_rows.append([c.role, repr(c.gas), need, have, emrg])
        # Rock bottom is a back-gas reserve: show it in bar only when the bottom
        # gas actually has a Bottom-role cylinder with a fill; else fall back to
        # litres. All the math (rock_bottom_bar / turn_pressure_bar) is the
        # report layer's.
        back = self._banks_by_gas().get(gas)
        is_bottom = back is not None and back.role == "Bottom"
        rock_bar = rep.rock_bottom_bar if is_bottom else None
        if rock_bar is not None:
            if rep.back_pressure_bar <= 0:
                rb_line = f"rock bottom {rock_bar:.0f} bar reserve"
            else:
                turn = rep.turn_pressure_bar
                rb_line = (f"rock bottom {rock_bar:.0f} bar · turn ~{turn:.0f} bar"
                           if turn is not None else
                           f"rock bottom {rock_bar:.0f} bar · over "
                           f"{rep.back_pressure_bar:.0f} bar fill!")
        else:
            rb_line = f"rock bottom {rep.rock_bottom_l:.0f} L (set bottom tank)"
        gp_title = (f"GAS PLAN · SAC {sac:g} ×{sac_mult:.2f} emergency"
                    f" · problem {gp.problem_minutes:g} min"
                    + (f" · {gp.divers} divers" if gp.divers > 1 else ""))
        return format_card([gp_title], plan_rows,
                           headers=["role", "gas", "need", "have", "(emrg)"],
                           footer_lines=[rb_line,
                                         "litres are ideal-gas: a 232 bar fill"
                                         " holds ~5% less, 300 bar ~10%"],
                           aligns=["<", "<", ">", ">", ">"])

    def _cards_stops(self, res: rp.PlanResult, scenarios) -> list[list[str]]:
        """The stops table with one column per lost-gas scenario, then the
        per-scenario gas usage in litres. With no scenarios, just the stops."""
        depth, gas, plan = res.max_depth_m, res.bottom_gas, res.plan
        segs = res.segments
        gp = self._gas_plan()
        gas_rows_raw = self._gas_rows_raw()
        stops = [s for s in segs if s.kind == "stop" and s.duration > 0]
        stop_cards: list[list[str]] = []
        if scenarios and len(scenarios) > 1:
            # Runtime when leaving the bottom phase (total minus TTS): on a
            # multi-level dive stopping at the FIRST bottom segment would pair
            # the max depth with the runtime of the first (maybe shallower)
            # level. It is also the row above the first stop, so it is what the
            # first leg is measured from.
            run_bottom = rp.runtime_min(
                b.total_runtime(segs) - b.time_to_surface(segs))
            per = [(label, *self._stops_by_depth(ss))
                   for label, ss in scenarios]
            depths_u = sorted({d for _l, at, _t in per for d in at}, reverse=True)
            labels = ["All" if l == "all" else l for l, _at, _t in per]
            body = [[f"{depth:.0f} m"] + [f"({run_bottom:d})"] * len(per)]
            body += [[f"{dm:g} m"] + ["" if dm not in at
                                      else f"{at[dm][0]:d} ({at[dm][1]:d})"
                                      for _l, at, _t in per]
                     for dm in depths_u]
            # One column per scenario: OK = the normal dive, then each lost
            # deco mix (keep the title short — format_card widens the last
            # column to fit long title lines, which skews a 2-scenario table).
            stop_cards.append(format_card(
                ["STOPS · min (runtime)"], body,
                headers=["depth", *labels],
                aligns=[">"] * (len(per) + 1)))

            # Per scenario: what the dive NEEDS against what is actually in the
            # cylinders (tank litres × fill pressure). Litres, SHORT flags and
            # bar-left all come from the shared report layer — the same figures
            # the per-cylinder card above and the CLI show.
            usage_rows: list[list[str]] = []
            for label, ss in scenarios:
                if usage_rows:
                    usage_rows.append([""] * 6)   # blank row between scenarios
                scen = ("OK" if label == "OK"
                        else "All" if label == "all" else label)
                srep = rp.gas_report(ss, gas, gp, gas_rows_raw, plan)
                tot_need = tot_emrg = tot_have = 0.0
                for i, c in enumerate(srep.cylinders):
                    have_l = c.tank_l * c.pressure_bar
                    tot_need += c.liters
                    tot_emrg += c.liters_emergency
                    tot_have += have_l
                    if have_l <= 0:
                        usage_rows.append([scen if i == 0 else "", repr(c.gas),
                                           "set tank", f"{c.liters:.0f}",
                                           f"({c.liters_emergency:.0f})", ""])
                        continue
                    short = " SHORT!" if c.short else ""
                    short_e = " SHORT!" if c.short_emergency else ""
                    # have_l > 0 means tank and fill are both set, so bar_left
                    # is never None here — `or 0.0` only satisfies the checker.
                    left = max(c.bar_left or 0.0, 0.0)
                    left_e = max(c.bar_left_emergency or 0.0, 0.0)
                    usage_rows.append(
                        [scen if i == 0 else "", repr(c.gas), f"{have_l:.0f}",
                         f"{c.liters:.0f}{short}",
                         f"({c.liters_emergency:.0f}{short_e})",
                         f"{left:.0f} / {left_e:.0f}"])
                usage_rows.append(["", "TOTAL", f"{tot_have:.0f}",
                                   f"{tot_need:.0f}", f"({tot_emrg:.0f})", ""])
            stop_cards.append(format_card(
                ["GAS USAGE · litres have / need (emergency)",
                 "(emergency) = need + rock-bottom reserve · "
                 "bar left at normal / emrg"], usage_rows,
                headers=["scenario", "gas", "have", "need", "(emrg)",
                         "bar left"],
                aligns=["<", "<", ">", ">", ">", ">"]))
        elif not stops:
            stop_cards.append(format_card(["BÜHLMANN STOPS"],
                                          [["—", "no mandatory stops"]],
                                          aligns=["<", "<"]))
        else:
            stop_cards.append(format_card(
                ["BÜHLMANN STOPS"],
                [[f"{s.depth_start:.0f} m", f"{s.duration:.0f}", repr(s.gas)]
                 for s in stops],
                headers=["depth", "min", "gas"], aligns=[">", ">", "<"]))

        return stop_cards

    def _error(self, msg: str) -> None:
        """No valid plan: replace every derived surface (Results text, the
        Runtime wetnotes card, and the Profile chart) with the reason, and mark
        the plan invalid so a stale schedule can never be printed or exported."""
        self._plan_ok = False
        self.readout.delete("1.0", tk.END)
        self.readout.insert(tk.END, msg)
        self.runtime_text.delete("1.0", tk.END)
        self.runtime_text.insert(tk.END, msg)
        self.ax.clear()
        self.ax.text(0.5, 0.5, msg, ha="center", va="center",
                     color=self._pal["chart_fg"], wrap=True,
                     transform=self.ax.transAxes)
        self.ax.set_axis_off()
        self.fig.patch.set_facecolor(self._pal["chart_bg"])
        self.canvas.draw_idle()

    # ----------------------------------------------------------- runtime ----

    def _write_runtime(self, res: rp.PlanResult, scenarios=None) -> None:
        """Wetnotes runtime as one *standalone* framed card per scenario — the
        main dive, then one per missing-gas contingency — each a full
        depth/stop/run/gas table with its own TTS / RT and the minimum-gas line.
        Underwater you just switch to the card for the gas you actually have.

        Like `_write_readout`, this renders `res` — it derives nothing."""
        depth, gas, plan = res.max_depth_m, res.bottom_gas, res.plan
        segs, levels = res.segments, res.levels
        bottom_time = levels[-1].runtime
        scen = list(scenarios) if scenarios else [("OK", segs)]

        # Minimum ("rock bottom") gas / turn pressure — the same reserve on every
        # card, driven by the back gas cylinder.
        gp = self._gas_plan()
        rep = res.gas
        assert rep is not None       # recompute always passes a GasPlan
        back = self._banks_by_gas().get(gas)
        is_bottom = back is not None and back.role == "Bottom"
        rock_bar = rep.rock_bottom_bar if is_bottom else None
        if rock_bar is not None:
            min_gas = f"MIN GAS {rock_bar:.0f} bar"
            turn = rep.turn_pressure_bar
            if turn is not None:
                min_gas += f" · TURN {turn:.0f} bar"
        else:
            min_gas = f"MIN GAS {rep.rock_bottom_l:.0f} L"

        # Square dive: "max depth / bottom time". Multi-level: the whole profile
        # as depth@runtime steps (runtime is cumulative min at the end of each
        # level), because a single "36 m / 40 min" misreads — 40 min is the last
        # level's runtime, not time spent at the max depth.
        if levels and len(levels) > 1:
            profile = " · ".join(f"{lv.depth:.0f}m@{lv.runtime:.0f}"
                                 for lv in levels)
        else:
            profile = f"{depth:.0f} m / {bottom_time:.0f} min"

        rows_for = rp.wetnotes_rows

        cards: list[str] = []
        for label, ss in scen:
            name = ("MAIN DIVE" if label == "OK"
                    else f"LOST {'ALL GASES' if label == 'all' else label}")
            title = [
                name, profile,
                f"{gas!r} · GF {plan.gf_low*100:.0f}/{plan.gf_high*100:.0f}"
                f" · TTS {b.time_to_surface(ss):.0f}"
                f" · RT {rp.runtime_min(b.total_runtime(ss)):d}",
            ]
            # The warnings go on the card itself, not only on the Results tab.
            # This is the artifact that leaves the screen and goes in the water,
            # and with no printed disclaimer they are the only caveat on it
            # (DECISIONS.md #4, #5). Per scenario, because a lost deco gas
            # changes which ppO2 offences the dive actually contains.
            footers = [f"⚠ {w}" for w in
                       rp.warning_lines(ss, plan, gas, depth)]
            footers.append(min_gas)
            if label != "OK":
                # The same accounting as every other litre on screen: the
                # bottom gas's own SAC (a deco cylinder is billed at sac_deco)
                # and the dive's environment. Computed by hand here once, it
                # disagreed with the GAS USAGE card above it on any dive that
                # was not sea-level salt.
                back_l = b.segment_gas_liters(
                    [x for x in ss if x.gas == gas],
                    gp.sac_for(gas, plan.deco_gases),
                    plan.surface_p, plan.msw_per_bar)
                footers.append(f"back gas {back_l:.0f} L on {gas!r}")
            # The whole schedule on one line, per scenario — what gets pasted
            # into a message or copied onto a slate. The Copy button above takes
            # the card text as a whole, so this travels with it.
            footers.append(rp.backup_line(ss))
            # Per scenario: a lost deco gas moves every cylinder's pressure, so
            # the bar column has to be re-derived for the card it appears on.
            bars = rp.leg_pressures(ss, gp, self._gas_rows_raw(), plan)
            # Slack from the long footer lines goes into the left-aligned `gas`
            # column, not the last one: `bar` is a number column and has to stay
            # snug against the schedule to be readable at a glance.
            card = format_card(title, rows_for(ss, bars),
                               headers=["depth", "stop", "run", "gas", "bar"],
                               footer_lines=footers,
                               aligns=[">", ">", ">", "<", ">"], widen=3)
            cards.append("\n".join(card))

        # Cut table: the bottom-timer backup matrix (computer failure, full gas
        # stack — matrix × lost-gas combinations are deliberately not planned).
        tb, ta = int(self.cont_tb.get()), int(self.cont_ta.get())
        db, da = int(self.cont_db.get()), int(self.cont_da.get())
        if (tb or ta or db or da) and levels:
            grid = b.contingency_schedules(levels, gas, plan,
                                           time_before=tb, time_after=ta,
                                           depth_before=db, depth_after=da)
            cards.append("\n".join(self._cut_table_card(
                grid, plan, depth, levels[-1].runtime)))

        self.runtime_text.delete("1.0", tk.END)
        self.runtime_text.insert(tk.END, "\n\n".join(cards))

    @staticmethod
    def _cut_table_card(grid, plan, planned_depth: float,
                        planned_time: float) -> list[str]:
        """The wetnotes cut-table matrix card: rows are the bottom-time
        variants, columns the depth variants, each cell the stop schedule as
        'depth:min' pairs plus the TTS — rounded UP, the conservative wetnotes
        convention ('no deco' when clean, 'n/a' when the variant can't be
        planned). '*' marks the planned row and column: on the dive, round the
        gauge UP to the next row/column."""
        title = ["CUT TABLE (square @ max depth)",
                 f"steps 3′ × 3 m · "
                 f"GF {plan.gf_low*100:.0f}/{plan.gf_high*100:.0f}"]
        headers = ["time\\depth"] + [
            f"{c.depth:g} m" + ("*" if abs(c.depth - planned_depth) < 1e-9
                                else "") for c in grid[0]]
        rows = [[f"{row[0].bottom_time:g}′"
                 + ("*" if abs(row[0].bottom_time - planned_time) < 1e-9
                    else "")] + [c.text() for c in row]
                for row in grid]
        return format_card(title, rows, headers=headers,
                           footer_lines=["cell: stop:min · TTS (UP) — * planned",
                                         "gauge: max depth + dive time"],
                           aligns=["<"] * len(headers), widen=0)

    def _render_runtime_png(self, path: str) -> str:
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.figure import Figure
        body = self.runtime_text.get("1.0", tk.END).rstrip("\n")
        body = body.translate(_BOX_TO_ASCII)   # keep the frame aligned in the PNG
        n = body.count("\n") + 2  # body lines + the eko-deco brand line
        fig = Figure(figsize=(4.6, max(2.0, 0.24 * n + 0.5)), dpi=150)
        FigureCanvasAgg(fig)
        fig.patch.set_facecolor("white")
        fig.text(0.04, 0.98, f"{LOGO_MARK} {APP_NAME}", va="top", ha="left",
                 family="monospace", fontsize=11, fontweight="bold", color=LOGO_COLOR)
        fig.text(0.04, 0.98, "\n" + body, va="top", ha="left", family="monospace",
                 fontsize=10, linespacing=1.4)
        fig.savefig(path, facecolor="white", bbox_inches="tight")
        return path

    def _export_runtime(self, path: str | None = None) -> None:
        if not self._plan_ok:
            self.runtime_status.config(text="⚠ no valid plan to export")
            return
        if path is None:
            from tkinter import filedialog
            path = filedialog.asksaveasfilename(
                defaultextension=".png", initialfile="runtime.png",
                filetypes=[("PNG image", "*.png")])
            if not path:
                return
        try:
            self._render_runtime_png(path)
        except (OSError, ValueError) as e:
            self.runtime_status.config(text=f"⚠ export failed: {e}")
            return
        self.runtime_status.config(text=f"saved {os.path.basename(path)}")

    def _copy_runtime(self) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(self.runtime_text.get("1.0", tk.END).rstrip())
        self.runtime_status.config(text="copied")

    # ------------------------------------------------------- config file ----

    def _apply_config(self, cfg: dict) -> None:
        was_building, self._building = self._building, True
        try:
            cfg = dc.normalize(cfg)    # migrate legacy keys, assign stable ids
            self._base_cfg = dict(cfg)
            self.gf_lo.set(str(cfg["gf_low"]))
            self.gf_hi.set(str(cfg["gf_high"]))
            self.last_stop6.set(cfg.get("last_stop_m", 3.0) >= 6.0)
            self.last_stop.set(f"{cfg.get('last_stop_m', 3.0):g}")
            self.descent_rate.set(f"{cfg.get('descent_rate', 18.0):g}")
            self.ascent_rate.set(f"{cfg.get('ascent_rate', ASCENT_RATE):g}")
            self.stop_interval.set(f"{cfg.get('stop_interval', 3.0):g}")
            self.ppo2_bottom.set(f"{cfg.get('ppo2_bottom', 1.4):.2f}")
            self.ppo2_deco.set(f"{cfg.get('ppo2_deco', 1.6):.2f}")
            self.ppo2_min.set(f"{cfg.get('ppo2_min', 0.18):.2f}")
            self.ppo2_switch_tol.set(f"{cfg.get('ppo2_switch_tol', 0.05):.2f}")
            self.gas_switch_policy.set(
                cfg.get('gas_switch_policy', 'at-mod'))
            self.min_stop_time.set(f"{cfg.get('min_stop_time', 1.0):g}")
            self.p_h2o.set(f"{cfg.get('p_h2o_bar', b.P_H2O):.4f}")
            self.sac.set(f"{cfg['sac_normal']:g}")
            self.sac_deco.set(f"{cfg.get('sac_deco') or 0:g}")
            self.sac_mult.set(f"{cfg.get('sac_multiplier', 2.0):.2f}")
            self.problem_min.set(f"{cfg.get('problem_minutes', 1.0):g}")
            self.two_divers.set(int(cfg.get("divers", 1)) >= 2)
            # msw/bar is the stored truth; the dropdown and the altitude box are
            # only ways of typing it, so set them FROM the numbers, not the
            # other way round (a custom value must survive a round-trip).
            mpb = float(cfg.get("msw_per_bar", b.MSW_PER_BAR))
            surf = float(cfg.get("surface_p_bar", b.P_ATM))
            self.msw_per_bar.set(f"{mpb:.6g}")
            self.surface_p.set(f"{surf:.6g}")
            self.water.set(rp.water_name(mpb))
            self.altitude.set(f"{b.altitude_at_surface_p(surf):.0f}")
            cont = cfg.get("contingency", {})
            for var, key in zip((self.cont_tb, self.cont_ta,
                                 self.cont_db, self.cont_da),
                                dc.CONTINGENCY_KEYS, strict=True):
                var.set(int(cont.get(key, 1)))
            for row in list(self.gas_rows):
                self._remove_gas_row(row)
            for g in cfg["gases"]:
                self._add_gas_row(g["role"], g["o2"], g.get("he", 0),
                                  g.get("tank_l", 0), g.get("pressure_bar", 232),
                                  enabled=g.get("enabled", True),
                                  recompute=False)
            # Levels are pure depth/time periods — gas is automatic by role.
            self.level_rows.clear()
            for w in self.level_list.grid_slaves():
                if int(w.grid_info().get("row", 0)) > 0:
                    w.destroy()
            # `levels` is dive 1, `repeats` the dives after it. A file written
            # before repetitive dives existed has no `repeats` and loads as the
            # single dive it has always been.
            self._dive_profiles = [
                {"surface_interval_min": 0.0,
                 "levels": [dict(lv) for lv in cfg["levels"]]}]
            for r in cfg.get("repeats", []):
                self._dive_profiles.append(
                    {"surface_interval_min": float(r["surface_interval_min"]),
                     "levels": [dict(lv) for lv in r["levels"]]})
            self._show_dive(0)
        finally:
            self._building = was_building
        if not self._building:
            self.recompute()

    def _collect_config(self) -> dict:
        cfg = dict(self._base_cfg)               # preserve fields the GUI can't edit
        cfg.pop("depth_m", None)                 # legacy square-profile keys
        cfg.pop("bottom_time_min", None)
        # Park the rows on screen first: saving while looking at dive 2 must
        # write dive 2's profile to dive 2, not over dive 1's.
        self._stash_dive()
        gases = [{"role": r["role"].get(),
                  "o2": int(float(r["fo2"].get() or 0)),
                  "he": int(float(r["fhe"].get() or 0)),
                  "tank_l": self._row_tank(r),
                  "pressure_bar": self._row_pressure(r),
                  "enabled": bool(r["use"].get())} for r in self.gas_rows]
        cfg.update({
            "repeats": [
                {"surface_interval_min": prof["surface_interval_min"],
                 "levels": prof["levels"]}
                for prof in self._dive_profiles[1:]],
            # Dive 1, as typed: lose nothing (`_stash_dive` used `_row_levels`).
            "levels": self._dive_profiles[0]["levels"],
            "gf_low": round(self._pct(self.gf_lo, 0.30) * 100),
            "gf_high": round(self._pct(self.gf_hi, 0.70) * 100),
            "last_stop_m": self._num(self.last_stop, 3.0, lo=0.0),
            "ascent_rate": self._num(self.ascent_rate, ASCENT_RATE, lo=0.5),
            "descent_rate": self._num(self.descent_rate, 18.0, lo=0.5),
            "stop_interval": self._num(self.stop_interval, 3.0, lo=0.5),
            "ppo2_bottom": self._num(self.ppo2_bottom, 1.4, lo=0.1),
            "ppo2_deco": self._num(self.ppo2_deco, 1.6, lo=0.1),
            "ppo2_min": self._num(self.ppo2_min, 0.18, lo=0.0),
            "ppo2_switch_tol": self._num(self.ppo2_switch_tol, 0.05, lo=0.0),
            "gas_switch_policy": self.gas_switch_policy.get(),
            "min_stop_time": self._num(self.min_stop_time, 1.0, lo=0.01),
            "p_h2o_bar": self._num(self.p_h2o, b.P_H2O, lo=0.0001),
            "sac_normal": self._num(self.sac, 20.0, lo=1.0),
            "sac_deco": (sd if (sd := self._num(self.sac_deco, 0.0, lo=0.0)) > 0
                         else None),
            "sac_multiplier": round(self._num(self.sac_mult, 2.0, lo=1.0), 2),
            "problem_minutes": self._num(self.problem_min, 1.0, lo=0.0),
            "divers": 2 if self.two_divers.get() else 1,
            "surface_p_bar": self._num(self.surface_p, b.P_ATM, lo=0.1),
            "msw_per_bar": self._num(self.msw_per_bar, b.MSW_PER_BAR, lo=1.0),
            "contingency": dict(zip(dc.CONTINGENCY_KEYS,
                                    (int(self.cont_tb.get()),
                                     int(self.cont_ta.get()),
                                     int(self.cont_db.get()),
                                     int(self.cont_da.get())),
                                    strict=True)),
            "gases": gases,
        })
        return cfg

    def _save_config(self) -> None:
        try:
            dc.save(self._collect_config())
        except (OSError, ValueError, tk.TclError) as e:
            self.cfg_status.config(text=f"⚠ save failed: {e}")
            return
        self.cfg_status.config(text="saved ✓")

    def _reload_config(self) -> None:
        # Strict load, non-destructive on failure: a corrupt or missing file
        # must not wipe the dive the user is looking at — report it and keep the
        # current settings in place.
        try:
            cfg = dc.load(strict=True)
        except (OSError, ValueError) as e:
            self.cfg_status.config(text=f"⚠ reload failed: {e}")
            return
        self._apply_config(cfg)
        self.cfg_status.config(text="reloaded")


def install_launcher() -> None:
    """Register a Linux .desktop launcher + icon for the current user.

    GNOME's dock/taskbar ignores the icon a window sets on itself
    (_NET_WM_ICON) and shows a generic gear unless a .desktop file matches the
    window's WM_CLASS — so the branded taskbar icon needs this one-time step:

        deco-gui --install-launcher
    """
    if sys.platform != "linux":
        print("--install-launcher is for Linux desktops only.")
        return
    import shutil

    data = os.path.join(os.path.expanduser("~"), ".local", "share")
    icon_dir = os.path.join(data, "icons", "hicolor", "512x512", "apps")
    app_dir = os.path.join(data, "applications")
    os.makedirs(icon_dir, exist_ok=True)
    os.makedirs(app_dir, exist_ok=True)
    shutil.copyfile(ICON_PNG, os.path.join(icon_dir, f"{APP_NAME}.png"))
    # Launch through the interpreter that is running us (`-m deco.app`) rather
    # than a bare `deco-gui`: it works from a venv, an editable checkout or a
    # pipx install without assuming the console script is on the dock's PATH.
    # Path= is the user's home so the GUI picks its per-user config, not
    # whatever dive_plan.json happens to sit in the launching directory.
    home = os.path.expanduser("~")
    desktop = os.path.join(app_dir, f"{APP_NAME}.desktop")
    with open(desktop, "w", encoding="utf-8") as f:
        f.write(f"""[Desktop Entry]
Type=Application
Name={APP_NAME}
Comment=Bühlmann ZHL-16C dive-deco planner
Exec={sys.executable} -m deco.app
Path={home}
Icon={APP_NAME}
Terminal=false
Categories=Education;Science;
StartupWMClass={APP_NAME}
""")
    print(f"Installed {desktop}\n(re-launch the app to see the icon; "
          "remove both files to uninstall)")


def main() -> None:
    if "--install-launcher" in sys.argv:
        install_launcher()
        return
    # className → WM_CLASS, which Linux docks/taskbars use to identify the app
    # (and to match the .desktop file --install-launcher registers).
    root = tk.Tk(className=APP_NAME)
    with contextlib.suppress(tk.TclError):
        ttk.Style().theme_use("clam")
    DecoApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
