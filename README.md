# Taskreel

Teach Hermes a local computer task once. Save the tool steps as a routine. Replay that routine with no model call. If a checkpoint fails, replay stops and names that step so the agent repairs only the failure.

Taskreel is a Hermes plugin. A skill cannot hook the tool lifecycle, store a routine across sessions, or draw the Desktop pane.

## Install

From the catalog, once the entry is merged:

```bash
hermes plugins install taskreel
hermes plugins enable taskreel
```

From this repo while the catalog pull request is open:

```bash
hermes plugins install https://github.com/SuryaXyz-art/taskreel --enable
```

Restart Hermes Desktop after the first install. The Taskreel pane sits on the right.

## Tools

| Tool | What it does |
|---|---|
| `save_routine` | Store this session's recorded steps under a short name. |
| `run_routine` | Replay that routine. `model_calls` is 0. Stops at `failed_step`. |
| `list_routines` | List saved names and step counts. |

Automatic checkpoints: `exit_ok` for the terminal tool, `not_error` for everything else. Pass `checkpoints` to `save_routine` to use `file_exists` or `output_contains` instead.

Load the workflow skill with `skill_view("taskreel:taskreel")`.

## Try it

1. Ask Hermes to sort or rename a small folder of files.
2. Say: save this as `demo-sort`.
3. Put the files back and say: run `demo-sort`.
4. Remove a folder a middle step needs. Replay stops on that step.

## Disclosure

- No network calls, no telemetry, no credentials, no background process.
- Routines are stored in the Hermes plugin data directory for the active profile (`plugin-data/taskreel/data.db`).
- Arguments and result summaries are redacted before they are stored. Values that look like tokens, keys, or passwords are replaced.
- `run_routine` dispatches each saved step through Hermes tool dispatch. Approvals and guardrails still apply. This plugin does not auto-approve and does not spawn a shell of its own.
- A `file_exists` checkpoint checks whether a path stored in the routine exists.
- The Desktop pane polls `/api/plugins/taskreel/status` about every 1.5 seconds. That route only reads the live status row.
- Unattended runs that need a person fail closed through Hermes approval. The plugin does not hang waiting for input.

## Layout

```text
plugin.yaml
__init__.py
store.py
redact.py
desktop/plugin.js
dashboard/plugin_api.py
skills/taskreel/SKILL.md
```
