"""Hermes Incremental Village: a 3D Stone Age village whose villagers are played by Hermes.

Agent half. Registers the village tools, the /village command and a dedicated
auxiliary model slot ("Village planner") so the player can point council calls
at a cheaper model in Settings -> Models. Model tokens are spent only by an
explicit "plan" request from the player, and never inside a cron run.
"""
from __future__ import annotations

import json
import logging

from .village import service
from .village.store import Store

log = logging.getLogger(__name__)

_store = Store()

_EMPTY = {"type": "object", "properties": {}, "additionalProperties": False}

SCHEMAS = {
    "village_status": {
        "name": "village_status",
        "description": "Show the Hermes Incremental Village: day, era, Insight, Trust, buildings, the villagers (position, "
                       "health, energy, skills, inventory), the player's guidance and today's model-token budget. Free.",
        "parameters": _EMPTY,
    },
    "village_guide": {
        "name": "village_guide",
        "description": "Give the villagers advice for their next council (max 300 chars). Villagers weigh it "
                       "but decide for themselves. Free; does not advance time.",
        "parameters": {"type": "object", "properties": {"text": {"type": "string", "description": "Advice; empty clears it."}},
                       "required": ["text"], "additionalProperties": False},
    },
    "village_habit_day": {
        "name": "village_habit_day",
        "description": "Skip ahead to a new day for free: villagers follow habits and instincts. No model call.",
        "parameters": _EMPTY,
    },
    "village_plan_day": {
        "name": "village_plan_day",
        "description": "Hold a village council: ONE batched model call in which each villager plans their next "
                       "day from only what they can see. The plans start at the next dawn, and the game validates every action. "
                       "Spends model tokens (about 1-3k) against a daily cap. Only call when the player asks.",
        "parameters": _EMPTY,
    },
}


def _json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _in_cron(ctx) -> bool:
    try:
        return bool(ctx.current_cron_execution())
    except Exception:
        return False


def register(ctx) -> None:
    ctx.register_auxiliary_task(
        service.AUX_TASK,
        display_name="Village planner",
        description="Hermes Incremental Village councils: one batched call plans all villagers' day.",
    )

    def status(args: dict, **kwargs) -> str:
        try:
            snap = service.snapshot(_store)
            return _json({"ok": True, "summary": service.format_status(snap), "budget": snap["budget"]})
        except Exception as exc:
            log.exception("village_status failed")
            return _json({"ok": False, "error": str(exc)})

    def guide(args: dict, **kwargs) -> str:
        try:
            snap = service.guide(_store, (args or {}).get("text", ""))
            return _json({"ok": True, "guidance": snap["world"]["guidance"]})
        except Exception as exc:
            return _json({"ok": False, "error": str(exc)})

    def habit(args: dict, **kwargs) -> str:
        try:
            out = service.habit_day(_store)
            return _json({"ok": True, "report": service.format_report(out["report"])})
        except service.VillageError as exc:
            return _json({"ok": False, "error": str(exc)})
        except Exception as exc:
            log.exception("village_habit_day failed")
            return _json({"ok": False, "error": str(exc)})

    def plan(args: dict, **kwargs) -> str:
        if _in_cron(ctx):
            return _json({"ok": False, "error": "Hermes Incremental Village never spends model tokens in scheduled runs."})
        try:
            out = service.plan_day(_store, ctx.llm)
            return _json({"ok": True, "plans": service.format_plans(out["plans"]), "usage": out["usage"],
                          "budget": out["budget"]})
        except service.VillageError as exc:
            return _json({"ok": False, "error": str(exc)})
        except Exception as exc:
            log.exception("village_plan_day failed")
            return _json({"ok": False, "error": str(exc)})

    for name, handler in (("village_status", status), ("village_guide", guide),
                          ("village_habit_day", habit), ("village_plan_day", plan)):
        ctx.register_tool(name=name, toolset="village", schema=SCHEMAS[name], handler=handler)

    def command(raw_args: str) -> str:
        parts = (raw_args or "").strip().split(maxsplit=1)
        sub = parts[0].lower() if parts else "status"
        rest = parts[1] if len(parts) > 1 else ""
        try:
            if sub == "plan":
                if _in_cron(ctx):
                    return "Hermes Incremental Village never spends model tokens in scheduled runs."
                out = service.plan_day(_store, ctx.llm, purpose="village.plan_day.command")
                u = out["usage"]
                b = out["budget"]
                return (service.format_plans(out["plans"]) +
                        f"\n\nCouncil cost {u['input_tokens'] + u['output_tokens']:,} tokens"
                        f"{' (estimated)' if u['estimated'] else ''}; "
                        f"{b['used_today']:,}/{b['daily_tokens']:,} used today.")
            if sub == "habit":
                return service.format_report(service.habit_day(_store)["report"])
            if sub == "guide":
                snap = service.guide(_store, rest)
                return f"Guidance set: {snap['world']['guidance'] or '(cleared)'}"
            if sub == "budget":
                if not rest:
                    return service.format_status(service.snapshot(_store))
                snap = service.set_budget(_store, rest.replace(",", "").replace("_", ""))
                return f"Daily village budget set to {snap['budget']['daily_tokens']:,} tokens."
            if sub == "status":
                return service.format_status(service.snapshot(_store))
            if sub == "ideas":
                return service.format_ideas(service.snapshot(_store))
            if sub == "plant":
                return service.format_ideas(service.plant(_store, rest.strip().lower()))
            if sub == "upgrade":
                return service.format_ideas(service.upgrade(_store, rest.strip().lower()))
            if sub == "speed":
                value = 0 if rest.strip().lower() == "pause" else int(rest.strip().rstrip("xX") or 1)
                snap = service.speed(_store, value)
                paused = snap["world"]["paused_at"] is not None
                return "Village paused." if paused else f"Village speed {snap['world']['speed']}x."
            if sub == "focus":
                return service.format_ideas(service.focus(_store, rest.strip().lower() or None))
            return ("Usage: /village [status | plan | habit | guide <advice> | budget [tokens] | ideas | "
                    "plant <idea> | upgrade <name> | focus <food|shelter|explore|learn> | speed <pause|1|2|4|8|16>]\n"
                    "plan holds a council (one model call, counts against the daily budget); everything else is free.")
        except service.VillageError as exc:
            return f"Village: {exc}"
        except service.engine.EngineUnavailable as exc:
            return f"Village: {exc}"
        except ValueError:
            return "Village: speed must be pause, 1, 2, 4, 8 or 16."

    ctx.register_command(
        name="village",
        handler=command,
        description="Hermes Incremental Village: status, plan (model council), habit (free day), guide, budget, ideas, plant, upgrade, focus, speed.",
        args_hint="[status|plan|habit|guide <advice>|budget [tokens]|ideas|plant <idea>|upgrade <name>|focus <kind>|speed <value>]",
    )
