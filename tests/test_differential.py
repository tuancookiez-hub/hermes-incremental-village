"""Differential tests: the frozen Python oracle (tests/reference_engine.py) against the Rust engine.

Both engines get the same inputs and must produce equal parsed JSON. Run from the repo root:

    python -m pytest tests/test_differential.py -q

Notes on how the two sides are kept comparable:

* ``CAMP`` is set on both modules together (``None`` finds a real camp from the seed).
* The Python oracle keeps live references between calls (a day's report shares its building dicts
  with the world), which a saved world never has. The service always saves and reloads between
  calls, so between days the oracle's world is passed through JSON, as it is in production.
  Everything inside a single call is compared before that round trip.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from village import bridge, engine as rust  # noqa: E402

_spec = importlib.util.spec_from_file_location("reference_engine", ROOT / "tests" / "reference_engine.py")
ref = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ref)

NOW = 1_700_000_000.0


def J(x):
    """What a saved-and-reloaded value looks like, with seen land spelled out tile by tile:
    the reference keeps "x,y" keys and Rust keeps a bitmap per chunk, and they must mean the same."""
    return _tiles(json.loads(json.dumps(x)))


def _tiles(x):
    if isinstance(x, list):
        return [_tiles(i) for i in x]
    if not isinstance(x, dict):
        return x
    out = {k: _tiles(v) for k, v in x.items()}
    if "skills" in out and "seen" in x:  # a villager
        out["seen"] = sorted(rust.seen_tiles(x))
    return out


def _rust_built() -> bool:
    try:
        return bridge.find_binary() is not None and bool(bridge.call("describe_action", None, {"action": {"verb": "rest"}}))
    except bridge.EngineUnavailable:
        return False


pytestmark = pytest.mark.skipif(not _rust_built(), reason="the Rust engine is not built; these tests compare it to the Python rules")


@pytest.fixture(autouse=True)
def _use_rust():
    before = rust._BACKEND
    rust.use_backend("rust")
    yield
    rust.use_backend(before)


@pytest.fixture(autouse=True)
def _camp(monkeypatch):
    monkeypatch.setattr(ref, "CAMP", None)
    monkeypatch.setattr(rust, "CAMP", None)


def set_camp(monkeypatch, camp):
    monkeypatch.setattr(ref, "CAMP", camp)
    monkeypatch.setattr(rust, "CAMP", camp)


def same(a, b, what=""):
    a, b = J(a), J(b)
    assert a == b, f"{what}: engines disagree\nreference: {json.dumps(a)[:1500]}\nrust:      {json.dumps(b)[:1500]}"


def worlds_equal(wr, wx, what=""):
    """Compare key by key so a failure names the key."""
    a, b = J(wr), J(wx)
    for k in sorted(set(a) | set(b)):
        assert a.get(k, "<absent>") == b.get(k, "<absent>"), f"{what}: world[{k!r}] differs\nreference: {json.dumps(a.get(k))[:1500]}\nrust:      {json.dumps(b.get(k))[:1500]}"


def pair(seed, now=NOW, perks=()):
    wr = ref.new_world(seed, now, perks)
    wx = rust.new_world(seed, now, perks)
    worlds_equal(wr, wx, f"new_world({seed})")
    return J(wr), wx


# ---------------------------------------------------------------- random numbers

RNG_SEEDS = [
    "", "a", "Ash", "5:1:herds", "12345:7:Ash:night", "9:3:Bryn:hunt:12,-4", "Zoë", "名前", "日本語のシード",
    "emoji 🌲🔥", "éèê", "x" * 200, "0:0:arrival", "-5:12:seeds", "\x00", "\x00\x00lead",
    "1000000:99:Coll:tools:2", "mixed ASCII und ümläute 123",
]


@pytest.mark.parametrize("seed", RNG_SEEDS)
def test_random_matches_cpython(seed):
    r = random.Random(seed)
    ops, want = [], []
    gen = random.Random(f"plan:{seed}")
    for _ in range(1500):
        kind = gen.choice(["random", "random", "bits", "randint", "choice"])
        if kind == "random":
            ops.append(["random"])
            want.append(r.random())
        elif kind == "bits":
            k = gen.randint(1, 64)
            ops.append(["bits", k])
            want.append(r.getrandbits(k))
        elif kind == "randint":
            a = gen.randint(-6, 6)
            b = a + gen.choice([0, 1, 2, 6, 7, 100, 1000, 65535])
            ops.append(["randint", a, b])
            want.append(r.randint(a, b))
        else:
            n = gen.choice([1, 2, 3, 4, 5, 6, 7, 8, 100, 256, 1000])
            ops.append(["choice", n])
            want.append(r.choice(range(n)))
    got = bridge.call("rng_probe", None, {"seed": seed, "ops": ops})["result"]
    assert got == want


def test_random_covers_many_engine_style_seeds():
    ops = [["random"], ["randint", 3, 5], ["choice", 4], ["randint", -3, 3]] * 50
    for seed in range(400):
        s = f"{seed * 7919}:{seed % 90}:{['Ash', 'Bryn', 'Coll', 'Dara'][seed % 4]}:night"
        r = random.Random(s)
        want = []
        for op in ops:
            want.append(r.random() if op[0] == "random" else r.randint(op[1], op[2]) if op[0] == "randint" else r.choice(range(op[1])))
        assert bridge.call("rng_probe", None, {"seed": s, "ops": ops})["result"] == want, s


# ---------------------------------------------------------------- land

def test_find_camp_for_200_seeds():
    for seed in range(1, 201):
        assert tuple(ref._find_camp(seed)) == tuple(rust._find_camp(seed)), seed


def test_land_chunks_everywhere():
    coords = [(0, 0), (-1, -1), (1, -1), (-3, 4), (5, -9), (-100, 100), (1000, -1000), (-123456, 7890),
              (10 ** 6, 10 ** 6), (-10 ** 6, 10 ** 6), (10 ** 9, -10 ** 9), (-(2 ** 33), 2 ** 33), (10 ** 11, 10 ** 11),
              (-(10 ** 11), -(10 ** 11)), (62500000000, 62500000000)]
    for seed in (0, 1, 5, 9, 42, 31337, 999999, 2 ** 31 - 1, 10 ** 12):
        for cx, cy in coords:
            assert ref._land(seed, cx, cy) == rust._land(seed, cx, cy), (seed, cx, cy)
    for seed in (3, 77):
        for cx in range(-6, 6):
            for cy in range(-6, 6):
                assert ref._land(seed, cx, cy) == rust._land(seed, cx, cy)


def test_land_char_at_negative_and_huge_tiles():
    for seed in (2, 11, 10 ** 6):
        for x, y in [(-1, -1), (-16, -16), (-17, 0), (0, -17), (15, 15), (16, 16), (-10 ** 12, 10 ** 12), (10 ** 12, -10 ** 12)]:
            assert ref._land_char(seed, x, y) == rust._land_char(seed, x, y)


# ---------------------------------------------------------------- free days

def test_forty_seeds_sixty_free_days_each():
    for seed in range(1, 41):
        wr, wx = pair(seed)
        for day in range(60):
            rr = ref.run_day(wr, {}, source="habit")
            rx = rust.run_day(wx, {}, source="habit")
            same(rr, rx, f"seed {seed} day {day + 1} report")
            worlds_equal(wr, wx, f"seed {seed} day {day + 1}")
            now = NOW + 7 + day
            same(ref.public_state(wr, now, ""), rust.public_state(wx, now, ""), f"seed {seed} day {day + 1} public_state")
            if day % 10 == 9:
                same(ref.public_state(wr, now, ref.land_rev(wr)), rust.public_state(wx, now, rust.land_rev(wx)), "public_state (page has the land)")
            wr = J(wr)
            if wx["fallen"]:
                break


# ---------------------------------------------------------------- scripted model plans

BUILDINGS = list(ref.BUILDINGS) + ["castle", "", "Hut", None, 7]
ITEMS = list(ref.ITEMS) + ["gold", "", None, 3, "Wood"]
GARBAGE = [None, "walk", 5, 2.5, [], "", ["walk"], {"no": "verb"}, {"verb": None}, {"verb": "fly"}, {"verb": 12},
           {"verb": ["walk"]}, {"verb": "WALK"}, {"verb": "walk"}, {"verb": "walk", "x": "3", "y": 4},
           {"verb": "walk", "x": 2.0, "y": 1}, {"verb": "walk", "x": 10 ** 12, "y": 0}, {"verb": "gather"},
           {"verb": "build"}, {"verb": "talk"}, {"verb": "talk", "target": 5, "text": 7},
           {"verb": "trade", "target": "Ash"}, {"verb": "trade", "target": "Bryn", "give": [], "get": 4},
           {"verb": "deposit", "item": "wood", "n": "many"}, {"verb": "take", "item": "food", "n": -3},
           {"verb": "take", "item": "food", "n": 0}, {"verb": "hunt"}, {"verb": "hunt", "item": "dragon"},
           {"verb": "experiment"}, {"verb": "experiment", "item": 4}, {"verb": "teach", "target": "Coll"},
           {"verb": "look", "extra": 1}, {"verb": "rest", "n": 2}]


def smart_action(rng, w, v):
    """An action that has a fair chance of working: trades of goods both sides hold, teaching a known skill,
    trying a planted idea, building what the villager can afford."""
    others = [o for o in w["villagers"] if o is not v]
    kind = rng.choice(["trade", "teach", "experiment", "build", "talk", "hunt", "deposit", "take"])
    if kind == "trade" and others:
        o = rng.choice(others)
        give = {k: 1 for k, n in v["inv"].items() if n > 0}
        get = {k: 1 for k, n in o["inv"].items() if n > 0}
        return {"verb": "trade", "target": o["name"], "give": dict(list(give.items())[:2]), "get": dict(list(get.items())[:2])}
    if kind == "teach" and others and v["skills"]:
        return {"verb": "teach", "target": rng.choice(others)["name"], "item": rng.choice(v["skills"])}
    if kind == "experiment":
        waiting = [i for i in w["guide"]["planted"] if i not in w["guide"]["known"]]
        return {"verb": "experiment", "item": rng.choice(waiting or list(ref.IDEAS))}
    if kind == "build":
        return {"verb": "build", "item": rng.choice(["lean_to", "depot", "field", "woodlot", "hut", "fire_pit", "drying_rack", "storehouse", "stone_house"])}
    if kind == "hunt":
        return {"verb": "hunt", "item": rng.choice(["deer", "boar"])}
    if kind == "talk" and others:
        return {"verb": "talk", "target": rng.choice(others)["name"], "text": rng.choice(["follow me", "berries north", "  hello  "])}
    return {"verb": kind, "item": rng.choice(["wood", "food", "stone"])}


def random_action(rng, w, v):
    if rng.random() < 0.3:
        return smart_action(rng, w, v)
    verb = rng.choice(list(ref.VERBS) + ["garbage"] * 2 + ["walk", "gather", "gather", "build"])
    others = [o["name"] for o in w["villagers"]] + ["Nobody", "ash", "BRYN", 3, None]
    seen = sorted(rust.seen_tiles(v))
    if verb == "garbage":
        return copy.deepcopy(rng.choice(GARBAGE))
    if verb == "walk":
        if seen and rng.random() < 0.8:
            x, y = map(int, rng.choice(seen).split(","))
        else:
            x, y = v["x"] + rng.randint(-30, 30), v["y"] + rng.randint(-30, 30)
        if rng.random() < 0.5:
            x, y = v["x"] + rng.randint(-5, 5), v["y"] + rng.randint(-5, 5)
        return {"verb": "walk", "x": x, "y": y}
    if verb in ("gather", "deposit", "take", "build", "hunt", "experiment", "teach"):
        pool = {"build": BUILDINGS, "hunt": ["deer", "boar", "wolf", None, "Deer"], "experiment": list(ref.IDEAS) + ["fire", None],
                "teach": list(ref.SKILLS) + ["magic", None]}.get(verb, ITEMS)
        act = {"verb": verb, "item": rng.choice(pool)}
        if verb in ("deposit", "take") and rng.random() < 0.6:
            act["n"] = rng.choice([1, 2, 3, 5, 100, 0, -1, "2", 1.5])
        if verb == "teach":
            act["target"] = rng.choice(others)
        return act
    if verb == "talk":
        return {"verb": "talk", "target": rng.choice(others),
                "text": rng.choice(["hello", "  padded  ", "", "   ", "x" * 120, "café ☕", "line\nbreak", "tab\t", " nbsp ", "'quote' \"dq\"", 42, None])}
    if verb == "trade":
        def goods():
            return rng.choice([None, {}, {"wood": 1}, {"food": 2}, {"wood": 2, "stone": 1}, {"gold": 1}, {"wood": 0}, {"wood": -1},
                               {"food": 1.5}, {"stone": 1, "food": 1, "water": 1}, "wood", {"meat": 1, "grain": 1}])
        return {"verb": "trade", "target": rng.choice(others), "give": goods(), "get": goods()}
    return {"verb": verb}


def random_plans(rng, w):
    plans = {}
    for v in w["villagers"]:
        if rng.random() < 0.15:
            continue  # this villager follows habit
        plan = {"actions": [random_action(rng, w, v) for _ in range(rng.randint(0, 8))]}
        if rng.random() < 0.8:
            plan["thought"] = rng.choice(["thinking", "x" * 300, "", None, 42, "ünïcode ✓"])
        if rng.random() < 0.7:
            plan["remember"] = rng.choice(["note", "  spaced out  ", "y" * 200, "", "   ", 3, None])
        if rng.random() < 0.4:
            plan["standing_orders"] = [random_action(rng, w, v) for _ in range(rng.randint(0, 5))] + rng.choice([[], ["junk"], [None]])
        if rng.random() < 0.05:
            plan["actions"] = rng.choice(["abc", {"a": 1}, None, 0, ""])
        plans[v["name"]] = plan
    if rng.random() < 0.1:
        plans["Ghost"] = {"actions": [{"verb": "rest"}]}
    return plans


def enrich(w, rng):
    """Give a world something of everything, so every rule has a chance to fire."""
    w["guide"]["insight"] = 200
    w["guide"]["trust"] = rng.choice([20, 45, 75])
    for v in w["villagers"]:
        v["skills"] = list(dict.fromkeys(v["skills"] + rng.sample(list(ref.SKILLS), rng.randint(0, 4))))
        v["inv"] = {k: rng.randint(0, 6) for k in rng.sample(list(ref.ITEMS), rng.randint(0, 6))}
        v["inv"].update(food=rng.randint(2, 6), wood=rng.randint(2, 6), stone=rng.randint(1, 4))
    w["store"] = {"wood": 12, "stone": 6, "food": 8, "meat": 3}


@pytest.mark.parametrize("camp_seed", [None, 3, 17, 23])
def test_scripted_model_plans_mixing_every_verb(monkeypatch, camp_seed):
    if camp_seed is None:
        set_camp(monkeypatch, (12, 12))
    for seed in range(1, 9):
        rng = random.Random(f"plans:{camp_seed}:{seed}")
        wr, wx = pair(seed + (camp_seed or 0), perks=rng.choice([(), ("full_packs", "old_songs"), ("seed_memory", "first_trust")]))
        if rng.random() < 0.7:
            enrich(wr, rng)
            wx = rust.new_world(wr["seed"], NOW, ())  # same start, then adopt the enriched state in place
            wx.clear()
            wx.update(copy.deepcopy(wr))
        for ideas in rng.sample(list(ref.IDEAS), rng.randint(0, 3)):
            same(ref.plant_idea(wr, ideas), rust.plant_idea(wx, ideas), "plant_idea")
        for day in range(25):
            if rng.random() < 0.2 and wr["villagers"]:
                focus = rng.choice([None, "food", "shelter", "explore", "learn", "bogus"])
                same(ref.set_focus(wr, focus), rust.set_focus(wx, focus), "set_focus")
            plans = random_plans(rng, wr) if rng.random() < 0.85 else {}
            source = rng.choice(["model", "model", "habit", "council"])
            unwatched = rng.random() < 0.2
            rr = ref.run_day(wr, copy.deepcopy(plans), source, unwatched)
            rx = rust.run_day(wx, copy.deepcopy(plans), source, unwatched)
            same(rr, rx, f"seed {seed} day {day + 1} report")
            worlds_equal(wr, wx, f"plans seed {seed} day {day + 1}")
            now = NOW + day
            same(ref.public_state(wr, now, ""), rust.public_state(wx, now, ""), "public_state")
            wr = J(wr)
            if rng.random() < 0.15:
                wr["pending_plans"] = random_plans(rng, wr)
                wx["pending_plans"] = copy.deepcopy(wr["pending_plans"])
            if rng.random() < 0.1:
                upgrade = rng.choice(list(ref.UPGRADES) + ["bogus"])
                same(ref.buy_upgrade(wr, upgrade), rust.buy_upgrade(wx, upgrade), "buy_upgrade")
                worlds_equal(wr, wx, "after buy_upgrade")
            if rng.random() < 0.1:
                idea = rng.choice(list(ref.IDEAS) + ["bogus"])
                same(ref.plant_idea(wr, idea), rust.plant_idea(wx, idea), "plant_idea")
            if wx["fallen"]:
                break


# ---------------------------------------------------------------- the clock

class Clock:
    def __init__(self, t):
        self.t = t


def test_advance_catch_up_and_speed_with_fake_clocks():
    for seed in range(1, 9):
        rng = random.Random(f"clock:{seed}")
        t = 5000.0 if seed % 2 else 5000  # alternate float and int clocks
        wr, wx = pair(seed, now=t)
        for step in range(40):
            op = rng.choice(["advance", "advance", "advance", "speed", "restart", "gap", "read"])
            if op == "advance" or op == "read":
                t += rng.choice([0, 1, 7.5, 30, 60, 119, 120, 121, 240, 361, 725])
            elif op == "gap":
                t += rng.choice([2000, 5000, 100000])
            elif op == "speed":
                speed = rng.choice([0, 1, 2, 4, 8, 16, 3, -1, 2.0, 0.0, "4", None, True, 1.5])
                a = ref.set_speed(wr, speed, t)
                b = rust.set_speed(wx, speed, t)
                same(a, b, f"set_speed({speed!r})")
            elif op == "restart":
                ref.restart_day(wr, t)
                rust.restart_day(wx, t)
            if op in ("advance", "gap"):
                a = ref.advance(wr, t)
                b = rust.advance(wx, t)
                same(a, b, f"seed {seed} step {step} advance away")
            worlds_equal(wr, wx, f"clock seed {seed} step {step} ({op})")
            if step % 4 == 0:
                same(ref.public_state(wr, t, "x"), rust.public_state(wx, t, "x"), "public_state during clock play")
            wr = J(wr)
            if wx["fallen"]:
                break


def test_advance_a_world_that_was_never_started_and_a_paused_one():
    wr, wx = pair(4, now=100.0)
    for t in (100.0, 100.0, 5000.0):
        same(ref.advance(wr, t), rust.advance(wx, t), "advance")
        worlds_equal(wr, wx, "advance")
    ref.set_speed(wr, 0, 5100.0)
    rust.set_speed(wx, 0, 5100.0)
    for t in (5200.0, 9000.0, 9031.0):
        same(ref.advance(wr, t), rust.advance(wx, t), "paused advance")
        worlds_equal(wr, wx, "paused advance")


# ---------------------------------------------------------------- views

def mid_game(seed, days, rng, perks=("full_packs", "first_trust", "old_songs", "seed_memory")):
    wr, wx = pair(seed, perks=perks)
    for day in range(days):
        if day == 3:
            for upgrade in ref.UPGRADES:
                wr["guide"]["insight"] = 50
                wx["guide"]["insight"] = 50
                same(ref.buy_upgrade(wr, upgrade), rust.buy_upgrade(wx, upgrade), "buy_upgrade")
            worlds_equal(wr, wx, "after upgrades")
        if day == 5:
            for idea in ref.IDEAS:
                wr["guide"]["insight"] = 99
                wx["guide"]["insight"] = 99
                same(ref.plant_idea(wr, idea), rust.plant_idea(wx, idea), f"plant {idea}")
            same(ref.set_focus(wr, "learn"), rust.set_focus(wx, "learn"), "focus")
        plans = random_plans(rng, wr) if day % 2 else {}
        rr = ref.run_day(wr, copy.deepcopy(plans), "model" if plans else "habit")
        rx = rust.run_day(wx, copy.deepcopy(plans), "model" if plans else "habit")
        same(rr, rx, f"mid_game day {day}")
        wr = J(wr)
        worlds_equal(wr, wx, f"mid_game day {day}")
    return wr, wx


def rich_world(seed):
    """A mid-game world with every building kind, a dark fire, depots, woodlots, fields, dead villagers."""
    rng = random.Random(seed)
    wr, wx = mid_game(seed, 14, rng)
    cx, cy = wr["camp"]
    kinds = list(ref.BUILDINGS)
    for i, kind in enumerate(kinds):
        b = {"kind": kind, "x": cx - 4 + i, "y": cy + 2, "by": "Ash", "day": 3}
        if kind == "fire_pit" and i % 2 == 0:
            b["lit"] = False
        wr["built"].append(b)
        if kind in ("field", "woodlot"):
            wr["stocks"][f"{b['x']},{b['y']}"] = rng.randint(0, 5)
            wr["changed"][f"{b['x']},{b['y']}"] = "."
            wr["soil"][f"{b['x']},{b['y']}"] = rng.choice([1.0, 0.7, 0.3])
        if kind == "woodlot":
            wr["woodlots"].append(f"{b['x']},{b['y']}")
        if kind == "depot":
            wr["depots"].append({"x": b["x"], "y": b["y"], "inv": {"wood": 4, "food": 3, "water": 1}})
    wr["dead"].append({"name": "Old", "trait": "gone", "x": 1, "y": 2, "energy": 0, "health": 0, "hungry": 3, "skills": [], "inv": {},
                       "memory": [], "heard": [], "feedback": [], "standing_orders": [], "thought": "", "cause": "hunger", "day": wr["day"] - 1})
    wr["herds"].append({"kind": "boar", "x": cx + 3, "y": cy + 3, "count": 2})
    wr["guide"]["known"] = ["coppicing", "sowing", "pottery", "masonry", "copper"]
    wr["guide"]["planted"] = ["coppicing", "sowing", "pottery", "masonry", "copper"]
    wx.clear()
    wx.update(copy.deepcopy(wr))
    return wr, wx


def test_land_view_and_rev_for_mid_game_worlds():
    for seed in (2, 7, 19):
        wr, wx = rich_world(seed)
        same(ref.land_view(wr), rust.land_view(wx), f"land_view {seed}")
        same(ref.land_rev(wr), rust.land_rev(wx), "land_rev")
        same(ref.resources(wr), rust.resources(wx), "resources")
    wr, wx = pair(5)
    same(ref.land_view(wr), rust.land_view(wx), "land_view of a new world")


def test_every_public_function_on_a_mid_game_world():
    for seed in (4, 11):
        wr, wx = rich_world(seed)
        # queries
        for fn in ("season", "era", "max_health", "land_rev", "resources", "land_view", "legacy_earned", "needs_council"):
            same(getattr(ref, fn)(wr), getattr(rust, fn)(wx), fn)
        same(ref.needs_council(wr, ref.resources(wr)), rust.needs_council(wx, rust.resources(wx)), "needs_council(held)")
        held = ref.resources(wr)
        held["wild"]["wood"] = 99
        same(ref.needs_council(wr, held), rust.needs_council(wx, copy.deepcopy(held)), "needs_council(held=99)")
        assert ref.settlement(wr) == rust.settlement(wx)
        for have in ("", "stale", ref.land_rev(wr)):
            same(ref.public_state(wr, NOW + 5, have), rust.public_state(wx, NOW + 5, have), "public_state")
        for vr, vx in zip(wr["villagers"], wx["villagers"]):
            same(ref.observe(wr, vr), rust.observe(wx, vx), "observe")
            assert ref.observe(wr, vr) == rust.observe(wx, vx)
            same(ref.instinct_actions(wr, vr), rust.instinct_actions(wx, vx), "instinct_actions")
            same(ref._scout(wr, vr), rust._scout(wx, vx), "_scout")
            same(ref._home(wr, vr), rust._home(wx, vx), "_home")
            for item in ref.ITEMS + ("nonsense",):
                assert ref._room(wr, vr, item) == rust._room(wx, vx, item)
            for _ in range(15):
                x = vr["x"] + random.Random(seed).randint(-12, 12)
                y = vr["y"] + random.Random(seed + 1).randint(-12, 12)
                same(ref.find_path(wr, vr, x, y), rust.find_path(wx, vx, x, y), "find_path")
        for idea in list(ref.IDEAS) + ["x"]:
            assert ref._knows(wr, idea) == rust._knows(wx, idea)
        for x in range(wr["camp"][0] - 8, wr["camp"][0] + 9, 2):
            for y in range(wr["camp"][1] - 8, wr["camp"][1] + 9, 2):
                assert ref.tile(wr, x, y) == rust.tile(wx, x, y)
                assert ref._char(wr, x, y) == rust._char(wx, x, y)
                assert ref._base_char(wr, x, y) == rust._base_char(wx, x, y)
                assert ref._lit_fire_near(wr, x, y) == rust._lit_fire_near(wx, x, y)
                for kind in ("water", "forest", "rock"):
                    assert ref._near_tile(wr, x, y, kind, 3) == rust._near_tile(wx, x, y, kind, 3)
        for act in [{"verb": "walk", "x": 3, "y": 4}, {"verb": "talk", "target": "Bryn", "text": "ünï"}, {"verb": "trade", "target": 3},
                    {"verb": "teach", "target": "T", "item": None}, {"verb": "gather", "item": "food"}, {"verb": "deposit"}, {"verb": "x"}, "act", None,
                    {"verb": "build", "item": "hut"}, {"verb": "look"}]:
            same(ref.describe_action(act) if isinstance(act, dict) else "-", rust.describe_action(act) if isinstance(act, dict) else "-", "describe_action")
        # mutators, each on a private copy
        def fresh():
            a = copy.deepcopy(wr)
            b = copy.deepcopy(wr)
            return a, b
        for name in ("_grow", "_seed_forest", "_herds_live"):
            a, b = fresh()
            for day in range(1, 8):
                a["day"] = b["day"] = day * 5 + 1
                getattr(ref, name)(a)
                getattr(rust, name)(b)
                worlds_equal(a, b, f"{name} day {day * 5 + 1}")
        a, b = fresh()
        for day in range(1, 40):
            a["day"] = b["day"] = day
            ea, eb = [], []
            ref._arrival(a, ea)
            rust._arrival(b, eb)
            same(ea, eb, "_arrival events")
            worlds_equal(a, b, f"_arrival day {day}")
        a, b = fresh()
        for cx, cy in [(5, 5), (-4, 9), (0, 0), (100, -100)]:
            ref._open_chunk(a, cx, cy)
            rust._open_chunk(b, cx, cy)
            worlds_equal(a, b, "_open_chunk")
        a, b = fresh()
        for va, vb in zip(a["villagers"], b["villagers"]):
            va["x"] = vb["x"] = va["x"] + 20
            assert ref._reveal(a, va) == rust._reveal(b, vb)
            worlds_equal(a, b, "_reveal")
        a, b = fresh()
        for upgrade in list(ref.UPGRADES) + ["bogus"]:
            a["guide"]["insight"] = b["guide"]["insight"] = 3
            same(ref.buy_upgrade(a, upgrade), rust.buy_upgrade(b, upgrade), "buy_upgrade")
            a["guide"]["insight"] = b["guide"]["insight"] = 30
            same(ref.buy_upgrade(a, upgrade), rust.buy_upgrade(b, upgrade), "buy_upgrade")
        worlds_equal(a, b, "upgrades")
        a, b = fresh()
        for idea in list(ref.IDEAS) + ["bogus"]:
            for insight in (0, 30):
                a["guide"]["insight"] = b["guide"]["insight"] = insight
                same(ref.plant_idea(a, idea), rust.plant_idea(b, idea), f"plant_idea {idea}")
        for focus in [None, "food", "shelter", "explore", "learn", "nonsense", ""]:
            same(ref.set_focus(a, focus), rust.set_focus(b, focus), f"set_focus {focus!r}")
            worlds_equal(a, b, "set_focus")
        for t in (0, 5):
            for speed in (0, 2, 99, 16, 1):
                same(ref.set_speed(a, speed, NOW + t), rust.set_speed(b, speed, NOW + t), "set_speed")
                worlds_equal(a, b, "set_speed")
        ref.restart_day(a, NOW + 9)
        rust.restart_day(b, NOW + 9)
        worlds_equal(a, b, "restart_day")


def test_execute_every_verb_on_a_rich_world():
    rng = random.Random(99)
    for seed in (4, 11, 21):
        base_r, _ = rich_world(seed)
        for trial in range(120):
            a, b = copy.deepcopy(base_r), copy.deepcopy(base_r)
            i = rng.randrange(len(a["villagers"]))
            va, vb = a["villagers"][i], b["villagers"][i]
            if rng.random() < 0.3:
                energy = rng.choice([0, 1, 5])
                va["energy"] = vb["energy"] = energy
            if rng.random() < 0.3:  # stand beside something worth using
                spot = rng.choice(a["built"] + a["depots"] + [{"x": a["store_at"][0], "y": a["store_at"][1]}])
                va["x"] = vb["x"] = spot["x"] + rng.randint(-1, 1)
                va["y"] = vb["y"] = spot["y"] + rng.randint(-1, 1)
                ref._reveal(a, va)
                rust._reveal(b, vb)
            act = random_action(rng, a, va)
            slots = rng.choice([8, 8, 4, 3, 2, 1])
            fa, fb = {}, {}
            ra = ref.execute(a, va, copy.deepcopy(act), slots, fa)
            rb = rust.execute(b, vb, copy.deepcopy(act), slots, fb)
            same(list(ra), list(rb), f"execute {act!r}")
            same(fa, fb, f"fx of {act!r}")
            worlds_equal(a, b, f"execute {act!r}")


# ---------------------------------------------------------------- the bridge keeps references live

def test_rust_updates_the_callers_dicts_in_place():
    set_camp = None  # noqa: F841 - the autouse fixture already cleared CAMP; use a real camp
    w = rust.new_world(8, NOW, ())
    ash = w["villagers"][0]
    inv = ash["inv"]
    villagers = w["villagers"]
    stocks = w["stocks"]
    rust.run_day(w, {}, source="habit")
    assert w["villagers"] is villagers and w["villagers"][0] is ash and ash["inv"] is inv and w["stocks"] is stocks
    assert w["day"] == 2 and w["log"]


# ---------------------------------------------------------------- rules, formatting, save format

def test_rules_json_equals_every_reference_constant():
    for name, value in vars(ref).items():
        if name.startswith("_") or not name.isupper() or name in ("CAMP", "FULL_STOCK_CHAR"):
            continue
        assert J(value) == rust._R[name], name
        assert J(getattr(rust, name)) == J(value), name
    assert set(rust._R) <= {n for n in vars(ref) if n.isupper() and not n.startswith("_")}


@pytest.mark.parametrize("born", [1.0, 0.1 + 0.2, 1234567.891, 1e16, 1.5e-5, 123456789012345678.0, 0, 7, 1_700_000_000, 1_700_000_000.123456, 5e-324])
def test_land_rev_prints_the_start_time_like_python(born):
    wr, wx = ref.new_world(6, born, ()), rust.new_world(6, born, ())
    assert ref.land_rev(wr) == rust.land_rev(wx)
    assert ref.public_state(wr, born)["land_id"] == rust.public_state(wx, born)["land_id"]


def test_unknown_keys_survive_a_round_trip():
    wr, wx = pair(3)
    for w in (wr, wx):
        w["mystery"] = {"a": [1, 2.5, None], "b": "ü"}
        w["villagers"][0]["mood"] = "calm"
        w["guide"]["secret"] = [1]
        w["built"].append({"kind": "lean_to", "x": 1, "y": 1, "note": "hand placed"})
        w["herds"].append({"kind": "deer", "x": 40, "y": 40, "count": 3, "tag": "x"})
        w["depots"].append({"x": 3, "y": 3, "inv": {}, "label": "d"})
    for _ in range(4):
        same(ref.run_day(wr, {}, "habit"), rust.run_day(wx, {}, "habit"), "report")
        worlds_equal(wr, wx, "unknown keys")
        wr = J(wr)
    assert wx["mystery"] == {"a": [1, 2.5, None], "b": "ü"} and wx["villagers"][0]["mood"] == "calm" and wx["guide"]["secret"] == [1]


def test_a_world_saved_by_rust_runs_on_python_and_back():
    wx = rust.new_world(12, NOW, ("full_packs",))
    for _ in range(9):
        rust.run_day(wx, {}, "habit")
    saved = J(wx)
    wr = copy.deepcopy(saved)
    for _ in range(6):
        same(ref.run_day(wr, {}, "habit"), rust.run_day(wx, {}, "habit"), "continuing a Rust-saved world on Python")
        wr = J(wr)
        worlds_equal(wr, wx, "cross load")
    assert saved["schema"] == ref.SCHEMA_VERSION == 10 and set(saved) <= set(wx) | {"_dirty", "_events"}


def test_a_list_of_seen_tiles_still_reads():
    wr, wx = pair(8)
    for w in (wr, wx):
        w["villagers"][0]["seen"] = ["11,12", "13,12"]
    same(ref.find_path(wr, wr["villagers"][0], 13, 12), rust.find_path(wx, wx["villagers"][0], 13, 12), "find_path")
    same(ref.execute(wr, wr["villagers"][0], {"verb": "walk", "x": 13, "y": 12}, 8), rust.execute(wx, wx["villagers"][0], {"verb": "walk", "x": 13, "y": 12}, 8), "walk")
    worlds_equal(wr, wx, "list seen")
    same(ref.public_state(wr, NOW), rust.public_state(wx, NOW), "public_state with list seen")
    ref._reveal(wr, wr["villagers"][0])
    rust._reveal(wx, wx["villagers"][0])
    worlds_equal(wr, wx, "after a look")
    assert isinstance(wx["villagers"][0]["seen"], dict)


def test_the_save_holds_chunk_maps_and_old_saves_still_load():
    wr, wx = pair(9)
    assert all(len(bits) == 64 for v in wx["villagers"] for bits in v["seen"].values())
    old = J(wr)
    for v in old["villagers"]:  # how every save before the bitmaps looked
        v["seen"] = {tile: 1 for tile in v["seen"]}
    rust._reveal(old, old["villagers"][0])
    worlds_equal(wr, old, "old save")
    assert all(len(bits) == 64 for bits in old["villagers"][1]["seen"].values())


def test_the_engine_plugin_and_crate_agree_on_the_version():
    import re
    plugin = re.search(r"^version: (\S+)", (ROOT / "plugin.yaml").read_text(encoding="utf-8"), re.M).group(1)
    crate = re.search(r'^version = "(\S+)"', (ROOT / "engine-rs/Cargo.toml").read_text(encoding="utf-8"), re.M).group(1)
    assert plugin == crate == bridge.ENGINE_VERSION
    assert json.loads((ROOT / "dashboard/manifest.json").read_text(encoding="utf-8"))["version"] == plugin


# ---------------------------------------------------------------- the process

def test_a_failing_request_is_an_error_not_a_crash_and_the_process_carries_on():
    wx = rust.new_world(3, NOW, ())
    wx["guide"]["planted"] = ["no_such_idea"]  # observe() cannot describe it: the engine panics inside
    with pytest.raises(bridge.EngineError):
        rust.observe(wx, wx["villagers"][0])
    with pytest.raises(bridge.EngineError):
        bridge.call("no_such_op", wx, {})
    wx["guide"]["planted"] = []
    assert rust.observe(wx, wx["villagers"][0]).startswith("## Ash")


def test_a_dead_engine_process_is_restarted_once():
    wx = rust.new_world(3, NOW, ())
    first = bridge._bridge._proc
    assert first is not None
    first.kill()
    first.wait()
    assert rust.era(wx) == "Stone Age"
    assert bridge._bridge._proc is not first and bridge._bridge._proc.poll() is None


def test_missing_or_stale_engine_raises_a_plain_sentence_when_rust_is_required(monkeypatch):
    bridge.close()
    monkeypatch.setenv("HERMES_VILLAGE_BACKEND", "rust")
    monkeypatch.setattr(bridge, "find_binary", lambda: None)
    with pytest.raises(bridge.EngineUnavailable, match="cargo install --path engine-rs"):
        rust.era({"guide": {"known": []}})
    monkeypatch.undo()
    bridge.close()
    monkeypatch.setenv("HERMES_VILLAGE_BACKEND", "rust")
    monkeypatch.setattr(bridge, "rules_sha256", lambda: "0" * 64)
    with pytest.raises(bridge.EngineUnavailable, match="out of date.*cargo install --path engine-rs"):
        rust.new_world(1, NOW, ())
    monkeypatch.undo()
    bridge.close()
    assert rust.new_world(1, NOW, ())["seed"] == 1


def test_an_engine_that_goes_away_hands_over_to_the_python_rules(monkeypatch):
    monkeypatch.delenv("HERMES_VILLAGE_BACKEND", raising=False)
    w = rust.new_world(4, NOW, ())
    rust.run_day(w, {}, "habit", unwatched=True)
    bridge.close()
    monkeypatch.setattr(bridge, "find_binary", lambda: None)
    rust.run_day(w, {}, "habit", unwatched=True)  # the same save carries on
    assert w["day"] == 3 and rust.backend() == "python"
    monkeypatch.undo()
    bridge.close()


def test_importing_the_engine_and_planner_never_starts_the_binary():
    import subprocess
    code = f"import sys; sys.path.insert(0, {str(ROOT)!r}); import village.engine, village.planner, village.bridge as b; print(b._bridge._proc)"
    out = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "None"
