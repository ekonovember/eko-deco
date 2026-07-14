"""eko-deco — interactive dive-profile visualizer for the Bühlmann ZHL-16C + GF model.

Left panel: dive settings (depth, bottom time, gradient factors, a fully editable
gas list where every mix — bottom / travel / deco — has its own O2, He and tank,
plus SAC and an emergency SAC multiplier; single diver). The rest of the window
is a two-tab notebook: **Results** (schedule, TTS, per-cylinder gas + rock
bottom, lost-deco-gas scenarios, wetnotes card) and **Profile** (the
depth-vs-time chart with the deco-ceiling overlay).

The dive is loaded from and saved to ``dive_plan.json`` (see ``dive_config.py``),
the same file the console planner reads/writes — so ``cli.py plan --save`` shows
up here on Reload, and vice-versa.

Run:
    python app.py
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import replace
import tkinter as tk
from tkinter import ttk
from typing import List, Optional, Tuple

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

import buhlmann as b
import dive_config as dc

# The GUI ascends at a fixed rate; keep it in step with the CLI DivePlan default
# (10 m/min) so the same inputs give the same schedule in both.
ASCENT_RATE = 10.0

# Branding: the eko-deco wordmark and its "<//>" logo mark.
APP_NAME = "eko-deco"
LOGO_MARK = "<//>"
LOGO_COLOR = "#0a84ff"
_PICTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pictures")
ICON_PNG = os.path.join(_PICTURES, "icon.png")
ICON_ICO = os.path.join(_PICTURES, "icon.ico")

# UI preferences (dark mode, …) live in their own file so they never mix with
# the dive itself: dive_plan.json stays shareable between CLI/GUI and machines.
UI_SETTINGS_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "ui_settings.json")

# Widget + chart palettes for the clam ttk theme.
LIGHT = {"bg": "#dcdad5", "fg": "#000000", "field": "#ffffff",
         "trough": "#c8c6c1", "border": "#9e9a91", "active": "#eeebe7",
         "chart_bg": "#ffffff", "chart_fg": "#000000", "grid": "#b0b0b0",
         "ceiling": "#c0392b"}
DARK = {"bg": "#2b2b2b", "fg": "#e6e6e6", "field": "#3c3f41",
        "trough": "#1f1f1f", "border": "#555555", "active": "#3a3d3f",
        "chart_bg": "#1e1e1e", "chart_fg": "#d0d0d0", "grid": "#666666",
        "ceiling": "#ff6b5e"}


def load_ui_settings() -> dict:
    try:
        with open(UI_SETTINGS_PATH, encoding="utf-8") as f:
            return dict(json.load(f))
    except (OSError, ValueError):
        return {}


def save_ui_settings(settings: dict) -> None:
    try:
        with open(UI_SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
            f.write("\n")
    except OSError:
        pass                                   # cosmetic preference; never fatal


def build_profile_points(segs) -> Tuple[List[float], List[float]]:
    """Concatenate segment endpoints into a (time, depth) polyline."""
    t, d, run = [0.0], [0.0], 0.0
    for s in segs:
        run += s.duration
        t.append(run)
        d.append(s.depth_end)
    return t, d


def format_card(title_lines: List[str], rows: List[List[str]],
                headers: Optional[List[str]] = None,
                footer_lines: Optional[List[str]] = None,
                aligns: Optional[List[str]] = None,
                widen: int = -1) -> List[str]:
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

    def grid(cells: List[str]) -> str:
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
    **{c: "-" for c in "─"},
    **{c: "|" for c in "│"},
    **{c: "+" for c in "┌┐└┘├┤┬┴┼"},
})


class DecoApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title(f"{APP_NAME} — Bühlmann ZHL-16C + gradient factors "
                   "+ rock bottom")
        self._ui_settings = load_ui_settings()
        try:                       # last session's size/position (ui_settings)
            root.geometry(str(self._ui_settings.get("geometry") or "1500x900"))
        except tk.TclError:
            root.geometry("1500x900")
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._set_window_icon()

        self._building = True
        self._base_cfg = dc.default_config()
        self._build_layout()
        self._apply_theme()
        self._apply_config(dc.load())
        self._building = False
        self.recompute()

    # ---------------------------------------------------------------- UI ----

    def _set_window_icon(self) -> None:
        """Use the <//> tile (pictures/icon.png) as the window + taskbar icon."""
        try:
            if sys.platform == "win32":
                # The taskbar groups Tk windows under python.exe and shows ITS
                # icon unless the process claims its own AppUserModelID; the
                # .ico also gives Windows pre-rendered small sizes.
                import ctypes
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                    "eko.deco")
                self.root.iconbitmap(default=ICON_ICO)
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
        self.level_list = ttk.Frame(levels)
        self.level_list.pack(fill=tk.X)
        for col, text in enumerate(("depth m", "run min", "gas", "")):
            ttk.Label(self.level_list, text=text, anchor="w").grid(
                row=0, column=col, padx=1, sticky="w")
        self.level_rows = []
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
        self.gas_rows = []
        ttk.Button(gases, text="+ Add gas", command=self._add_gas_row).pack(
            anchor="w", pady=(4, 0))

        # --- gas planning (single diver: SAC + emergency multiplier) ---
        gp = ttk.LabelFrame(left, text="Gas planning (rock bottom)", padding=6)
        gp.pack(fill=tk.X, pady=(8, 0))
        sacrow = ttk.Frame(gp)
        sacrow.pack(fill=tk.X, pady=2)
        self.sac = self._add_spin(sacrow, "SAC (L/min)", 1, 99, 0.5, 20,
                                  fmt="%.1f")
        self.sac_mult = self._add_spin(sacrow, "Emergency ×", 1.0, 9.0, 0.05, 2.0,
                                       fmt="%.2f")

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
        self.cfg_status = ttk.Label(cfgrow, text=os.path.basename(dc.DEFAULT_PATH))
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
                  width: int = 5, fmt: Optional[str] = None) -> tk.StringVar:
        """Labelled numeric up/down packed onto `row` (several fit one line)."""
        ttk.Label(row, text=label).pack(side=tk.LEFT)
        var = tk.StringVar(value=(fmt % init) if fmt else f"{init:g}")
        kwargs = {"format": fmt} if fmt else {}
        ttk.Spinbox(row, from_=lo, to=hi, increment=increment, width=width,
                    textvariable=var, **kwargs).pack(side=tk.LEFT, padx=(4, 10))
        # Recompute from a variable trace, not the Spinbox command, so a
        # programmatic var.set() (loading dive_plan.json) refreshes too.
        var.trace_add("write",
                      lambda *_: None if self._building else self.recompute())
        return var

    def _num(self, var, default: float, lo: Optional[float] = None) -> float:
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

    # A level's gas: "auto" = let the planner pick the gas that is relevant at
    # that depth (the bottom mix while it is breathable, a travel mix where it
    # is not) — drawn from the Gases panel like every other choice here.
    AUTO_GAS = "auto"

    @staticmethod
    def _gas_label(g: b.Gas) -> str:
        """Dropdown label for a mix: OXYGEN, AIR, EAN 50, TMX 18/40."""
        o2 = int(round(g.fO2 * 100))
        if g.fHe > 0:
            return f"TMX {o2}/{int(round(g.fHe * 100))}"
        if o2 == 100:
            return "OXYGEN"
        if o2 == 21:
            return "AIR"
        return f"EAN {o2}"

    def _gas_choices(self) -> List[str]:
        """The level gas dropdown: 'auto' plus every gas in the Gases panel that
        is ticked for use. The panel is the single source of truth — a level can
        only breathe a gas the diver actually carries."""
        out = [self.AUTO_GAS]
        for row in self.gas_rows:
            g = self._row_gas(row)
            if g is not None and self._gas_label(g) not in out:
                out.append(self._gas_label(g))
        return out

    def _refresh_level_gas_choices(self) -> None:
        """Keep each level's gas dropdown in step with the Gases panel: edited
        mixes, added, removed and unticked gases all flow through — the boxes
        resize to the longest label. A level pointing at a gas that is no longer
        carried falls back to 'auto' rather than planning a gas the diver
        doesn't have."""
        choices = self._gas_choices()
        width = max(len(c) for c in choices)
        for row in self.level_rows:
            row["gas_box"].configure(values=choices, width=width)
            if row["gas"].get() not in choices:
                row["gas"].set(self.AUTO_GAS)

    def _add_level_row(self, depth: float = 30, runtime: float = 40,
                       gas: str = AUTO_GAS, recompute: bool = True) -> None:
        depth_var = tk.StringVar(value=f"{depth:g}")
        run_var = tk.StringVar(value=f"{runtime:g}")
        gas_var = tk.StringVar(value=gas or self.AUTO_GAS)

        choices = self._gas_choices()
        gas_box = ttk.Combobox(self.level_list, textvariable=gas_var,
                               width=max(len(c) for c in choices),
                               state="readonly", values=choices)
        widgets = [
            ttk.Spinbox(self.level_list, from_=1, to=300, width=5,
                        textvariable=depth_var),
            ttk.Spinbox(self.level_list, from_=1, to=999, width=5,
                        textvariable=run_var),
            gas_box,
        ]
        row = {"widgets": widgets, "depth": depth_var, "runtime": run_var,
               "gas": gas_var, "gas_box": gas_box}
        widgets.append(ttk.Button(self.level_list, text="✕", width=2,
                                  style="GasDel.TButton",
                                  command=lambda: self._remove_level_row(row)))
        for var in (depth_var, run_var, gas_var):
            var.trace_add("write",
                          lambda *_: None if self._building else self.recompute())
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

    def _row_levels(self) -> List[b.Level]:
        """Every level row exactly as typed — never drops one. This is what gets
        saved: a field left blank mid-edit must not silently delete the level."""
        by_label = {self._gas_label(g): g for g in
                    (self._row_gas(r) for r in self.gas_rows) if g is not None}
        return [b.Level(self._num(row["depth"], 0.0, lo=0.0),
                        self._num(row["runtime"], 0.0, lo=0.0),
                        by_label.get(row["gas"].get()))
                for row in self.level_rows]

    def _levels(self) -> List[b.Level]:
        """The rows that can actually be planned — a row being edited (blank or
        zero depth/runtime) is skipped so the plan doesn't blow up mid-keystroke.
        Use `_row_levels` when persisting, so nothing is lost."""
        return [l for l in self._row_levels() if l.depth > 0 and l.runtime > 0]

    # The bare "use" checkbox is much narrower than its header, so left-aligning
    # both (like every other column) leaves it visibly adrift under the label.
    # Centre that one column — header and box — so they line up.
    GAS_USE_COL = 5
    GAS_STICKY = ("w", "w", "w", "w", "w", "", "w")   # role..bar, use, ✕

    def _add_gas_row(self, role: str = "Deco", fo2: float = 50, fhe: float = 0,
                     tank: float = 11, pressure: float = 232,
                     enabled: bool = True, recompute: bool = True,
                     gas_id: Optional[int] = None) -> None:
        role_var = tk.StringVar(value=role)
        fo2_var = tk.StringVar(value=str(int(fo2)))
        fhe_var = tk.StringVar(value=str(int(fhe)))
        tank_var = tk.StringVar(value=str(int(tank)))
        press_var = tk.StringVar(value=str(int(pressure)))
        use_var = tk.BooleanVar(value=enabled)     # unticked = don't count

        widgets = [
            ttk.Combobox(self.gas_list, textvariable=role_var, width=6,
                         state="readonly", values=dc.ROLES),
            ttk.Spinbox(self.gas_list, from_=5, to=100, width=4, textvariable=fo2_var),
            ttk.Spinbox(self.gas_list, from_=0, to=95, width=4, textvariable=fhe_var),
            ttk.Spinbox(self.gas_list, from_=0, to=30, width=5, textvariable=tank_var),
            ttk.Spinbox(self.gas_list, from_=0, to=300, width=4, textvariable=press_var),
        ]

        # The numeric config id rides along invisibly (levels reference gases
        # by it); rows added in the UI leave it None and dive_config assigns
        # the next free number on save.
        row = {"widgets": widgets, "role": role_var, "fo2": fo2_var,
               "fhe": fhe_var, "tank": tank_var, "pressure": press_var,
               "use": use_var, "id": gas_id}
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
        travel, deco = [], []
        for row in self.gas_rows:
            g = self._row_gas(row)
            role = row["role"].get()
            if g is None or role == "Bottom":
                continue
            (travel if role == "Travel" else deco).append(g)
        base = self._base_cfg
        return b.DivePlan(
            gf_low=self._pct(self.gf_lo, 0.30),
            gf_high=self._pct(self.gf_hi, 0.70),
            ascent_rate=base.get("ascent_rate", ASCENT_RATE),
            descent_rate=base.get("descent_rate", 18.0),
            stop_interval=base.get("stop_interval", 3.0),
            last_stop_depth=6.0 if self.last_stop6.get() else 3.0,
            ppo2_bottom=base.get("ppo2_bottom", 1.4),
            ppo2_deco=base.get("ppo2_deco", 1.6),
            ppo2_min=base.get("ppo2_min", 0.18),
            deco_gases=tuple(deco),
            travel_gases=tuple(travel),
        )

    def recompute(self) -> None:
        self._refresh_level_gas_choices()   # the Gases list may have changed
        levels = self._levels()
        if not levels:                      # every row mid-edit / emptied
            return
        gas = self._bottom_gas()
        plan = self._make_plan()
        depth = b.max_depth(levels)
        bottom_time = levels[-1].runtime    # runtime at the end of the bottom

        try:
            segs, tissues = b.plan_multilevel(levels, gas, plan)
        except Exception as e:                # noqa: BLE001 - surface any input error
            self._error(f"Plan error: {e}")
            return

        scenarios = self._lost_gas_scenarios(levels, gas, plan, segs)
        self._draw(segs, depth, bottom_time, b.ceiling_profile(segs, plan),
                   levels)
        self._write_readout(depth, gas, plan, bottom_time, segs, tissues,
                            scenarios, levels)
        self._write_runtime(depth, gas, plan, bottom_time, segs, scenarios,
                            levels)

    def _lost_gas_scenarios(self, levels, gas, plan,
                            segs) -> List[Tuple[str, list]]:
        """Contingency schedules for losing deco gas, MultiDeco-style: the normal
        dive ("OK"), then one re-plan per deco gas without it, and — with two or
        more deco gases — an "all" worst case with every deco gas gone. Only
        Deco-role gases can be lost; bottom and travel gases always stay. Works
        for any number of deco gases (nothing assumes two).

        A lost gas is stripped from BOTH the deco stack and any level that names
        it (that level falls back to "auto"), so losing a mix truly removes it —
        otherwise a level breathing it would keep the "lost" gas on the schedule."""
        scenarios: List[Tuple[str, list]] = [("OK", segs)]
        deco = plan.deco_gases
        losses = [(repr(g), (g,)) for g in deco]        # (label, gases lost)
        if len(deco) > 1:
            losses.append(("all", tuple(deco)))
        for label, lost in losses:
            remaining = tuple(d for d in deco if d not in lost)
            lost_levels = [replace(lv, gas=None)
                           if (lv.gas is not None and lv.gas in lost) else lv
                           for lv in levels]
            try:
                lost_segs, _ = b.plan_multilevel(
                    lost_levels, gas, replace(plan, deco_gases=remaining))
            except Exception:  # noqa: BLE001 - a scenario that can't be planned
                continue       # (e.g. hypoxic gap) just drops its column
            scenarios.append((label, lost_segs))
        return scenarios

    @staticmethod
    def _stops_by_depth(segs) -> Tuple[dict, float]:
        """{stop depth (m, int): (minutes, runtime at end of stop)} + total RT."""
        run, at = 0.0, {}
        for s in segs:
            run += s.duration
            if s.kind == "stop" and s.duration > 0:
                at[int(round(s.depth_start))] = (s.duration, run)
        return at, run

    @staticmethod
    def _liters_by_gas(segs, sac: float) -> List[Tuple[str, float]]:
        """[(gas repr, litres at `sac`)] in order of first use."""
        out, seen = [], []
        for s in segs:
            key = repr(s.gas)
            if key in seen:
                continue
            seen.append(key)
            out.append((key, b.segment_gas_liters(
                [x for x in segs if repr(x.gas) == key], sac)))
        return out

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
                    f"{int(round(s.duration))}′ @ {s.depth_start:.0f} m",
                    xy=(run_t + s.duration / 2, s.depth_start),
                    xytext=(0, -14), textcoords="offset points",
                    ha="center", fontsize=8, color="#d62728")
            if prev is not None and repr(s.gas) != repr(prev):
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

    def _write_readout(self, depth, gas, plan, bottom_time,
                       segs, tissues, scenarios=None, levels=None) -> None:
        ceil_now = b.ceiling_depth(tissues, plan.gf_high)
        total = b.total_runtime(segs)
        tts = b.time_to_surface(segs)
        stops = [s for s in segs if s.kind == "stop" and s.duration > 0]
        deco_total = sum(s.duration for s in stops)
        ndl_min = b.ndl(depth, gas, plan)
        ndl_label = ">10 h" if ndl_min is None else f"{ndl_min} min"

        cards: List[List[str]] = []

        # --- header line, MultiDeco-style ---
        suffix = (" with unusable deco mix scenario"
                  if scenarios and len(scenarios) > 1 else "")
        if levels and len(levels) > 1:
            profile = " → ".join(f"{l.depth:.0f} m @ {l.runtime:.0f}"
                                 for l in levels)
            cards.append([f"Dive {profile} min{suffix}",
                          f"max {depth:.0f} m · average "
                          f"{b.average_depth(segs):.1f} m"])
        else:
            cards.append([f"Dive {depth:.0f} m / {bottom_time:.0f} min{suffix}"])

        # --- profile violates its own ceiling? (only possible multi-level) ---
        for s in b.ceiling_violations(segs):
            cards.append([f"⚠  level at {s.depth_start:.0f} m is ABOVE the "
                          f"ceiling ({s.ceiling_m:.1f} m)",
                          "the profile itself violates decompression"])

        # --- GAS ---
        gas_rows = [
            ["fractions", f"O₂ {gas.fO2*100:.0f}% · He {gas.fHe*100:.0f}%"
                          f" · N₂ {gas.fN2*100:.0f}%"],
            [f"ppO₂ @ {depth:.0f} m", f"{gas.ppo2(depth):.2f} bar"],
            ["MOD @ 1.4", f"{gas.mod(1.4):.0f} m"],
        ]
        if gas.min_depth(plan.ppo2_min) > 0:
            note = "" if plan.travel_gases else " (need travel gas!)"
            gas_rows.append(["hypoxic below",
                             f"{gas.min_depth(plan.ppo2_min):.0f} m{note}"])
        if plan.travel_gases:
            gas_rows.append(["travel gas",
                             ", ".join(repr(g) for g in plan.travel_gases)])
        if plan.deco_gases:
            gas_rows.append(["deco gas",
                             ", ".join(repr(g) for g in plan.deco_gases)])
        cards.append(format_card([f"GAS · {gas!r}"], gas_rows, aligns=["<", "<"]))

        # --- DIVE ---
        cards.append(format_card(["DIVE"], [
            ["GF low / high", f"{plan.gf_low*100:.0f} / {plan.gf_high*100:.0f}"],
            [f"NDL @ {depth:.0f} m", ndl_label],
            ["bottom time", f"{bottom_time:.0f} min"],
            ["runtime", f"{total:.0f} min"],
            ["TTS", f"{tts:.0f} min"],
            ["deco total", f"{deco_total:.0f} min · {len(stops)} stops"],
            ["final ceiling", f"{ceil_now:.2f} m"],
        ], aligns=["<", "<"]))

        # --- GAS PLAN (per-cylinder + rock bottom) ---
        sac = self._num(self.sac, 20.0, lo=1.0)
        sac_mult = self._num(self.sac_mult, 2.0, lo=1.0)
        gp = b.GasPlan(sac=sac, sac_multiplier=sac_mult,
                       problem_minutes=self._base_cfg.get("problem_minutes", 1.0))
        tanks, roles, press = {}, {}, {}
        back_tank = back_pressure = 0.0
        for row in self.gas_rows:
            g = self._row_gas(row)
            if g is None:
                continue
            tanks[repr(g)] = self._row_tank(row)
            press[repr(g)] = self._row_pressure(row)
            roles[repr(g)] = row["role"].get()
            if row["role"].get() == "Bottom" and g == gas:
                back_tank = self._row_tank(row)
                back_pressure = self._row_pressure(row)
        plan_rows: List[List[str]] = []
        seen: List[str] = []
        for s in segs:
            key = repr(s.gas)
            if key in seen:
                continue
            seen.append(key)
            liters = b.segment_gas_liters([x for x in segs if x.gas == s.gas], sac)
            liters_e = liters * sac_mult          # same volume at the emergency SAC
            tk_l = tanks.get(key, 0.0)
            pr = press.get(key, 0.0)
            label = roles.get(key, "stage")
            if tk_l <= 0:
                need, have = f"{liters:.0f} L", "set tank"
                emrg = f"{liters_e:.0f} L"
            elif pr > 0:
                used, used_e = liters / tk_l, liters_e / tk_l
                need = f"{used:.0f} bar" + (" SHORT!" if used > pr + 1e-9 else "")
                have = f"{pr:.0f} bar"
                emrg = f"{used_e:.0f} bar" + (" SHORT!" if used_e > pr + 1e-9 else "")
            else:
                need, have = f"{liters / tk_l:.0f} bar", f"{tk_l:.0f} L"
                emrg = f"{liters_e / tk_l:.0f} bar"
            plan_rows.append([label, key, need, have, emrg])
        rock = b.rock_bottom_liters(depth, gp, plan.ascent_rate)
        if back_tank > 0:
            rock_bar = rock / back_tank
            usable = back_pressure - rock_bar
            if back_pressure <= 0:
                rb_line = f"rock bottom {rock_bar:.0f} bar reserve"
            elif usable > 0:
                rb_line = (f"rock bottom {rock_bar:.0f} bar · "
                           f"turn ~{back_pressure - usable / 2.0:.0f} bar")
            else:
                rb_line = (f"rock bottom {rock_bar:.0f} bar · "
                           f"over {back_pressure:.0f} bar fill!")
        else:
            rb_line = f"rock bottom {rock:.0f} L (set bottom tank)"
        gp_title = f"GAS PLAN · SAC {sac:g} ×{sac_mult:.2f} emergency"
        gas_plan_card = format_card([gp_title], plan_rows,
                                    headers=["role", "gas", "need", "have",
                                             "(emrg)"],
                                    footer_lines=[rb_line],
                                    aligns=["<", "<", ">", ">", ">"])

        # --- stops + gas usage, MultiDeco-style lost-gas scenarios, framed
        # like every other results card: the stops table with one column per
        # scenario (cells "stop (runtime)", the bottom row first), then a
        # per-scenario gas-usage card in litres. ---
        stop_cards: List[List[str]] = []
        if scenarios and len(scenarios) > 1:
            per = [(label, *self._stops_by_depth(ss)) for label, ss in scenarios]
            depths_u = sorted({d for _l, at, _t in per for d in at}, reverse=True)
            run_bottom = 0.0                 # runtime when leaving the bottom
            for s in segs:
                run_bottom += s.duration
                if s.kind == "bottom":
                    break
            labels = ["All" if l == "all" else l for l, _at, _t in per]
            body = [[f"{depth:.0f} m"] + [f"({run_bottom:.0f})"] * len(per)]
            body += [[f"{dm} m"] + ["" if dm not in at
                                    else f"{at[dm][0]:.0f} ({at[dm][1]:.0f})"
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
            # cylinders (tank litres x fill pressure), so "SHORT!" is backed by
            # the numbers it was judged on.
            usage_rows: List[List[str]] = []
            for label, ss in scenarios:
                if usage_rows:
                    usage_rows.append([""] * 6)   # blank row between scenarios
                scen = ("OK" if label == "OK"
                        else "All" if label == "all" else label)
                tot_need = tot_emrg = tot_have = 0.0
                for i, (key, liters) in enumerate(self._liters_by_gas(ss, sac)):
                    liters_e = liters * sac_mult  # same volume at emergency SAC
                    tk_l, pr = tanks.get(key, 0.0), press.get(key, 0.0)
                    have = tk_l * pr
                    tot_need += liters
                    tot_emrg += liters_e
                    tot_have += have
                    if have <= 0:
                        usage_rows.append([scen if i == 0 else "", key,
                                           "set tank", f"{liters:.0f}",
                                           f"({liters_e:.0f})", ""])
                        continue
                    short = " SHORT!" if have < liters else ""
                    short_e = " SHORT!" if have < liters_e else ""
                    usage_rows.append(
                        [scen if i == 0 else "", key, f"{have:.0f}",
                         f"{liters:.0f}{short}", f"({liters_e:.0f}{short_e})",
                         f"{max(have - liters, 0) / tk_l:.0f} / "
                         f"{max(have - liters_e, 0) / tk_l:.0f}"])
                usage_rows.append(["", "TOTAL", f"{tot_have:.0f}",
                                   f"{tot_need:.0f}", f"({tot_emrg:.0f})", ""])
            stop_cards.append(format_card(
                ["GAS USAGE · litres have / need (emergency)",
                 "bar left at the normal / emergency SAC"], usage_rows,
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

        cards[1:1] = stop_cards               # right under the header line
        cards.append(gas_plan_card)

        lines: List[str] = []
        for i, card in enumerate(cards):
            if i:
                lines.append("")
            lines += card
        self.readout.delete("1.0", tk.END)
        self.readout.insert(tk.END, "\n".join(lines))

    def _error(self, msg: str) -> None:
        self.readout.delete("1.0", tk.END)
        self.readout.insert(tk.END, msg)

    # ----------------------------------------------------------- runtime ----

    def _write_runtime(self, depth, gas, plan, bottom_time, segs,
                       scenarios=None, levels=None) -> None:
        """Wetnotes runtime as one *standalone* framed card per scenario — the
        main dive, then one per missing-gas contingency — each a full
        depth/stop/run/gas table with its own TTS / RT and the minimum-gas line.
        Underwater you just switch to the card for the gas you actually have."""
        scen = list(scenarios) if scenarios else [("OK", segs)]

        # Minimum ("rock bottom") gas / turn pressure — the same reserve on every
        # card, driven by the back gas cylinder.
        sac = self._num(self.sac, 20.0, lo=1.0)
        gp = b.GasPlan(sac=sac, sac_multiplier=self._num(self.sac_mult, 2.0, lo=1.0),
                       problem_minutes=self._base_cfg.get("problem_minutes", 1.0))
        rock = b.rock_bottom_liters(depth, gp, plan.ascent_rate)
        back_tank = back_pressure = 0.0
        for row in self.gas_rows:
            g = self._row_gas(row)
            if g is not None and row["role"].get() == "Bottom" and g == gas:
                back_tank, back_pressure = self._row_tank(row), self._row_pressure(row)
        if back_tank > 0:
            rb = rock / back_tank
            min_gas = f"MIN GAS {rb:.0f} bar"
            if back_pressure > rb:
                min_gas += (f" · TURN "
                            f"{back_pressure - (back_pressure - rb) / 2:.0f} bar")
        else:
            min_gas = f"MIN GAS {rock:.0f} L"

        # Square dive: "max depth / bottom time". Multi-level: the whole profile
        # as depth@runtime steps (runtime is cumulative min at the end of each
        # level), because a single "36 m / 40 min" misreads — 40 min is the last
        # level's runtime, not time spent at the max depth.
        if levels and len(levels) > 1:
            profile = " · ".join(f"{lv.depth:.0f}m@{lv.runtime:.0f}"
                                 for lv in levels)
        else:
            profile = f"{depth:.0f} m / {bottom_time:.0f} min"

        def rows_for(ss):
            rows, run = [], 0.0
            for s in ss:
                run += s.duration
                if s.kind == "bottom":
                    rows.append([f"{s.depth_end:.0f} m", "-", f"{run:.0f}",
                                 repr(s.gas)])
                elif s.kind == "stop" and s.duration > 0:
                    rows.append([f"{s.depth_start:.0f} m", f"{s.duration:.0f}",
                                 f"{run:.0f}", repr(s.gas)])
            rows.append(["surf", "-", f"{run:.0f}", ""])
            return rows

        cards: List[str] = []
        for label, ss in scen:
            name = ("MAIN DIVE" if label == "OK"
                    else f"LOST {'ALL GASES' if label == 'all' else label}")
            title = [
                name, profile,
                f"{gas!r} · GF {plan.gf_low*100:.0f}/{plan.gf_high*100:.0f}"
                f" · TTS {b.time_to_surface(ss):.0f} · RT {b.total_runtime(ss):.0f}",
            ]
            footers = [min_gas]
            if label != "OK":
                back_l = b.segment_gas_liters([x for x in ss if x.gas == gas], sac)
                footers.append(f"back gas {back_l:.0f} L on {gas!r}")
            card = format_card(title, rows_for(ss),
                               headers=["depth", "stop", "run", "gas"],
                               footer_lines=footers, aligns=[">", ">", ">", "<"])
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
                        planned_time: float) -> List[str]:
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
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_agg import FigureCanvasAgg
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

    def _export_runtime(self, path: str = None) -> None:
        if path is None:
            from tkinter import filedialog
            path = filedialog.asksaveasfilename(
                defaultextension=".png", initialfile="runtime.png",
                filetypes=[("PNG image", "*.png")])
            if not path:
                return
        self._render_runtime_png(path)
        self.runtime_status.config(text=f"saved {os.path.basename(path)}")

    def _copy_runtime(self) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(self.runtime_text.get("1.0", tk.END).rstrip())
        self.runtime_status.config(text="copied")

    # ------------------------------------------------------- config file ----

    def _apply_config(self, cfg: dict) -> None:
        was_building, self._building = self._building, True
        try:
            cfg = dc._merged(cfg)      # migrate legacy depth_m/bottom_time_min
            self._base_cfg = dict(cfg)
            self.gf_lo.set(str(cfg["gf_low"]))
            self.gf_hi.set(str(cfg["gf_high"]))
            self.last_stop6.set(cfg.get("last_stop_m", 3.0) >= 6.0)
            self.sac.set(f"{cfg['sac_normal']:g}")
            self.sac_mult.set(f"{cfg.get('sac_multiplier', 2.0):.2f}")
            cont = cfg.get("contingency", {})
            for var, key in zip((self.cont_tb, self.cont_ta,
                                 self.cont_db, self.cont_da),
                                dc.CONTINGENCY_KEYS):
                var.set(int(cont.get(key, 1)))
            for row in list(self.gas_rows):
                self._remove_gas_row(row)
            for g in cfg["gases"]:
                self._add_gas_row(g["role"], g["o2"], g.get("he", 0),
                                  g.get("tank_l", 0), g.get("pressure_bar", 232),
                                  enabled=g.get("enabled", True),
                                  recompute=False, gas_id=g.get("id"))
            # levels after the gases, so the gas dropdowns can be populated;
            # a level's gas is an id into the stack (None = automatic)
            by_id = {g["id"]: g for g in cfg["gases"] if g.get("id")}
            self.level_rows.clear()
            for w in self.level_list.winfo_children():
                if int(w.grid_info().get("row", 0)) > 0:
                    w.destroy()
            for lv in cfg["levels"]:
                gid = lv.get("gas_id")
                label = (self._gas_label(dc.gas_of(by_id[gid])) if gid in by_id
                         else self.AUTO_GAS)
                self._add_level_row(lv["depth_m"], lv["runtime_min"], label,
                                    recompute=False)
        finally:
            self._building = was_building
        if not self._building:
            self.recompute()

    def _collect_config(self) -> dict:
        cfg = dict(self._base_cfg)               # preserve fields the GUI can't edit
        cfg.pop("depth_m", None)                 # legacy square-profile keys
        cfg.pop("bottom_time_min", None)
        cfg.update({
            # Levels write the legacy inline mix; dive_config.save normalizes
            # it to a gas_id referencing the stack (None = automatic), so the
            # file on disk never carries a separate mix definition.
            "levels": [{"depth_m": l.depth, "runtime_min": l.runtime,
                        "gas": (None if l.gas is None
                                else {"o2": round(l.gas.fO2 * 100),
                                      "he": round(l.gas.fHe * 100)})}
                       for l in self._row_levels()],   # as typed: lose nothing
            "gf_low": int(round(self._pct(self.gf_lo, 0.30) * 100)),
            "gf_high": int(round(self._pct(self.gf_hi, 0.70) * 100)),
            "last_stop_m": 6.0 if self.last_stop6.get() else 3.0,
            "sac_normal": self._num(self.sac, 20.0, lo=1.0),
            "sac_multiplier": round(self._num(self.sac_mult, 2.0, lo=1.0), 2),
            "contingency": dict(zip(dc.CONTINGENCY_KEYS,
                                    (int(self.cont_tb.get()),
                                     int(self.cont_ta.get()),
                                     int(self.cont_db.get()),
                                     int(self.cont_da.get())))),
            "gases": [{"id": r["id"], "role": r["role"].get(),
                       "o2": int(float(r["fo2"].get() or 0)),
                       "he": int(float(r["fhe"].get() or 0)),
                       "tank_l": self._row_tank(r),
                       "pressure_bar": self._row_pressure(r),
                       "enabled": bool(r["use"].get())} for r in self.gas_rows],
        })
        return cfg

    def _save_config(self) -> None:
        dc.save(self._collect_config())
        self.cfg_status.config(text="saved ✓")

    def _reload_config(self) -> None:
        self._apply_config(dc.load())
        self.cfg_status.config(text="reloaded")


def install_launcher() -> None:
    """Register a Linux .desktop launcher + icon for the current user.

    GNOME's dock/taskbar ignores the icon a window sets on itself
    (_NET_WM_ICON) and shows a generic gear unless a .desktop file matches the
    window's WM_CLASS — so the branded taskbar icon needs this one-time step:

        python app.py --install-launcher
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
    here = os.path.dirname(os.path.abspath(__file__))
    desktop = os.path.join(app_dir, f"{APP_NAME}.desktop")
    with open(desktop, "w", encoding="utf-8") as f:
        f.write(f"""[Desktop Entry]
Type=Application
Name={APP_NAME}
Comment=Bühlmann ZHL-16C dive-deco planner (educational)
Exec={sys.executable} {os.path.join(here, "app.py")}
Path={here}
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
    try:
        ttk.Style().theme_use("clam")
    except tk.TclError:
        pass
    DecoApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
