"""The two engines behind village.engine: the built-in Python rules and the optional Rust engine."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from village import bridge, engine  # noqa: E402

NOW = 1_700_000_000.0


@pytest.fixture
def python_rules():
    before = engine._BACKEND
    engine.use_backend("python")
    yield
    engine.use_backend(before)


def rust_available() -> bool:
    try:
        return bridge.find_binary() is not None and bool(bridge.call("describe_action", None, {"action": {"verb": "rest"}}))
    except bridge.EngineUnavailable:
        return False


def test_the_shipped_python_rules_are_the_tested_reference():
    shipped = (ROOT / "village" / "pyengine.py").read_bytes().replace(b"\r\n", b"\n")
    reference = (ROOT / "tests" / "reference_engine.py").read_bytes().replace(b"\r\n", b"\n")
    assert shipped == reference


def test_seen_land_packs_and_unpacks_to_the_same_tiles():
    tiles = {f"{x},{y}" for x, y in [(0, 0), (15, 15), (16, 0), (-1, -1), (-17, 33), (63, 64), (7, 200), (-300, 5)]}
    v = {"seen": dict.fromkeys(tiles, 1)}
    engine._pack_seen(v)
    assert all(isinstance(bits, str) and len(bits) == 64 for bits in v["seen"].values())
    assert engine.seen_tiles(v) == tiles
    engine._unpack_seen(v)
    assert set(v["seen"]) == tiles
    engine._pack_seen(v)
    assert engine.seen_tiles(v) == tiles


def test_a_village_lives_without_the_rust_engine(python_rules):
    w = engine.new_world(11, NOW)
    for _ in range(12):
        engine.run_day(w, {}, "habit", unwatched=True)
    assert w["day"] == 13
    assert all(isinstance(bits, str) for v in w["villagers"] for bits in v["seen"].values())
    json.dumps(w)  # a save is plain JSON
    state = engine.public_state(w, NOW + 5, "")
    assert state["day"] in (12, 13) and state["land_view"]["rev"]
    assert isinstance(engine.observe(w, w["villagers"][0]), str) if w["villagers"] else True


def test_a_missing_engine_falls_back_to_python(monkeypatch):
    monkeypatch.delenv("HERMES_VILLAGE_BACKEND", raising=False)
    monkeypatch.setattr(bridge, "find_binary", lambda: None)
    before = engine._BACKEND
    engine.use_backend(None)
    try:
        assert engine.backend() == "python"
        assert engine.new_world(3, NOW)["day"] == 1
    finally:
        engine.use_backend(before)


@pytest.mark.skipif(not rust_available(), reason="the Rust engine is not built")
def test_a_save_moves_between_engines_and_plays_out_the_same():
    before = engine._BACKEND
    try:
        engine.use_backend("python")
        w = engine.new_world(23, NOW)
        for _ in range(6):
            engine.run_day(w, {}, "habit", unwatched=True)
        saved = json.loads(json.dumps(w))
        a, b = copy.deepcopy(saved), copy.deepcopy(saved)
        for _ in range(6):
            engine.run_day(a, {}, "habit", unwatched=True)
        engine.use_backend("rust")
        for _ in range(6):
            engine.run_day(b, {}, "habit", unwatched=True)
        assert json.loads(json.dumps(a)) == json.loads(json.dumps(b))
    finally:
        engine.use_backend(before)
