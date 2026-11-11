"""Ways of life: what each villager keeps doing on days nobody plans, for free.

A way is an ordered list of goals, such as ``["food", "fire", "shelter", "explore"]``. A council lets
Hermes rewrite it; until then a villager has a default that suits what they know. Each new day this
module turns every way into that villager's standing orders. It never changes the world itself: the
orders are ordinary actions, and the engine validates and runs them like any other habit.

Nothing here is a rule of the game. It only reads the land a villager has already seen, so when what
is nearby runs out, the only thing left to do is go and look further away.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from . import engine
from . import pyengine as py

GOALS: dict[str, str] = {
    "food": "keep everyone fed",
    "fire": "build and feed a fire pit",
    "rack": "build a drying rack",
    "shelter": "build huts",
    "wood": "stock the store with wood",
    "stone": "stock the store with stone",
    "learn": "try out the ideas the guide has planted",
    "farm": "sow fields near water",
    "woodlot": "tend woodlots",
    "store": "build a storehouse",
    "house": "build stone houses",
    "explore": "walk out and find new land",
}
MAX_GOALS = 6
_BUILDS = {"fire": "fire_pit", "rack": "drying_rack", "shelter": "hut", "farm": "field", "woodlot": "woodlot",
           "store": "storehouse", "house": "stone_house"}
_KINDS = {"wood": "forest", "stone": "rock"}
_BY_SKILL = {"firemaking": ["fire", "wood", "shelter", "house", "explore"],
             "weaving": ["rack", "shelter", "woodlot", "store", "explore"],
             "foraging": ["food", "farm", "learn", "shelter", "explore"],
             "farming": ["farm", "food", "shelter", "explore"]}
_NEWCOMER = ["food", "shelter", "wood", "learn", "explore"]


def clean(way: Any) -> list[str]:
    """A way as the game will keep it: known goals only, no repeats, at most MAX_GOALS."""
    out: list[str] = []
    for goal in way if isinstance(way, list) else []:
        if isinstance(goal, str) and goal in GOALS and goal not in out:
            out.append(goal)
    return out[:MAX_GOALS]


def default_way(v: dict) -> list[str]:
    for skill in v.get("skills") or []:
        if skill in _BY_SKILL:
            return list(_BY_SKILL[skill])
    return list(_NEWCOMER)


def ways(world: dict) -> dict[str, list[str]]:
    """Every living villager's way: the one a council gave them, or their default."""
    kept = world.get("ways") if isinstance(world.get("ways"), dict) else {}
    return {v["name"]: clean(kept.get(v["name"])) or default_way(v) for v in world["villagers"]}


def set_way(world: dict, name: str, way: Any) -> bool:
    way = clean(way)
    v = engine.villager(world, name)
    if v is None or not way:
        return False
    kept = world.get("ways") if isinstance(world.get("ways"), dict) else {}
    world["ways"] = {**kept, v["name"]: way}
    world["ways_day"] = None  # work the orders out again
    return True


# ---------------------------------------------------------------- goals into actions

def _walk_then(spot: tuple[int, int] | None, *acts: dict) -> list[dict] | None:
    return [{"verb": "walk", "x": spot[0], "y": spot[1]}, *acts] if spot else None


def _haul(world: dict, v: dict, item: str, kind: str) -> list[dict] | None:
    trip = py._gather_trip(world, v, item, kind)
    return trip + [{"verb": "deposit", "item": item}] if trip else None


def _build(world: dict, v: dict, name: str, limit: int) -> list[dict] | None:
    spec = py.BUILDINGS[name]
    have = sum(1 for b in world["built"] if b["kind"] == name)
    if have >= min(limit, spec["max"]) or (spec["skill"] and spec["skill"] not in v["skills"]) \
            or (spec.get("idea") and not py._knows(world, spec["idea"])):
        return None
    missing = [k for k, n in spec["cost"].items() if py._have(world, v, k) < n]
    if missing:
        item = missing[0]
        return py._gather_trip(world, v, item, _KINDS[item]) or None if item in _KINDS else None
    if spec.get("near_water"):
        taken = {(b["x"], b["y"]) for b in world["built"]}
        spot = py._search(world, v, lambda x, y: (x, y) not in taken and py.tile(world, x, y) == "grass"
                          and f"{x},{y}" in v["seen"] and py._near_tile(world, x, y, "water", spec["near_water"]),
                          adjacent=False)
    else:
        spot = py._open_ground(world, v)
    return _walk_then(spot, {"verb": "build", "item": name})


def _larder(world: dict) -> int:
    """Meals per head worth keeping. Nothing grows in winter, so autumn is for filling the store."""
    return {"spring": 5, "summer": 6, "autumn": 10, "winter": 4}[py.season(world)]


def _toward(world: dict, v: dict, goal: str, people: int, food: int, claimed: Counter) -> list[dict] | None:
    """The actions that serve one goal today, or None when it needs nothing, or cannot be done by
    this villager with what they know of the land."""
    if goal == "food":
        if v["hungry"] <= 0 and food >= people * _larder(world):
            return None
        return _walk_then(py._nearest_food(world, v), {"verb": "gather", "item": "food"}, {"verb": "gather", "item": "food"},
                          {"verb": "deposit", "item": "food"})
    if goal in ("wood", "stone"):
        stored = sum(inv.get(goal, 0) for _, _, inv in py._stores(world))
        return None if stored >= (10 if goal == "wood" else 6) else _haul(world, v, goal, _KINDS[goal])
    if goal == "learn":
        if claimed["learn"] or not any(i not in world["guide"]["known"] for i in world["guide"]["planted"]):
            return None
        return py._focus_learn(world, v) or None
    if goal == "explore":
        return None if py.season(world) == "winter" else (py._scout(world, v) or None)
    if goal == "fire" and any(b["kind"] == "fire_pit" for b in world["built"])             and sum(inv.get("wood", 0) for _, _, inv in py._stores(world)) < 4:
        return _haul(world, v, "wood", "forest")  # a fire with no wood in the store goes out tonight
    limit = {"fire": 1 + people // 3, "rack": 1, "shelter": (people + 3) // 2, "farm": 1 + people // 2,
             "woodlot": 1 + people // 3, "store": 1, "house": 1 + people // 3}[goal]
    if claimed[goal] >= (2 if goal == "shelter" else 1):
        return None
    return _build(world, v, _BUILDS[goal], limit)


def orders(world: dict) -> dict[str, list[dict]]:
    """Today's standing orders for every villager, from their ways. The world is not changed."""
    people = len(world["villagers"])
    packed = [v for v in world["villagers"] if engine._packed(v)]  # inside a day the land is already unpacked
    for v in packed:
        engine._unpack_seen(v)
    try:
        py.CAMP = engine.CAMP
        food = sum(py._edible(v["inv"]) for v in world["villagers"]) + sum(py._edible(inv) for _, _, inv in py._stores(world))
        out: dict[str, list[dict]] = {}
        claimed: Counter = Counter()
        for name, way in ways(world).items():
            v = engine.villager(world, name)
            acts = None
            # hunger comes before any way: nobody builds on an empty stomach
            short = v["hungry"] > 0 or food < people * (6 if py.season(world) == "autumn" else 4)
            # an idea the guide has planted is worth a day of anyone's time: it changes everything after
            for goal in (["food"] if short else []) + ["learn"] + way:
                acts = _toward(world, v, goal, people, food, claimed)
                if acts:
                    claimed[goal] += 1
                    break
            if not acts:
                # everything they wanted is done, or what it needs is not on any land they know
                # and winter is no time to sleep in the open, so then they stay by the fire
                acts = [] if py.season(world) == "winter" else (py._scout(world, v) or [])
            out[name] = [a for a in acts if isinstance(a, dict)][:py.MAX_ACTIONS]
        return out
    finally:
        for v in packed:
            engine._pack_seen(v)


def apply(world: dict) -> bool:
    """Give every villager today's orders, once a day. Returns whether anything was written."""
    if not world["villagers"] or world.get("fallen") or world.get("ways_day") == world["day"]:
        return False
    for name, acts in orders(world).items():
        engine.villager(world, name)["standing_orders"] = acts
    world["ways_day"] = world["day"]
    return True


def describe(way: list[str]) -> str:
    return ", then ".join(GOALS[g] for g in way)


py.BEFORE_DAY = apply  # every day the village lives, watched or not, starts from its ways
