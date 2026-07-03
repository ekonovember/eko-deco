"""Interactive dive-profile visualizer for the Bühlmann ZHL-16C + GF model.

Left panel: dive settings (depth, bottom time, gradient factors, a fully editable
gas list where every mix — bottom / travel / deco — has its own O2, He and tank,
plus SAC and solo/team). Middle: the depth-vs-time profile with a Ratio-Deco
overlay. Right: the results panel (schedule, TTS, per-cylinder gas + rock bottom).

The dive is loaded from and saved to ``dive_plan.json`` (see ``dive_config.py``),
the same file the console planner reads/writes — so ``cli.py plan --save`` shows
up here on Reload, and vice-versa.

Run:
    python app.py
"""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import ttk
from typing import List, Tuple

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

import buhlmann as b
import dive_config as dc
import ratio_deco as rd

# The GUI ascends at a fixed rate; keep it in step with the CLI DivePlan default
# (10 m/min) so the same inputs give the same schedule in both.
ASCENT_RATE = 10.0


def build_profile_points(segs) -> Tuple[List[float], List[float]]:
    """Concatenate segment endpoints into a (time, depth) polyline."""
    t, d, run = [0.0], [0.0], 0.0
    for s in segs:
        run += s.duration
        t.append(run)
        d.append(s.depth_end)
    return t, d


def build_ratio_profile(segs, rd_result, ascent_rate: float
                        ) -> Tuple[List[float], List[float]]:
    """Depth-vs-time polyline for the Ratio Deco schedule: it shares the Bühlmann
    descent + bottom, then follows the RD stops."""
    t, d, run, bottom_depth = [0.0], [0.0], 0.0, 0.0
    for s in segs:
        run += s.duration
        t.append(run)
        d.append(s.depth_end)
        if s.kind == "bottom":
            bottom_depth = s.depth_end
            break
    cur = bottom_depth
    if not rd_result.min_deco and rd_result.stops:
        for stop in rd_result.stops:
            run += abs(cur - stop.depth_m) / ascent_rate
            t.append(run)
            d.append(stop.depth_m)
            run += stop.minutes
            t.append(run)
            d.append(stop.depth_m)
            cur = stop.depth_m
    run += cur / ascent_rate
    t.append(run)
    d.append(0.0)
    return t, d


class DecoApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("Bühlmann ZHL-16C — Deco Profile Visualizer")
        root.geometry("1500x900")

        self._building = True
        self._base_cfg = dc.default_config()
        self._ascent = ASCENT_RATE
        self._build_layout()
        self._apply_config(dc.load())
        self._building = False
        self.recompute()

    # ---------------------------------------------------------------- UI ----

    def _build_layout(self) -> None:
        main = ttk.Frame(self.root, padding=6)
        main.pack(fill=tk.BOTH, expand=True)

        left = ttk.LabelFrame(main, text="Dive", padding=8)
        left.pack(side=tk.LEFT, fill=tk.Y)

        right = ttk.Frame(main)
        right.pack(side=tk.RIGHT, fill=tk.Y, padx=(6, 0))
        results = ttk.LabelFrame(right, text="Results", padding=6)
        runtime_frame = ttk.LabelFrame(right, text="Runtime — wetnotes (printable)",
                                       padding=6)
        runtime_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(6, 0))
        results.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        center = ttk.Frame(main)
        center.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(6, 0))

        # --- dive settings ---
        self.depth = self._add_slider(left, "Depth (m)", 6, 120, 1, 45)
        self.bottom = self._add_slider(left, "Bottom time (min)", 1, 200, 1, 10)
        self._add_gf_row(left)

        # --- gases (bottom / travel / deco, each with O2/He + tank) ---
        gases = ttk.LabelFrame(left, text="Gases", padding=6)
        gases.pack(fill=tk.X, pady=(8, 0))
        hdr = ttk.Frame(gases)
        hdr.pack(fill=tk.X)
        for text, w in (("role", 7), ("O₂%", 5), ("He%", 5), ("tank L", 6), ("bar", 5)):
            ttk.Label(hdr, text=text, width=w, anchor="w").pack(side=tk.LEFT, padx=1)
        self.gas_list = ttk.Frame(gases)
        self.gas_list.pack(fill=tk.X)
        self.gas_rows = []
        ttk.Button(gases, text="+ Add gas", command=self._add_gas_row).pack(
            anchor="w", pady=(4, 0))

        # --- gas planning ---
        gp = ttk.LabelFrame(left, text="Gas planning (rock bottom)", padding=6)
        gp.pack(fill=tk.X, pady=(8, 0))
        self.sac = self._add_slider(gp, "SAC normal (L/min)", 5, 40, 1, 20)
        self.sac_stress = self._add_slider(gp, "SAC distress (L/min)", 5, 80, 1, 40)
        self.solo = tk.BooleanVar(value=False)
        ttk.Checkbutton(gp, text="Solo dive (else 2 divers)", variable=self.solo,
                        command=lambda: None if self._building else self.recompute()
                        ).pack(anchor="w", pady=(2, 0))

        self.show_rd = self._add_checkbox(
            self._packed(ttk.Frame(left)), "Ratio Deco vs Bühlmann panel", True)

        # --- config file save / reload ---
        cfgrow = ttk.Frame(left)
        cfgrow.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(cfgrow, text="Save", command=self._save_config).pack(side=tk.LEFT)
        ttk.Button(cfgrow, text="Reload", command=self._reload_config).pack(
            side=tk.LEFT, padx=4)
        self.cfg_status = ttk.Label(cfgrow, text=os.path.basename(dc.DEFAULT_PATH))
        self.cfg_status.pack(side=tk.LEFT, padx=4)

        # --- results panel (scrollable) ---
        self.readout = tk.Text(results, width=46, height=28, font=("Consolas", 9),
                               relief="flat", bg=self.root.cget("bg"))
        scroll = ttk.Scrollbar(results, command=self.readout.yview)
        self.readout.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.readout.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # --- runtime "wetnotes" card (bottom-right, printable) ---
        self.runtime_text = tk.Text(runtime_frame, width=46, height=14,
                                    font=("Consolas", 9), relief="flat",
                                    bg=self.root.cget("bg"))
        self.runtime_text.pack(fill=tk.X)
        rt_btns = ttk.Frame(runtime_frame)
        rt_btns.pack(fill=tk.X, pady=(4, 0))
        ttk.Button(rt_btns, text="Export PNG",
                   command=self._export_runtime).pack(side=tk.LEFT)
        ttk.Button(rt_btns, text="Copy",
                   command=self._copy_runtime).pack(side=tk.LEFT, padx=4)
        self.runtime_status = ttk.Label(rt_btns, text="")
        self.runtime_status.pack(side=tk.LEFT, padx=4)

        # --- chart ---
        self.fig = Figure(figsize=(8, 6), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.fig, master=center)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    def _packed(self, frame) -> ttk.Frame:
        frame.pack(fill=tk.X, pady=(8, 0))
        return frame

    def _add_slider(self, parent, label, lo, hi, step, init) -> tk.DoubleVar:
        row = ttk.Frame(parent)
        row.pack(fill=tk.X, pady=2)
        var = tk.DoubleVar(value=init)

        head = ttk.Frame(row)
        head.pack(fill=tk.X)
        ttk.Label(head, text=label).pack(side=tk.LEFT)
        value_lbl = ttk.Label(head, text=f"{init:g}", width=6, anchor="e")
        value_lbl.pack(side=tk.RIGHT)

        def on_change(_):
            value_lbl.config(text=f"{var.get():.0f}")
            if not self._building:
                self.recompute()

        scale = ttk.Scale(row, from_=lo, to=hi, orient="horizontal",
                          variable=var, command=on_change)
        scale.pack(fill=tk.X)
        return var

    def _add_checkbox(self, parent, label, init=False) -> tk.BooleanVar:
        var = tk.BooleanVar(value=init)
        ttk.Checkbutton(
            parent, text=label, variable=var,
            command=lambda: None if self._building else self.recompute(),
        ).pack(side=tk.LEFT, anchor="w", padx=(0, 8))
        return var

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
        for v in (self.gf_lo, self.gf_hi):
            v.trace_add("write", lambda *_: None if self._building else self.recompute())

    def _add_gas_row(self, role: str = "Deco", fo2: float = 50, fhe: float = 0,
                     tank: float = 11, pressure: float = 232,
                     recompute: bool = True) -> None:
        rf = ttk.Frame(self.gas_list)
        rf.pack(fill=tk.X, pady=1)
        role_var = tk.StringVar(value=role)
        fo2_var = tk.StringVar(value=str(int(fo2)))
        fhe_var = tk.StringVar(value=str(int(fhe)))
        tank_var = tk.StringVar(value=str(int(tank)))
        press_var = tk.StringVar(value=str(int(pressure)))

        ttk.Combobox(rf, textvariable=role_var, width=6, state="readonly",
                     values=dc.ROLES).pack(side=tk.LEFT, padx=1)
        ttk.Spinbox(rf, from_=5, to=100, width=4, textvariable=fo2_var).pack(
            side=tk.LEFT, padx=1)
        ttk.Spinbox(rf, from_=0, to=95, width=4, textvariable=fhe_var).pack(
            side=tk.LEFT, padx=1)
        ttk.Spinbox(rf, from_=0, to=30, width=5, textvariable=tank_var).pack(
            side=tk.LEFT, padx=1)
        ttk.Spinbox(rf, from_=0, to=300, width=4, textvariable=press_var).pack(
            side=tk.LEFT, padx=1)

        row = {"frame": rf, "role": role_var, "fo2": fo2_var,
               "fhe": fhe_var, "tank": tank_var, "pressure": press_var}
        ttk.Button(rf, text="✕", width=2,
                   command=lambda: self._remove_gas_row(row)).pack(side=tk.LEFT, padx=1)
        for var in (role_var, fo2_var, fhe_var, tank_var, press_var):
            var.trace_add("write",
                          lambda *_: None if self._building else self.recompute())
        self.gas_rows.append(row)
        if recompute and not self._building:
            self.recompute()

    def _remove_gas_row(self, row) -> None:
        if row in self.gas_rows:
            self.gas_rows.remove(row)
            row["frame"].destroy()
            if not self._building:
                self.recompute()

    def _row_gas(self, row):
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
            ppo2_bottom=base.get("ppo2_bottom", 1.4),
            ppo2_deco=base.get("ppo2_deco", 1.6),
            ppo2_min=base.get("ppo2_min", 0.18),
            deco_gases=tuple(deco),
            travel_gases=tuple(travel),
        )

    def recompute(self) -> None:
        depth = float(self.depth.get())
        gas = self._bottom_gas()
        plan = self._make_plan()
        bottom_time = max(1.0, float(self.bottom.get()))

        try:
            segs, tissues = b.plan_dive(depth, bottom_time, gas, plan)
        except Exception as e:                # noqa: BLE001 - surface any input error
            self._error(f"Plan error: {e}")
            return

        rd_result = rd.ratio_deco(depth, bottom_time)
        self._ascent = plan.ascent_rate
        self._draw(segs, depth, bottom_time, rd_result)
        self._write_readout(depth, gas, plan, bottom_time, segs, tissues, rd_result)
        self._write_runtime(depth, gas, plan, bottom_time, segs)

    # -------------------------------------------------------------- draw ----

    def _draw(self, segs, bottom_depth: float, bottom_time: float,
              rd_result=None) -> None:
        t, d = build_profile_points(segs)
        self.ax.clear()

        self.ax.plot(t, d, color="#1f77b4", linewidth=2, label="Bühlmann GF")
        self.ax.fill_between(t, d, max(d) * 1.05 + 1, color="#1f77b4", alpha=0.10)
        x_max = max(t)

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

        if rd_result is not None and self.show_rd.get():
            t2, d2 = build_ratio_profile(segs, rd_result, self._ascent)
            self.ax.plot(t2, d2, color="#ff7f0e", linewidth=1.6, linestyle="--",
                         label="Ratio Deco (std gas)")
            x_max = max(x_max, max(t2))
            self.ax.legend(loc="lower right", fontsize=8)

        self.ax.set_xlabel("Runtime (min)")
        self.ax.set_ylabel("Depth (m)")
        self.ax.set_title(
            f"Profile  —  bottom {bottom_depth:.0f} m for {bottom_time:.0f} min "
            f"(total {sum(s.duration for s in segs):.0f} min)")
        self.ax.invert_yaxis()
        self.ax.grid(True, alpha=0.3)
        self.ax.set_xlim(0, x_max * 1.02 + 1)
        self.ax.set_ylim(max(d) * 1.10 + 2, 0)
        self.fig.tight_layout()
        self.canvas.draw_idle()

    # ----------------------------------------------------------- readout ----

    def _write_readout(self, depth, gas, plan, bottom_time,
                       segs, tissues, rd_result=None) -> None:
        ceil_now = b.ceiling_depth(tissues, plan.gf_high)
        total = b.total_runtime(segs)
        tts = b.time_to_surface(segs)
        stops = [s for s in segs if s.kind == "stop" and s.duration > 0]
        deco_total = sum(s.duration for s in stops)
        ndl_min = b.ndl(depth, gas, plan)
        ndl_label = ">10 h" if ndl_min is None else f"{ndl_min} min"

        lines = [
            f"Bottom gas : {gas!r}",
            f"  fO₂ {gas.fO2*100:.0f}%  fHe {gas.fHe*100:.0f}%  fN₂ {gas.fN2*100:.0f}%",
            f"  ppO₂@{depth:.0f}m: {gas.ppo2(depth):.2f} bar",
            f"  MOD 1.4   : {gas.mod(1.4):.0f} m",
        ]
        if gas.min_depth(plan.ppo2_min) > 0:
            note = "" if plan.travel_gases else "  (need travel gas!)"
            lines.append(f"  hypoxic <  : {gas.min_depth(plan.ppo2_min):.0f} m{note}")
        if plan.travel_gases:
            lines.append(f"  travel    : {', '.join(repr(g) for g in plan.travel_gases)}")
        if plan.deco_gases:
            lines.append(f"  deco      : {', '.join(repr(g) for g in plan.deco_gases)}")

        lines += [
            "",
            f"GF low/high : {plan.gf_low*100:.0f} / {plan.gf_high*100:.0f}",
            f"NDL @ {depth:.0f} m : {ndl_label}",
            f"Bottom time : {bottom_time:.0f} min",
            f"Runtime     : {total:.0f} min",
            f"TTS         : {tts:.0f} min",
            f"Deco total  : {deco_total:.0f} min ({len(stops)} stops)",
            f"Final ceil  : {ceil_now:.2f} m",
        ]

        # --- per-cylinder gas + rock bottom ---
        sac = float(self.sac.get())
        sac_stress = float(self.sac_stress.get())
        divers = 1 if self.solo.get() else 2
        gp = b.GasPlan(sac=sac, sac_stress=sac_stress, divers=divers,
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
        lines += ["", f"Gas  SAC {sac:.0f}/{sac_stress:.0f}, "
                      f"{'solo' if divers == 1 else '2 divers'}:"]
        seen = []
        for s in segs:
            key = repr(s.gas)
            if key in seen:
                continue
            seen.append(key)
            liters = b.segment_gas_liters([x for x in segs if x.gas == s.gas], sac)
            tk_l = tanks.get(key, 0.0)
            pr = press.get(key, 0.0)
            label = roles.get(key, "stage")
            if tk_l <= 0:
                lines.append(f"  {label} {s.gas!r}: {liters:.0f} L (set tank)")
            elif pr > 0:
                used = liters / tk_l
                short = "  SHORT!" if used > pr + 1e-9 else ""
                lines.append(f"  {label} {s.gas!r}: {used:.0f}/{pr:.0f} bar "
                             f"({pr - used:.0f} left) / {tk_l:.0f} L{short}")
            else:
                lines.append(f"  {label} {s.gas!r}: {liters / tk_l:.0f} bar / {tk_l:.0f} L")
        rock = b.rock_bottom_liters(depth, gp, plan.ascent_rate)
        if back_tank > 0:
            rock_bar = rock / back_tank
            line = f"  Rock bottom: {rock_bar:.0f} bar reserve"
            if back_pressure > 0:
                usable = back_pressure - rock_bar
                if usable > 0:
                    line += (f"; from {back_pressure:.0f} turn "
                             f"~{back_pressure - usable / 2.0:.0f} bar")
                else:
                    line += f" — over {back_pressure:.0f} bar fill!"
            lines.append(line)
        else:
            lines.append(f"  Rock bottom: {rock:.0f} L (set bottom tank)")

        # --- Ratio Deco comparison ---
        if rd_result is not None and self.show_rd.get():
            r = rd_result
            std = r.bottom_gas + (f" + {', '.join(r.deco_gases)}" if r.deco_gases else "")
            lines += ["", "Ratio Deco vs Bühlmann (educational):",
                      f"  std gas : {std}"]
            if r.min_deco:
                lines.append(f"  ratio {r.ratio:.2f} -> min deco (no stops)")
                lines.append(f"  deco:  Bühlmann {deco_total:.0f}  |  RD 0 min")
            else:
                lines.append(f"  ratio {r.ratio:.2f}   first stop {r.first_stop_m:.0f} m")
                lines.append(f"  deco:  Bühlmann {deco_total:.0f}  |  RD "
                             f"{r.scheduled_deco_min:.0f} min")
                for s in r.stops:
                    lines.append(f"  {s.depth_m:>3.0f} m  {s.minutes:>4.1f} min   "
                                 f"on {s.gas}")

        # --- Bühlmann stops ---
        lines += ["", "Bühlmann stops:"]
        if not stops:
            lines.append("  (none — no mandatory stops)")
        else:
            for s in stops:
                lines.append(f"  {s.depth_start:>3.0f} m  "
                             f"{s.duration:>4.0f} min   on {s.gas!r}")

        self.readout.delete("1.0", tk.END)
        self.readout.insert(tk.END, "\n".join(lines))

    def _error(self, msg: str) -> None:
        self.readout.delete("1.0", tk.END)
        self.readout.insert(tk.END, msg)

    # ----------------------------------------------------------- runtime ----

    def _write_runtime(self, depth, gas, plan, bottom_time, segs) -> None:
        """Compact wetnotes runtime: max depth + each stop with cumulative runtime
        and gas, plus TTS and the minimum-gas / turn pressure."""
        total = b.total_runtime(segs)
        tts = b.time_to_surface(segs)
        lines = [
            f"RUNTIME   {depth:.0f} m / {bottom_time:.0f} min",
            f"{gas!r}   GF {plan.gf_low*100:.0f}/{plan.gf_high*100:.0f}"
            f"   TTS {tts:.0f}   RT {total:.0f}",
            " depth  stop   run   gas",
            "-" * 30,
        ]
        run = 0.0
        for s in segs:
            run += s.duration
            if s.kind == "bottom":
                lines.append(f" {s.depth_end:>4.0f} m    -  {run:>4.0f}   {s.gas!r}")
            elif s.kind == "stop" and s.duration > 0:
                lines.append(f" {s.depth_start:>4.0f} m  {s.duration:>3.0f}  "
                             f"{run:>4.0f}   {s.gas!r}")
        lines.append(f"  surf      -  {total:>4.0f}")

        sac = float(self.sac.get())
        divers = 1 if self.solo.get() else 2
        gp = b.GasPlan(sac=sac, sac_stress=float(self.sac_stress.get()),
                       divers=divers,
                       problem_minutes=self._base_cfg.get("problem_minutes", 1.0))
        rock = b.rock_bottom_liters(depth, gp, plan.ascent_rate)
        back_tank = back_pressure = 0.0
        for row in self.gas_rows:
            g = self._row_gas(row)
            if g is not None and row["role"].get() == "Bottom" and g == gas:
                back_tank, back_pressure = self._row_tank(row), self._row_pressure(row)
        lines.append("-" * 30)
        if back_tank > 0:
            rb = rock / back_tank
            slate = f" MIN GAS {rb:.0f} bar ({'solo' if divers == 1 else '2 divers'})"
            if back_pressure > rb:
                slate += f"   TURN {back_pressure - (back_pressure - rb) / 2:.0f} bar"
            lines.append(slate)
        else:
            lines.append(f" MIN GAS {rock:.0f} L")

        self.runtime_text.delete("1.0", tk.END)
        self.runtime_text.insert(tk.END, "\n".join(lines))

    def _render_runtime_png(self, path: str) -> str:
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        text = self.runtime_text.get("1.0", tk.END).rstrip("\n")
        n = text.count("\n") + 1
        fig = Figure(figsize=(4.6, max(2.0, 0.24 * n + 0.5)), dpi=150)
        FigureCanvasAgg(fig)
        fig.patch.set_facecolor("white")
        fig.text(0.04, 0.98, text, va="top", ha="left", family="monospace",
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
            self._base_cfg = dict(cfg)
            self.depth.set(cfg["depth_m"])
            self.bottom.set(cfg["bottom_time_min"])
            self.gf_lo.set(str(cfg["gf_low"]))
            self.gf_hi.set(str(cfg["gf_high"]))
            self.solo.set(bool(cfg.get("solo")))
            self.sac.set(cfg["sac_normal"])
            self.sac_stress.set(cfg["sac_stress"])
            self.show_rd.set(bool(cfg.get("show_rd", True)))
            for row in list(self.gas_rows):
                self._remove_gas_row(row)
            for g in cfg["gases"]:
                self._add_gas_row(g["role"], g["o2"], g.get("he", 0),
                                  g.get("tank_l", 0), g.get("pressure_bar", 232),
                                  recompute=False)
        finally:
            self._building = was_building
        if not self._building:
            self.recompute()

    def _collect_config(self) -> dict:
        cfg = dict(self._base_cfg)               # preserve fields the GUI can't edit
        cfg.update({
            "depth_m": float(self.depth.get()),
            "bottom_time_min": float(self.bottom.get()),
            "gf_low": int(round(self._pct(self.gf_lo, 0.30) * 100)),
            "gf_high": int(round(self._pct(self.gf_hi, 0.70) * 100)),
            "solo": bool(self.solo.get()),
            "sac_normal": float(self.sac.get()),
            "sac_stress": float(self.sac_stress.get()),
            "show_rd": bool(self.show_rd.get()),
            "gases": [{"role": r["role"].get(),
                       "o2": int(float(r["fo2"].get() or 0)),
                       "he": int(float(r["fhe"].get() or 0)),
                       "tank_l": self._row_tank(r),
                       "pressure_bar": self._row_pressure(r)} for r in self.gas_rows],
        })
        return cfg

    def _save_config(self) -> None:
        dc.save(self._collect_config())
        self.cfg_status.config(text="saved ✓")

    def _reload_config(self) -> None:
        self._apply_config(dc.load())
        self.cfg_status.config(text="reloaded")


def main() -> None:
    root = tk.Tk()
    try:
        ttk.Style().theme_use("clam")
    except tk.TclError:
        pass
    DecoApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
