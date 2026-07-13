"""ctypes wrapper around Subsurface's native deco.cpp (test oracle).

The model math — tissue loading (`add_segment`), the gradient-factor ceiling
(`tissue_tolerance_calc`, `deco_allowed_depth`, `get_gf`) — is the real,
unmodified Subsurface code compiled into subsurface_oracle/libsubsurface_deco.so
(pinned upstream commit in subsurface_oracle/upstream/UPSTREAM.txt; GPL-2.0,
see subsurface_oracle/README.md for the license boundary).

Only `plan()` below is ours: a minimal schedule loop in the style of
Subsurface's planner.cpp (trial ascent with snapshot/restore, 3 m stop
quantization, 60 s stop increments). It is NOT a port of planner.cpp — treat
schedule-level comparisons as "Subsurface model + a simple planner", and
ceiling/tissue-level comparisons as ground truth.

Units mirror Subsurface: pressures in bar, depths in metres (converted through
salinity exactly like dive.cpp), gas fractions in permille.
"""

from __future__ import annotations

import ctypes
import math
import os
import subprocess
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "subsurface_oracle")
_LIB_PATH = os.path.join(_DIR, "libsubsurface_deco.so")

SEAWATER_SALINITY = 10300
FRESHWATER_SALINITY = 10000
SURFACE_MBAR = 1013  # Subsurface 1_atm


def _load_lib() -> ctypes.CDLL:
    if not os.path.exists(_LIB_PATH):
        subprocess.run([os.path.join(_DIR, "build.sh")], check=True,
                       capture_output=True)
    lib = ctypes.CDLL(_LIB_PATH)
    D, I, S, P = ctypes.c_double, ctypes.c_int, ctypes.c_short, ctypes.c_void_p
    DA = ctypes.POINTER(ctypes.c_double)
    sig = {
        "srf_new": ([], P),
        "srf_free": ([P], None),
        "srf_set_gf": ([S, S], None),
        "srf_set_dive": ([I, I], None),
        "srf_clear_deco": ([P, D], None),
        "srf_add_segment": ([P, D, I, I, I], None),
        "srf_tissue_tolerance": ([P, D], D),
        "srf_allowed_depth_mm": ([D, D, I], I),
        "srf_get_gf": ([P, D], D),
        "srf_tissues": ([P, DA, DA], None),
        "srf_set_tissues": ([P, DA, DA], None),
        "srf_gf_low_pressure_this_dive": ([P], D),
        "srf_set_gf_low_pressure_this_dive": ([P, D], None),
        "srf_guiding_tissue": ([P], I),
        "srf_copy": ([P, P], None),
    }
    for name, (argtypes, restype) in sig.items():
        fn = getattr(lib, name)
        fn.argtypes, fn.restype = argtypes, restype
    return lib


_lib: Optional[ctypes.CDLL] = None


def lib() -> ctypes.CDLL:
    global _lib
    if _lib is None:
        _lib = _load_lib()
    return _lib


@dataclass(frozen=True)
class Gas:
    """Breathing gas in Subsurface permille units."""
    o2: int            # permille
    he: int = 0        # permille

    @property
    def fo2(self) -> float:
        return self.o2 / 1000.0

    def __repr__(self) -> str:
        if self.he:
            return f"{self.o2 // 10}/{self.he // 10}"
        return "air" if self.o2 == 210 else f"EAN{self.o2 // 10}"


@dataclass
class Stop:
    depth_m: float
    minutes: float


class SubsurfaceDeco:
    """One deco_state driven through the native Subsurface functions."""

    def __init__(self, gf_low: int = 30, gf_high: int = 80,
                 surface_mbar: int = SURFACE_MBAR,
                 salinity: int = SEAWATER_SALINITY):
        self._lib = lib()
        self.surface_mbar = surface_mbar
        self.salinity = salinity
        self.gf_low, self.gf_high = gf_low, gf_high
        self.ds = self._lib.srf_new()
        self._configure()
        self._lib.srf_clear_deco(self.ds, self.surface_bar)

    # deco.cpp keeps GF and the dive in globals; re-assert ours before use so
    # several SubsurfaceDeco instances with different settings can coexist.
    def _configure(self) -> None:
        self._lib.srf_set_gf(self.gf_low, self.gf_high)
        self._lib.srf_set_dive(self.surface_mbar, self.salinity)

    def __del__(self):
        try:
            self._lib.srf_free(self.ds)
        except Exception:
            pass

    # -- unit conversions, exactly like the stub dive / dive.cpp --------------

    @property
    def surface_bar(self) -> float:
        return self.surface_mbar / 1000.0

    @property
    def specific_weight(self) -> float:
        """mbar per mm, == bar per metre."""
        return self.salinity * 0.981 / 100000.0

    @property
    def msw_per_bar(self) -> float:
        """eko-deco's msw_per_bar equivalent for this salinity."""
        return 1.0 / self.specific_weight

    def depth_to_bar(self, depth_m: float) -> float:
        return (self.surface_mbar + depth_m * 1000.0 * self.specific_weight) / 1000.0

    def bar_to_depth(self, bar: float) -> float:
        return max(0.0, (bar * 1000.0 - self.surface_mbar) / self.specific_weight / 1000.0)

    # -- native calls ----------------------------------------------------------

    def clear(self) -> None:
        self._configure()
        self._lib.srf_clear_deco(self.ds, self.surface_bar)

    def add_segment(self, pressure_bar: float, gas: Gas, seconds: int) -> None:
        self._configure()
        self._lib.srf_add_segment(self.ds, pressure_bar, gas.o2, gas.he, seconds)

    def add_flat(self, depth_m: float, gas: Gas, seconds: int) -> None:
        self.add_segment(self.depth_to_bar(depth_m), gas, seconds)

    def add_ramp(self, from_m: float, to_m: float, rate_m_min: float,
                 gas: Gas, slice_s: int = 1) -> float:
        """Depth change as 1 s constant-pressure slices at mid-slice depth
        (Subsurface's planner feeds the model discrete samples the same way).
        Returns the duration in minutes."""
        total_s = int(round(abs(to_m - from_m) / rate_m_min * 60.0))
        if total_s == 0:
            return 0.0
        step = (to_m - from_m) / total_s
        for i in range(0, total_s, slice_s):
            n = min(slice_s, total_s - i)
            mid = from_m + step * (i + n / 2.0)
            self.add_segment(self.depth_to_bar(mid), gas, n)
        return total_s / 60.0

    def tolerance_bar(self) -> float:
        self._configure()
        return self._lib.srf_tissue_tolerance(self.ds, self.surface_bar)

    def ceiling_m(self, smooth: bool = False) -> float:
        """Ceiling in metres; smooth=False rounds up to 3 m stop multiples."""
        self._configure()
        mm = self._lib.srf_allowed_depth_mm(self.tolerance_bar(),
                                            self.surface_bar,
                                            1 if smooth else 0)
        return mm / 1000.0

    def gf_at(self, pressure_bar: float) -> float:
        self._configure()
        return self._lib.srf_get_gf(self.ds, pressure_bar)

    def tissues(self) -> Tuple[List[float], List[float]]:
        n2 = (ctypes.c_double * 16)()
        he = (ctypes.c_double * 16)()
        self._lib.srf_tissues(self.ds, n2, he)
        return list(n2), list(he)

    def set_tissues(self, n2: Sequence[float], he: Sequence[float]) -> None:
        an = (ctypes.c_double * 16)(*n2)
        ah = (ctypes.c_double * 16)(*he)
        self._lib.srf_set_tissues(self.ds, an, ah)

    @property
    def gf_low_pressure_this_dive(self) -> float:
        return self._lib.srf_gf_low_pressure_this_dive(self.ds)

    @gf_low_pressure_this_dive.setter
    def gf_low_pressure_this_dive(self, bar: float) -> None:
        self._lib.srf_set_gf_low_pressure_this_dive(self.ds, bar)

    def snapshot(self) -> ctypes.c_void_p:
        other = self._lib.srf_new()
        self._lib.srf_copy(other, self.ds)
        return other

    def restore(self, snap: ctypes.c_void_p) -> None:
        self._lib.srf_copy(self.ds, snap)

    def free_snapshot(self, snap: ctypes.c_void_p) -> None:
        self._lib.srf_free(snap)

    # -- schedule loop (ours, planner.cpp-style; see module docstring) --------

    def switch_depth(self, gas: Gas, ppo2_max: float = 1.6,
                     stop_interval: float = 3.0, ppo2_tol: float = 0.05) -> float:
        """Ascent switch depth: MOD snapped to the nearest stop multiple —
        same rule as eko-deco DivePlan.switch_depth (O2 at the 6 m stop)."""
        mod = self.bar_to_depth(ppo2_max / gas.fo2)
        if mod <= 0:
            return mod
        snapped = round(mod / stop_interval) * stop_interval
        if (snapped > mod and gas.fo2 * self.depth_to_bar(snapped)
                > ppo2_max + ppo2_tol + 1e-9):
            snapped = math.floor(mod / stop_interval) * stop_interval
        return snapped

    def best_gas(self, depth_m: float, gases: Sequence[Gas],
                 ppo2_max: float = 1.6, ppo2_min: float = 0.18) -> Gas:
        """Richest gas usable at depth — same rule as eko-deco DivePlan.best_gas."""
        amb = self.depth_to_bar(depth_m)
        usable = [g for g in gases
                  if depth_m <= self.switch_depth(g, ppo2_max) + 1e-9
                  and g.fo2 * amb >= ppo2_min - 1e-9]
        return max(usable, key=lambda g: g.o2) if usable else gases[0]

    def plan(self, bottom_depth: float, bottom_time: float, bottom_gas: Gas,
             deco_gases: Sequence[Gas] = (), descent_rate: float = 18.0,
             ascent_rate: float = 10.0, stop_interval: float = 3.0,
             from_current: bool = False,
             max_minutes: float = 24 * 60) -> Tuple[List[Stop], float]:
        """Square-profile schedule — a one-level dive."""
        return self.plan_levels([(bottom_depth, bottom_time, None)], bottom_gas,
                                deco_gases, descent_rate, ascent_rate,
                                stop_interval, from_current, max_minutes)

    def plan_levels(self, levels: Sequence[Tuple[float, float, Optional[Gas]]],
                    bottom_gas: Gas, deco_gases: Sequence[Gas] = (),
                    descent_rate: float = 18.0, ascent_rate: float = 10.0,
                    stop_interval: float = 3.0, from_current: bool = False,
                    max_minutes: float = 24 * 60) -> Tuple[List[Stop], float]:
        """Multi-level schedule. `levels` is [(depth, runtime, gas|None)] where
        runtime is the run time at the END of the level (descent included) and
        gas None = the bottom gas (the oracle's profiles never need the
        travel-mix substitution) — matching eko-deco's `Level`. from_current=True continues from the present tissue state
        (repetitive dive). Returns (stops, time-to-surface: the final ascent
        only, travel between levels is bottom time)."""
        gases = [bottom_gas, *deco_gases]
        if not from_current:
            self.clear()

        run = 0.0
        depth = 0.0
        for level_depth, runtime, level_gas in levels:
            gas = level_gas or bottom_gas
            rate = descent_rate if level_depth > depth else ascent_rate
            run += self.add_ramp(depth, level_depth, rate, gas)
            self.add_flat(level_depth, gas, int(round(max(0.0, runtime - run) * 60.0)))
            run = runtime
            depth = level_depth
        bottom_depth = depth

        stops: List[Stop] = []
        tts = 0.0
        depth = bottom_depth
        while depth > 1e-9:
            target = max(0.0, (math.ceil(depth / stop_interval - 1e-9) - 1)
                         * stop_interval)
            # trial ascent, exactly like planner.cpp: move up, then check
            snap = self.snapshot()
            gas = self.best_gas((depth + target) / 2.0, gases)
            t = self.add_ramp(depth, target, ascent_rate, gas)
            if self.ceiling_m(smooth=False) <= target + 1e-9:
                self.free_snapshot(snap)
                tts += t
                depth = target
                continue
            self.restore(snap)
            self.free_snapshot(snap)
            gas = self.best_gas(depth, gases)
            self.add_flat(depth, gas, 60)
            tts += 1.0
            if stops and stops[-1].depth_m == depth:
                stops[-1].minutes += 1.0
            else:
                stops.append(Stop(depth, 1.0))
            if tts > max_minutes:
                raise RuntimeError("schedule exceeded max_minutes")
        return stops, tts

    def ndl_min(self, depth_m: float, gas: Gas, max_min: int = 600) -> Optional[int]:
        """Minutes at depth (after instantaneous descent) before the ceiling
        drops below the surface — same definition as eko-deco ndl()."""
        self.clear()
        amb = self.depth_to_bar(depth_m)
        for minute in range(1, max_min + 1):
            self.add_segment(amb, gas, 60)
            if self.ceiling_m(smooth=True) > 1e-9:
                return minute - 1
        return None
