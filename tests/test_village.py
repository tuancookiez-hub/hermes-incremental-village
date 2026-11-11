"""Engine + service tests. No Hermes install or model needed: a fake llm stands in.

Run from the repo root:  python -m pytest tests -q
"""
from __future__ import annotations

import sqlite3
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from village import engine, planner, service  # noqa: E402
from village.store import Store  # noqa: E402


@pytest.fixture(autouse=True)
def fixed_camp(monkeypatch):
    """Most rules are easier to read with the camp pinned to (12,12)."""
    monkeypatch.setattr(engine, "CAMP", (12, 12))


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(service, "clock", c)
    return c


@pytest.fixture
def store(tmp_path, clock):
    return Store(lambda: sqlite3.connect(tmp_path / "t.db", check_same_thread=False))


def world():
    return engine.new_world(42, 0.0)


def put(w, x, y, char):
    w["changed"][f"{x},{y}"] = char


def flatten(w, size=24):
    """Plain grass over the part of the land a test works on."""
    for y in range(size):
        for x in range(size):
            put(w, x, y, ".")


# ---------------------------------------------------------------- engine

def test_new_world_shape():
    w = world()
    assert w["camp"] == [12, 12] and w["chunks"]
    assert [v["name"] for v in w["villagers"]] == ["Ash", "Bryn", "Coll"]
    assert all(v["seen"] for v in w["villagers"])
    assert all(v["inv"] == {"food": 2} for v in w["villagers"])


def test_walk_to_unseen_tile_rejected():
    w = world()
    ash = w["villagers"][0]
    used, err, _ = engine.execute(w, ash, {"verb": "walk", "x": 0, "y": 0}, 8)
    assert err and "never seen" in err and used == 1
    assert (ash["x"], ash["y"]) == (11, 12)


def test_walk_reveals_and_costs_by_distance():
    w = world()
    ash = w["villagers"][0]
    used, err, _ = engine.execute(w, ash, {"verb": "walk", "x": 7, "y": 12}, 8)
    assert err is None and used == 2 and (ash["x"], ash["y"]) == (7, 12)
    assert "3,12" in engine.seen_tiles(ash)


def test_gather_needs_adjacent_resource():
    w = world()
    ash = w["villagers"][0]
    _, err, _ = engine.execute(w, ash, {"verb": "gather", "item": "wood"}, 8)
    assert err and "no wood" in err
    engine.execute(w, ash, {"verb": "walk", "x": 7, "y": 11}, 8)  # (6,11) is forced forest
    w["stocks"]["6,11"] = 6
    _, err, _ = engine.execute(w, ash, {"verb": "gather", "item": "wood"}, 8)
    assert err is None and ash["inv"]["wood"] == 2
    fx = {}
    engine.execute(w, ash, {"verb": "gather", "item": "wood"}, 8, fx)
    assert fx["gain"] == {"wood": 2} and fx["source"] == [6, 11]


def test_build_needs_materials_then_succeeds():
    w = world()
    ash = w["villagers"][0]
    _, err, _ = engine.execute(w, ash, {"verb": "build", "item": "lean_to"}, 8)
    assert err and "needs 4 wood" in err
    ash["inv"]["wood"] = 4
    used, err, _ = engine.execute(w, ash, {"verb": "build", "item": "lean_to"}, 8)
    assert err is None and used == 3 and w["built"][0]["by"] == "Ash" and ash["inv"]["wood"] == 0
    w["built"] += [{"kind": "lean_to", "x": i, "y": 0, "by": "Ash", "day": 1} for i in range(engine.BUILDINGS["lean_to"]["max"])]
    ash["inv"]["wood"] = 4
    ash["x"] = 13
    _, err, _ = engine.execute(w, ash, {"verb": "build", "item": "lean_to"}, 8)
    assert err and "enough" in err


def test_building_skill_gate_and_effects():
    w = world()
    ash, bryn, coll = w["villagers"]
    bryn["inv"].update(stone=3, wood=1)
    _, err, _ = engine.execute(w, bryn, {"verb": "build", "item": "fire_pit"}, 8)
    assert err and "firemaking" in err
    w["built"].append({"kind": "drying_rack", "x": 1, "y": 1, "by": "Bryn", "day": 1})
    coll["x"], coll["y"] = 12, 7  # beside the forced berries at (12,6)
    engine._reveal(w, coll)
    fx = {}
    engine.execute(w, coll, {"verb": "gather", "item": "food"}, 8, fx)
    assert fx["gain"] == {"food": 4}  # 2 base + foraging + rack


def test_trade_moves_goods_only_when_both_have_them():
    w = world()
    ash, bryn, _ = w["villagers"]
    ash["inv"]["wood"] = 3
    act = {"verb": "trade", "target": "Bryn", "give": {"wood": 2}, "get": {"food": 1}}
    _, err, _ = engine.execute(w, ash, act, 8)
    assert err is None and ash["inv"] == {"food": 3, "wood": 1} and bryn["inv"] == {"food": 1, "wood": 2}
    for bad in ({"give": {"gold": 1}}, {"give": {"wood": -1}}, {}, {"give": {"wood": 99}}, {"get": {"stone": 1}}):
        _, err, _ = engine.execute(w, ash, {"verb": "trade", "target": "Bryn", **bad}, 8)
        assert err


def test_walk_routes_around_water_and_only_over_seen_land():
    w = world()
    ash = w["villagers"][0]
    flatten(w)
    for y in range(11, 14):
        put(w, 12, y, "~")
    ash["x"], ash["y"] = 11, 12
    ash["seen"] = {f"{x},{y}": 1 for x in range(24) for y in range(24)}
    path = engine.find_path(w, ash, 13, 12)
    assert all(engine.tile(w, x, y) != "water" for x, y in path)
    assert len(path) > 3  # the straight line crosses water
    ash["seen"] = ["11,12", "13,12"]
    _, err, _ = engine.execute(w, ash, {"verb": "walk", "x": 13, "y": 12}, 8)
    assert err and "no way" in err


def test_talk_and_teach_need_range_and_skill():
    w = world()
    ash, bryn, coll = w["villagers"]
    _, err, _ = engine.execute(w, ash, {"verb": "teach", "target": "Coll", "item": "weaving"}, 8)
    assert err and "cannot teach" in err
    _, err, _ = engine.execute(w, ash, {"verb": "teach", "target": "Coll", "item": "firemaking"}, 8)
    assert err is None and "firemaking" in coll["skills"]
    _, err, _ = engine.execute(w, ash, {"verb": "talk", "target": "Bryn", "text": "berries north"}, 8)
    assert err is None and bryn["heard"][-1] == "Ash: berries north"
    bryn["x"] = 20
    _, err, _ = engine.execute(w, ash, {"verb": "talk", "target": "Bryn", "text": "hi"}, 8)
    assert err and "too far" in err


def test_energy_gate_and_garbage_actions():
    w = world()
    ash = w["villagers"][0]
    ash["energy"] = 0
    _, err, _ = engine.execute(w, ash, {"verb": "look"}, 8)
    assert err and "tired" in err
    _, err, _ = engine.execute(w, ash, {"verb": "rest"}, 8)
    assert err is None and ash["energy"] == 3
    for junk in ("walk", {"verb": "fly"}, {"verb": "walk", "x": "a"}, {"verb": "gather", "item": "gold"}):
        used, err, _ = engine.execute(w, ash, junk, 8)
        assert err and used == 1


def test_run_day_respects_slots_and_falls_back_to_habit():
    w = world()
    plans = {"Ash": {"actions": [{"verb": "look"}] * 6 + [{"verb": "look"}] * 3, "thought": "hm",
                     "remember": "the camp is quiet", "standing_orders": [{"verb": "rest"}]}}
    report = engine.run_day(w, plans, source="model")
    ash_steps = report["villagers"][0]["steps"]
    assert len(ash_steps) == engine.MAX_ACTIONS  # capped at 6 actions
    assert [s["at"] for s in ash_steps] == list(range(6)) and all("after" in s for s in ash_steps)
    assert report["villagers"][1]["mode"] == "habit" and report["villagers"][1]["steps"]  # instincts
    assert w["day"] == 2 and w["villagers"][0]["standing_orders"] == [{"verb": "rest"}]
    assert w["villagers"][0]["memory"] == ["day 1: the camp is quiet"]


def test_observe_is_local_only():
    w = world()
    text = engine.observe(w, w["villagers"][0])
    rows = [ln for ln in text.splitlines() if ln and set(ln) <= set(".TRb~@LF,SD")]
    assert len(rows) == 2 * engine.VISION + 1 and all(len(r) == 2 * engine.VISION + 1 for r in rows)


def test_parse_plans_ignores_unknown_and_malformed():
    w = world()
    parsed = {"villagers": [{"name": "Zed", "actions": []}, {"name": "ash", "actions": [{"verb": "look"}]},
                            {"name": "Bryn"}, "junk"]}
    assert list(planner.parse_plans(w, parsed)) == ["Ash"]
    assert planner.parse_plans(w, None) == {}


def test_prompt_is_small():
    w = world()
    assert planner.estimate_input_tokens(w) < 3000


# ---------------------------------------------------------------- living village

def test_hunger_is_paid_overnight():
    w = world()
    ash = w["villagers"][0]
    ash["inv"] = {}
    ash["energy"] = 5
    engine.run_day(w, {"Ash": {"actions": []}}, source="model")
    assert ash["energy"] == 5 + engine.HUNGRY_ENERGY and "went to sleep hungry" in ash["feedback"]
    ash["inv"] = {"food": 1}
    ash["energy"] = 5
    engine.run_day(w, {"Ash": {"actions": []}}, source="model")
    assert ash["energy"] == 5 + engine.OVERNIGHT_ENERGY and ash["inv"]["food"] == 0


def test_bushes_run_out_and_regrow_but_not_in_winter():
    w = world()
    ash = w["villagers"][0]
    ash["x"], ash["y"] = 12, 7
    engine._reveal(w, ash)
    w["stocks"] = {"12,6": 3}
    fx = {}
    engine.execute(w, ash, {"verb": "gather", "item": "food"}, 8, fx)
    assert fx["gain"] == {"food": 2} and w["stocks"]["12,6"] == 1
    fx = {}
    engine.execute(w, ash, {"verb": "gather", "item": "food"}, 8, fx)
    assert fx["gain"] == {"food": 1} and w["stocks"]["12,6"] == 0
    _, err, _ = engine.execute(w, ash, {"verb": "gather", "item": "food"}, 8)
    assert err and "picked bare" in err
    w["day"] = 3
    engine._grow(w)
    assert w["stocks"]["12,6"] == 1
    w["day"] = 16
    assert engine.season(w) == "winter"
    _, err, _ = engine.execute(w, ash, {"verb": "gather", "item": "food"}, 8)
    assert err and "bare for the winter" in err
    engine._grow(w)
    assert w["stocks"]["12,6"] == 1


def test_food_rots_unless_dried():
    w = world()
    ash = w["villagers"][0]
    ash["inv"] = {"food": 9}
    engine.run_day(w, {"Ash": {"actions": []}}, source="model")
    assert ash["inv"]["food"] == 6  # ate 1, a quarter of 8 rotted
    w["built"].append({"kind": "drying_rack", "x": 1, "y": 1, "by": "Bryn", "day": 1})
    ash["inv"] = {"food": 9}
    engine.run_day(w, {"Ash": {"actions": []}}, source="model")
    assert ash["inv"]["food"] == 8


def test_hunger_kills_and_the_dead_stay_visible_for_their_last_day():
    w = world()
    ash = w["villagers"][0]
    ash["inv"], ash["health"] = {}, 1
    ash["x"], ash["y"] = 20, 20
    report = engine.run_day(w, {"Ash": {"actions": []}}, source="model")
    assert report["deaths"] == [{"name": "Ash", "cause": "hunger"}] and engine.villager(w, "Ash") is None
    assert "Ash died of hunger" in report["events"]
    state = engine.public_state(w, 0.0)
    assert [v["dying"] for v in state["villagers"] if v["name"] == "Ash"] == ["hunger"]
    assert state["dead"][0]["x"] == 20
    engine.run_day(w, {}, source="habit")
    assert "Ash" not in [v["name"] for v in engine.public_state(w, 0.0)["villagers"]]


def test_winter_cold_needs_shelter_nearby():
    w = world()
    w["day"] = 16
    ash = w["villagers"][0]
    ash["inv"], ash["health"] = {"food": 2}, 4
    engine.run_day(w, {"Ash": {"actions": []}}, source="model")
    assert ash["health"] == 3 and "nearly froze in the open" in ash["feedback"]
    w["built"].append({"kind": "lean_to", "x": ash["x"] + 1, "y": ash["y"], "by": "Ash", "day": 1})
    w["day"] = 17
    ash["inv"] = {"food": 2}
    engine.run_day(w, {"Ash": {"actions": []}}, source="model")
    assert ash["health"] >= 3 and "nearly froze in the open" not in ash["feedback"]


def test_fire_keeps_wolves_away():
    bites = safe = 0
    for seed in range(200):
        w = engine.new_world(seed, 0.0)
        for v in w["villagers"]:
            v["inv"] = {"food": 2}
        engine.run_day(w, {v["name"]: {"actions": []} for v in w["villagers"]}, source="model")
        bites += sum(e["night"]["bitten"] for e in w["log"][-1]["villagers"])
        w = engine.new_world(seed, 0.0)
        w["built"].append({"kind": "fire_pit", "x": 12, "y": 12, "by": "Ash", "day": 1})
        w["store"] = {"wood": 5}
        engine.run_day(w, {v["name"]: {"actions": []} for v in w["villagers"]}, source="model")
        safe += sum(e["night"]["bitten"] for e in w["log"][-1]["villagers"])
    assert bites > 0 and safe == 0


def test_picking_bushes_bare_teaches_farming_and_fields_need_water():
    w = world()
    bryn = w["villagers"][1]
    bryn["x"], bryn["y"] = 12, 7
    w["stocks"] = {"12,6": 2}
    w["emptied"] = engine.EMPTIED_FOR_FARMING - 1
    engine.execute(w, bryn, {"verb": "gather", "item": "food"}, 8)
    assert "farming" in bryn["skills"]
    bryn["inv"]["wood"] = 2
    dry = next((x, y) for y in range(24) for x in range(24)
               if engine.tile(w, x, y) == "grass" and not engine._near_tile(w, x, y, "water", 3))
    bryn["x"], bryn["y"] = dry
    _, err, _ = engine.execute(w, bryn, {"verb": "build", "item": "field"}, 8)
    assert err and "water" in err
    wet = next((x, y) for y in range(24) for x in range(24)
               if engine.tile(w, x, y) == "grass" and engine._near_tile(w, x, y, "water", 3))
    bryn["x"], bryn["y"] = wet
    _, err, _ = engine.execute(w, bryn, {"verb": "build", "item": "field"}, 8)
    assert err is None and w["stocks"][f"{wet[0]},{wet[1]}"] == 0
    w["day"] = 2
    engine._grow(w)
    assert w["stocks"][f"{wet[0]},{wet[1]}"] == engine.FIELD_GROWTH


def test_a_watched_village_can_fall_but_an_absence_cannot_end_it():
    w = world()
    for v in w["villagers"]:
        v["inv"], v["health"] = {}, 1
    report = engine.run_day(w, {v["name"]: {"actions": []} for v in w["villagers"]}, source="model")
    assert w["fallen"] == 1 and len(report["deaths"]) == 3
    before = w["day"]
    assert engine.advance(w, engine.DAY_SECONDS * 5) is None and w["day"] == before
    assert engine.public_state(w, 0.0)["fallen"] == 1
    w = world()
    for v in w["villagers"]:
        v["inv"], v["health"] = {}, 1
    engine.run_day(w, {v["name"]: {"actions": []} for v in w["villagers"]}, source="habit", unwatched=True)
    assert len(w["villagers"]) == 1 and not w["fallen"]


def test_a_spare_bed_and_full_bellies_bring_a_wanderer():
    w = world()
    for v in w["villagers"]:
        v["inv"] = {"food": 9}
    events = []
    for day in range(1, 60):
        w["day"] = day
        engine._arrival(w, events)
    assert len(w["villagers"]) == 3  # no spare bed yet
    w["built"].append({"kind": "hut", "x": 12, "y": 12, "by": "Ash", "day": 1})
    for day in range(60, 120):
        w["day"] = day
        engine._arrival(w, events)
    assert len(w["villagers"]) == 5 and "wandered in" in events[0]


def test_insight_comes_from_living_building_and_losing():
    w = world()
    engine.run_day(w, {}, source="habit")
    assert w["guide"]["insight"] >= 1
    before = w["guide"]["insight"]
    ash = w["villagers"][0]
    ash["inv"], ash["health"] = {}, 1
    ash["x"], ash["y"] = 20, 20
    report = engine.run_day(w, {"Ash": {"actions": []}}, source="model")
    assert report["deaths"] and w["guide"]["insight"] >= before + 3


def test_ideas_cost_insight_and_follow_history():
    w = world()
    assert "costs 5 Insight" in engine.plant_idea(w, "sowing")
    w["guide"]["insight"] = 50
    assert "builds on" in engine.plant_idea(w, "pottery")
    assert engine.plant_idea(w, "sowing") is None and w["guide"]["insight"] == 45
    assert "already" in engine.plant_idea(w, "sowing")
    assert "no idea" in engine.plant_idea(w, "wormholes")
    assert "an idea came to you" in engine.observe(w, w["villagers"][0])


def test_experiments_use_materials_can_fail_and_unlock():
    w = world()
    w["guide"]["insight"] = 20
    bryn = w["villagers"][1]
    _, err, _ = engine.execute(w, bryn, {"verb": "experiment", "item": "sowing"}, 8)
    assert err and "nobody has had the idea" in err
    engine.plant_idea(w, "sowing")
    wet = next((x, y) for y in range(24) for x in range(24)
               if engine.tile(w, x, y) == "grass" and engine._near_tile(w, x, y, "water", 3))
    bryn["x"], bryn["y"] = wet
    bryn["inv"] = {}
    _, err, _ = engine.execute(w, bryn, {"verb": "experiment", "item": "sowing"}, 8)
    assert err and "needs 1 food" in err
    tries = 0
    while not engine._knows(w, "sowing"):
        bryn["inv"]["food"], bryn["energy"] = 1, 5
        w["day"] += 1
        used, err, _ = engine.execute(w, bryn, {"verb": "experiment", "item": "sowing"}, 8)
        assert err is None and used == engine.EXPERIMENT_SLOTS and bryn["inv"]["food"] == 0
        tries += 1
        assert tries < 8  # failures raise the odds until it must work
    assert "farming" in bryn["skills"] and engine.era(w) == "Farming Age"


def test_buildings_wait_for_their_idea():
    w = world()
    ash = w["villagers"][0]
    ash["inv"] = {"wood": 9, "stone": 9}
    _, err, _ = engine.execute(w, ash, {"verb": "build", "item": "storehouse"}, 8)
    assert err and "pottery" in err
    w["guide"]["known"].append("pottery")
    _, err, _ = engine.execute(w, ash, {"verb": "build", "item": "storehouse"}, 8)
    assert err is None
    ash["inv"] = {"food": 9}
    engine.run_day(w, {"Ash": {"actions": []}}, source="model")
    assert ash["inv"]["food"] == 8  # the storehouse stopped the rot


def test_upgrades_change_the_rules():
    w = world()
    w["guide"]["insight"] = 30
    assert engine.buy_upgrade(w, "keen_eyes") is None
    assert "already" in engine.buy_upgrade(w, "keen_eyes")
    assert engine.buy_upgrade(w, "hardy") is None and engine.max_health(w) == engine.MAX_HEALTH + 1
    rows = [ln for ln in engine.observe(w, w["villagers"][0]).splitlines() if ln and set(ln) <= set(".TRb~@LF,SD")]
    assert len(rows) == 2 * (engine.VISION + 1) + 1


def test_trust_is_earned_by_results():
    w = world()
    engine.set_focus(w, "explore")
    for _ in range(engine.FOCUS_DAYS):
        report = engine.run_day(w, {}, source="habit")
    assert any("Your advice" in e for e in report["events"])
    assert w["guide"]["trust"] != engine.START_TRUST
    w = world()
    engine.set_focus(w, "food")
    ash = w["villagers"][0]
    ash["inv"], ash["health"], ash["x"], ash["y"] = {}, 1, 20, 20
    for _ in range(engine.FOCUS_DAYS):
        engine.run_day(w, {}, source="habit")
    assert w["guide"]["trust"] == engine.START_TRUST - 10
    assert "must be one of" in engine.set_focus(w, "dance")


def test_low_trust_means_free_days_ignore_the_focus():
    w = world()
    w["built"].append({"kind": "lean_to", "x": 12, "y": 12, "by": "Ash", "day": 1})
    ash = w["villagers"][0]
    ash["inv"], ash["x"] = {"food": 5}, 9  # close enough to know the forest at (6,11)
    engine._reveal(w, ash)
    engine.set_focus(w, "shelter")
    assert any(a.get("item") == "wood" for a in engine.instinct_actions(w, ash))
    w["guide"]["trust"] = engine.TRUST_HEEDED - 1
    assert not any(a.get("item") == "wood" for a in engine.instinct_actions(w, ash))


def test_legacy_outlives_a_village_and_shapes_the_next(store, clock):
    service.reset(store, 42)
    with store.tx() as db:
        w = store.load_world(db)
        w["day"], w["fallen"] = 41, 40
        w["guide"]["known"] = ["sowing"]
        store.save_world(db, w)
    snap = service.reset(store, 7)
    assert snap["legacy"]["points"] == 2 + 1 + 1 and snap["legacy"]["villages"][-1]["fallen"]
    snap = service.buy_perk(store, "old_songs")
    assert snap["legacy"]["points"] == 1 and "old_songs" in snap["legacy"]["perks"]
    with pytest.raises(service.VillageError, match="costs"):
        service.buy_perk(store, "seed_memory")
    snap = service.reset(store, 8)
    assert snap["world"]["guide"]["insight"] >= 5


def test_guide_actions_refuse_cleanly_and_save(store, clock):
    with pytest.raises(service.VillageError, match="costs"):
        service.plant(store, "sowing")
    with store.tx() as db:
        w = store.load_world(db)
        w["guide"]["insight"] = 10
        store.save_world(db, w)
    assert "sowing" in service.plant(store, "sowing")["world"]["guide"]["planted"]
    assert service.focus(store, "learn")["world"]["guide"]["focus"] == "learn"
    assert service.focus(store, None)["world"]["guide"]["focus"] is None
    assert "being tried" in service.format_ideas(service.snapshot(store))


def test_speed_shortens_days_without_moving_the_day():
    w = world()
    engine.advance(w, 0.0)
    assert engine.advance(w, engine.DAY_SECONDS / 2) is None and w["day"] == 2
    assert engine.set_speed(w, 16, engine.DAY_SECONDS / 2) is None
    played = (engine.DAY_SECONDS / 2 - w["day_started_at"]) * 16
    assert played == pytest.approx(engine.DAY_SECONDS / 2)
    now = engine.DAY_SECONDS / 2 + engine.DAY_SECONDS / 32  # the other half of the day at 16x
    engine.advance(w, now + 0.01)
    assert w["day"] == 3
    assert "speed must be" in engine.set_speed(w, 3, now)


def test_pause_stops_time_and_resumes_where_it_stopped():
    w = world()
    engine.advance(w, 0.0)
    engine.set_speed(w, 0, 10.0)
    for t in (15.0, 20.0, 25.0):
        engine.advance(w, t)
    assert w["day"] == 2
    engine.set_speed(w, 1, 25.0)
    assert 25.0 - w["day_started_at"] == pytest.approx(10.0)


def test_leaving_at_high_speed_falls_back_to_normal_time():
    w = world()
    engine.advance(w, 0.0)
    engine.set_speed(w, 16, 0.0)
    engine.advance(w, 5.0)
    day = w["day"]
    engine.advance(w, 5.0 + engine.DAY_SECONDS * 3)  # gone for 3 normal days, not 48
    assert w["speed"] == 1 and w["day"] == day + 3


def test_leaving_while_paused_lets_time_run_again():
    w = world()
    engine.advance(w, 0.0)
    engine.set_speed(w, 0, 1.0)
    engine.advance(w, 1.0 + engine.DAY_SECONDS * 3)
    assert w["paused_at"] is None and w["day"] >= 4


def test_a_council_while_paused_waits_for_the_dawn(store, clock):
    service.speed(store, 0)
    clock.t += 5
    out = service.plan_day(store, FakeLlm(GOOD))
    assert out["world"]["paused_at"] is not None and out["world"]["council_ready"]
    clock.t += 5
    assert service.speed(store, 4)["world"]["speed"] == 4


def test_trees_and_rock_run_out_and_the_land_changes():
    w = world()
    ash = w["villagers"][0]
    ash["x"], ash["y"] = 7, 11  # beside the forced forest at (6,11)
    w["stocks"] = {"6,11": 3}
    fx = {}
    engine.execute(w, ash, {"verb": "gather", "item": "wood"}, 8, fx)
    assert fx["gain"] == {"wood": 2} and w["stocks"]["6,11"] == 1
    fx = {}
    engine.execute(w, ash, {"verb": "gather", "item": "wood"}, 8, fx)
    assert fx["gain"] == {"wood": 1} and "6,11" not in w["stocks"]
    assert engine.tile(w, 6, 11) == "grass" and engine._base_char(w, 6, 11) == "T"
    assert any("trees" in e for e in w["_events"])
    state = engine.public_state(w, 0.0)
    assert state["land_view"]["land"]["0,0"][11 * 16 + 6] == "T"  # the page keeps the land's shape and hides what is gone


def test_stone_never_runs_out_but_a_part_cut_forest_regrows():
    w = world()
    ash = w["villagers"][0]
    ash["x"], ash["y"] = 16, 12  # beside the forced rock at (17,12)
    for _ in range(30):
        ash["inv"], ash["energy"] = {}, 5
        _, err, _ = engine.execute(w, ash, {"verb": "gather", "item": "stone"}, 8)
        assert err is None
    assert engine.tile(w, 17, 12) == "rock"
    w["stocks"] = {"6,11": 2}
    w["day"] = engine.TREE_REGROW_DAYS
    engine._grow(w)
    assert w["stocks"]["6,11"] == 3


def test_cleared_land_only_returns_beside_living_forest():
    w = world()
    w["stocks"].pop("6,11", None)
    for y in range(9, 14):
        for x in range(4, 9):
            put(w, x, y, ".")
    w["shaped"]["6,11"] = "T"
    for _ in range(60):
        engine._seed_forest(w)
        w["day"] += 20
    assert engine.tile(w, 6, 11) == "grass"  # nothing nearby to seed it
    put(w, 5, 11, "T")
    for _ in range(60):
        engine._seed_forest(w)
        w["day"] += 20
    assert engine.tile(w, 6, 11) == "forest" and w["stocks"]["6,11"] == 1


def test_the_store_is_shared_and_needs_a_walk():
    w = world()
    ash, bryn, _ = w["villagers"]
    ash["inv"] = {"wood": 5}
    ash["x"], ash["y"] = 20, 20
    _, err, _ = engine.execute(w, ash, {"verb": "deposit", "item": "wood"}, 8)
    assert err and "too far" in err
    ash["x"], ash["y"] = 12, 12
    _, err, _ = engine.execute(w, ash, {"verb": "deposit", "item": "wood", "n": 3}, 8)
    assert err is None and w["store"]["wood"] == 3 and ash["inv"]["wood"] == 2
    _, err, _ = engine.execute(w, bryn, {"verb": "take", "item": "wood"}, 8)
    assert err is None and bryn["inv"]["wood"] == 3 and w["store"]["wood"] == 0


def test_builders_near_the_store_can_use_it():
    w = world()
    ash = w["villagers"][0]
    w["store"] = {"wood": 3}
    ash["inv"] = {"wood": 1}
    ash["x"], ash["y"] = 11, 12
    _, err, _ = engine.execute(w, ash, {"verb": "build", "item": "lean_to"}, 8)
    assert err is None and w["store"]["wood"] == 0 and ash["inv"]["wood"] == 0


def test_carrying_has_a_limit_and_stone_is_heavy():
    w = world()
    ash = w["villagers"][0]
    ash["x"], ash["y"] = 16, 12
    ash["inv"] = {"wood": 11}
    _, err, _ = engine.execute(w, ash, {"verb": "gather", "item": "stone"}, 8)
    assert err and "cannot carry" in err


def test_fires_burn_wood_and_go_out():
    w = world()
    w["built"].append({"kind": "fire_pit", "x": 12, "y": 13, "by": "Ash", "day": 1})
    w["store"] = {"wood": 1}
    report = engine.run_day(w, {v["name"]: {"actions": []} for v in w["villagers"]}, source="model")
    assert w["store"]["wood"] == 0 and not w["fire_out"]
    report = engine.run_day(w, {v["name"]: {"actions": []} for v in w["villagers"]}, source="model")
    assert w["fire_out"] and any("went out" in e for e in report["events"])
    assert not engine._lit_fire_near(w, 12, 13)


def test_thirst_needs_water_nearby_or_in_the_pack():
    w = world()
    ash = w["villagers"][0]
    dry = next(((x, y) for y in range(24) for x in range(24)
                if engine.tile(w, x, y) == "grass" and not engine._near_tile(w, x, y, "water", engine.WATER_RANGE)), None)
    if dry is None:
        flatten(w, 40)
        dry = (12, 12)
    ash["x"], ash["y"], ash["inv"] = dry[0], dry[1], {"food": 2}
    engine.run_day(w, {"Ash": {"actions": []}}, source="model")
    assert "went to sleep thirsty" in ash["feedback"]
    ash["inv"] = {"food": 2, "water": 1}
    engine.run_day(w, {"Ash": {"actions": []}}, source="model")
    assert "went to sleep thirsty" not in ash["feedback"] and ash["inv"]["water"] == 0


def test_grain_keeps_and_fields_tire():
    w = world()
    w["woodlots"], w["stocks"] = [], {"10,10": 8}
    ash = w["villagers"][0]
    ash["x"], ash["y"], ash["inv"] = 11, 10, {}
    fx = {}
    engine.execute(w, ash, {"verb": "gather", "item": "food"}, 8, fx)
    assert fx["gain"] == {"grain": 2} and w["soil"]["10,10"] < 1
    ash["inv"] = {"grain": 9}
    engine.run_day(w, {"Ash": {"actions": []}}, source="model")
    assert ash["inv"]["grain"] == 8  # ate one, none rotted


def test_meat_rots_fast():
    w = world()
    ash = w["villagers"][0]
    ash["inv"] = {"meat": 7}
    engine.run_day(w, {"Ash": {"actions": []}}, source="model")
    assert ash["inv"]["meat"] == 3


def test_herds_start_out_of_sight_and_can_be_hunted_out():
    for seed in (1, 7, 42):
        w = engine.new_world(seed, 0.0)
        assert w["herds"] and all(engine.dist(h["x"], h["y"], 12, 12) >= 8 for h in w["herds"])
        assert engine.resources(w)["herds"] == []
    w = world()
    ash = w["villagers"][0]
    herd = w["herds"][0]
    herd.update(kind="deer", count=1)
    w["herds"] = [herd]
    for day in range(1, 60):
        if not w["herds"]:
            break
        w["day"] = day
        ash["x"], ash["y"], ash["energy"], ash["inv"] = w["herds"][0]["x"], w["herds"][0]["y"], 5, {}
        _, err, _ = engine.execute(w, ash, {"verb": "hunt", "item": "deer"}, 8)
        assert err is None
    assert not w["herds"] and ash["inv"].get("meat") == engine.MEAT_PER_KILL
    _, err, _ = engine.execute(w, ash, {"verb": "hunt", "item": "deer"}, 8)
    assert err and "close enough" in err


def test_herds_breed_each_spring():
    w = world()
    w["herds"] = [{"kind": "deer", "x": 2, "y": 2, "count": 2}]
    w["day"] = 21
    assert engine.season(w) == "spring"
    engine._herds_live(w)
    assert w["herds"][0]["count"] == 3


def test_coppicing_gives_renewable_wood():
    w = world()
    w["guide"]["known"].append("coppicing")
    ash = w["villagers"][0]
    ash["x"], ash["y"], ash["inv"] = 11, 13, {"wood": 2}
    _, err, _ = engine.execute(w, ash, {"verb": "build", "item": "woodlot"}, 8)
    assert err is None
    key = "11,13"
    assert w["stocks"][key] == 0
    w["day"] = engine.WOODLOT_GROW_DAYS
    engine._grow(w)
    assert w["stocks"][key] == 1
    ash["x"], ash["y"] = 11, 12
    _, err, _ = engine.execute(w, ash, {"verb": "gather", "item": "wood"}, 8)
    assert err is None and key in w["stocks"] and ash["inv"]["wood"] == 1


def test_the_readout_counts_only_what_they_have_seen():
    w = world()
    r = engine.resources(w)
    assert r["held"]["food"] == 6
    everything = sum(n for k, n in w["stocks"].items() if engine.tile(w, *map(int, k.split(","))) == "forest")
    assert 0 < r["wild"]["wood"] < everything
    w["stocks"] = {}
    assert any("very little" in reason for reason in engine.needs_council(w))


def test_the_land_is_natural_and_comes_from_the_seed_alone():
    chars = "".join("".join(engine._land(5, cx, cy)) for cy in range(-12, 12, 2) for cx in range(-12, 12, 2))
    for ch, low, high in (("~", 0.05, 0.25), ("T", 0.1, 0.45), ("R", 0.04, 0.2), ("b", 0.02, 0.2)):
        assert low < chars.count(ch) / len(chars) < high, ch
    engine._land.cache_clear()
    assert "".join(engine._land(5, -3, 4)) == "".join(engine._land(5, -3, 4))
    assert engine._land(5, 0, 0) != engine._land(6, 0, 0)
    assert engine._land(5, 0, 0) != engine._land(5, 1, 0)


def test_the_land_has_no_edge():
    w = world()
    for x, y in ((-1, -1), (-5000, 3), (1_000_000, -1_000_000), (10 ** 12, 10 ** 12)):
        assert engine.tile(w, x, y) in engine.TILE_CHARS


def test_chunks_join_up_with_negative_coordinates():
    assert engine._land_char(9, -1, -1) == engine._land(9, -1, -1)[15][15]
    assert engine._land_char(9, -16, -16) == engine._land(9, -1, -1)[0][0]
    assert engine._land_char(9, -17, 0) == engine._land(9, -2, 0)[0][15]


def test_a_chunk_only_exists_once_it_is_seen():
    w = world()
    assert "-40,-40" not in w["chunks"] and not any(int(k.split(",")[0]) < -100 for k in w["stocks"])
    ash = w["villagers"][0]
    ash["x"], ash["y"] = -640, -640
    engine._reveal(w, ash)
    assert "-40,-40" in w["chunks"] and any(int(k.split(",")[0]) < -600 for k in w["stocks"])


def test_opening_a_chunk_twice_changes_nothing():
    w = world()
    herds, stocks = list(w["herds"]), dict(w["stocks"])
    for key in list(w["chunks"]):
        engine._open_chunk(w, *map(int, key.split(",")))
    assert w["herds"] == herds and w["stocks"] == stocks


def test_every_seed_finds_open_camp_land(monkeypatch):
    monkeypatch.setattr(engine, "CAMP", None)
    for seed in range(1, 15):
        w = engine.new_world(seed, 0.0)
        cx, cy = w["camp"]
        assert engine.tile(w, cx, cy) == "grass"
        assert all(not (engine.tile(w, v["x"], v["y"]) == "water") for v in w["villagers"])
        assert any(engine.find_path(w, w["villagers"][0], cx + dx, cy + dy) for dx, dy in ((-4, 0), (4, 0), (0, -4), (0, 4)))
    assert engine.new_world(3, 0.0)["camp"] == engine.new_world(3, 0.0)["camp"]


def test_villagers_can_leave_the_camp_in_any_direction(monkeypatch):
    monkeypatch.setattr(engine, "CAMP", None)
    for seed in (1, 2, 3, 4):
        w = engine.new_world(seed, 0.0)
        start = tuple(w["camp"])
        done, queue, far = {start}, [start], 0
        while queue and far < 120:
            x, y = queue.pop(0)
            far = max(far, engine.dist(x, y, *start))
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    n = (x + dx, y + dy)
                    if n not in done and engine._char(w, *n) != "~":
                        done.add(n)
                        queue.append(n)
        assert far >= 120


def test_a_villager_walks_past_the_old_edges_on_negative_tiles():
    w = world()
    ash = w["villagers"][0]
    flatten(w)
    for x in range(-40, 1):
        put(w, x, 2, ".")
    ash["x"], ash["y"], ash["inv"] = 0, 2, {}
    engine._reveal(w, ash)
    for _ in range(12):
        ash["energy"] = engine.MAX_ENERGY
        _, err, _ = engine.execute(w, ash, {"verb": "walk", "x": ash["x"] - engine.VISION, "y": 2}, 8, {})
        assert err is None
    assert ash["x"] < -30 and f"{ash['x']},2" in engine.seen_tiles(ash)
    assert any(int(k.split(",")[0]) < -2 for k in w["chunks"])


def test_only_seen_land_and_its_neighbours_reach_the_page():
    w = world()
    view = engine.land_view(w)
    mine = {tuple(map(int, k.split(","))) for k in view["seen"]}
    allowed = {(cx + dx, cy + dy) for cx, cy in mine for dy in (-1, 0, 1) for dx in (-1, 0, 1)}
    assert {tuple(map(int, k.split(","))) for k in view["land"]} == allowed
    assert all(len(rows) == 256 for rows in view["land"].values())
    assert all(len(mask) == 256 for mask in view["seen"].values())
    seen = set().union(*(engine.seen_tiles(v) for v in w["villagers"]))
    assert sum(mask.count("1") for mask in view["seen"].values()) == len(seen)
    assert all(k in seen for k in view["stocks"])


def test_the_camp_clearing_reaches_the_page():
    w = world()
    land = engine.land_view(w)["land"]
    assert land["0,0"][11 * 16 + 6] == "T" and land["0,0"][12 * 16 + 12] == "."


def test_the_page_skips_land_it_already_holds():
    w = world()
    state = engine.public_state(w, 0.0)
    assert "land_view" in state
    assert "land_view" not in engine.public_state(w, 0.0, state["land_rev"])
    engine.run_day(w, {}, source="habit")
    assert "land_view" in engine.public_state(w, 0.0, state["land_rev"])


def test_a_new_village_never_shares_a_land_revision():
    assert engine.land_rev(engine.new_world(5, 1.0)) != engine.land_rev(engine.new_world(5, 2.0))


def test_a_save_holds_changes_not_land():
    import json
    w = world()
    size = len(json.dumps(w))
    ash = w["villagers"][0]
    ash["x"], ash["y"] = 16000, 16000
    assert engine.tile(w, 16000, 16000) in engine.TILE_CHARS
    assert len(json.dumps(w)) < size + 200  # looking at far land costs nothing
    assert "grid" not in w and "base_grid" not in w


def test_seen_land_saves_by_the_chunk_not_the_tile():
    import json
    w = world()
    ash = w["villagers"][0]
    tiles = {f"{x},{y}": 1 for y in range(-200, 200) for x in range(-200, 200)}
    ash["seen"] = dict(tiles)
    engine._reveal(w, ash)
    assert engine.seen_tiles(ash) >= set(tiles)
    assert len(json.dumps(ash["seen"])) < len(json.dumps(tiles)) / 8
    assert all(len(bits) == 64 for bits in ash["seen"].values())
    again = json.loads(json.dumps(w))
    assert engine.seen_tiles(again["villagers"][0]) == engine.seen_tiles(ash)
    engine._reveal(again, again["villagers"][0])  # loads back and keeps working
    assert engine.public_state(again, 0.0)["villagers"][0]["seen_count"] == len(engine.seen_tiles(ash))


def test_the_seen_map_covers_negative_tiles():
    w = world()
    ash = w["villagers"][0]
    ash["seen"], ash["x"], ash["y"] = {}, -33, -2
    engine._reveal(w, ash)
    expected = {f"{x},{y}": 1 for y in range(-6, 3) for x in range(-37, -28)}
    assert engine.seen_tiles(ash) == set(expected)


def test_a_felled_tree_survives_a_save():
    import json
    w = world()
    ash = w["villagers"][0]
    ash["x"], ash["y"] = 7, 11
    w["stocks"]["6,11"] = 1
    engine.execute(w, ash, {"verb": "gather", "item": "wood"}, 8, {})
    w = json.loads(json.dumps(w))
    assert engine.tile(w, 6, 11) == "grass" and engine._base_char(w, 6, 11) == "T"


def test_herds_turn_up_as_the_land_opens():
    w = world()
    ash = w["villagers"][0]
    for i in range(1, 40):
        ash["x"], ash["y"] = i * 48, 0
        engine._reveal(w, ash)
    assert len(w["herds"]) > 10
    assert all(h["kind"] in ("deer", "boar") and 3 <= h["count"] <= 5 for h in w["herds"])


def test_scouts_head_for_land_they_have_not_seen():
    w = world()
    flatten(w, 60)
    ash = w["villagers"][0]
    acts = engine._scout(w, ash)
    x, y = acts[0]["x"], acts[0]["y"]
    known = engine.seen_tiles(ash)
    assert f"{x},{y}" in known
    assert any(f"{x + dx},{y + dy}" not in known for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))


def test_a_starving_band_moves_on_instead_of_going_home():
    w = world()
    flatten(w, 60)
    w["stocks"], w["herds"] = {}, []
    ash = w["villagers"][0]
    ash["inv"] = {}
    acts = engine.instinct_actions(w, ash)
    assert acts[0]["verb"] == "walk" and acts[-1]["verb"] == "look"


def test_nobody_scouts_into_the_winter():
    w = world()
    flatten(w, 60)
    w["built"].append({"kind": "lean_to", "x": 12, "y": 12, "by": "Ash", "day": 1})
    w["store"] = {"food": 40, "wood": 10}
    w["day"] = engine.SEASON_DAYS * 3 + 1
    assert engine.season(w) == "winter"
    ash = w["villagers"][0]
    ash["x"], ash["y"], ash["inv"] = 30, 12, {"food": 5, "water": 1}
    ash["seen"] = {f"{x},{y}": 1 for x in range(60) for y in range(60)}
    acts = engine.instinct_actions(w, ash)
    assert acts[0]["verb"] == "walk" and abs(acts[0]["x"] - 12) <= 2


def test_a_long_walk_stops_at_nightfall_and_carries_on():
    w = world()
    ash = w["villagers"][0]
    ash["seen"] = {f"{x},{y}": 1 for x in range(24) for y in range(24)}
    flatten(w)
    fx = {}
    used, err, text = engine.execute(w, ash, {"verb": "walk", "x": 23, "y": 12}, 2, fx)
    assert err is None and used == 2 and "for the night" in text
    assert ash["x"] == 17 and len(fx["path"]) == 7 and fx["path"][-1] == [ash["x"], ash["y"]]


def test_a_depot_stores_goods_far_from_camp():
    w = world()
    ash = w["villagers"][0]
    flatten(w)
    ash["x"], ash["y"], ash["inv"] = 3, 3, {"wood": 5}
    used, err, _ = engine.execute(w, ash, {"verb": "build", "item": "depot"}, 8)
    assert err is None and w["depots"][0]["x"] == 3
    _, err, _ = engine.execute(w, ash, {"verb": "deposit", "item": "wood"}, 8)
    assert err is None and w["depots"][0]["inv"]["wood"] == 3 and w["store"] == {}
    assert engine.resources(w)["held"]["wood"] == 3
    ash["x"] = 6
    _, err, _ = engine.execute(w, ash, {"verb": "take", "item": "wood"}, 8)
    assert err and "too far" in err


def test_pack_frames_carry_more():
    w = world()
    ash = w["villagers"][0]
    ash["inv"] = {"wood": 12}
    assert engine._room(w, ash, "wood") == 0
    w["guide"]["insight"] = 10
    assert engine.buy_upgrade(w, "pack_frames") is None
    assert engine._room(w, ash, "wood") == engine.PACK_FRAME_BONUS


def test_a_nomad_far_from_shelter_raises_a_new_lean_to():
    w = world()
    flatten(w)
    w["built"].append({"kind": "lean_to", "x": 2, "y": 2, "by": "Ash", "day": 1})
    ash = w["villagers"][0]
    ash["x"], ash["y"], ash["inv"] = 20, 20, {"wood": 4, "food": 5}
    ash["seen"] = {f"{x},{y}": 1 for x in range(24) for y in range(24)}
    acts = engine.instinct_actions(w, ash)
    assert acts[-1] == {"verb": "build", "item": "lean_to"}


def test_a_villager_far_from_home_camps_out():
    w = world()
    w["built"].append({"kind": "lean_to", "x": 2, "y": 2, "by": "Ash", "day": 1})
    ash = w["villagers"][0]
    ash["x"], ash["y"] = 20, 20
    assert engine._home(w, ash) == (20, 20)


def test_seen_stays_compact_and_keeps_working():
    w = world()
    view = engine.land_view(w)
    assert sum(r.count("1") for r in view["seen"].values()) > 50
    assert all(k in set().union(*(engine.seen_tiles(v) for v in w["villagers"])) for k in view["stocks"])


def test_advance_runs_days_lazily_and_digests_absence():
    w = world()
    assert engine.advance(w, 0.0) is None and w["day"] == 2  # first day plays at once
    assert engine.advance(w, engine.DAY_SECONDS - 1) is None and w["day"] == 2
    assert engine.advance(w, engine.DAY_SECONDS) is None and w["day"] == 3
    digest = engine.advance(w, engine.DAY_SECONDS * 6)
    assert digest["days"] == 5 and w["day"] == 8 and w["away"]["days"] == 5


def test_long_absence_is_capped():
    w = world()
    engine.advance(w, 0.0)
    now = engine.DAY_SECONDS * 1000.0
    digest = engine.advance(w, now)
    assert digest["days"] == engine.MAX_CATCHUP_DAYS and w["day_started_at"] == now


def test_free_days_are_valid_across_many_worlds(monkeypatch):
    monkeypatch.setattr(engine, "CAMP", None)
    for seed in range(1, 40):
        w = engine.new_world(seed, 0.0)
        engine.advance(w, 0.0)
        for i in range(1, 6):
            engine.advance(w, engine.DAY_SECONDS * i * 12.0)
            assert w["log"][-1]["rejected"] <= 3
        assert w["day"] > 30 or w["fallen"] > 15  # nobody starves before the first winter


def test_free_villagers_raise_the_first_shelter():
    w = world()
    engine.advance(w, 0.0)
    engine.advance(w, engine.DAY_SECONDS * 30.0)
    assert any(b["kind"] == "lean_to" for b in w["built"])


def test_replay_positions_chain_through_a_day():
    w = world()
    engine.advance(w, 0.0)
    for e in w["log"][-1]["villagers"]:
        x, y = e["start"]["x"], e["start"]["y"]
        for s in e["steps"]:
            if s.get("path"):
                assert s["path"][0] == [x, y]
                x, y = s["path"][-1]
            assert (s["after"]["x"], s["after"]["y"]) == (x, y)
        assert sum(s["slots"] for s in e["steps"]) <= engine.SLOTS_PER_DAY


# ---------------------------------------------------------------- service

class FakeLlm:
    def __init__(self, parsed, usage=(900, 300), fail=None):
        self.parsed, self.usage, self.fail, self.calls = parsed, usage, fail, []

    def complete_structured(self, **kw):
        self.calls.append(kw)
        if self.fail:
            raise self.fail
        return SimpleNamespace(parsed=self.parsed, text="{}", provider="fake", model="fake-1",
                               usage=SimpleNamespace(input_tokens=self.usage[0], output_tokens=self.usage[1]))


GOOD = {"villagers": [{"name": "Ash", "thought": "Wood first.", "actions": [
    {"verb": "walk", "x": 7, "y": 11}, {"verb": "gather", "item": "wood"}],
    "standing_orders": [{"verb": "gather", "item": "wood"}]}]}


def test_plan_day_spends_and_records(store, clock):
    service.reset(store, 42)  # GOOD walks to (7,11), which is water in about 1 world in 24
    llm = FakeLlm(GOOD)
    clock.t += 10
    before = service.snapshot(store)["world"]
    out = service.plan_day(store, llm)
    w = out["world"]
    # the day in progress keeps playing; nobody moves until the next dawn
    assert w["day"] == before["day"] and w["day_started_at"] == before["day_started_at"]
    assert w["current"]["source"] == "habit" and w["council_ready"]
    assert out["budget"]["used_today"] == 1200 and out["budget"]["calls_today"] == 1
    kw = llm.calls[0]
    assert kw["task"] == service.AUX_TASK and kw["max_tokens"] == planner.MAX_OUTPUT_TOKENS
    clock.t += engine.DAY_SECONDS
    w = service.snapshot(store)["world"]
    assert w["current"]["source"] == "model" and not w["council_ready"]
    assert w["current"]["villagers"][0]["steps"][1]["ok"]


def test_budget_gate_blocks_before_calling(store):
    service.set_budget(store, 1000)
    llm = FakeLlm(GOOD)
    with pytest.raises(service.VillageError, match="budget"):
        service.plan_day(store, llm)
    assert llm.calls == []


def test_failed_call_releases_lock_and_keeps_day(store):
    with pytest.raises(service.VillageError, match="could not meet"):
        service.plan_day(store, FakeLlm(None, fail=RuntimeError("503")))
    snap = service.snapshot(store)
    assert snap["world"]["current"]["source"] == "habit" and not snap["budget"]["planning"]


def test_unusable_reply_charges_but_does_not_advance(store):
    with pytest.raises(service.VillageError, match="not a usable plan"):
        service.plan_day(store, FakeLlm({"nope": 1}))
    snap = service.snapshot(store)
    assert snap["world"]["day"] == 1 and snap["budget"]["used_today"] == 1200


def test_clock_moving_during_a_call_does_not_waste_the_plan(store, clock):
    class Slow(FakeLlm):
        def complete_structured(self, **kw):
            clock.t += engine.DAY_SECONDS * 3
            return super().complete_structured(**kw)
    service.reset(store, 42)  # a world where Ash, the only one GOOD plans for, lives through these days
    out = service.plan_day(store, Slow(GOOD))
    assert out["world"]["council_ready"]
    clock.t += engine.DAY_SECONDS
    assert service.snapshot(store)["world"]["current"]["source"] == "model"


def test_reset_during_a_call_discards_the_plan(store):
    class Resetting(FakeLlm):
        def complete_structured(self, **kw):
            service.reset(store, 7)
            return super().complete_structured(**kw)
    with pytest.raises(service.VillageError, match="new village"):
        service.plan_day(store, Resetting(GOOD))


def test_absence_is_free_and_acknowledged(store, clock):
    service.snapshot(store)
    clock.t += engine.DAY_SECONDS * 10
    snap = service.snapshot(store)
    assert snap["world"]["away"]["days"] == 10 and snap["budget"]["calls_today"] == 0
    assert snap["budget"]["used_today"] == 0
    assert service.acknowledge_away(store)["world"]["away"] is None


def test_overlapping_requests_do_not_collide(store, clock):
    errors = []

    def hammer():
        try:
            for _ in range(25):
                service.snapshot(store)
                service.focus(store, "food")
        except Exception as exc:  # noqa: BLE001 - any failure here is the bug
            errors.append(exc)

    workers = [threading.Thread(target=hammer) for _ in range(8)]
    for t in workers:
        t.start()
    for t in workers:
        t.join()
    assert errors == []


def test_idle_reads_do_not_rewrite_the_save(store, clock):
    service.snapshot(store)
    before = store._db().total_changes
    clock.t += 5
    service.snapshot(store)
    assert store._db().total_changes == before


def test_habit_day_is_free(store):
    service.snapshot(store)
    out = service.habit_day(store)
    assert out["budget"]["calls_today"] == 0 and out["world"]["day"] == 2
    assert out["report"]["villagers"][0]["mode"] == "habit"
    assert out["world"]["current"]["day"] == 2


def test_one_council_per_dawn(store, clock):
    llm = FakeLlm(GOOD)
    service.plan_day(store, llm)
    with pytest.raises(service.VillageError, match="already decided"):
        service.plan_day(store, llm)
    assert len(llm.calls) == 1
    clock.t += engine.DAY_SECONDS
    service.plan_day(store, llm)
    assert len(llm.calls) == 2


def test_new_land_is_reported_so_the_page_can_reveal_it_as_they_walk():
    w = world()
    before = set().union(*(engine.seen_tiles(v) for v in w["villagers"]))
    plans = {"Ash": {"actions": [{"verb": "walk", "x": 7, "y": 12}]}}
    report = engine.run_day(w, plans, source="model")
    state = engine.public_state(w, 0.0)
    assert report["revealed"] and not before & set(report["revealed"])
    x, y = map(int, report["revealed"][0].split(","))
    assert state["land_view"]["seen"][f"{x >> 4},{y >> 4}"][(y & 15) * 16 + (x & 15)] == "1"
    assert state["vision"] == engine.VISION


def test_guidance_triggers_council_reason(store, clock):
    service.plan_day(store, FakeLlm(GOOD))
    clock.t += engine.DAY_SECONDS
    service.snapshot(store)
    snap = service.guide(store, "  Build   a lean-to  ")
    assert snap["world"]["guidance"] == "Build a lean-to"
    assert "you gave new guidance" in snap["world"]["council_reasons"]
    out = service.plan_day(store, FakeLlm(GOOD))
    assert "you gave new guidance" not in out["world"]["council_reasons"]
    assert engine.settlement({"built": [1, 2]}) == "Hamlet"


def test_no_llm_refuses(store):
    with pytest.raises(service.VillageError):
        service.plan_day(store, None)


def test_budget_validation(store):
    with pytest.raises(service.VillageError):
        service.set_budget(store, "lots")
    with pytest.raises(service.VillageError):
        service.set_budget(store, -1)


def fall(store):
    """Bring everyone to one bad night and let the day run."""
    service.snapshot(store)
    with store.tx() as db:
        w = store.load_world(db)
        for v in w["villagers"]:
            v["health"], v["inv"] = 1, {}
        w["store"] = {}
        store.save_world(db, w)
    with store.tx() as db:
        w = store.load_world(db)
        engine.run_day(w, {v["name"]: {"actions": []} for v in w["villagers"]}, source="model")
        store.save_world(db, w)
    return w


def test_the_last_day_can_still_be_paused_and_resumed(store):
    assert fall(store)["fallen"]
    assert service.speed(store, 0)["world"]["paused_at"] is not None
    assert service.speed(store, 4)["world"]["paused_at"] is None
    with pytest.raises(service.VillageError):
        service.focus(store, "food")


def test_a_fallen_village_keeps_its_land_on_screen(store):
    alive = service.snapshot(store)["world"]["land_view"]
    fall(store)
    gone = service.snapshot(store)["world"]
    assert not gone["villagers"] or all(v.get("dying") for v in gone["villagers"])
    assert set(alive["seen"]) <= set(gone["land_view"]["seen"])
    assert any("1" in bits for bits in gone["land_view"]["seen"].values())


def test_the_chronicle_tells_the_story_and_starts_over_with_the_village(store):
    first = service.snapshot(store)["chronicle"]
    assert first == [{"day": 1, "text": "Ash, Bryn and Coll made camp."}]
    fall(store)
    told = [n["text"] for n in service.snapshot(store)["chronicle"]]
    assert "Ash died of " in " ".join(told) and "The village has fallen." in told
    assert len(told) == len(set(told))
    assert len(service.reset(store)["chronicle"]) == 1


def test_the_chronicle_notes_a_first_building_once(store):
    service.snapshot(store)
    with store.tx() as db:
        w = store.load_world(db)
        w["built"] += [{"kind": "lean_to", "x": 12, "y": 12, "by": "Ash", "day": w["day"]},
                       {"kind": "lean_to", "x": 13, "y": 12, "by": "Bryn", "day": w["day"]}]
        engine.run_day(w, {}, source="habit")
        store.save_world(db, w)
    told = [n["text"] for n in service.snapshot(store)["chronicle"]]
    # Bryn may go on to build something else that day; what matters is one line for the first lean-to
    assert told.count("Ash built the first lean-to.") == 1 and "Bryn built the first lean-to." not in told


# ---------------------------------------------------------------- ways of life

from village import policy  # noqa: E402


def test_everyone_has_a_way_and_it_becomes_their_orders(store):
    snap = service.reset(store, 42)  # a world where they wake beside trees and bushes they can see
    ways = snap["world"]["ways"]
    assert set(ways) == {"Ash", "Bryn", "Coll"} and all(ways.values())
    assert all(goal in policy.GOALS for way in ways.values() for goal in way)
    with store.tx() as db:
        w = store.load_world(db)
    assert w["ways_day"] == w["day"]
    assert any(v["standing_orders"] for v in w["villagers"])
    assert all(a.get("verb") in engine.VERBS for v in w["villagers"] for a in v["standing_orders"])


def test_a_way_only_keeps_real_goals():
    assert policy.clean(["food", "fly", "food", 7, "explore"]) == ["food", "explore"]
    assert policy.clean("food") == [] and len(policy.clean(list(policy.GOALS))) == policy.MAX_GOALS


def test_a_council_can_change_a_way_and_it_is_kept(store, clock):
    service.reset(store, 42)
    plan = {"villagers": [{**GOOD["villagers"][0], "way": ["stone", "house", "nonsense", "explore"]}]}
    service.plan_day(store, FakeLlm(plan))
    assert service.snapshot(store)["world"]["ways"]["Ash"] == ["stone", "house", "explore"]
    with store.tx() as db:
        w = store.load_world(db)
    assert "way" not in w["pending_plans"]["Ash"]  # the engine is only ever handed actions
    clock.t += engine.DAY_SECONDS * 3
    assert service.snapshot(store)["world"]["ways"]["Ash"] == ["stone", "house", "explore"]


def test_ways_take_a_village_further_than_instincts_and_spend_nothing(store, monkeypatch):
    def live(days, with_ways):
        monkeypatch.setattr(engine._py, "BEFORE_DAY", policy.apply if with_ways else None)
        w = engine.new_world(7, 0.0)
        for _ in range(days):
            engine.run_day(w, {}, "habit", unwatched=True)
        return w
    plain, guided = live(40, False), live(40, True)
    assert len(guided["built"]) > len(plain["built"]) + 2
    assert service.snapshot(store)["budget"]["used_today"] == 0


def test_when_nothing_is_left_nearby_they_go_looking(store):
    w = engine.new_world(7, 0.0)
    for key in list(w["stocks"]):
        w["stocks"][key] = 0  # every bush and tree they know of is bare
    w["ways"] = {v["name"]: ["food"] for v in w["villagers"]}
    acts = policy.orders(w)
    assert all(a and a[0]["verb"] in ("walk", "look") for a in acts.values())
    assert all(a.get("verb") != "gather" for plan in acts.values() for a in plan)


def test_nobody_scouts_in_winter():
    w = engine.new_world(7, 0.0)
    w["day"] = engine.SEASON_DAYS * 3 + 1
    assert engine.season(w) == "winter"
    w["ways"] = {v["name"]: ["explore"] for v in w["villagers"]}
    assert all(acts == [] for acts in policy.orders(w).values())
