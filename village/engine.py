"""The village rules, behind the names the rest of the plugin uses.

The rules themselves are in ``village/pyengine.py``: plain Python, nothing to install. This module
adds one thing. The rules test single tiles, so they hold the land a villager has seen as "x,y"
keys; a save holds it as one 256-bit map per chunk, which is far smaller. Every call here unpacks
the seen land on the way in and packs it again on the way out.
"""
from __future__ import annotations

from functools import wraps
from typing import Any

from . import pyengine as _py
from .pyengine import *  # noqa: F401,F403 - every constant and table (BUILDINGS, IDEAS, ...)

CAMP: tuple[int, int] | None = None  # None finds open land near the middle of the seed's world


def seen_tiles(v: dict) -> set[str]:
    """Every tile a villager knows, as "x,y" keys, whichever way their seen land is held."""
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


def _packed(v: dict) -> bool:
    seen = v.get("seen")
    return isinstance(seen, dict) and bool(seen) and all(isinstance(x, str) for x in seen.values())


def _pack_seen(v: dict) -> None:
    """Rewrite one villager's seen land as a 256-bit map per chunk, the form a save holds."""
    seen = v.get("seen")
    if seen is None or _packed(v) or (isinstance(seen, dict) and not seen):
        return
    chunks: dict[str, int] = {}
    for key in seen:
        x, y = map(int, key.split(","))
        index = (y & 15) * 16 + (x & 15)
        bit = 255 - ((index // 64) * 64 + 63 - index % 64)  # the inverse of seen_tiles
        ck = f"{x >> 4},{y >> 4}"
        chunks[ck] = chunks.get(ck, 0) | (1 << bit)
    v["seen"] = {ck: format(bits, "064x") for ck, bits in sorted(chunks.items())}


def _unpack_seen(v: dict) -> None:
    seen = v.get("seen")
    if seen is None or (isinstance(seen, dict) and not _packed(v)):
        return
    v["seen"] = dict.fromkeys(sorted(seen_tiles(v)), 1)


def _villagers(world: Any) -> list:
    return world["villagers"] if isinstance(world, dict) and isinstance(world.get("villagers"), list) else []


_depth = 0  # a call made from inside another call (a day's hook) must leave the land unpacked


def _wrap(name: str):
    fn = getattr(_py, name)

    @wraps(fn)
    def call(*args: Any, **kwargs: Any) -> Any:
        global _depth
        _py.CAMP = CAMP
        world = args[0] if args else None
        people = list(_villagers(world))
        for v in people:
            _unpack_seen(v)
        _depth += 1
        try:
            out = fn(*args, **kwargs)
        finally:
            _depth -= 1
            if _depth == 0:
                for v in _villagers(world) + people:  # villagers can join or die during a call
                    _pack_seen(v)
        if name == "new_world":
            for v in _villagers(out):
                _pack_seen(v)
        return out

    if hasattr(fn, "cache_clear"):
        call.cache_clear = fn.cache_clear
    return call


for _name in (
    "_land", "_land_char", "_find_camp", "tile", "_char", "_base_char", "_near_tile", "new_world", "season", "era",
    "max_health", "_knows", "_lit_fire_near", "_room", "_reveal", "_open_chunk", "find_path", "observe",
    "describe_action", "execute", "instinct_actions", "_scout", "_home", "_arrival", "_herds_live", "_seed_forest",
    "_grow", "run_day", "advance", "plant_idea", "buy_upgrade", "set_focus", "legacy_earned", "set_speed",
    "restart_day", "needs_council", "land_rev", "land_view", "resources", "public_state", "settlement", "population",
):
    globals()[_name] = _wrap(_name)
del _name
