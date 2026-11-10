"""Read-only status for the Desktop pane. Mounted at /api/plugins/taskreel."""

from __future__ import annotations

import json

from fastapi import APIRouter

router = APIRouter()


@router.get("/status")
def status() -> dict:
    try:
        from plugins.plugin_storage import plugin_db

        conn = plugin_db("taskreel")
    except Exception as exc:
        return {"phase": "idle", "routine": None, "message": str(exc), "steps": []}
    try:
        row = conn.execute("SELECT payload FROM live WHERE id = 1").fetchone()
    except Exception:
        row = None
    finally:
        conn.close()
    if not row:
        return {"phase": "idle", "routine": None, "message": "No task recorded yet.", "steps": []}
    try:
        data = json.loads(row[0])
    except json.JSONDecodeError:
        return {"phase": "idle", "routine": None, "message": "Status unreadable.", "steps": []}
    return data if isinstance(data, dict) else {"phase": "idle", "steps": []}
