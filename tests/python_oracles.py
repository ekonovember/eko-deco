"""Adapters for the third-party **Python** decompression libraries.

The compiled oracles (`subsurface_oracle/`, `baker_oracle/`) pin us to a C++
and a Fortran implementation. These add two independent *Python* ones, which
cost nothing to run and are trivially skippable:

* **decotengu** — Artur Wróblewski's library, a full engine with its own ascent
  and stop-time search (linear scan then binary search for the exact minimum,
  no runtime padding). GPL-3.
* **decodaitengu** — a maintained fork with a clean model-level API
  (`init` / `load` / `ceiling`) and helium plus hydrogen support. GPL-3.

**Not vendored and not a runtime dependency.** They are ordinary
`pip install` test dependencies in the ``[dev]`` extra, imported only by the
test suite, exactly like g++ and gfortran are only needed to build the compiled
oracles. Nothing in `src/deco` imports them, no code is copied out of them, and
the wheel does not carry them — the same license boundary the vendored oracles
are held to, kept by not vendoring at all.

Every entry point here degrades to ``None``/``False`` when the library is
missing, so the suite still runs on a bare stdlib Python.
"""

from __future__ import annotations

from dataclasses import dataclass

from deco import buhlmann as b

# --------------------------------------------------------------------------
# availability
# --------------------------------------------------------------------------

try:
    import decotengu as _dt
    from decotengu.model import ZH_L16B_GF as _DT_B
    from decotengu.model import ZH_L16C_GF as _DT_C
    HAVE_DECOTENGU = True
except Exception:                                    # pragma: no cover
    HAVE_DECOTENGU = False

try:
    from decodaitengu.models.zhl16b import ZHL16B_PARAMS as _DD_B_PARAMS
    from decodaitengu.models.zhl16c import ZHL16C
    from decodaitengu.models.zhl16c import ZHL16C_PARAMS as _DD_C_PARAMS
    from decodaitengu.types import Gas as _DDGas
    HAVE_DECODAITENGU = True
except Exception:                                    # pragma: no cover
    HAVE_DECODAITENGU = False

SKIP_REASON = ("third-party python oracle not installed — "
               "pip install -e '.[dev]' (decotengu, decodaitengu)")


def coefficients(gas: str = "n2", variant: str = "C") -> dict[str, tuple]:
    """The ZH-L16 ``(half-times, a, b)`` tables each project ships.

    A pure data check and the cheapest cross-check there is: if four
    independent projects transcribed Bühlmann's tables the same way, ours is
    not a transcription error — and where one differs, this says which.
    """
    if gas == "n2":
        out: dict[str, tuple] = {
            "eko-deco": (b.N2_HALFTIME, b.N2_A, b.N2_B)}
    else:
        out = {"eko-deco": (b.HE_HALFTIME, b.HE_A, b.HE_B)}
    if HAVE_DECOTENGU:
        m = (_DT_C if variant == "C" else _DT_B)()
        out["decotengu"] = ((tuple(m.N2_HALF_LIFE), tuple(m.N2_A), tuple(m.N2_B))
                            if gas == "n2" else
                            (tuple(m.HE_HALF_LIFE), tuple(m.HE_A), tuple(m.HE_B)))
    if HAVE_DECODAITENGU:
        p = _DD_C_PARAMS if variant == "C" else _DD_B_PARAMS
        out["decodaitengu"] = ((tuple(p.n2_half_life), tuple(p.n2_a),
                                tuple(p.n2_b)) if gas == "n2" else
                               (tuple(p.he_half_life), tuple(p.he_a),
                                tuple(p.he_b)))
    return out


# --------------------------------------------------------------------------
# decodaitengu — model level (tissue loading + ceiling)
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Segment:
    """One leg, in eko-deco's terms: depths in msw, duration in minutes."""
    depth_start: float
    depth_end: float
    minutes: float
    gas: b.Gas


def decodaitengu_ceiling(segments, gf: float, surface_p: float = b.P_ATM,
                         msw_per_bar: float = b.MSW_PER_BAR) -> float | None:
    """Ceiling **pressure** (bar) after `segments`, per decodaitengu's ZH-L16C.

    Its `load()` takes the ambient pressure at the START of a leg plus a rate
    in bar/min, which is the Schreiner form our `update_tissues` uses, so the
    two are being asked the identical question.
    """
    if not HAVE_DECODAITENGU:
        return None
    model = ZHL16C()
    tissues = model.init(surface_p)
    for s in segments:
        p0 = b.depth_to_p_amb(s.depth_start, surface_p, msw_per_bar)
        p1 = b.depth_to_p_amb(s.depth_end, surface_p, msw_per_bar)
        rate = (p1 - p0) / s.minutes if s.minutes > 0 else 0.0
        tissues = model.load(tissues, p0, s.minutes,
                             _DDGas(s.gas.fO2 * 100, s.gas.fHe * 100), rate)
    return model.ceiling(tissues, gf)


# --------------------------------------------------------------------------
# decotengu — engine level (a whole schedule)
# --------------------------------------------------------------------------

def decotengu_stops(depth: float, bottom_time: float, gas: b.Gas,
                    deco_gases=(), *, gf_low: float, gf_high: float,
                    descent_rate: float = 18.0, ascent_rate: float = 10.0,
                    p_h2o: float = b.P_H2O,
                    last_stop_6m: bool = False) -> list[tuple[float, float]]:
    """`[(depth_m, minutes)]` from decotengu's own engine, deepest first.

    `bottom_time` is eko-deco's runtime-at-the-end-of-the-bottom; decotengu
    counts its bottom time from arriving at depth, so the descent is subtracted
    here rather than at every call site.

    Its stop times are the exact minimum found by binary search and then
    rounded up to whole minutes — no runtime padding — so they are NOT directly
    comparable with ours stop-for-stop. What they do check is that the same
    obligation lands in the same whole minute.
    """
    if not HAVE_DECOTENGU:
        return []
    engine = _dt.create()
    engine.model = _DT_C()
    engine.model.gf_low, engine.model.gf_high = gf_low, gf_high
    engine.model.water_vapour_pressure = p_h2o
    engine.descent_rate, engine.ascent_rate = descent_rate, ascent_rate
    engine.last_stop_6m = last_stop_6m
    engine.add_gas(0, round(gas.fO2 * 100))
    for g in deco_gases:
        switch = b.DivePlan(gf_low=gf_low, gf_high=gf_high).switch_depth(g)
        engine.add_gas(round(switch), round(g.fO2 * 100))
    list(engine.calculate(depth, bottom_time - depth / descent_rate))
    return [(float(s.depth), float(s.time)) for s in engine.deco_table]
