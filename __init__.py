"""Taskreel: record a Hermes task, then replay it with no model call."""

from __future__ import annotations

import json
from pathlib import Path

from .store import OWN_TOOLS, Store, check_name, replay

_store: Store | None = None


def _db_connect():
    from plugins.plugin_storage import plugin_db

    return plugin_db("taskreel")


def _get_store() -> Store:
    global _store
    if _store is None:
        _store = Store(_db_connect)
    return _store


def _session(kwargs: dict) -> str:
    for key in ("task_id", "session_id"):
        value = kwargs.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:128]
    return "default"


def _dump(payload: dict) -> str:
    return json.dumps(payload, default=str)


def _on_post_tool_call(tool_name="", args=None, result=None, task_id="", session_id="", **kwargs):
    if tool_name in OWN_TOOLS:
        return None
    session = task_id or session_id or kwargs.get("session_id") or "default"
    if not isinstance(session, str) or not session.strip():
        session = "default"
    try:
        _get_store().record_step(session.strip()[:128], str(tool_name or ""), args, result)
    except Exception:
        return None
    return None


def _save(args, **kwargs):
    name = args.get("name") if isinstance(args, dict) else None
    checkpoints = args.get("checkpoints") if isinstance(args, dict) else None
    try:
        return _dump(_get_store().save_routine(str(name or ""), _session(kwargs), checkpoints))
    except Exception as exc:
        return _dump({"error": f"{type(exc).__name__}: {exc}"})


def _list(args, **kwargs):
    del args, kwargs
    try:
        return _dump(_get_store().list_routines())
    except Exception as exc:
        return _dump({"error": f"{type(exc).__name__}: {exc}"})


def _run(ctx, args, **kwargs):
    del kwargs
    name = str((args or {}).get("name") or "")
    error = check_name(name)
    if error:
        return _dump({"error": error})
    try:
        steps = _get_store().load_routine(name)
    except Exception as exc:
        return _dump({"error": f"{type(exc).__name__}: {exc}"})
    if steps is None:
        return _dump({"error": f"No routine named {name}. Call list_routines."})
    store = _get_store()
    store.mark_live(
        {
            "phase": "running",
            "routine": name,
            "message": f"Replaying {name}",
            "steps": [{"tool": step.get("tool"), "summary": "pending", "ok": None} for step in steps],
        }
    )
    store.push_replay()
    try:
        outcome = replay(steps, lambda tool, tool_args: ctx.dispatch_tool(tool, tool_args))
    finally:
        store.pop_replay()
    phase = "done" if outcome.get("ok") else "failed"
    store.mark_live(
        {
            "phase": phase,
            "routine": name,
            "message": "Replay finished" if outcome.get("ok") else outcome.get("detail") or "Replay stopped",
            "steps": outcome.get("steps_done") or [],
        }
    )
    return _dump(outcome)


def register(ctx):
    skills_dir = Path(__file__).parent / "skills"
    if skills_dir.is_dir():
        for child in sorted(skills_dir.iterdir()):
            skill_md = child / "SKILL.md"
            if child.is_dir() and skill_md.is_file():
                ctx.register_skill(child.name, skill_md)

    ctx.register_tool(
        name="save_routine",
        toolset="taskreel",
        schema={
            "name": "save_routine",
            "description": (
                "Save this session's recorded tool steps as a named routine. "
                "Do the task with normal tools first. Optional checkpoints override "
                "the automatic check on each step."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Short routine id, lowercase, e.g. demo-sort."},
                    "checkpoints": {
                        "type": "array",
                        "description": "Optional, one object per recorded step.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "kind": {
                                    "type": "string",
                                    "enum": ["exit_ok", "not_error", "file_exists", "output_contains"],
                                },
                                "path": {"type": "string"},
                                "text": {"type": "string"},
                            },
                            "required": ["kind"],
                        },
                    },
                },
                "required": ["name"],
            },
        },
        handler=_save,
    )
    ctx.register_tool(
        name="list_routines",
        toolset="taskreel",
        schema={
            "name": "list_routines",
            "description": "List saved taskreel routines and their step counts.",
            "parameters": {"type": "object", "properties": {}},
        },
        handler=_list,
    )
    ctx.register_tool(
        name="run_routine",
        toolset="taskreel",
        schema={
            "name": "run_routine",
            "description": (
                "Replay a saved routine with no model call. Each step is dispatched "
                "with the exact arguments that were recorded. The tool's own approval "
                "still runs, for example the terminal dangerous-command prompt. Replay "
                "does not go through other plugins' pre_tool_call hooks or tool "
                "middleware, so guard plugins do not see these steps. Stops on the "
                "first failed checkpoint and returns failed_step. model_calls is 0."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Routine name passed to save_routine."},
                },
                "required": ["name"],
            },
        },
        handler=lambda args, **kwargs: _run(ctx, args, **kwargs),
    )
    ctx.register_hook("post_tool_call", _on_post_tool_call)
