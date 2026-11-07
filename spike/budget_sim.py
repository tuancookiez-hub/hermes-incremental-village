"""Feasibility spike: batched villager planning under a daily model budget.

Offline and free: a scripted stand-in "planner" replaces the model so we can
measure prompt size, test the validator, and model the daily cost before any
paid call. Run:  python spike/budget_sim.py [--days 10] [--seed 7]

Design under test
-----------------
* ONE structured model call plans the whole village for one in-game day
  (all 3 villagers in one JSON reply), never one call per villager/action.
* Each villager's observation contains only tiles within its vision radius
  plus its own short memory. The prompt never shows the whole map.
* The game engine validates and executes every action and owns time
  (8 slots/day) and resources. Rejected actions cost 1 slot and are fed back
  as "what went wrong" in the next observation.
* "Habit days": if nothing new happened (no new tiles seen, no rejections,
  no new guidance), villagers repeat their standing orders deterministically
  for 0 tokens. The model is consulted only when there is something to decide.
* Hard caps: max_tokens on output, a per-real-day token budget, and the
  player must press "Plan day" (no background calls).
"""
from __future__ import annotations

import argparse
import json
import random
from dataclasses import dataclass, field

W = H = 24
SLOTS_PER_DAY = 8
VISION = 4
TALK_RANGE = 2
MAX_ACTIONS = 6
TILE_CHARS = {"grass": ".", "forest": "T", "rock": "R", "berries": "b", "water": "~"}
YIELD = {"forest": "wood", "rock": "stone", "berries": "food", "water": "water"}
BUILDINGS = {  # name -> (cost, skill needed, slots)
    "lean_to": ({"wood": 4}, None, 3),
    "fire_pit": ({"stone": 3, "wood": 1}, "firemaking", 2),
    "drying_rack": ({"wood": 3}, "weaving", 3),
}
VERBS = ("look", "walk", "gather", "build", "talk", "trade", "teach", "rest")

# ---------------------------------------------------------------- world

def make_world(rng: random.Random) -> list[list[str]]:
    g = [["grass"] * W for _ in range(H)]
    for kind, n, r in (("forest", 7, 2), ("rock", 4, 1), ("berries", 5, 1), ("water", 2, 2)):
        for _ in range(n):
            cx, cy = rng.randrange(W), rng.randrange(H)
            for y in range(max(0, cy - r), min(H, cy + r + 1)):
                for x in range(max(0, cx - r), min(W, cx + r + 1)):
                    if rng.random() < 0.7:
                        g[y][x] = kind
    return g


@dataclass
class Villager:
    name: str
    x: int
    y: int
    skills: set[str]
    inv: dict[str, int] = field(default_factory=dict)
    energy: int = 10
    memory: list[str] = field(default_factory=list)  # <= 4 short lines, model-written
    seen: set[tuple[int, int]] = field(default_factory=set)
    standing_orders: list[dict] = field(default_factory=list)
    feedback: list[str] = field(default_factory=list)


@dataclass
class Village:
    grid: list[list[str]]
    villagers: dict[str, Villager]
    built: list[tuple[str, int, int]] = field(default_factory=list)
    day: int = 1
    guidance: str = ""
    guidance_new: bool = False
    log: list[str] = field(default_factory=list)


def dist(ax, ay, bx, by) -> int:
    return max(abs(ax - bx), abs(ay - by))


# ---------------------------------------------------------------- observation

def visible(v: Village, vil: Villager) -> list[tuple[int, int, str]]:
    out = []
    for y in range(max(0, vil.y - VISION), min(H, vil.y + VISION + 1)):
        for x in range(max(0, vil.x - VISION), min(W, vil.x + VISION + 1)):
            out.append((x, y, v.grid[y][x]))
    return out


def observe(v: Village, vil: Villager) -> tuple[str, int]:
    """Compact egocentric view. Returns (text, newly_seen_tiles)."""
    tiles = visible(v, vil)
    new = sum(1 for x, y, _ in tiles if (x, y) not in vil.seen)
    vil.seen.update((x, y) for x, y, _ in tiles)
    rows = []
    for y in range(max(0, vil.y - VISION), min(H, vil.y + VISION + 1)):
        rows.append("".join("@" if (x, y) == (vil.x, vil.y) else TILE_CHARS[v.grid[y][x]]
                            for x in range(max(0, vil.x - VISION), min(W, vil.x + VISION + 1))))
    near = [o.name for o in v.villagers.values()
            if o is not vil and dist(o.x, o.y, vil.x, vil.y) <= VISION]
    parts = [
        f"## {vil.name} at ({vil.x},{vil.y}) energy {vil.energy}/10",
        f"skills: {', '.join(sorted(vil.skills)) or 'none'}; carrying: {json.dumps(vil.inv)}",
        "view (top-left=(%d,%d)):\n%s" % (max(0, vil.x - VISION), max(0, vil.y - VISION), "\n".join(rows)),
    ]
    if near:
        parts.append("nearby: " + ", ".join(near))
    if vil.memory:
        parts.append("memory: " + " | ".join(vil.memory[-4:]))
    if vil.feedback:
        parts.append("yesterday failed: " + " | ".join(vil.feedback[-3:]))
    return "\n".join(parts), new


SYSTEM = f"""You voice the villagers of a Stone Age camp. Each villager decides for
themself from ONLY what they see and remember. The player is a guide, not a ruler:
weigh their advice but villagers may disagree. Plan today for each villager.
Rules: day has {SLOTS_PER_DAY} slots. Costs: look 1, walk 1 per 3 tiles, gather 2 (must stand on
or next to the resource), build 3 (needs materials and skill), talk/trade 1 and teach 2
(target within {TALK_RANGE} tiles), rest 1 (+3 energy). Every action except rest uses 1 energy.
Buildings: {json.dumps({k: {"cost": c, "skill": s} for k, (c, s, _) in BUILDINGS.items()})}.
Legend: {json.dumps({v: k for k, v in TILE_CHARS.items()})}, @=you. Coords are absolute (x,y).
At most {MAX_ACTIONS} actions per villager. The game rejects invalid actions; a rejected
action still costs 1 slot. Keep memory notes under 12 words each. Reply JSON only."""

PLAN_SCHEMA = {
    "type": "object",
    "required": ["villagers"],
    "properties": {"villagers": {"type": "array", "maxItems": 3, "items": {
        "type": "object", "required": ["name", "actions"],
        "properties": {
            "name": {"type": "string"},
            "thought": {"type": "string", "maxLength": 120},
            "actions": {"type": "array", "maxItems": MAX_ACTIONS, "items": {
                "type": "object", "required": ["verb"],
                "properties": {"verb": {"enum": list(VERBS)}, "x": {"type": "integer"},
                               "y": {"type": "integer"}, "target": {"type": "string"},
                               "item": {"type": "string"}, "text": {"type": "string", "maxLength": 80},
                               "give": {"type": "object"}, "get": {"type": "object"}}}},
            "remember": {"type": "string", "maxLength": 80},
            "standing_orders": {"type": "array", "maxItems": 3}}}}},
}


def build_prompt(v: Village) -> tuple[str, str, int]:
    views, new_total = [], 0
    for vil in v.villagers.values():
        text, new = observe(v, vil)
        views.append(text)
        new_total += new
    camp = f"Day {v.day}. Built: {[b[0] for b in v.built] or 'nothing yet'}."
    guide = f"Player guidance: {v.guidance}" if v.guidance else "No guidance today."
    return SYSTEM, "\n\n".join([camp, guide, *views]), new_total


def est_tokens(s: str) -> int:
    # ~4 chars/token for English. The ASCII map rows tokenize worse (~2.5 chars/token),
    # so this is padded by 20%. Replace with result.usage once a real call is approved.
    return int(len(s) / 4 * 1.2) + 1


# ---------------------------------------------------------------- validation + execution

def execute(v: Village, vil: Villager, act: dict, slots: int) -> tuple[int, str | None]:
    """Return (slots_used, error|None). Engine is the only source of truth."""
    verb = act.get("verb")
    if verb not in VERBS:
        return 1, f"unknown verb {verb!r}"
    if verb != "rest" and vil.energy <= 0:
        return 1, "too tired"
    if verb == "rest":
        vil.energy = min(10, vil.energy + 3)
        return 1, None
    if verb == "look":
        vil.energy -= 1
        return 1, None
    if verb == "walk":
        x, y = act.get("x"), act.get("y")
        if not (isinstance(x, int) and isinstance(y, int) and 0 <= x < W and 0 <= y < H):
            return 1, "walk needs in-bounds x,y"
        if (x, y) not in vil.seen:
            return 1, f"{vil.name} has never seen ({x},{y})"  # no omniscient pathing
        if v.grid[y][x] == "water":
            return 1, "cannot stand in water"
        cost = max(1, -(-dist(vil.x, vil.y, x, y) // 3))
        if cost > slots:
            return slots, "ran out of daylight while walking"
        vil.x, vil.y = x, y
        vil.energy -= 1
        return cost, None
    if verb == "gather":
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                tx, ty = vil.x + dx, vil.y + dy
                if 0 <= tx < W and 0 <= ty < H and YIELD.get(v.grid[ty][tx]) == act.get("item"):
                    vil.inv[act["item"]] = vil.inv.get(act["item"], 0) + 2
                    vil.energy -= 1
                    return 2, None
        return 1, f"no {act.get('item')} next to ({vil.x},{vil.y})"
    if verb == "build":
        name = act.get("item")
        if name not in BUILDINGS:
            return 1, f"unknown building {name!r}"
        cost, skill, used = BUILDINGS[name]
        if skill and skill not in vil.skills:
            return 1, f"{vil.name} does not know {skill}"
        if any(vil.inv.get(k, 0) < n for k, n in cost.items()):
            return 1, f"not enough materials for {name} (needs {cost})"
        for k, n in cost.items():
            vil.inv[k] -= n
        v.built.append((name, vil.x, vil.y))
        vil.energy -= 1
        return used, None
    other = v.villagers.get(act.get("target", ""))
    if other is None or other is vil:
        return 1, f"no villager named {act.get('target')!r}"
    if dist(vil.x, vil.y, other.x, other.y) > TALK_RANGE:
        return 1, f"{other.name} is too far away to hear"
    vil.energy -= 1
    if verb == "talk":
        other.memory.append(f"{vil.name} said: {str(act.get('text', ''))[:60]}")
        return 1, None
    if verb == "teach":
        skill = act.get("item")
        if skill not in vil.skills:
            return 1, f"{vil.name} cannot teach {skill!r}"
        other.skills.add(skill)
        return 2, None
    if verb == "trade":
        give, get = act.get("give") or {}, act.get("get") or {}
        if any(vil.inv.get(k, 0) < n for k, n in give.items()) or \
           any(other.inv.get(k, 0) < n for k, n in get.items()):
            return 1, "trade failed: someone lacks the goods"
        for k, n in give.items():
            vil.inv[k] -= n; other.inv[k] = other.inv.get(k, 0) + n
        for k, n in get.items():
            other.inv[k] -= n; vil.inv[k] = vil.inv.get(k, 0) + n
        return 1, None
    return 1, "unhandled"


def run_day(v: Village, plan: dict) -> dict:
    stats = {"ok": 0, "rejected": 0, "malformed_villagers": 0}
    by_name = {p.get("name"): p for p in plan.get("villagers", []) if isinstance(p, dict)}
    for vil in v.villagers.values():
        vil.feedback = []
        p = by_name.get(vil.name)
        if p is None:
            stats["malformed_villagers"] += 1
            actions = vil.standing_orders  # fall back to habit
        else:
            actions = p.get("actions", [])[:MAX_ACTIONS]
            if p.get("remember"):
                vil.memory = (vil.memory + [str(p["remember"])[:80]])[-4:]
            if p.get("standing_orders"):
                vil.standing_orders = p["standing_orders"][:3]
        slots = SLOTS_PER_DAY
        for act in actions:
            if slots <= 0:
                break
            used, err = execute(v, vil, act if isinstance(act, dict) else {}, slots)
            slots -= used
            if err:
                stats["rejected"] += 1
                vil.feedback.append(err)
            else:
                stats["ok"] += 1
        vil.energy = min(10, vil.energy + 2)  # overnight
    v.day += 1
    return stats


# ---------------------------------------------------------------- stand-in planner

def fake_planner(v: Village, rng: random.Random) -> dict:
    """Plausible, imperfect model: mostly sensible, ~15% bad actions."""
    out = []
    for vil in v.villagers.values():
        acts = []
        seen_res = [(x, y, v.grid[y][x]) for (x, y) in vil.seen if v.grid[y][x] in YIELD]
        if seen_res:
            x, y, kind = min(seen_res, key=lambda t: dist(vil.x, vil.y, t[0], t[1]))
            if v.grid[y][x] == "water":
                x = x + 1 if x + 1 < W and v.grid[y][x + 1] != "water" else x
            acts += [{"verb": "walk", "x": x, "y": y}, {"verb": "gather", "item": YIELD[kind]}]
        if vil.inv.get("wood", 0) >= 4:
            acts.append({"verb": "build", "item": "lean_to"})
        if rng.random() < 0.15:
            acts.append({"verb": "walk", "x": rng.randrange(W), "y": rng.randrange(H)})  # unseen
        if rng.random() < 0.15:
            acts.append({"verb": "build", "item": "fire_pit"})  # likely lacks skill
        acts.append({"verb": "look"})
        out.append({"name": vil.name, "thought": "...", "actions": acts,
                    "remember": f"day {v.day}: worked near ({vil.x},{vil.y})",
                    "standing_orders": acts[:3]})
    return {"villagers": out}


def fake_reply_tokens(plan: dict) -> int:
    return est_tokens(json.dumps(plan, separators=(",", ":")))


# ---------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=10)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--max-output", type=int, default=900, help="max_tokens cap per plan call")
    ap.add_argument("--daily-budget", type=int, default=40_000, help="tokens per real-world day")
    a = ap.parse_args()
    rng = random.Random(a.seed)
    grid = make_world(rng)
    vs = {}
    for name, skills in (("Ash", {"firemaking"}), ("Bryn", {"weaving"}), ("Coll", set())):
        while True:
            x, y = rng.randrange(8, 16), rng.randrange(8, 16)
            if grid[y][x] != "water":
                break
        vs[name] = Villager(name, x, y, set(skills))
    v = Village(grid, vs)

    guidance_days = {1: "Find food first, then shelter.", 4: "Ash should teach fire to Coll.",
                     7: "Build a lean-to before the rains."}
    total_in = total_out = calls = habit_days = 0
    print(f"{'day':>3} {'mode':<6} {'in_tok':>6} {'out_tok':>7} {'ok':>3} {'rej':>3}  built")
    for _ in range(a.days):
        if v.day in guidance_days:
            v.guidance, v.guidance_new = guidance_days[v.day], True
        system, user, new_tiles = build_prompt(v)
        any_feedback = any(vil.feedback for vil in v.villagers.values())
        needs_model = v.day == 1 or v.guidance_new or any_feedback or new_tiles > 6
        if needs_model:
            in_tok = est_tokens(system) + est_tokens(user)
            plan = fake_planner(v, rng)
            out_tok = min(a.max_output, fake_reply_tokens(plan))
            total_in += in_tok; total_out += out_tok; calls += 1
            mode = "PLAN"
        else:
            plan = {"villagers": [{"name": n, "actions": vil.standing_orders}
                                  for n, vil in v.villagers.items()]}
            in_tok = out_tok = 0
            habit_days += 1
            mode = "habit"
        v.guidance_new = False
        s = run_day(v, plan)
        print(f"{v.day - 1:>3} {mode:<6} {in_tok:>6} {out_tok:>7} {s['ok']:>3} {s['rejected']:>3}  "
              f"{[b[0] for b in v.built]}")

    per_call = (total_in + total_out) / max(calls, 1)
    print("\n--- budget model ---")
    print(f"model calls: {calls}/{a.days} days ({habit_days} free habit days)")
    print(f"avg tokens per plan call: {per_call:,.0f} (in {total_in / max(calls,1):,.0f} / out {total_out / max(calls,1):,.0f})")
    print(f"system prompt alone: {est_tokens(SYSTEM)} tok (static, cache-friendly)")
    print(f"daily budget {a.daily_budget:,} tok => ~{a.daily_budget / per_call:.0f} plan calls "
          f"=> ~{a.daily_budget / per_call / (calls / a.days):.0f} in-game days per real day")
    print("cost per 1M tok is model-specific; e.g. at $0.50/M in + $2/M out a plan call costs "
          f"${(total_in / max(calls,1)) * 0.5e-6 + (total_out / max(calls,1)) * 2e-6:.4f}")
    print("\nsample prompt (day %d):\n" % v.day + build_prompt(v)[1][:1200])


if __name__ == "__main__":
    main()
