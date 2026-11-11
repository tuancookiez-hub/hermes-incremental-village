"""Batched villager planning: one structured model call plans every villager's day.

Each villager's section of the prompt holds only that villager's own view
(engine.observe). The reply is a request; the engine validates every action.
"""
from __future__ import annotations

import json
from typing import Any

from . import engine, policy

MAX_OUTPUT_TOKENS = 1500  # hard cap for the first three villagers; also the budget gate's worst case
TOKENS_PER_EXTRA_VILLAGER = 400


def output_cap(world: dict) -> int:
    return MAX_OUTPUT_TOKENS + TOKENS_PER_EXTRA_VILLAGER * max(0, len(world["villagers"]) - 3)


_BUILDING_TEXT = "; ".join(
    f"{name} costs {', '.join(f'{n} {k}' for k, n in b['cost'].items())}, {b['slots']} slots"
    f"{', needs ' + b['skill'] if b['skill'] else ''} ({b['effect']})"
    for name, b in engine.BUILDINGS.items())
_WAY_TEXT = "; ".join(f"{goal} ({what})" for goal, what in policy.GOALS.items())

SYSTEM = f"""You voice the villagers of a small Stone Age camp. You are NOT a god and not
a manager: each villager decides for themself, from ONLY what they can see, remember and
have heard. They have their own temperament. A guide (the player) sometimes gives advice;
villagers usually listen but may disagree or bargain, and should say so in their thought.
The village's Trust in the guide (0-100) is shown each day. Above {engine.TRUST_EAGER} they gladly follow advice; below
{engine.TRUST_HEEDED} they are wary and usually do what they think best.
Villagers cannot see each other's views; to coordinate they must talk.

Plan the NEXT day for every villager, starting from where they are shown now. A day has {engine.SLOTS_PER_DAY} time slots.
Actions and slot costs:
- look (1): look around again.
- walk x y (1 per {engine.WALK_PER_SLOT} tiles): only to a tile the villager has seen; not into water. A walk longer than the
  daylight left goes as far as it can, and the villager sleeps there and must walk again tomorrow.
- gather item (2): wood next to T, stone next to R, food next to b, water next to ~. Must be on or next to it.
- build item (see below): standing on open grass, carrying the materials yourself.
- talk target text (1) / teach target item (2) / trade target give get (1): target within
  {engine.TALK_RANGE} tiles. Teach a skill you know. give and get look like {{"wood": 2}}.
- deposit item n / take item n (1): within {engine.STORE_REACH} tiles of a store (S). Everyone shares them.
  n is optional. Builders within {engine.BUILD_REACH} tiles of a store can use what is in it.
- hunt item (deer or boar) ({engine.HUNT_SLOTS}): within {engine.HUNT_REACH} tiles of the animals (D). It can miss, and boar can gore.
- rest (1): +3 energy.
- experiment item ({engine.EXPERIMENT_SLOTS}): test an idea that came to you. It uses materials and can fail, but each attempt
  makes the next likelier. Only ideas listed under a villager can be tried.
Every action except rest uses 1 energy; at 0 energy only rest works. Villagers recover
{engine.OVERNIGHT_ENERGY} energy overnight if they eat 1 food they carry, only {engine.HUNGRY_ENERGY} if not.
Invalid actions fail and still cost a slot.
Survival is real and villagers die for good. Health is out of {engine.MAX_HEALTH}: a night without food costs 1,
freezing costs 1, a wolf bite costs {engine.WOLF_BITE}, and a safe fed night heals 1. At 0 they die.
A year is {engine.SEASON_DAYS * len(engine.SEASONS)} days: spring, summer, autumn, winter, {engine.SEASON_DAYS} days each.
In winter nothing grows and bushes cannot be picked, so food must be saved first.
Bushes hold {engine.BUSH_FOOD} food and regrow 1 every {engine.BUSH_REGROW_DAYS} days; "," is a bush picked bare.
Each night 1 in {engine.ROT_SHARE} food and half of all meat rots unless the camp has a drying rack. Grain keeps.
A villager carries at most {engine.CARRY_LIMIT}, and stone counts double, so haul to the store.
Sleeping more than {engine.WATER_RANGE} tiles from water means drinking 1 carried or stored water. Two dry nights in a row cost health.
A fire pit burns 1 wood from the store each night. If the store has none, it goes out and gives no warmth or safety.
Herds live far from camp, wander and breed in spring. Hunt one out and it is gone.
The land has no edge and you can only see a little of it. Nearby food and wood thin out, but there is always more
further away: walk to the limit of what you have seen and look.
Early people lived as nomads: following food, sleeping where they stopped, carrying what they could.
A depot is a cheap cache anywhere; a lean_to or fire_pit can be raised at each new camp. Far goods must be hauled,
so weigh the walk against moving the camp itself, or against settling down and farming.
In winter, sleeping more than {engine.SHELTER_RANGE} tiles from a lean_to, hut or fire_pit means freezing.
Sleeping more than {engine.SHELTER_RANGE} tiles from a lit fire_pit risks wolves; shelter lowers the risk.
You voice only the named villagers, at most {engine.MAX_VILLAGERS}. Around them live the folk: a growing number who
work the land near the store, build homes and fields, and follow no plan. One of them steps up when a villager dies.
Rock never runs out, but it is heavy and may be far away. A forest tile holds {engine.TREE_WOOD} wood. Cleared forest stays bare
unless young trees seed from a neighbouring tile, which is slow. Fields tire with every harvest and recover if rested.
Picking bushes bare may teach someone farming. Fields (F) are harvested with gather food.
Buildings: {_BUILDING_TEXT}.
The camp grows from Camp to Hamlet (2 buildings) to Village (4). Materials are carried
personally, so pooling them for a building takes a trade.
Councils are rare and cost the guide dearly, so most days nobody plans. On those days each villager
follows their "way": an ordered list of goals they keep working through by themselves, first one that
needs doing first. Goals: {_WAY_TEXT}.
Set "way" (at most {policy.MAX_GOALS} goals) whenever a villager's life should change: it is what they will
do for many days after this council. A way cannot talk, teach, trade or decide anything new; those need a plan.
Coordinates are absolute (x,y); a view's top-left is given. @ marks the villager, L a building, F a field.
At most {engine.MAX_ACTIONS} actions each. "standing_orders" (max 3 actions) is the habit the
villager repeats on days nobody plans; make it something sensible to repeat.
"remember" is one short note (under 12 words) the villager keeps. "thought" is one sentence
in the villager's own voice. Reply with JSON only."""

_ACTION = {
    "type": "object",
    "required": ["verb"],
    "properties": {
        "verb": {"type": "string", "enum": list(engine.VERBS)},
        "x": {"type": "integer"}, "y": {"type": "integer"},
        "item": {"type": "string"}, "target": {"type": "string"},
        "text": {"type": "string", "maxLength": 80}, "n": {"type": "integer"},
        "give": {"type": "object"}, "get": {"type": "object"},
    },
}

PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["villagers"],
    "properties": {
        "villagers": {
            "type": "array", "maxItems": engine.MAX_VILLAGERS,
            "items": {
                "type": "object",
                "required": ["name", "actions"],
                "properties": {
                    "name": {"type": "string"},
                    "thought": {"type": "string", "maxLength": 160},
                    "actions": {"type": "array", "maxItems": engine.MAX_ACTIONS, "items": _ACTION},
                    "remember": {"type": "string", "maxLength": 80},
                    "standing_orders": {"type": "array", "maxItems": 3, "items": _ACTION},
                    "way": {"type": "array", "maxItems": policy.MAX_GOALS, "items": {"type": "string", "enum": list(policy.GOALS)}},
                },
            },
        }
    },
}


def build_input(world: dict) -> str:
    built = ", ".join(f"{b['kind']} at ({b['x']},{b['y']})" for b in world["built"]) or "nothing yet"
    guide = (f"The guide advises: \"{world['guidance']}\"" if world["guidance"]
             else "The guide has said nothing today.")
    current = policy.ways(world)
    views = [engine.observe(world, v) + f"\nway: {', '.join(current[v['name']])}" for v in world["villagers"]]
    now = engine.season(world)
    left = engine.SEASON_DAYS - (world["day"] - 1) % engine.SEASON_DAYS
    g = world["guide"]
    focus = f" The guide urges them to {engine.FOCUSES[g['focus']]}." if g["focus"] else ""
    known = ", ".join(engine.IDEAS[i]["name"].lower() for i in g["known"]) or "nothing yet"
    head = (f"Day {world['day']}, {now}, {left} days of it left. Camp has built: {built}. "
            f"The village knows: {known}. Trust in the guide: {g['trust']}/100.{focus} "
            f"{engine.population(world):,} people live here, with homes for {engine.housing(world):,} of the folk.")
    return "\n\n".join([head, guide, *views])


def estimate_tokens(text: str) -> int:
    # ~4 chars/token for prose; ASCII map rows tokenize worse, so pad 25%.
    return int(len(text) / 4 * 1.25) + 1


def estimate_input_tokens(world: dict) -> int:
    return estimate_tokens(SYSTEM) + estimate_tokens(build_input(world)) + estimate_tokens(json.dumps(PLAN_SCHEMA))


def parse_plans(world: dict, parsed: Any) -> dict[str, dict]:
    """Keep only well-formed plans for villagers that exist. Anything else falls
    back to habit inside the engine."""
    plans: dict[str, dict] = {}
    if not isinstance(parsed, dict) or not isinstance(parsed.get("villagers"), list):
        return plans
    for p in parsed["villagers"]:
        if not isinstance(p, dict):
            continue
        v = engine.villager(world, p.get("name", ""))
        if v is None or v["name"] in plans or not isinstance(p.get("actions"), list):
            continue
        plans[v["name"]] = p
    return plans
