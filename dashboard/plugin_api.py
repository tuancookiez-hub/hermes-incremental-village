"""Hermes Incremental Village backend routes for the Desktop page, mounted at /api/plugins/hermes-village/.

These routes never call a model. Planning a day goes through the /village plan
command (agent half), which owns ctx.llm and the budget gate.
"""
from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter()


def _load_core():
    """Import the plugin's own ``village`` package (it sits beside ``dashboard/``)
    under a private module name, since this file is imported standalone."""
    name = "hermes_village_dashboard_core"
    if name in sys.modules:
        return sys.modules[name]
    pkg_dir = Path(__file__).resolve().parent.parent / "village"
    spec = importlib.util.spec_from_file_location(name, pkg_dir / "__init__.py",
                                                  submodule_search_locations=[str(pkg_dir)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_load_core()
from hermes_village_dashboard_core import service  # noqa: E402
from hermes_village_dashboard_core.store import Store  # noqa: E402

_store = Store()


async def _run(fn, *args) -> Any:
    try:
        return await asyncio.to_thread(fn, _store, *args)
    except service.VillageError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except service.engine.EngineUnavailable as exc:  # says what to install or rebuild; the page shows it
        raise HTTPException(status_code=503, detail=str(exc)) from None


@router.get("/state")
async def state(have: str = "") -> dict:
    return await _run(service.snapshot, have[:64])


@router.get("/engine")
async def engine_status() -> dict:
    return await _run(service.engine_status)


@router.post("/engine")
async def install_engine(body: dict | None = None) -> dict:
    """Downloads the pinned engine. Only the player's own button or /village setup comes here."""
    return await _run(service.install_engine)


@router.post("/guide")
async def guide(body: dict) -> dict:
    return await _run(service.guide, str((body or {}).get("text", "")))


@router.post("/habit")
async def habit(body: dict | None = None) -> dict:
    return await _run(service.habit_day)


@router.post("/budget")
async def budget(body: dict) -> dict:
    return await _run(service.set_budget, (body or {}).get("daily_tokens"))


@router.post("/ack")
async def ack(body: dict | None = None) -> dict:
    return await _run(service.acknowledge_away)


@router.post("/plant")
async def plant(body: dict) -> dict:
    return await _run(service.plant, (body or {}).get("idea"))


@router.post("/upgrade")
async def upgrade(body: dict) -> dict:
    return await _run(service.upgrade, (body or {}).get("upgrade"))


@router.post("/focus")
async def focus(body: dict) -> dict:
    return await _run(service.focus, (body or {}).get("focus"))


@router.post("/speed")
async def speed(body: dict) -> dict:
    return await _run(service.speed, (body or {}).get("speed"))


@router.post("/perk")
async def perk(body: dict) -> dict:
    return await _run(service.buy_perk, (body or {}).get("perk"))


@router.post("/reset")
async def reset(body: dict | None = None) -> dict:
    return await _run(service.reset, (body or {}).get("seed"))
