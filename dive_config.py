"""Shared dive-plan configuration (JSON) for the CLI and the GUI.

The same file (``dive_plan.json`` next to this module) is read by the Tkinter app
on startup and written by ``cli.py plan --save``, so a dive planned in the console
shows up in the GUI, and vice-versa. It is plain JSON — safe to edit by hand or by
an agent.

Schema::

    {
      "levels": [
        {"depth_m": 45, "runtime_min": 25, "gas": null},
        {"depth_m": 30, "runtime_min": 40, "gas": {"o2": 32, "he": 0}}
      ],
      "gf_low": 30, "gf_high": 70,
      "sac_normal": 20, "sac_multiplier": 2.0, "problem_minutes": 1,
      "ascent_rate": 10, "descent_rate": 18, "stop_interval": 3, "last_stop_m": 3,
      "ppo2_bottom": 1.4, "ppo2_deco": 1.6, "ppo2_min": 0.18,
      "gases": [
        {"role": "Bottom", "o2": 21, "he": 0, "tank_l": 24, "pressure_bar": 232,
         "enabled": true},
        {"role": "Deco",   "o2": 50, "he": 0, "tank_l": 11, "pressure_bar": 200,
         "enabled": true}
      ]
    }

Roles: ``Bottom`` (back gas), ``Travel`` (descent gas for hypoxic mixes), ``Deco``.
``enabled: false`` keeps a gas in the list but leaves it out of the plan.

``levels`` is the dive profile, one entry per level. ``runtime_min`` is the
runtime at the **end** of that level — cumulative minutes since leaving the
surface, descent included — so the values must increase down the list. A level's
``gas`` forces a mix for that level; ``null`` ("auto") lets the planner use the
gas that is relevant at that depth — the bottom mix while it is breathable, a
travel mix where it is not. A
square profile is simply a single level. Configs written before multi-level
support (``depth_m`` + ``bottom_time_min``) are migrated to one level on load.
"""

from __future__ import annotations

import json
import os
from typing import List, Tuple

import buhlmann as b

ROLES = ("Bottom", "Travel", "Deco")
DEFAULT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dive_plan.json")


def default_config() -> dict:
    return {
        "levels": [{"depth_m": 45.0, "runtime_min": 10.0, "gas": None}],
        "gf_low": 30,
        "gf_high": 70,
        "sac_normal": 20.0,
        "sac_multiplier": 2.0,
        "problem_minutes": 1.0,
        "ascent_rate": 10.0,
        "descent_rate": 18.0,
        "stop_interval": 3.0,
        "last_stop_m": 3.0,
        "ppo2_bottom": 1.4,
        "ppo2_deco": 1.6,
        "ppo2_min": 0.18,
        "gases": [
            {"role": "Bottom", "o2": 21, "he": 0, "tank_l": 24, "pressure_bar": 232},
            {"role": "Deco", "o2": 50, "he": 0, "tank_l": 11, "pressure_bar": 200},
        ],
    }


def load(path: str = DEFAULT_PATH) -> dict:
    """Read a config, falling back to the default if it is missing or invalid."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            cfg = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return default_config()
    return _merged(cfg)


def save(cfg: dict, path: str = DEFAULT_PATH) -> str:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(_merged(cfg), fh, indent=2)
        fh.write("\n")
    return path


LEGACY_KEYS = ("solo", "sac_stress", "depth_m", "bottom_time_min", "show_rd")


def _merged(cfg: dict) -> dict:
    base = default_config()
    base.update({k: v for k, v in cfg.items()
                 if k != "gases" and k not in LEGACY_KEYS})
    # Legacy configs stored an absolute distress SAC (plus a solo flag);
    # translate it into the emergency multiplier and drop both keys.
    if "sac_multiplier" not in cfg and "sac_stress" in cfg:
        sac = float(cfg.get("sac_normal", base["sac_normal"])) or 1.0
        base["sac_multiplier"] = round(float(cfg["sac_stress"]) / sac, 2)
    # Legacy configs were square-profile only: one depth + one bottom time.
    # That is a single level, and bottom_time_min already meant "runtime at the
    # end of the bottom", so it carries over unchanged.
    if "levels" not in cfg and "depth_m" in cfg:
        base["levels"] = [_merge_level({
            "depth_m": cfg["depth_m"],
            "runtime_min": cfg.get("bottom_time_min",
                                   default_config()["levels"][0]["runtime_min"]),
        })]
    elif cfg.get("levels"):
        base["levels"] = [_merge_level(l) for l in cfg["levels"]]
    # A dive always has at least one level: never let an empty list through
    # (it would leave the planner with no profile at all).
    if not base.get("levels"):
        base["levels"] = default_config()["levels"]
    gases = cfg.get("gases")
    if gases:
        base["gases"] = [_merge_gas(g) for g in gases]
    return base


def _merge_level(l: dict) -> dict:
    gas = l.get("gas")
    return {"depth_m": float(l.get("depth_m", 30.0)),
            "runtime_min": float(l.get("runtime_min", 20.0)),
            "gas": ({"o2": int(gas["o2"]), "he": int(gas.get("he", 0))}
                    if gas else None)}


def _merge_gas(g: dict) -> dict:
    role = g.get("role", "Deco")
    if role not in ROLES:
        role = "Deco"
    return {"role": role, "o2": g.get("o2", 21), "he": g.get("he", 0),
            "tank_l": g.get("tank_l", 0), "pressure_bar": g.get("pressure_bar", 232),
            "enabled": bool(g.get("enabled", True))}


def gas_of(g: dict) -> b.Gas:
    return b.Gas(g["o2"] / 100.0, g.get("he", 0) / 100.0)


def levels_of(cfg: dict) -> List[b.Level]:
    """The dive profile as ``buhlmann.Level`` objects (runtime is cumulative)."""
    cfg = _merged(cfg)
    return [b.Level(l["depth_m"], l["runtime_min"],
                    gas_of(l["gas"]) if l.get("gas") else None)
            for l in cfg["levels"]]


def to_buhlmann(cfg: dict) -> Tuple[b.Gas, b.DivePlan, b.GasPlan, List[tuple]]:
    """Return ``(bottom_gas, DivePlan, GasPlan, gases)`` where ``gases`` is a list
    of ``(role, Gas, tank_l, pressure_bar)`` tuples."""
    cfg = _merged(cfg)
    gases = [(g["role"], gas_of(g), float(g.get("tank_l", 0)),
              float(g.get("pressure_bar", 232)))
             for g in cfg["gases"] if g.get("enabled", True)]
    bottom = next((gas for role, gas, _t, _p in gases if role == "Bottom"),
                  gases[0][1] if gases else b.AIR)
    travel = tuple(gas for role, gas, _t, _p in gases if role == "Travel")
    deco = tuple(gas for role, gas, _t, _p in gases if role == "Deco")
    plan = b.DivePlan(gf_low=cfg["gf_low"] / 100.0, gf_high=cfg["gf_high"] / 100.0,
                      ascent_rate=cfg.get("ascent_rate", 10.0),
                      descent_rate=cfg.get("descent_rate", 18.0),
                      stop_interval=cfg.get("stop_interval", 3.0),
                      last_stop_depth=cfg.get("last_stop_m", 3.0),
                      ppo2_bottom=cfg.get("ppo2_bottom", 1.4),
                      ppo2_deco=cfg.get("ppo2_deco", 1.6),
                      ppo2_min=cfg.get("ppo2_min", 0.18),
                      travel_gases=travel, deco_gases=deco)
    gp = b.GasPlan(sac=cfg["sac_normal"],
                   sac_multiplier=cfg.get("sac_multiplier", 2.0),
                   problem_minutes=cfg.get("problem_minutes", 1.0))
    return bottom, plan, gp, gases
