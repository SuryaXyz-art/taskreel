"""Unit tests for routine storage. No Hermes process required."""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from redact import redact_text
from store import Store, check_checkpoint, replay


def memory_store() -> tuple[Store, Path]:
    directory = tempfile.TemporaryDirectory()
    path = Path(directory.name) / "data.db"

    def connect():
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn

    store = Store(connect)
    store._directory = directory
    return store, path


class RedactTests(unittest.TestCase):
    def test_assigned_secret(self):
        text = redact_text("token=abcd1234efgh")
        self.assertIn("[REDACTED]", text)
        self.assertNotIn("abcd1234efgh", text)

    def test_openai_style_key(self):
        text = redact_text("sk-" + "a" * 20)
        self.assertEqual(text, "[REDACTED]")


class CheckpointTests(unittest.TestCase):
    def test_exit_ok(self):
        ok, _ = check_checkpoint({"kind": "exit_ok"}, '{"exit_code": 0}')
        self.assertTrue(ok)
        bad, _ = check_checkpoint({"kind": "exit_ok"}, '{"exit_code": 1}')
        self.assertFalse(bad)

    def test_not_error(self):
        ok, _ = check_checkpoint({"kind": "not_error"}, '{"success": true}')
        self.assertTrue(ok)
        bad, _ = check_checkpoint({"kind": "not_error"}, '{"error": "nope"}')
        self.assertFalse(bad)

    def test_file_exists(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "made.txt"
            bad, _ = check_checkpoint({"kind": "file_exists", "path": str(target)}, "ok")
            self.assertFalse(bad)
            target.write_text("x", encoding="utf-8")
            ok, _ = check_checkpoint({"kind": "file_exists", "path": str(target)}, "ok")
            self.assertTrue(ok)


class RoutineTests(unittest.TestCase):
    def test_save_and_replay_stops_on_failure(self):
        store, _ = memory_store()
        command = "echo " + ("x" * 800)
        store.record_step(
            "s",
            "terminal",
            {"command": command, "token": "sekretvalue1"},
            "token=sekretvalue1 exit_code: 0",
        )
        shown = json.dumps(store.read_live())
        self.assertNotIn("sekretvalue1", shown)
        self.assertIn("[REDACTED]", shown)
        store.record_step("s", "save_routine", {"name": "ignored"}, "{}")
        saved = store.save_routine("demo-sort", "s", None)
        self.assertTrue(saved["ok"])
        self.assertEqual(saved["steps"], 1)
        stored = store.load_routine("demo-sort")[0]["args"]
        self.assertEqual(stored["command"], command)
        self.assertEqual(stored["token"], "sekretvalue1")
        shown = json.dumps(store.read_live())
        self.assertNotIn("sekretvalue1", shown)

        calls = []

        def dispatch(tool, args):
            calls.append((tool, args))
            return '{"exit_code": 2}'

        outcome = replay(store.load_routine("demo-sort"), dispatch)
        self.assertFalse(outcome["ok"])
        self.assertEqual(outcome["failed_step"], 0)
        self.assertEqual(outcome["model_calls"], 0)
        self.assertEqual(calls, [("terminal", {"command": command, "token": "sekretvalue1"})])

    def test_save_refuses_args_that_cannot_round_trip(self):
        store, _ = memory_store()
        store.record_step("s", "write_file", {"content": (1, 2)}, "ok")
        saved = store.save_routine("demo-sort", "s", None)
        self.assertIn("step 1 (write_file)", saved["error"])

    def test_replay_success(self):
        store, _ = memory_store()
        store.record_step("s", "terminal", {"command": "echo hi"}, "exit_code: 0")
        store.save_routine("demo-sort", "s", [{"kind": "output_contains", "text": "done"}])
        outcome = replay(store.load_routine("demo-sort"), lambda tool, args: "done")
        self.assertTrue(outcome["ok"])
        self.assertEqual(outcome["model_calls"], 0)


if __name__ == "__main__":
    unittest.main()
