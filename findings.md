# Findings

## Existing `/plan`

- `cli_app.router.ReplRouter._handle_plan()` currently routes `/plan <task>` into `_run_agent_line(..., allow_auto_skill=False)`.
- `app_runtime.agent_execution.run_agent_once()` also recognizes `/plan` and rewrites it to a one-shot planning prompt.
- This is not Claude Code-style plan mode because the state does not persist across turns and tools are not restricted.

## Runtime Seams

- `ToolRuntime.on_before_execute()` already supports soft/hard blocking hooks.
- Tools expose `effect`; current read tools use `effect = "read"`, write tools use `effect = "write"`, bash uses `effect = "execute"`.
- A plan-mode guard can block every non-read tool centrally.

## Session State

- `SessionMeta` is persisted to `meta.json`.
- Adding defaulted fields to `SessionMeta.from_dict()` is enough for V1 persistence without migrating existing sessions.
