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
4. If the result has `failed_step`, fix only that step, then save the routine again. The index starts at 0, so 0 is the first step and 1 is the second.

`run_routine` reports `model_calls: 0`. Each replayed step still hits that tool's own approval, such as the terminal dangerous-command prompt. Other plugins' pre_tool_call hooks and tool middleware do not see the replay.
