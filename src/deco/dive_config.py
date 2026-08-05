"""Shared dive-plan configuration (JSON) for the CLI and the GUI.

The same file is read by the Tkinter app on startup and written by ``deco plan
--save``, so a dive planned in the console shows up in the GUI, and vice-versa.
It is plain JSON — safe to edit by hand or by an agent. Where it lives is
:func:`default_path`: ``$DECO_CONFIG``, else ``./dive_plan.json`` when the
working directory has one (a checkout, or any folder you keep dives in), else
the per-user config directory.

Schema::

    {
      "levels": [
        {"depth_m": 45, "runtime_min": 25},
        {"depth_m": 30, "runtime_min": 40}
      ],
      "gf_low": 30, "gf_high": 70,
      "sac_normal": 20, "sac_deco": null,
      "sac_multiplier": 2.0, "problem_minutes": 1, "divers": 1,
      "ascent_rate": 10, "descent_rate": 18, "stop_interval": 3, "last_stop_m": 3,
      "ppo2_bottom": 1.4, "ppo2_deco": 1.6, "ppo2_min": 0.18,
      "ppo2_switch_tol": 0.05, "min_stop_time": 1.0,
      "surface_p_bar": 1.01325, "msw_per_bar": 10.0, "p_h2o_bar": 0.0567,
      "contingency": {"time_before": 1, "time_after": 1,
                      "depth_before": 1, "depth_after": 1},
      "gases": [
        {"role": "Bottom", "o2": 21, "he": 0, "tank_l": 24,
         "pressure_bar": 232, "enabled": true},
        {"role": "Deco",   "o2": 50, "he": 0, "tank_l": 11,
         "pressure_bar": 200, "enabled": true}
      ]
    }

Roles: ``Bottom`` (back gas), ``Travel`` (descent gas for hypoxic mixes) and
``Deco``. Gas is chosen **automatically by role** — there is no per-level gas
override: the bottom gas is breathed on the bottom phase, a travel mix is
swapped in on descent where the bottom mix is hypoxic, and deco gases are
switched to on the final ascent. ``enabled: false`` keeps a gas in the list but
leaves it out of the plan.

``levels`` is the dive profile, one entry per level: ``depth_m`` and cumulative
``runtime_min``. ``runtime_min`` is the runtime at the **end** of that level —
cumulative minutes since leaving the surface, descent included — so the values
must increase down the list. Levels are contiguous, as in every planner: the
transit to a level runs at the standard rate and its time is part of that
level's runtime. A square profile is simply a single level.
Migrations on load: pre-multilevel configs (``depth_m`` + ``bottom_time_min``)
become one level; any legacy per-level gas reference (a level ``gas_id`` or an
inline ``{"o2", "he"}`` mix), any legacy ``Level``-role gas and any legacy
``start_min`` arrival time are dropped — gas is automatic-by-role now, and
levels no longer carry an arrival time.

``sac_deco`` is an optional second consumption rate for gas breathed off a
designated ``Deco`` cylinder (``null`` = one rate for the whole dive, the
previous behaviour). ``surface_p_bar`` and ``msw_per_bar`` are the environment:
surface pressure and how many metres of water make a bar — 10.0 for salt water
(the default), 10 1/3 for fresh (``buhlmann.WATER_TYPES``). They move every
pressure the plan derives, so ppO₂, MOD, END, density, CNS/OTU, gas volumes and
the schedule itself all follow. ``p_h2o_bar`` is the alveolar water-vapour
pressure — 0.0567 (Schreiner), what MultiDeco, Shearwater and GFDECO use;
Bühlmann's own 0.0627 is what Subsurface uses — and
``ppo2_switch_tol`` how far above ``ppo2_deco`` a gas switch may be rounded
deeper to land on a stop depth. ``min_stop_time`` is the grid a stop's runtime
is padded onto (Baker's ``Minimum_Deco_Stop_Time``; 1 min makes a table-friendly
schedule, smaller values a near-continuous one). All are real algorithm inputs,
so all are settable rather than baked in (DECISIONS #19).

``contingency`` sizes the backup cut-table matrix as step counts on the fixed
3 min × 3 m grid: ``time_before``/``time_after`` bottom-time rows shorter/longer
than planned, ``depth_before``/``depth_after`` depth columns shallower/deeper.
A zero count disables that direction. Legacy ``time_delta_min``/``depth_delta_m``
deltas are migrated on load (delta → round(delta/3) steps; depth only deeper).
"""

from __future__ import annotations

import contextlib
import json
import os

from deco import buhlmann as b

ROLES = ("Bottom", "Travel", "Deco")

CONFIG_NAME = "dive_plan.json"
CONFIG_ENV = "DECO_CONFIG"


def user_config_path() -> str:
    """Where a dive lives when you are not standing in a project directory:
    ``$XDG_CONFIG_HOME/eko-deco/dive_plan.json`` (``%APPDATA%`` on Windows)."""
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    else:
        base = (os.environ.get("XDG_CONFIG_HOME")
                or os.path.join(os.path.expanduser("~"), ".config"))
    return os.path.join(base, "eko-deco", CONFIG_NAME)


def default_path() -> str:
    """The config the CLI and GUI reach for when no path is given.

    ``$DECO_CONFIG`` wins; otherwise ``./dive_plan.json`` when it exists, so
    running either front end from a checkout (or any dive folder) shares that
    dive between them; otherwise the per-user config path, so an installed
    ``deco`` run from an arbitrary directory does not scatter plans around.
    Resolved per call — never cached — because the working directory is the
    input and may change between calls."""
    env = os.environ.get(CONFIG_ENV)
    if env:
        return env
    local = os.path.join(os.getcwd(), CONFIG_NAME)
    if os.path.exists(local):
        return local
    return user_config_path()


def default_config() -> dict:
    return {
        "levels": [{"depth_m": 45.0, "runtime_min": 10.0}],
        "gf_low": 30,
        "gf_high": 70,
        "sac_normal": 20.0,
        "sac_deco": None,
        "sac_multiplier": 2.0,
        "problem_minutes": 1.0,
        "divers": 1,
        "ascent_rate": 10.0,
        "descent_rate": 18.0,
        "stop_interval": 3.0,
        "last_stop_m": 3.0,
        "ppo2_bottom": 1.4,
        "ppo2_deco": 1.6,
        "ppo2_min": 0.18,
        "ppo2_switch_tol": 0.05,
        "min_stop_time": 1.0,
        "surface_p_bar": b.P_ATM,
        "msw_per_bar": b.MSW_PER_BAR,
        "p_h2o_bar": b.P_H2O,
        "contingency": {"time_before": 1, "time_after": 1,
                        "depth_before": 1, "depth_after": 1},
        "gases": [
            {"role": "Bottom", "o2": 21, "he": 0,
             "tank_l": 24, "pressure_bar": 232},
            {"role": "Deco", "o2": 50, "he": 0,
             "tank_l": 11, "pressure_bar": 200},
        ],
    }


def load(path: str | None = None, strict: bool = False) -> dict:
    """Read a config (``default_path()`` when none is given). Lenient by
    default: a missing, unparsable or semantically
    invalid file falls back to the default config (the GUI's first launch).
    ``strict=True`` raises instead — FileNotFoundError / OSError for file
    problems, ValueError (json.JSONDecodeError is one) for broken JSON *or*
    JSON whose values can't be normalized (e.g. ``"depth_m": "oops"``) — the
    CLI uses it so a typo'd path or a broken hand-edit errors out rather than
    silently planning the default dive."""
    path = path or default_path()
    try:
        with open(path, encoding="utf-8") as fh:
            cfg = json.load(fh)
    except (OSError, json.JSONDecodeError):
        if strict:
            raise
        return default_config()
    try:
        return _merged(cfg)
    except (TypeError, ValueError, KeyError, AttributeError) as e:
        # Valid JSON, invalid content: a string depth, a list where a dict
        # belongs… normalization failures are config corruption too.
        if strict:
            raise ValueError(f"invalid dive config values: {e}") from e
        return default_config()


def save(cfg: dict, path: str | None = None) -> str:
    """Write the (normalized) config atomically: a temp file in the same
    directory replaced over ``path`` with ``os.replace``, so an interrupted
    write can never leave a truncated shared plan behind."""
    path = path or default_path()
    merged = _merged(cfg)                      # normalize BEFORE touching disk
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = f"{path}.tmp{os.getpid()}"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(merged, fh, indent=2)
            fh.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            with contextlib.suppress(OSError):
                os.remove(tmp)
    return path


LEGACY_KEYS = ("solo", "sac_stress", "depth_m", "bottom_time_min", "show_rd")


def normalize(cfg: dict) -> dict:
    """Normalize a raw config dict: fill defaults, run legacy migrations,
    assign stable gas ids. This is what ``load`` applies to every file it
    reads — front ends use this instead of reaching into module internals.
    Raises TypeError/ValueError/KeyError on semantically corrupt input
    (``load`` maps those per its strict/lenient contract)."""
    return _merged(cfg)


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
    # Gases: drop legacy "Level"-role entries entirely (they existed only to be
    # force-breathed on a level; gas is automatic-by-role now).
    gases = cfg.get("gases")
    if gases:
        merged = [_merge_gas(g) for g in gases if g.get("role") != "Level"]
        if merged:
            base["gases"] = merged
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
    if isinstance(cfg.get("contingency"), dict):
        base["contingency"] = _merge_contingency(cfg["contingency"])
    return base


def _merge_level(l: dict) -> dict:
    """One level: depth + cumulative end-runtime, nothing else. Legacy keys are
    dropped — a per-level gas reference (``gas_id`` or an inline ``{"o2", "he"}``
    mix), because gas is chosen automatically by role now, and ``start_min``,
    because levels are contiguous and the transit is part of the runtime (no
    planner has an arrival time; see the module docstring)."""
    return {"depth_m": float(l.get("depth_m", 30.0)),
            "runtime_min": float(l.get("runtime_min", 20.0))}


def _merge_gas(g: dict) -> dict:
    role = g.get("role", "Deco")
    if role not in ROLES:
        role = "Deco"
    return {"role": role, "o2": g.get("o2", 21), "he": g.get("he", 0),
            "tank_l": g.get("tank_l", 0), "pressure_bar": g.get("pressure_bar", 232),
            "enabled": bool(g.get("enabled", True))}


CONTINGENCY_KEYS = ("time_before", "time_after", "depth_before", "depth_after")


def _merge_contingency(c: dict) -> dict:
    default = default_config()["contingency"]
    # Legacy delta blocks (time ±DT min / depth +DD m) become step counts on
    # the fixed 3 min × 3 m grid: DT → round(DT/3) rows both ways, DD →
    # round(DD/3) deeper columns (the old matrix never went shallower).
    if (not any(k in c for k in CONTINGENCY_KEYS)
            and ("time_delta_min" in c or "depth_delta_m" in c)):
        t = round(float(c.get("time_delta_min", 0)) / 3)
        c = {"time_before": t, "time_after": t, "depth_before": 0,
             "depth_after": round(float(c.get("depth_delta_m", 0)) / 3)}
    return {k: max(0, round(float(c.get(k, default[k]))))
            for k in CONTINGENCY_KEYS}


def contingency_of(cfg: dict) -> tuple[int, int, int, int]:
    """The cut-table step counts as ``(time_before, time_after, depth_before,
    depth_after)`` — 3-min / 3-m steps around the planned dive."""
    c = _merged(cfg)["contingency"]
    return tuple(c[k] for k in CONTINGENCY_KEYS)


def gas_of(g: dict) -> b.Gas:
    return b.Gas(g["o2"] / 100.0, g.get("he", 0) / 100.0)


def levels_of(cfg: dict) -> list[b.Level]:
    """The dive profile as ``buhlmann.Level`` objects (runtime is cumulative).
    Levels are pure depth/time periods — gas is always chosen automatically by
    role (bottom gas while breathable, travel where not, deco on ascent)."""
    cfg = _merged(cfg)
    return [b.Level(l["depth_m"], l["runtime_min"]) for l in cfg["levels"]]


def to_buhlmann(cfg: dict) -> tuple[b.Gas, b.DivePlan, b.GasPlan, list[tuple]]:
    """Return ``(bottom_gas, DivePlan, GasPlan, gases)`` where ``gases`` is a list
    of ``(role, Gas, tank_l, pressure_bar)`` tuples. Gas selection is automatic
    by role: ``Bottom`` on the bottom phase, ``Travel`` swapped in on descent
    where the bottom mix is hypoxic, ``Deco`` switched to on ascent."""
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
                      ppo2_switch_tol=cfg.get("ppo2_switch_tol", 0.05),
                      min_stop_time=cfg.get("min_stop_time", 1.0),
                      surface_p=cfg.get("surface_p_bar", b.P_ATM),
                      msw_per_bar=cfg.get("msw_per_bar", b.MSW_PER_BAR),
                      p_h2o=cfg.get("p_h2o_bar", b.P_H2O),
                      travel_gases=travel, deco_gases=deco)
    sac_deco = cfg.get("sac_deco")
    gp = b.GasPlan(sac=cfg["sac_normal"],
                   sac_deco=None if sac_deco is None else float(sac_deco),
                   sac_multiplier=cfg.get("sac_multiplier", 2.0),
                   problem_minutes=cfg.get("problem_minutes", 1.0),
                   divers=int(cfg.get("divers", 1)))
    return bottom, plan, gp, gases
