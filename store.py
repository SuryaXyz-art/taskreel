"""Routine storage and checkpoint checks. No Hermes imports."""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any, Callable

try:
    from .redact import redact, redact_text
except ImportError:  # unit tests load this file as a top-level module
    from redact import redact, redact_text

OWN_TOOLS = frozenset({"save_routine", "run_routine", "list_routines"})
_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,40}$")
_EXIT = re.compile(r"exit_code[\"'\s:=]+(-?\d+)")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def check_name(name: str) -> str | None:
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        return "Routine name must match ^[a-z0-9][a-z0-9_-]{0,40}$."
    return None


def _as_text(result: Any) -> str:
    if isinstance(result, str):
        return result
    try:
        return json.dumps(result, default=str)
    except TypeError:
        return str(result)


def check_checkpoint(checkpoint: dict | None, result: Any) -> tuple[bool, str]:
    kind = (checkpoint or {}).get("kind") or "not_error"
    text = _as_text(result)
    if kind == "exit_ok":
        match = _EXIT.search(text)
        if match and int(match.group(1)) == 0:
            return True, "exit_code 0"
        return False, "terminal exit_code was not 0"
    if kind == "output_contains":
        needle = str((checkpoint or {}).get("text") or "")
        if needle and needle in text:
            return True, "output contained the expected text"
        return False, "output did not contain the expected text"
    if kind == "file_exists":
        path = str((checkpoint or {}).get("path") or "")
        if not path or "\x00" in path:
            return False, "file_exists checkpoint has no path"
        from pathlib import Path

        if Path(path).exists():
            return True, "path exists"
        return False, f"path does not exist: {path}"
    try:
        parsed = json.loads(text) if text[:1] in "{[" else None
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict) and "error" in parsed and "exit_code" not in parsed:
        return False, str(parsed.get("error"))[:240]
    if text.startswith("Tool execution failed"):
        return False, text[:240]
    return True, "no error"


def default_checkpoint(tool: str) -> dict:
    if tool == "terminal":
        return {"kind": "exit_ok"}
    return {"kind": "not_error"}


def encode_exact_args(args: Any) -> str | None:
    """Return JSON that round-trips to the same dict, or None if it cannot."""
    if not isinstance(args, dict):
        return None
    try:
        encoded = json.dumps(args, sort_keys=True)
        decoded = json.loads(encoded)
    except (TypeError, ValueError):
        return None
    if decoded != args:
        return None
    return encoded


class Store:
    def __init__(self, connect: Callable[[], sqlite3.Connection]):
        self._connect = connect
        self._lock = threading.Lock()
        self._replay_depth = 0
        self._init()

    def _init(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS steps (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT NOT NULL,
                        tool_name TEXT NOT NULL,
                        args_json TEXT NOT NULL,
                        summary TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        lossy INTEGER NOT NULL DEFAULT 1
                    );
                    CREATE TABLE IF NOT EXISTS routines (
                        name TEXT PRIMARY KEY,
                        steps_json TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS live (
                        id INTEGER PRIMARY KEY CHECK (id = 1),
                        payload TEXT NOT NULL
                    );
                    """
                )
                columns = {row[1] for row in conn.execute("PRAGMA table_info(steps)")}
                if "lossy" not in columns:
                    conn.execute("ALTER TABLE steps ADD COLUMN lossy INTEGER NOT NULL DEFAULT 1")
                conn.commit()
            finally:
                conn.close()

    @property
    def replaying(self) -> bool:
        return self._replay_depth > 0

    def push_replay(self) -> None:
        with self._lock:
            self._replay_depth += 1

    def pop_replay(self) -> None:
        with self._lock:
            self._replay_depth = max(0, self._replay_depth - 1)

    def _write_live(self, conn: sqlite3.Connection, payload: dict) -> None:
        conn.execute(
            "INSERT INTO live (id, payload) VALUES (1, ?) "
            "ON CONFLICT(id) DO UPDATE SET payload = excluded.payload",
            (json.dumps(payload),),
        )

    def read_live(self) -> dict:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute("SELECT payload FROM live WHERE id = 1").fetchone()
            finally:
                conn.close()
        if not row:
            return {"phase": "idle", "routine": None, "message": "No task recorded yet.", "steps": []}
        try:
            data = json.loads(row[0])
        except json.JSONDecodeError:
            return {"phase": "idle", "routine": None, "message": "Status unreadable.", "steps": []}
        return data if isinstance(data, dict) else {"phase": "idle", "steps": []}

    def record_step(self, session_id: str, tool_name: str, args: Any, result: Any) -> None:
        if self.replaying or tool_name in OWN_TOOLS:
            return
        exact = encode_exact_args(args)
        summary = redact(_as_text(result))[:240]
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "INSERT INTO steps (session_id, tool_name, args_json, summary, created_at, lossy) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        session_id,
                        tool_name,
                        exact if exact is not None else "{}",
                        summary,
                        utc_now(),
                        0 if exact is not None else 1,
                    ),
                )
                rows = conn.execute(
                    "SELECT tool_name, summary FROM steps WHERE session_id = ? ORDER BY id",
                    (session_id,),
                ).fetchall()
                self._write_live(
                    conn,
                    {
                        "phase": "recording",
                        "routine": None,
                        "message": f"{len(rows)} step(s) recorded",
                        "steps": [{"tool": name, "summary": text, "ok": None} for name, text in rows],
                    },
                )
                conn.commit()
            finally:
                conn.close()

    def session_steps(self, session_id: str) -> list[dict]:
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT tool_name, args_json, lossy FROM steps WHERE session_id = ? ORDER BY id",
                    (session_id,),
                ).fetchall()
            finally:
                conn.close()
        steps = []
        for index, (tool_name, args_json, lossy) in enumerate(rows, start=1):
            if tool_name in OWN_TOOLS:
                continue
            try:
                args = json.loads(args_json)
            except json.JSONDecodeError:
                args = None
                lossy = 1
            if not isinstance(args, dict):
                args = {}
                lossy = 1
            steps.append(
                {
                    "step": index,
                    "tool": tool_name,
                    "args": args,
                    "lossy": bool(lossy),
                    "checkpoint": default_checkpoint(tool_name),
                }
            )
        return steps

    def save_routine(self, name: str, session_id: str, checkpoints: list | None) -> dict:
        error = check_name(name)
        if error:
            return {"error": error}
        steps = self.session_steps(session_id)
        if not steps:
            return {"error": "No steps recorded in this session yet. Do the task first, then save it."}
        blocked = [step for step in steps if step.get("lossy")]
        if blocked:
            listed = ", ".join(f"step {step['step']} ({step['tool']})" for step in blocked)
            return {
                "error": (
                    "Refusing to save because these steps cannot be replayed exactly: "
                    f"{listed}. Re-record each one. Replay never sends truncated or redacted arguments."
                )
            }
        if checkpoints is not None:
            if not isinstance(checkpoints, list) or len(checkpoints) != len(steps):
                return {"error": f"checkpoints must be a list of {len(steps)} objects, one per recorded step."}
            applied = []
            for step, raw in zip(steps, checkpoints):
                if not isinstance(raw, dict) or raw.get("kind") not in {
                    "exit_ok",
                    "not_error",
                    "file_exists",
                    "output_contains",
                }:
                    return {"error": "Each checkpoint needs kind exit_ok, not_error, file_exists, or output_contains."}
                checkpoint = {"kind": raw["kind"]}
                if raw.get("kind") == "file_exists":
                    checkpoint["path"] = str(raw.get("path") or "")
                if raw.get("kind") == "output_contains":
                    checkpoint["text"] = str(raw.get("text") or "")
                applied.append({**step, "checkpoint": checkpoint})
            steps = applied
        stored = [
            {"tool": step["tool"], "args": step["args"], "checkpoint": step["checkpoint"]}
            for step in steps
        ]
        payload = json.dumps(stored)
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "INSERT INTO routines (name, steps_json, updated_at) VALUES (?, ?, ?) "
                    "ON CONFLICT(name) DO UPDATE SET steps_json = excluded.steps_json, updated_at = excluded.updated_at",
                    (name, payload, utc_now()),
                )
                self._write_live(
                    conn,
                    {
                        "phase": "saved",
                        "routine": name,
                        "message": f"Saved {name} ({len(steps)} steps)",
                        "steps": [{"tool": step["tool"], "summary": step["checkpoint"]["kind"], "ok": True} for step in steps],
                    },
                )
                conn.commit()
            finally:
                conn.close()
        return {"ok": True, "name": name, "steps": len(steps)}

    def list_routines(self) -> dict:
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute("SELECT name, steps_json FROM routines ORDER BY name").fetchall()
            finally:
                conn.close()
        routines = []
        for name, blob in rows:
            try:
                count = len(json.loads(blob))
            except json.JSONDecodeError:
                count = 0
            routines.append({"name": name, "steps": count})
        return {"routines": routines}

    def load_routine(self, name: str) -> list[dict] | None:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute("SELECT steps_json FROM routines WHERE name = ?", (name,)).fetchone()
            finally:
                conn.close()
        if not row:
            return None
        data = json.loads(row[0])
        return data if isinstance(data, list) else None

    def mark_live(self, payload: dict) -> None:
        with self._lock:
            conn = self._connect()
            try:
                self._write_live(conn, payload)
                conn.commit()
            finally:
                conn.close()


def replay(steps: list[dict], dispatch: Callable[[str, dict], str]) -> dict:
    done = []
    for index, step in enumerate(steps):
        tool = str(step.get("tool") or "")
        args = step.get("args") if isinstance(step.get("args"), dict) else {}
        if tool in OWN_TOOLS:
            return {"error": f"Refusing to replay taskreel tool {tool}."}
        try:
            result = dispatch(tool, args)
        except Exception as exc:
            result = json.dumps({"error": f"{type(exc).__name__}: {exc}"})
        ok, detail = check_checkpoint(step.get("checkpoint"), result)
        shown_detail = redact_text(str(detail))
        done.append({"tool": tool, "summary": shown_detail, "ok": ok})
        if not ok:
            return {
                "ok": False,
                "failed_step": index,
                "tool": tool,
                "args": redact(args),
                "result": redact(_as_text(result))[:500],
                "detail": shown_detail,
                "model_calls": 0,
                "steps_done": done,
            }
    return {"ok": True, "steps": len(steps), "model_calls": 0, "steps_done": done}
