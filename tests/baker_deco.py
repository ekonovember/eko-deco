"""Runner for Erik Baker's GFDECO Fortran program (test oracle).

Generates GFDECO.IN / GFDECO.SET in a temp directory, executes the compiled
baker_oracle/gfdeco binary and parses the deco schedule out of GFDECO.OUT.

Input semantics mirror eko-deco's plan_dive: bottom_time is total runtime to
leaving the bottom (descent included); depths in msw; 3 m stops by default.
Gas switches are given to GFDECO as depth-based changes (Baker's program
applies a change when reaching the first stop at or above that depth).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "baker_oracle")
# build.sh is a convenience for humans; the build below is driven from Python so
# it works on Windows too (where a .sh script would not run at all).
_BIN = os.path.join(_DIR, "gfdeco.exe" if os.name == "nt" else "gfdeco")


def ensure_built() -> str:
    if os.path.exists(_BIN):
        return _BIN
    fc = os.environ.get("FC") or shutil.which("gfortran")
    if fc is None:
        raise RuntimeError(
            "no Fortran compiler on PATH (looked for gfortran, and $FC). This "
            "test compiles Erik Baker's original GFDECO to check the planner "
            "against it — it is a missing compiler, not missing data. Install "
            "one (Debian/Ubuntu: apt install gfortran · macOS: brew install "
            "gcc · Windows: MSYS2/MinGW-w64, or run the suite under WSL) and "
            "these tests will run. Everything else in the suite works without it.")
    proc = subprocess.run([fc, "-std=legacy", "-O2", "-o", _BIN,
                           os.path.join(_DIR, "gfdeco.f")],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError("compiling the Baker GFDECO oracle failed:\n"
                           + (proc.stderr or proc.stdout)[-2000:])
    return _BIN


@dataclass(frozen=True)
class BakerGas:
    """Gas fractions plus the depth at which GFDECO switches to it on ascent
    (`switch_depth` 0 = bottom gas). Fractions must sum to 1."""
    fo2: float
    fhe: float = 0.0
    switch_depth: float = 0.0

    @property
    def fn2(self) -> float:
        return 1.0 - self.fo2 - self.fhe


@dataclass
class BakerResult:
    stops: List[Tuple[float, float]]   # (depth m, minutes) deepest first
    tts: float                         # minutes, leaving bottom -> surface
    first_stop: Optional[float]
    raw_output: str


def plan(bottom_depth: float, bottom_time: float, gases: Sequence[BakerGas],
         gf_low: float, gf_high: float, descent_rate: float = 18.0,
         ascent_rate: float = 10.0, step_size: float = 3.0,
         last_stop_step: Optional[float] = None,
         min_stop_time: float = 1.0) -> BakerResult:
    """Run GFDECO for a square profile — a one-level dive."""
    return plan_levels([(bottom_depth, bottom_time, 1)], gases, gf_low, gf_high,
                       descent_rate, ascent_rate, step_size, last_stop_step,
                       min_stop_time)


def plan_levels(levels: Sequence[Tuple[float, float, int]],
                gases: Sequence[BakerGas],
                gf_low: float, gf_high: float, descent_rate: float = 18.0,
                ascent_rate: float = 10.0, step_size: float = 3.0,
                last_stop_step: Optional[float] = None,
                min_stop_time: float = 1.0) -> BakerResult:
    """Run GFDECO for a multi-level profile.

    `levels` is [(depth, runtime, mix_number)], where runtime is the run time at
    the END of the level (GFDECO's `Run_Time_End_of_Segment`) and mix_number is
    a 1-based index into `gases` — exactly the semantics of eko-deco's `Level`.

    GFDECO takes this natively (gfdeco.f: profile code 1 = ascent/descent,
    code 2 = constant depth, 99 = decompress), so no reinterpretation is needed:
    each level becomes a travel leg plus a constant-depth segment.

    gases[0] is the bottom gas; further gases switch in on the deco ascent at
    their switch_depth. last_stop_step, if given, changes the step size at that
    depth (e.g. 6.0 -> last stop at 6 m).
    """
    ensure_built()
    lines = ["eko-deco cross-check profile", str(len(gases))]
    for g in gases:
        lines.append(f"{g.fo2:.3f},{g.fhe:.3f},{g.fn2:.3f}")

    depth = 0.0
    for level_depth, runtime, mix in levels:
        rate = descent_rate if level_depth > depth else -ascent_rate
        if abs(level_depth - depth) > 1e-9:
            lines += ["1", f"{depth:g},{level_depth:g},{rate:g},{mix}"]
        lines += ["2", f"{level_depth:g},{runtime:g},{mix}"]
        depth = level_depth
    lines.append("99")

    bottom_depth = depth                       # the deco ascent starts here

    # GFDECO takes the ascent's starting depth from the FIRST change entry, so
    # every entry must be at or above the depth the diver is actually at. A deco
    # gas whose switch depth is deeper than the bottom (a shallow last level) is
    # therefore breathable from the moment the ascent begins — which is exactly
    # what eko-deco's best_gas does — so it becomes the starting mix rather than
    # a change at a depth that was never visited.
    start_mix = levels[-1][2]
    start_fo2 = gases[start_mix - 1].fo2
    for i, g in enumerate(gases[1:], start=2):
        if g.switch_depth >= bottom_depth - 1e-9 and g.fo2 > start_fo2:
            start_mix, start_fo2 = i, g.fo2
    changes = [(bottom_depth, start_mix, step_size)]
    for i, g in enumerate(gases[1:], start=2):
        if g.switch_depth < bottom_depth - 1e-9:
            changes.append((g.switch_depth, i, step_size))
    changes.sort(key=lambda c: -c[0])
    if last_stop_step is not None:
        # keep the mix already in effect at that depth (shallowest change
        # at or below it, mirroring GFDECO's sequential change loop)
        mix_at = 1
        for depth, mix, _ in changes:
            if depth >= last_stop_step:
                mix_at = mix
        changes.append((last_stop_step, mix_at, last_stop_step))
        changes.sort(key=lambda c: -c[0])
    lines.append(str(len(changes)))
    for depth, mix, step in changes:
        lines.append(f"{depth:g},{mix},-{ascent_rate:g},{step:g}")
    lines.append("0")  # no repetitive dive

    settings = ("&Program_Settings\n"
                "    Units='msw'\n"
                "    Altitude_Dive_Algorithm='off'\n"
                f"    Minimum_Deco_Stop_Time={min_stop_time:g}\n"
                f"    Gradient_Factor_Lo={gf_low:.2f}\n"
                f"    Gradient_Factor_Hi={gf_high:.2f}\n"
                "/\n")

    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "GFDECO.IN"), "w") as f:
            f.write("\n".join(lines) + "\n")
        with open(os.path.join(tmp, "GFDECO.SET"), "w") as f:
            f.write(settings)
        subprocess.run([_BIN], cwd=tmp, check=True,
                       stdin=subprocess.DEVNULL, capture_output=True,
                       timeout=60)
        with open(os.path.join(tmp, "GFDECO.OUT")) as f:
            out = f.read()
    return _parse(out, levels[-1][1])   # TTS is measured from leaving the bottom


# constant-depth deco stop rows end with: <stop depth> <stop time> <run time>
_STOP_RE = re.compile(r"\|\s*(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)"
                      r"\s+(\d+(?:\.\d+)?)\s*$")
# any segment row starts with: <seg#> <segment time> <run time> |
_SEG_RE = re.compile(r"^\s*\d+\s+(-?[\d.]+|[\d.]+)\s+([\d.]+)\s+\|")


def _parse(out: str, bottom_time: float) -> BakerResult:
    in_deco = False
    stops: List[Tuple[float, float]] = []
    max_run = bottom_time
    for line in out.splitlines():
        if "DECOMPRESSION PROFILE" in line:
            in_deco = True
            continue
        if not in_deco:
            continue
        m = _SEG_RE.match(line)
        if m:
            try:
                max_run = max(max_run, float(m.group(2)))
            except ValueError:
                pass
        s = _STOP_RE.search(line)
        if s and "Descent" not in line:
            depth, minutes = float(s.group(1)), float(s.group(2))
            stops.append((depth, minutes))
    return BakerResult(stops=stops, tts=max_run - bottom_time,
                       first_stop=stops[0][0] if stops else None,
                       raw_output=out)
