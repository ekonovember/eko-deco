"""eko-deco — Bühlmann ZHL-16C decompression model with Erik Baker's gradient factors.

The package is layered so the model can be used without dragging a UI along:

``deco.buhlmann``
    The model itself — 16 tissue compartments, the Schreiner equation, GF
    ceilings, multi-level planning, gas planning, ppO₂/CNS/OTU/END checks.
    Standard library only.
``deco.report``
    Everything user-facing that is *computed* (warnings, cylinder accounting,
    ``PlanResult``), shared by both front ends so they cannot drift apart.
    Standard library only.
``deco.dive_config``
    The shared ``dive_plan.json`` schema — load/save/normalize.
``deco.cli``
    The console front end (``deco …``).
``deco.app``
    The Tkinter + matplotlib GUI (``deco-gui``).
``deco.cards``
    The 90 × 64 mm wetnotes runtime-card layout engine (matplotlib). It
    computes nothing — you feed it numbers from ``deco plan --json``.

``app`` and ``cards`` are the only modules allowed to import third-party
packages, and both need the ``[gui]`` extra.

Typical use::

    from deco import buhlmann as b

    segments, tissues = b.plan_dive(45, 25, b.Gas(0.21, 0.35), b.DivePlan())

Schedules are computed, not certified: see the ppO₂, ceiling and gas-density
warnings in :mod:`deco.buhlmann` — the planner plans what it is given and
reports what is wrong with it rather than refusing.
"""

from __future__ import annotations

__all__ = ["__version__", "buhlmann", "dive_config", "report"]

__version__ = "0.1.0"


def __getattr__(name: str):  # pragma: no cover - thin lazy-import shim
    """Import submodules on first attribute access.

    Keeps ``import deco`` free of side effects (and of the ``app`` and ``cards``
    modules' matplotlib/tkinter imports) while still letting ``deco.buhlmann`` work
    after a bare ``import deco``.
    """
    if name in ("buhlmann", "dive_config", "report", "cli", "app", "cards"):
        import importlib

        return importlib.import_module(f".{name}", __name__)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
