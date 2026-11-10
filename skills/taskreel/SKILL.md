---
name: taskreel
description: "Teach a local task once, save it, and replay it with no model call."
version: 1.0.0
---

# Taskreel

Use this when the user wants a repeatable local task.

1. Do the task with the normal Hermes tools (terminal, files, and so on).
2. Call `save_routine` with a short lowercase name such as `demo-sort`.
3. Later, call `run_routine` with that name. Do not redo the steps yourself.
4. If the result has `failed_step`, fix only that step, then save the routine again.

`run_routine` reports `model_calls: 0`. Replay still goes through Hermes approvals.
