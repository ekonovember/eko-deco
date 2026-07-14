"""Shared dive-plan configuration (JSON) for the CLI and the GUI.

The same file (``dive_plan.json`` next to this module) is read by the Tkinter app
on startup and written by ``cli.py plan --save``, so a dive planned in the console
shows up in the GUI, and vice-versa. It is plain JSON — safe to edit by hand or by
an agent.

Schema::

    {
      "levels": [
        {"depth_m": 45, "runtime_min": 25, "gas_id": null},
        {"depth_m": 30, "runtime_min": 40, "gas_id": 2}
      ],
      "gf_low": 30, "gf_high": 70,
      "sac_normal": 20, "sac_multiplier": 2.0, "problem_minutes": 1,
      "ascent_rate": 10, "descent_rate": 18, "stop_interval": 3, "last_stop_m": 3,
      "ppo2_bottom": 1.4, "ppo2_deco": 1.6, "ppo2_min": 0.18,
      "contingency": {"time_before": 1, "time_after": 1,
                      "depth_before": 1, "depth_after": 1},
      "gases": [
        {"id": 1, "role": "Bottom", "o2": 21, "he": 0, "tank_l": 24,
         "pressure_bar": 232, "enabled": true},
        {"id": 2, "role": "Deco",   "o2": 50, "he": 0, "tank_l": 11,
         "pressure_bar": 200, "enabled": true}
      ]
    }

Roles: ``Bottom`` (back gas), ``Travel`` (descent gas for hypoxic mixes), ``Deco``.
``enabled: false`` keeps a gas in the list but leaves it out of the plan.

``levels`` is the dive profile, one entry per level. ``runtime_min`` is the
runtime at the **end** of that level — cumulative minutes since leaving the
surface, descent included — so the values must increase down the list. A level's
``gas_id`` references a gas in ``gases`` — the stack is the single source of
truth; levels never carry their own mix definitions. Gas ids are plain unique
numbers (1, 2, …) generated dynamically when a gas is defined and kept for the
life of the entry — deliberately numeric so an id can never be mistaken for a
display label, and never shown in the UI. Because the id names the cylinder
entry (not a mix snapshot), editing a gas's mix carries every level that
references it along automatically. ``gas_id: null`` — the default, also what a
missing or stale id normalizes to — means **automatic** gas selection: the
bottom gas while it is breathable, a travel mix where it is not. Any real id
forces that stack gas for the level, and every calculation (planning,
consumption) uses the referenced entry. A square profile is simply a
single level. Migrations on load: pre-multilevel configs (``depth_m`` +
``bottom_time_min``) become one level; legacy inline level gases
(``"gas": {"o2": .., "he": ..}``) are matched to the stack by mix — a mix the
stack doesn't carry is parked as a disabled entry and referenced, so the plan
doesn't change.

``contingency`` sizes the backup cut-table matrix as step counts on the fixed
3 min × 3 m grid: ``time_before``/``time_after`` bottom-time rows shorter/longer
than planned, ``depth_before``/``depth_after`` depth columns shallower/deeper.
A zero count disables that direction. Legacy ``time_delta_min``/``depth_delta_m``
deltas are migrated on load (delta → round(delta/3) steps; depth only deeper).
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
        "levels": [{"depth_m": 45.0, "runtime_min": 10.0, "gas_id": None}],
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
        "contingency": {"time_before": 1, "time_after": 1,
                        "depth_before": 1, "depth_after": 1},
        "gases": [
            {"id": 1, "role": "Bottom", "o2": 21, "he": 0,
             "tank_l": 24, "pressure_bar": 232},
            {"id": 2, "role": "Deco", "o2": 50, "he": 0,
             "tank_l": 11, "pressure_bar": 200},
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
    # "gases", "levels" and "contingency" are merged entry-by-entry below: a
    # partial hand-edited block must fill in defaults, not clobber them wholesale.
    base.update({k: v for k, v in cfg.items()
                 if k not in ("gases", "levels", "contingency")
                 and k not in LEGACY_KEYS})
    # Legacy configs stored an absolute distress SAC (plus a solo flag);
    # translate it into the emergency multiplier and drop both keys.
    if "sac_multiplier" not in cfg and "sac_stress" in cfg:
        sac = float(cfg.get("sac_normal", base["sac_normal"])) or 1.0
        base["sac_multiplier"] = round(float(cfg["sac_stress"]) / sac, 2)
    # Gases before levels: a level's gas is an id into the gas stack.
    gases = cfg.get("gases")
    if gases:
        base["gases"] = [_merge_gas(g) for g in gases]
    _assign_gas_ids(base["gases"])
    # Legacy configs were square-profile only: one depth + one bottom time.
    # That is a single level, and bottom_time_min already meant "runtime at the
    # end of the bottom", so it carries over unchanged.
    if "levels" not in cfg and "depth_m" in cfg:
        base["levels"] = [_merge_level({
            "depth_m": cfg["depth_m"],
            "runtime_min": cfg.get("bottom_time_min",
                                   default_config()["levels"][0]["runtime_min"]),
        }, base["gases"])]
    elif cfg.get("levels"):
        base["levels"] = [_merge_level(l, base["gases"]) for l in cfg["levels"]]
    # A dive always has at least one level: never let an empty list through
    # (it would leave the planner with no profile at all).
    if not base.get("levels"):
        base["levels"] = default_config()["levels"]
    if isinstance(cfg.get("contingency"), dict):
        base["contingency"] = _merge_contingency(cfg["contingency"])
    return base


def _assign_gas_ids(gases: List[dict]) -> None:
    """Every gas gets a unique plain-number id (1, 2, …) the moment it is
    defined; existing ids are kept, so a level's reference survives mix edits —
    the id names the cylinder entry, not a mix snapshot. Blank, duplicate or
    invalid ids get the next free number. Deliberately numeric so an id can
    never be mistaken for a display label (it is never shown in the UI)."""
    seen: set = set()
    for g in gases:
        gid = g.get("id")
        ok = (isinstance(gid, (int, float)) and not isinstance(gid, bool)
              and int(gid) > 0 and int(gid) not in seen)
        g["id"] = int(gid) if ok else None
        if ok:
            seen.add(int(gid))
    nxt = max(seen, default=0) + 1
    for g in gases:
        if g["id"] is None:
            g["id"] = nxt
            seen.add(nxt)
            nxt += 1


def _merge_level(l: dict, gases: List[dict]) -> dict:
    """One level, its gas normalized to a ``gas_id`` into ``gases`` (None =
    automatic). Legacy inline mixes are matched to the stack; a mix the stack
    doesn't carry is parked as a disabled entry so the plan doesn't change."""
    gid = l.get("gas_id")
    if isinstance(gid, (int, float)) and not isinstance(gid, bool):
        gid = int(gid)                         # 5000.0 from a hand-edit = 5000
    if gid not in {g["id"] for g in gases}:
        gid, gas = None, l.get("gas")          # legacy inline {"o2", "he"}?
        if isinstance(gas, dict):
            o2, he = int(gas["o2"]), int(gas.get("he", 0))
            gid = next((g["id"] for g in gases
                        if int(g["o2"]) == o2 and int(g.get("he", 0)) == he),
                       None)
            if gid is None:
                parked = _merge_gas({"role": "Deco", "o2": o2, "he": he,
                                     "tank_l": 0, "enabled": False})
                gases.append(parked)
                _assign_gas_ids(gases)
                gid = parked["id"]
    return {"depth_m": float(l.get("depth_m", 30.0)),
            "runtime_min": float(l.get("runtime_min", 20.0)),
            "gas_id": gid}


def _merge_gas(g: dict) -> dict:
    role = g.get("role", "Deco")
    if role not in ROLES:
        role = "Deco"
    return {"id": g.get("id"),
            "role": role, "o2": g.get("o2", 21), "he": g.get("he", 0),
            "tank_l": g.get("tank_l", 0), "pressure_bar": g.get("pressure_bar", 232),
            "enabled": bool(g.get("enabled", True))}


CONTINGENCY_KEYS = ("time_before", "time_after", "depth_before", "depth_after")


def _merge_contingency(c: dict) -> dict:
    default = default_config()["contingency"]
    # Legacy delta blocks (time ±DT min / depth +DD m) become step counts on
    # the fixed 3 min × 3 m grid: DT → round(DT/3) rows both ways, DD →
    # round(DD/3) deeper columns (the old matrix never went shallower).
    if not any(k in c for k in CONTINGENCY_KEYS):
        if "time_delta_min" in c or "depth_delta_m" in c:
            t = round(float(c.get("time_delta_min", 0)) / 3)
            c = {"time_before": t, "time_after": t, "depth_before": 0,
                 "depth_after": round(float(c.get("depth_delta_m", 0)) / 3)}
    return {k: max(0, int(round(float(c.get(k, default[k])))))
            for k in CONTINGENCY_KEYS}


def contingency_of(cfg: dict) -> Tuple[int, int, int, int]:
    """The cut-table step counts as ``(time_before, time_after, depth_before,
    depth_after)`` — 3-min / 3-m steps around the planned dive."""
    c = _merged(cfg)["contingency"]
    return tuple(c[k] for k in CONTINGENCY_KEYS)


def gas_of(g: dict) -> b.Gas:
    return b.Gas(g["o2"] / 100.0, g.get("he", 0) / 100.0)


def levels_of(cfg: dict) -> List[b.Level]:
    """The dive profile as ``buhlmann.Level`` objects (runtime is cumulative).
    ``gas_id: None`` becomes ``Level.gas None`` — automatic selection (bottom
    gas while breathable, travel where not); a real id forces that stack gas."""
    cfg = _merged(cfg)
    by_id = {g["id"]: g for g in cfg["gases"]}
    return [b.Level(l["depth_m"], l["runtime_min"],
                    gas_of(by_id[l["gas_id"]]) if l["gas_id"] else None)
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
