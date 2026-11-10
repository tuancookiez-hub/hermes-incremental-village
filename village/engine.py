"""Deterministic Stone Age village rules, behind one set of names.

The rules exist twice and are held equal by the differential tests: ``village/pyengine.py`` (Python,
always there, needs nothing installed) and ``engine-rs`` (Rust, optional and faster). This module
keeps the names the rest of the plugin uses (``engine.run_day``, ``engine.BUILDINGS``, ...) and sends
each call to the Rust engine when one that matches this version is installed, and to the Python
rules otherwise. Every constant and table is in ``village/rules.json``.

Worlds are plain JSON-style dicts, as before. After a call that changes the world, the caller's
``world`` dict, its ``villagers`` list and each villager dict are updated in place, so references
such as ``ash = world["villagers"][0]`` stay live. Villagers are passed by position in
``world["villagers"]``.
"""
from __future__ import annotations

import json
import logging
import os
from functools import lru_cache, wraps
from pathlib import Path
from typing import Any

from . import bridge
from . import pyengine as _py
from .bridge import EngineError, EngineUnavailable  # noqa: F401 - re-exported for callers

_R: dict[str, Any] = json.loads(Path(__file__).with_name("rules.json").read_text(encoding="utf-8"))

# ---------------------------------------------------------------- constants (from rules.json)

SCHEMA_VERSION = _R["SCHEMA_VERSION"]
DAY_SECONDS = _R["DAY_SECONDS"]
DAWN_FRACTION = _R["DAWN_FRACTION"]
WALK_PER_SLOT = _R["WALK_PER_SLOT"]
HOME_REACH = _R["HOME_REACH"]
WORK_FRACTION = _R["WORK_FRACTION"]
MAX_CATCHUP_DAYS = _R["MAX_CATCHUP_DAYS"]
SPEEDS = tuple(_R["SPEEDS"])
SPEED_IDLE_SECONDS = _R["SPEED_IDLE_SECONDS"]
CHUNK = _R["CHUNK"]
CAMP_CLEARING = _R["CAMP_CLEARING"]
CAMP_WATER = _R["CAMP_WATER"]
CLIMATE_PULL = _R["CLIMATE_PULL"]
WATER_BELOW = _R["WATER_BELOW"]
ROCK_ABOVE = _R["ROCK_ABOVE"]
FOREST_ABOVE = _R["FOREST_ABOVE"]
BERRIES_ABOVE = _R["BERRIES_ABOVE"]
SEARCH_REACH = _R["SEARCH_REACH"]
SLOTS_PER_DAY = _R["SLOTS_PER_DAY"]
VISION = _R["VISION"]
TALK_RANGE = _R["TALK_RANGE"]
MAX_ACTIONS = _R["MAX_ACTIONS"]
MAX_ENERGY = _R["MAX_ENERGY"]
OVERNIGHT_ENERGY = _R["OVERNIGHT_ENERGY"]
HUNGRY_ENERGY = _R["HUNGRY_ENERGY"]
MEMORY_LINES = _R["MEMORY_LINES"]
HEARD_LINES = _R["HEARD_LINES"]
MAX_VILLAGERS = _R["MAX_VILLAGERS"]
MAX_HEALTH = _R["MAX_HEALTH"]
SEASON_DAYS = _R["SEASON_DAYS"]
SEASONS = tuple(_R["SEASONS"])
BUSH_FOOD = _R["BUSH_FOOD"]
TREE_WOOD = _R["TREE_WOOD"]
TREE_REGROW_DAYS = _R["TREE_REGROW_DAYS"]
SEEDING_CHANCE = _R["SEEDING_CHANCE"]
WOODLOT_GROW_DAYS = _R["WOODLOT_GROW_DAYS"]
CARRY_LIMIT = _R["CARRY_LIMIT"]
PACK_FRAME_BONUS = _R["PACK_FRAME_BONUS"]
WEIGHTS = _R["WEIGHTS"]
STORE_REACH = _R["STORE_REACH"]
BUILD_REACH = _R["BUILD_REACH"]
FIRE_FUEL_REACH = _R["FIRE_FUEL_REACH"]
WATER_RANGE = _R["WATER_RANGE"]
SOIL_LOSS = _R["SOIL_LOSS"]
SOIL_REST = _R["SOIL_REST"]
EDIBLE = tuple(_R["EDIBLE"])
HUNT_REACH = _R["HUNT_REACH"]
HUNT_SLOTS = _R["HUNT_SLOTS"]
MEAT_PER_KILL = _R["MEAT_PER_KILL"]
GORE_DAMAGE = _R["GORE_DAMAGE"]
HERD_LIMIT = _R["HERD_LIMIT"]
HERD_CHANCE = _R["HERD_CHANCE"]
ANIMALS = _R["ANIMALS"]
BUSH_REGROW_DAYS = _R["BUSH_REGROW_DAYS"]
FIELD_FOOD = _R["FIELD_FOOD"]
FIELD_GROWTH = _R["FIELD_GROWTH"]
ROT_SHARE = _R["ROT_SHARE"]
ROT_BY_ITEM = _R["ROT_BY_ITEM"]
SHELTER_RANGE = _R["SHELTER_RANGE"]
WOLF_CHANCE = _R["WOLF_CHANCE"]
WOLF_BITE = _R["WOLF_BITE"]
EMPTIED_FOR_FARMING = _R["EMPTIED_FOR_FARMING"]
FIELD_WATER_RANGE = _R["FIELD_WATER_RANGE"]
START_TRUST = _R["START_TRUST"]
TRUST_HEEDED = _R["TRUST_HEEDED"]
TRUST_EAGER = _R["TRUST_EAGER"]
FOCUS_DAYS = _R["FOCUS_DAYS"]
EXPERIMENT_SLOTS = _R["EXPERIMENT_SLOTS"]
FOCUSES = _R["FOCUSES"]
IDEAS = _R["IDEAS"]
FUTURE_ERAS = tuple(_R["FUTURE_ERAS"])
UPGRADES = _R["UPGRADES"]
PERKS = _R["PERKS"]
WANDERERS = tuple(_R["WANDERERS"])
TERRAIN = tuple(_R["TERRAIN"])
TILE_CHARS = _R["TILE_CHARS"]
YIELD = _R["YIELD"]
ITEMS = tuple(_R["ITEMS"])
SKILLS = tuple(_R["SKILLS"])
BUILDINGS = _R["BUILDINGS"]
LEVELS = tuple((n, label) for n, label in _R["LEVELS"])
VERBS = tuple(_R["VERBS"])
STARTING_VILLAGERS = tuple(_R["STARTING_VILLAGERS"])
FULL_STOCK = _R["FULL_STOCK"]

CAMP: tuple[int, int] | None = None  # None finds open land near the middle of the seed's world

_CHAR_TO_TILE = {c: t for t, c in TILE_CHARS.items()}
FULL_STOCK_CHAR = {TILE_CHARS[t]: n for t, n in FULL_STOCK.items()}


def seen_tiles(v: dict) -> set[str]:
    """Every tile a villager knows, as "x,y" keys. A save holds one 256-bit map per chunk."""
    seen = v["seen"]
    tiles: set[str] = set()
    for key in seen:
        value = seen[key] if isinstance(seen, dict) else 1
        if not isinstance(value, str):
            tiles.add(key)
            continue
        cx, cy = map(int, key.split(","))
        bits = bin(int(value, 16))[2:].zfill(256)
        for limb in range(4):  # limbs are stored low first, each written high bit first
            word = bits[limb * 64:(limb + 1) * 64][::-1]
            tiles.update(f"{cx * 16 + (limb * 64 + i) % 16},{cy * 16 + (limb * 64 + i) // 16}"
                         for i, bit in enumerate(word) if bit == "1")
    return tiles


# ---------------------------------------------------------------- plumbing

def _sync(old: Any, new: Any) -> Any:
    """Make ``old`` equal ``new`` in place where both are containers of the same kind, so anyone
    holding a reference to a nested dict or list sees the change. Returns what to store."""
    if old == new and type(old) is type(new):
        return old
    if isinstance(old, dict) and isinstance(new, dict):
        for k in [k for k in old if k not in new]:
            del old[k]
        for k, v in new.items():
            old[k] = _sync(old[k], v) if k in old else v
        return old
    if isinstance(old, list) and isinstance(new, list):
        common = min(len(old), len(new))
        for i in range(common):
            old[i] = _sync(old[i], new[i])
        del old[common:]
        old.extend(new[common:])
        return old
    return new


def _apply(world: dict, resp: dict) -> None:
    """Fold the engine's updated world back into the caller's dict, keeping every identity."""
    new = resp["world"]
    old_villagers = world["villagers"]
    for src, state in resp.get("gone") or ():
        _sync(old_villagers[src], state)  # a villager who died keeps their last state
    kept = []
    for nv, src in zip(new.pop("villagers"), resp["vmap"]):
        if src is None:
            kept.append(nv)
        else:
            _sync(old_villagers[src], nv)
            kept.append(old_villagers[src])
    for k in [k for k in world if k != "villagers" and k not in new]:
        del world[k]
    for k, v in new.items():
        world[k] = _sync(world[k], v) if k in world else v
    old_villagers[:] = kept


def _index(world: dict, v: dict) -> int:
    for i, o in enumerate(world["villagers"]):
        if o is v:
            return i
    for i, o in enumerate(world["villagers"]):
        if o == v:
            return i
    raise ValueError(f"{v.get('name') if isinstance(v, dict) else v!r} is not one of this world's villagers")


def _read(op: str, world: dict, **args: Any) -> Any:
    return bridge.call(op, world, args)["result"]


def _write(op: str, world: dict, **args: Any) -> Any:
    resp = bridge.call(op, world, args)
    _apply(world, resp)
    return resp["result"]


def _land_slice(world: dict, **args: Any) -> dict:
    return {"seed": world["seed"], "changed": world["changed"], "shaped": world["shaped"], **args}


# ---------------------------------------------------------------- pure helpers kept in Python

def dist(ax: int, ay: int, bx: int, by: int) -> int:
    return max(abs(ax - bx), abs(ay - by))


def villager(world: dict, name: str) -> dict | None:
    for v in world["villagers"]:
        if v["name"].lower() == str(name).lower():
            return v
    return None


def settlement(world: dict) -> str:
    name = LEVELS[0][1]
    for need, label in LEVELS:
        if len(world["built"]) >= need:
            name = label
    return name


# ---------------------------------------------------------------- land

@lru_cache(maxsize=4096)
def _land(seed: int, cx: int, cy: int) -> tuple[str, ...]:
    """One chunk of untouched land, made by the engine. Pure in (seed, cx, cy)."""
    return tuple(bridge.call("_land", None, {"seed": seed, "cx": cx, "cy": cy})["result"])


def _land_char(seed: int, x: int, y: int) -> str:
    return _land(seed, x >> 4, y >> 4)[y & 15][x & 15]


def _find_camp(seed: int) -> tuple[int, int]:
    x, y = bridge.call("_find_camp", None, {"seed": seed})["result"]
    return x, y


def tile(world: dict, x: int, y: int) -> str:
    return bridge.call("tile", None, _land_slice(world, x=x, y=y))["result"]


def _char(world: dict, x: int, y: int) -> str:
    return bridge.call("_char", None, _land_slice(world, x=x, y=y))["result"]


def _base_char(world: dict, x: int, y: int) -> str:
    return bridge.call("_base_char", None, _land_slice(world, x=x, y=y))["result"]


def _near_tile(world: dict, x: int, y: int, kind: str, reach: int) -> bool:
    return bridge.call("_near_tile", None, _land_slice(world, x=x, y=y, kind=kind, reach=reach))["result"]


# ---------------------------------------------------------------- creation

def new_world(seed: int, now: float, perks: tuple | list = ()) -> dict[str, Any]:
    camp = list(CAMP) if CAMP else None
    return bridge.call("new_world", None, {"seed": seed, "now": now, "perks": list(perks), "camp": camp})["result"]


def season(world: dict) -> str:
    return _read("season", world)


def era(world: dict) -> str:
    return _read("era", world)


def max_health(world: dict) -> int:
    return _read("max_health", world)


def _knows(world: dict, idea: str) -> bool:
    return _read("_knows", world, idea=idea)


def _lit_fire_near(world: dict, x: int, y: int) -> bool:
    return _read("_lit_fire_near", world, x=x, y=y)


def _room(world: dict, v: dict, item: str) -> int:
    return _read("_room", world, vi=_index(world, v), item=item)


def _reveal(world: dict, v: dict) -> int:
    return _write("_reveal", world, vi=_index(world, v))


def _open_chunk(world: dict, cx: int, cy: int) -> None:
    _write("_open_chunk", world, cx=cx, cy=cy)


def find_path(world: dict, v: dict, x: int, y: int) -> list[list[int]] | None:
    return _read("find_path", world, vi=_index(world, v), x=x, y=y)


# ---------------------------------------------------------------- perception

def observe(world: dict, v: dict) -> str:
    """Egocentric text view: only what this villager can see and remembers."""
    return _read("observe", world, vi=_index(world, v))


def describe_action(a: dict) -> str:
    return bridge.call("describe_action", None, {"action": a})["result"]


# ---------------------------------------------------------------- execution

def execute(world: dict, v: dict, act: Any, slots_left: int, fx: dict | None = None) -> tuple[int, str | None, str]:
    """Validate and apply one action. Returns (slots_used, error_or_None, summary).
    ``fx`` collects what the page needs to show it: path, gain, built, target."""
    fx = {} if fx is None else fx
    resp = bridge.call("execute", world, {"vi": _index(world, v), "act": act, "slots_left": slots_left, "fx": fx})
    _apply(world, resp)
    fx.clear()
    fx.update(resp["result"]["fx"])
    used, err, summary = resp["result"]["out"]
    return used, err, summary


def instinct_actions(world: dict, v: dict) -> list[dict]:
    return _read("instinct_actions", world, vi=_index(world, v))


def _scout(world: dict, v: dict) -> list[dict]:
    return _read("_scout", world, vi=_index(world, v))


def _home(world: dict, v: dict) -> tuple[int, int] | None:
    spot = _read("_home", world, vi=_index(world, v))
    return None if spot is None else (spot[0], spot[1])


# ---------------------------------------------------------------- the world turns

def _arrival(world: dict, events: list[str]) -> None:
    events[:] = _write("_arrival", world, events=list(events))


def _herds_live(world: dict) -> None:
    _write("_herds_live", world)


def _seed_forest(world: dict) -> None:
    _write("_seed_forest", world)


def _grow(world: dict) -> None:
    _write("_grow", world)


def run_day(world: dict, plans: dict[str, dict], source: str, unwatched: bool = False) -> dict:
    """Resolve one in-game day. ``plans`` maps villager name -> {actions, thought,
    remember, standing_orders}. Villagers without a plan follow their habit, then
    their instincts. Returns a report the page can replay, and advances the day."""
    resp = bridge.call("run_day", world, {"plans": plans, "source": source, "unwatched": unwatched})
    _apply(world, resp)
    return world["log"][-1]  # the report is the newest log entry, as it always was


def advance(world: dict, now: float) -> dict | None:
    """Bring the clock up to ``now``: free days only, never a model call. Returns a
    digest when the village lived through two or more days since it was last seen."""
    away = _write("advance", world, now=now)
    return None if away is None else world["away"]


# ---------------------------------------------------------------- guide and clock

def plant_idea(world: dict, idea: str) -> str | None:
    """Spend Insight to put an idea in the villagers' heads. Returns a refusal or None."""
    return _write("plant_idea", world, idea=idea)


def buy_upgrade(world: dict, upgrade: str) -> str | None:
    return _write("buy_upgrade", world, upgrade=upgrade)


def set_focus(world: dict, focus: str | None) -> str | None:
    return _write("set_focus", world, focus=focus)


def legacy_earned(world: dict) -> int:
    """What a finished village leaves behind: its years, and everything it worked out."""
    return _read("legacy_earned", world)


def set_speed(world: dict, speed: Any, now: float) -> str | None:
    """Speed 0 pauses. Returns a refusal or None."""
    return _write("set_speed", world, speed=speed, now=now)


def restart_day(world: dict, now: float) -> None:
    """A new day was just resolved by hand: its playback starts now, even while paused."""
    _write("restart_day", world, now=now)


# ---------------------------------------------------------------- what the page sees

def needs_council(world: dict, held: dict | None = None) -> list[str]:
    """Reasons the village would benefit from a model-planned day. Empty means the
    villagers can carry on by themselves."""
    return _read("needs_council", world, held=held)


def land_rev(world: dict) -> str:
    """Changes whenever the land the page holds goes out of date, and for every new village."""
    return _read("land_rev", world)


def land_view(world: dict) -> dict:
    """Only what has been seen, plus the chunks around it so the ground can be drawn right up to
    the edge of the dark."""
    return _read("land_view", world)


def resources(world: dict) -> dict:
    """What the village holds, and what it knows is still out there."""
    return _read("resources", world)


def public_state(world: dict, now: float, have: str = "") -> dict:
    """What the page may show. ``have`` is the land revision the page already holds."""
    return _read("public_state", world, now=now, have=have)


# ---------------------------------------------------------------- which engine answers

log = logging.getLogger(__name__)
_BACKEND: str | None = None  # "rust" or "python", decided on the first call


def backend() -> str:
    """HERMES_VILLAGE_BACKEND=python or =rust forces one. Otherwise Rust when a matching engine is
    installed, and the built-in Python rules when it is not."""
    global _BACKEND
    if _BACKEND is None:
        want = os.environ.get("HERMES_VILLAGE_BACKEND", "").strip().lower()
        if want in ("python", "rust"):
            _BACKEND = want
        else:
            try:
                if bridge.find_binary() is None:
                    raise EngineUnavailable("no engine binary")
                bridge.call("describe_action", None, {"action": {"verb": "rest"}})
                _BACKEND = "rust"
            except (EngineUnavailable, EngineError, OSError) as exc:
                log.info("hermes-village: using the built-in Python rules (%s)", exc)
                _BACKEND = "python"
    return _BACKEND


def use_backend(name: str | None) -> None:
    """Tests pick an engine with this. None decides again on the next call."""
    global _BACKEND
    _BACKEND = name


def _pack_seen(v: dict) -> None:
    """Rewrite one villager's seen land as a 256-bit map per chunk, the form a save holds."""
    seen = v.get("seen")
    if seen is None or (isinstance(seen, dict) and all(isinstance(x, str) for x in seen.values())):
        return
    chunks: dict[str, int] = {}
    for key in seen_tiles(v):
        x, y = map(int, key.split(","))
        index = (y & 15) * 16 + (x & 15)
        # the inverse of seen_tiles: limbs low first, each written high bit first
        bit = 255 - ((index // 64) * 64 + 63 - index % 64)
        ck = f"{x >> 4},{y >> 4}"
        chunks[ck] = chunks.get(ck, 0) | (1 << bit)
    v["seen"] = {ck: format(bits, "064x") for ck, bits in sorted(chunks.items())}


def _unpack_seen(v: dict) -> None:
    """The Python rules test single tiles, so they hold seen land as "x,y" keys."""
    seen = v.get("seen")
    if seen is None or (isinstance(seen, dict) and not any(isinstance(x, str) for x in seen.values())):
        return
    v["seen"] = dict.fromkeys(sorted(seen_tiles(v)), 1)


def _villagers(world: Any) -> list:
    return world["villagers"] if isinstance(world, dict) and isinstance(world.get("villagers"), list) else []


def _in_python(name: str):
    fn = getattr(_py, name)

    def call(*args: Any, **kwargs: Any) -> Any:
        _py.CAMP = CAMP
        world = args[0] if args else None
        people = list(_villagers(world))
        for v in people:
            _unpack_seen(v)
        try:
            out = fn(*args, **kwargs)
        finally:
            # villagers can join or die during a call, so pack whoever is there now as well
            for v in _villagers(world) + people:
                _pack_seen(v)
        if name == "new_world":
            for v in _villagers(out):
                _pack_seen(v)
        return out

    return call


def _either(name: str):
    rust, python = globals()[name], _in_python(name)

    @wraps(rust)
    def call(*args: Any, **kwargs: Any) -> Any:
        if backend() == "python":
            return python(*args, **kwargs)
        try:
            return rust(*args, **kwargs)
        except EngineUnavailable as exc:
            if os.environ.get("HERMES_VILLAGE_BACKEND", "").strip().lower() == "rust":
                raise
            # the engine went away mid-game: the world is untouched, so the Python rules carry on
            log.warning("hermes-village: the Rust engine stopped (%s); carrying on with the Python rules", exc)
            use_backend("python")
            return python(*args, **kwargs)

    if hasattr(rust, "cache_clear"):  # the land cache: clear it in whichever engine holds one
        def cache_clear() -> None:
            rust.cache_clear()
            getattr(_py, name).cache_clear()
        call.cache_clear = cache_clear
    return call


for _name in (
    "_land", "_land_char", "_find_camp", "tile", "_char", "_base_char", "_near_tile", "new_world", "season", "era",
    "max_health", "_knows", "_lit_fire_near", "_room", "_reveal", "_open_chunk", "find_path", "observe",
    "describe_action", "execute", "instinct_actions", "_scout", "_home", "_arrival", "_herds_live", "_seed_forest",
    "_grow", "run_day", "advance", "plant_idea", "buy_upgrade", "set_focus", "legacy_earned", "set_speed",
    "restart_day", "needs_council", "land_rev", "land_view", "resources", "public_state",
):
    globals()[_name] = _either(_name)
del _name
