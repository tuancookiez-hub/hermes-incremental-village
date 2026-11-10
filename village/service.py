"""Village operations shared by the agent tools, the /village command and the
Desktop backend routes. Only ``plan_day`` spends model tokens, and only when it
is handed an ``llm`` (the plugin's ctx.llm) by a user-initiated call."""
from __future__ import annotations

import logging
import random
import sys
import time
from typing import Any

from . import engine, planner, policy
from .store import PLUGIN_ID, Store

log = logging.getLogger(__name__)

DEFAULT_DAILY_TOKENS = 30_000
MIN_DAILY_TOKENS, MAX_DAILY_TOKENS = 0, 2_000_000
PLANNING_LOCK_SECONDS = 180
AUX_TASK = "village_planner"


class VillageError(Exception):
    """A refusal the player should read (budget, lock, bad input)."""


def _notify(day: int) -> None:
    # Broadcasting imports the whole gateway transport stack when it is not already
    # loaded. Only a gateway process has clients to reach, so anywhere else (CLI chat,
    # the plugin host, tests) skip it; the Desktop page polls as a fallback.
    if "tui_gateway.server" not in sys.modules:
        return
    try:
        from hermes_cli.plugin_events import broadcast_plugin_event
        broadcast_plugin_event(PLUGIN_ID, "state.updated", {"day": day})
    except Exception:  # older host or a wedged transport: polling covers it
        log.debug("hermes-village state event not delivered", exc_info=True)


def clock() -> float:
    return time.time()


def _legacy(store: Store, db) -> dict:
    """Legacy outlives any one village, so it is kept beside the save, not inside it."""
    return store.get_setting(db, "legacy", None) or {"points": 0, "perks": [], "villages": []}


# What gets written down in the village's history, out of everything a day reports.
_WORTH_TELLING = ("died of", "has fallen", "looking for a home", "came through the winter", "has begun",
                  "noticed seeds", "worked out", "The fire went out")
_CHRONICLE_LINES = 200


def _building_name(kind: str) -> str:
    return "lean-to" if kind == "lean_to" else kind.replace("_", " ")


def _chronicle(store: Store, db, world: dict) -> dict:
    """The story of this village, kept beside the save because the day log only holds the last
    few days. Deaths and first buildings come from the save itself, so days caught up while nobody
    was looking still make it in."""
    book = store.get_setting(db, "chronicle", None)
    if not book or book.get("village") != world["seed"]:
        names = [v["name"] for v in world["villagers"]]
        people = f"{', '.join(names[:-1])} and {names[-1]}" if len(names) > 1 else "".join(names)
        book = {"village": world["seed"], "upto": 0, "lines": [{"day": 1, "text": f"{people} made camp."}], "firsts": [], "seen": {}}
    if world["day"] == book["upto"]:
        return book
    told = {(n["day"], n["text"]) for n in book["lines"]}

    def tell(day: int, text: str) -> None:
        if (day, text) not in told:
            told.add((day, text))
            book["lines"].append({"day": day, "text": text})

    for report in world["log"]:
        for event in report.get("events", ()):
            if any(mark in event for mark in _WORTH_TELLING):
                tell(report["day"], event if event.endswith(".") else f"{event}.")
    for grave in world["dead"]:
        tell(grave["day"], f"{grave['name']} died of {grave['cause']}.")
    for building in world["built"]:
        if building["kind"] not in book["firsts"] and "day" in building:
            book["firsts"].append(building["kind"])
            who = f"{building['by']} built" if building.get("by") else "They built"
            tell(building["day"], f"{who} the first {_building_name(building['kind'])}.")
    for villager in world["villagers"]:  # the dead take what they saw with them, so it is noted here
        for chunk, bits in villager["seen"].items():
            book["seen"][chunk] = f"{int(bits, 16) | int(book['seen'].get(chunk, '0'), 16):064x}"
    book["lines"].sort(key=lambda n: n["day"])
    book["lines"] = book["lines"][-_CHRONICLE_LINES:]
    book["upto"] = world["day"]
    store.set_setting(db, "chronicle", book)
    return book


def _world(store: Store, db) -> dict:
    """Load the village and catch its clock up. This is the only thing that moves
    time on its own: it happens when someone looks, never in a background job, and
    it never spends tokens."""
    world = store.load_world(db)
    fresh = world is None or world.get("schema") != engine.SCHEMA_VERSION
    if fresh:
        world = engine.new_world(random.SystemRandom().randrange(1, 1_000_000), clock(), _legacy(store, db)["perks"])
    engine.advance(world, clock())
    # Each new day, every villager's way of life becomes that day's standing orders. Free, and only
    # ordinary actions: the engine still validates and runs each one.
    wrote = policy.apply(world)
    if world.pop("_dirty", False) or fresh or wrote:
        store.save_world(db, world)
    return world


def _budget(store: Store, db, world: dict) -> dict:
    daily = int(store.get_setting(db, "daily_tokens", DEFAULT_DAILY_TOKENS))
    used, calls = store.spend_today(db)
    last = store.last_spend(db)
    worst_case = planner.estimate_input_tokens(world) + planner.output_cap(world)
    typical = (last["input_tokens"] + last["output_tokens"]) if last and last["outcome"] == "ok" else \
        planner.estimate_input_tokens(world) + planner.output_cap(world) // 2
    lock = float(store.get_setting(db, "planning_since", 0) or 0)
    return {
        "daily_tokens": daily, "used_today": used, "calls_today": calls,
        "remaining": max(0, daily - used), "est_call_tokens": typical, "worst_case_tokens": worst_case,
        "can_plan": used + worst_case <= daily and time.time() - lock > PLANNING_LOCK_SECONDS,
        "planning": time.time() - lock <= PLANNING_LOCK_SECONDS,
        "last_call": last,
    }


def snapshot(store: Store, have: str = "") -> dict:
    with store.tx() as db:
        world = _world(store, db)
        legacy = _legacy(store, db)
        book = _chronicle(store, db, world)
        state = engine.public_state(world, clock(), have)
        state["ways"] = policy.ways(world)
        state["way_goals"] = policy.GOALS
        if world["fallen"] and world["dead"]:
            # With nobody left alive there is nobody to see the land, but the village's end should
            # still happen somewhere. The last to die stands in, knowing all that was ever seen.
            witness = {**world, "villagers": [{**world["dead"][-1], "seen": book["seen"]}]}
            state["resources"] = engine.resources(witness)
            if "land_view" in state:
                state["land_view"] = engine.land_view(witness)
        return {"world": state, "budget": _budget(store, db, world), "chronicle": book["lines"],
                "legacy": {**legacy, "perks_for_sale": engine.PERKS, "would_earn": engine.legacy_earned(world)}}


def guide(store: Store, text: str) -> dict:
    text = " ".join(str(text or "").split())[:300]
    with store.tx() as db:
        world = _world(store, db)
        world["guidance"] = text
        world["guidance_day"] = world["day"]
        store.save_world(db, world)
    _notify(world["day"])
    return snapshot(store)


def set_budget(store: Store, daily_tokens: Any) -> dict:
    try:
        value = int(daily_tokens)
    except (TypeError, ValueError):
        raise VillageError("daily_tokens must be a whole number") from None
    if not MIN_DAILY_TOKENS <= value <= MAX_DAILY_TOKENS:
        raise VillageError(f"daily_tokens must be between {MIN_DAILY_TOKENS} and {MAX_DAILY_TOKENS}")
    with store.tx() as db:
        store.set_setting(db, "daily_tokens", value)
    return snapshot(store)


def reset(store: Store, seed: Any = None) -> dict:
    try:
        seed = int(seed) if seed is not None else random.SystemRandom().randrange(1, 1_000_000)
    except (TypeError, ValueError):
        raise VillageError("seed must be a whole number") from None
    with store.tx() as db:
        legacy = _legacy(store, db)
        old = store.load_world(db)
        if old and old.get("schema") == engine.SCHEMA_VERSION:
            earned = engine.legacy_earned(old)
            legacy["points"] += earned
            legacy["villages"] = (legacy["villages"] + [{
                "days": old["day"] - 1, "fallen": bool(old["fallen"]), "era": old["guide"]["era"], "earned": earned,
                "dead": len(old["dead"])}])[-5:]
            store.set_setting(db, "legacy", legacy)
        world = engine.new_world(seed, clock(), legacy["perks"])
        engine.advance(world, clock())
        world.pop("_dirty", None)
        store.save_world(db, world)
        store.set_setting(db, "planning_since", 0)
        store.set_setting(db, "chronicle", None)  # the same seed can come back, and its story is new
    _notify(world["day"])
    return snapshot(store)


def _guide_action(store: Store, act, after_the_end: bool = False) -> dict:
    with store.tx() as db:
        world = _world(store, db)
        if world["fallen"] and not after_the_end:
            raise_after = f"the village fell on day {world['fallen']}; start a new one"
        else:
            raise_after = act(world)
            if raise_after is None:
                store.save_world(db, world)
    if raise_after:
        raise VillageError(raise_after)
    _notify(world["day"])
    return snapshot(store)


def plant(store: Store, idea: Any) -> dict:
    return _guide_action(store, lambda w: engine.plant_idea(w, str(idea)))


def upgrade(store: Store, name: Any) -> dict:
    return _guide_action(store, lambda w: engine.buy_upgrade(w, str(name)))


def focus(store: Store, name: Any) -> dict:
    return _guide_action(store, lambda w: engine.set_focus(w, str(name) if name else None))


def speed(store: Store, value: Any) -> dict:
    # The last day still plays out on the page, so the clock must keep working: a pause on that day
    # would otherwise never lift, and the village's end would never be shown.
    return _guide_action(store, lambda w: engine.set_speed(w, value, clock()), after_the_end=True)


def buy_perk(store: Store, perk: Any) -> dict:
    perk = str(perk)
    spec = engine.PERKS.get(perk)
    refusal = None
    with store.tx() as db:
        legacy = _legacy(store, db)
        if spec is None:
            refusal = f"there is no legacy called {perk!r}"
        elif perk in legacy["perks"]:
            refusal = f"you already have {spec['name'].lower()}"
        elif legacy["points"] < spec["cost"]:
            refusal = f"{spec['name']} costs {spec['cost']} Legacy; you have {legacy['points']}"
        else:
            legacy["points"] -= spec["cost"]
            legacy["perks"].append(perk)
            store.set_setting(db, "legacy", legacy)
    if refusal:
        raise VillageError(refusal)
    return snapshot(store)


def format_ideas(snap: dict) -> str:
    g = snap["world"]["guide"]
    lines = [f"{g['era']}. Insight {g['insight']}, Trust {g['trust']}/100, focus: {g['focus'] or 'none'}."]
    for key, spec in g["ideas"].items():
        state = "known" if key in g["known"] else ("being tried" if key in g["planted"] else f"{spec['cost']} Insight")
        lines.append(f"- {key}: {spec['name']} ({state}) unlocks {spec['unlocks']}. {spec['history']}")
    lines.append("Upgrades: " + ", ".join(f"{k} ({v['cost']})" for k, v in g["upgrades_for_sale"].items() if k not in g["upgrades"]))
    return "\n".join(lines)


def acknowledge_away(store: Store) -> dict:
    with store.tx() as db:
        world = _world(store, db)
        world["away"] = None
        store.save_world(db, world)
    return snapshot(store)


def habit_day(store: Store) -> dict:
    """Skip ahead to a new free day: habits and instincts only, no model call."""
    with store.tx() as db:
        world = _world(store, db)
        if world["fallen"]:
            raise VillageError(f"the village fell on day {world['fallen']}; start a new one")
        if time.time() - float(store.get_setting(db, "planning_since", 0) or 0) <= PLANNING_LOCK_SECONDS:
            raise VillageError("the villagers are still holding council; wait for it to finish")
        report = engine.run_day(world, {}, source="habit")
        engine.restart_day(world, clock())
        store.save_world(db, world)
    _notify(world["day"])
    return {**snapshot(store), "report": report}


def plan_day(store: Store, llm: Any, *, purpose: str = "village.plan_day") -> dict:
    """One batched structured call plans the whole village for one day.

    Refuses (no call) when today's token budget cannot cover the worst case
    (estimated input + the output cap) or another plan is in flight."""
    if llm is None:
        raise VillageError("model access is unavailable here; plan from a Hermes chat with /village plan")
    with store.tx() as db:
        world = _world(store, db)
        if world["fallen"]:
            raise VillageError(f"the village fell on day {world['fallen']}; start a new one")
        if world["pending_plans"]:
            raise VillageError("the council has already decided; its plans start at the next dawn")
        budget = _budget(store, db, world)
        if budget["planning"]:
            raise VillageError("the villagers are already holding council")
        if not budget["can_plan"]:
            raise VillageError(
                f"today's village budget is spent: {budget['used_today']:,} of {budget['daily_tokens']:,} tokens "
                f"used and a plan may take up to {budget['worst_case_tokens']:,}. Use a free habit day, "
                f"or raise the budget with /village budget <tokens>.")
        store.set_setting(db, "planning_since", time.time())
        day, seed = world["day"], world["seed"]
        instructions, text = planner.SYSTEM, planner.build_input(world)
        est_in = planner.estimate_input_tokens(world)
        cap = planner.output_cap(world)

    result, error = None, None
    try:
        result = llm.complete_structured(
            instructions=instructions,
            input=[{"type": "text", "text": text}],
            json_schema=planner.PLAN_SCHEMA,
            schema_name="village.day_plan",
            purpose=purpose,
            task=AUX_TASK,
            temperature=0.7,
            max_tokens=cap,
            timeout=90,
        )
    except Exception as exc:  # provider error, timeout, trust gate: report, never crash the host
        error = exc
        log.warning("hermes-village plan call failed: %s", exc)

    with store.tx() as db:
        store.set_setting(db, "planning_since", 0)
        usage = getattr(result, "usage", None)
        in_tok = int(getattr(usage, "input_tokens", 0) or 0)
        out_tok = int(getattr(usage, "output_tokens", 0) or 0)
        estimated = in_tok == 0 and out_tok == 0
        if estimated:  # provider gave no usage: charge the conservative estimate
            in_tok = est_in if error is None else 0
            out_tok = planner.estimate_tokens(getattr(result, "text", "") or "") if result else 0
        world = _world(store, db)
        plans = planner.parse_plans(world, getattr(result, "parsed", None)) if result else {}
        new_ways = {name: plan.pop("way") for name, plan in plans.items() if "way" in plan}
        outcome = "error" if error else ("ok" if plans else "unparsed")
        store.record_spend(db, game_day=day, input_tokens=in_tok, output_tokens=out_tok, estimated=estimated,
                           provider=getattr(result, "provider", None), model=getattr(result, "model", None),
                           outcome=outcome)
        # Refusals are raised only after COMMIT, so the spend record and the
        # lock release survive them.
        failure = None
        if error:
            failure = f"the council could not meet: {error}"
        elif world["seed"] != seed or world["day"] < day:
            failure = "a new village started while the council met; nothing was applied"
        elif world["fallen"]:
            failure = "the village fell while the council met; nothing was applied"
        elif not plans:
            failure = "the council's answer was not a usable plan; nobody acted (tokens were still spent)"
        else:
            # The day in progress plays out. These plans begin at the next dawn, so
            # nobody jumps to wherever the rest of today would have left them.
            world["pending_plans"] = plans
            world["last_planned_day"] = world["day"]
            for name, way in new_ways.items():  # what they keep doing after this council, for free
                policy.set_way(world, name, way)
            store.save_world(db, world)
    _notify(world["day"])
    if failure:
        raise VillageError(failure)
    return {**snapshot(store), "plans": plans,
            "usage": {"input_tokens": in_tok, "output_tokens": out_tok, "estimated": estimated}}


def format_plans(plans: dict) -> str:
    lines = ["The council has decided. These plans start at the next dawn."]
    for name, plan in plans.items():
        lines.append(f"- {name}: {plan.get('thought') or 'no comment'}")
        lines += [f"    {engine.describe_action(a)}" for a in plan.get("actions") or [] if isinstance(a, dict)]
    return "\n".join(lines)


def format_report(report: dict) -> str:
    lines = [f"Day {report['day']} ({'council' if report['source'] == 'model' else 'habit'}): "
             f"{report['ok']} actions done, {report['rejected']} failed."]
    lines += [f"* {e}" for e in report.get("events", [])]
    for v in report["villagers"]:
        head = f"- {v['name']}" + (f" — \"{v['thought']}\"" if v.get("thought") else f" ({v['mode']})")
        lines.append(head)
        for s in v["steps"]:
            lines.append(f"    {'✓' if s['ok'] else '✗'} {engine.describe_action(s['action'])}: {s['result']}")
        if not v["steps"]:
            lines.append("    (idle)")
    return "\n".join(lines)


def format_status(snap: dict) -> str:
    w, b = snap["world"], snap["budget"]
    fallen = [f"The village fell on day {w['fallen']}. Start a new one."] if w["fallen"] else []
    g = w["guide"]
    lines = fallen + [f"{w['settlement']}, {g['era']}, {w['season']}, day {w['day']}. Insight {g['insight']}, Trust {g['trust']}/100. Built: {', '.join(x['kind'] for x in w['built']) or 'nothing'}. "
             f"Guidance: {w['guidance'] or '(none)'}",
             f"Budget: {b['used_today']:,}/{b['daily_tokens']:,} tokens today, {b['calls_today']} council(s); "
             f"next council ~{b['est_call_tokens']:,} tokens (max {b['worst_case_tokens']:,})."]
    for v in w["villagers"]:
        inv = ", ".join(f"{n} {k}" for k, n in v["inv"].items() if n) or "nothing"
        if v.get("dying"):
            lines.append(f"- {v['name']} died of {v['dying']}.")
            continue
        way = " > ".join(w.get("ways", {}).get(v["name"], []))
        lines.append(f"- {v['name']} at ({v['x']},{v['y']}), health {v['health']}, energy {v['energy']}, skills "
                     f"{', '.join(v['skills'])}, carrying {inv}. Way: {way or 'instincts'}.")
    if w["council_reasons"]:
        lines.append("Worth a council: " + "; ".join(w["council_reasons"]) + ".")
    return "\n".join(lines)

