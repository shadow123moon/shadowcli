# ShadowCLI Plan Mode V1

Goal: implement a first usable Claude Code-style plan mode for ShadowCLI: persistent mode state, read-only tool guard, explicit plan exit/approval, and tests.

## Phases

1. Status: completed
   Map current `/plan`, runtime, and tool guard seams.
2. Status: completed
   Add plan mode state and CLI commands.
3. Status: completed
   Add read-only guard in tool runtime.
4. Status: completed
   Add model guidance/context injection for active plan mode.
5. Status: completed
   Add focused tests and run test suite.

## Decisions

- First version does not implement subagents.
- `/plan <task>` becomes mode entry, not one-shot planning prompt.
- Keep `/plan` without args as status/help.
- Add `/exit-plan` for approval and mode exit.
- Guard must be enforced by runtime, not only prompt text.

## Implementation Summary

Plan Mode V1 已完成，包含以下组件：

- **状态管理** (`sessions/plan_mode.py`): PlanModeState dataclass，支持 enter/exit/reset，可序列化到 session meta
- **运行时防护** (`app_runtime/plan_guard.py`): 基于 tool.effect 的 hook，拦截非 read 工具
- **CLI 命令** (`cli_app/commands.py`, `cli_app/router.py`): /plan, /exit-plan
- **上下文注入** (`sessions/context.py`): active 时注入只读指引，exit 后注入 approved_plan
- **持久化** (`sessions/types.py`, `sessions/manager.py`): SessionMeta.plan_mode 字段，跨会话恢复
- **测试覆盖** (`tests/test_plan_mode.py`): 27 个测试用例，覆盖状态、防护、持久化、上下文注入

代码行数：~330 行核心实现 + ~340 行测试 = ~670 行

## Errors Encountered

| Error | Attempt | Resolution |
| --- | --- | --- |
