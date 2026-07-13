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
import subprocess
import tempfile
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "baker_oracle")
_BIN = os.path.join(_DIR, "gfdeco")


def ensure_built() -> str:
    if not os.path.exists(_BIN):
        subprocess.run([os.path.join(_DIR, "build.sh")], check=True,
                       capture_output=True)
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
    """Run GFDECO for a square profile. gases[0] is the bottom gas; further
    gases switch in at their switch_depth. last_stop_step, if given, changes
    the step size at that depth (e.g. 6.0 -> last stop at 6 m)."""
    ensure_built()
    lines = ["eko-deco cross-check profile", str(len(gases))]
    for g in gases:
        lines.append(f"{g.fo2:.3f},{g.fhe:.3f},{g.fn2:.3f}")
    lines += ["1", f"0,{bottom_depth:g},{descent_rate:g},1",
              "2", f"{bottom_depth:g},{bottom_time:g},1",
              "99"]
    changes = [(bottom_depth, 1, step_size)]
    for i, g in enumerate(gases[1:], start=2):
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
    return _parse(out, bottom_time)


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
