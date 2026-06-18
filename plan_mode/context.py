from __future__ import annotations

from .state import PlanModeState


def plan_mode_context(state: PlanModeState) -> str:
    if state.active:
        return "\n".join([
            "## 当前模式: Plan Mode",
            f"任务: {state.task}",
            "",
            "你现在处于只读计划模式。",
            "- 目标是探索代码、提出方案、澄清问题，不要实现或修改文件。",
            "- 可以使用 read/ls/grep/find/web 等只读工具，也可以用 bash 执行 git status/git diff 这类只读检查。",
            "- 复杂探索可调用 fork_explore_agents 并行拆分边界；单点探索可调用 explore_agent；需要方案草案可调用 plan_agent。它们都是只读子 agent。",
            "- 不要调用 write/edit/propose_memory/MCP 等会产生副作用的工具；这些工具不会在 plan mode 中暴露或会被运行时拒绝。",
            "- 计划完成后，调用 exit_plan_mode 工具请求用户确认，或让用户执行 /exit-plan <计划内容>。",
        ])
    if state.approved_plan:
        return "\n".join([
            "## 已批准计划",
            state.approved_plan,
        ])
    return ""


def format_plan_mode_status(state: PlanModeState) -> str:
    if not state.active:
        return "当前未处于 plan mode。用法: /plan <任务>"
    return "\n".join([
        "当前处于 plan mode。",
        f"任务: {state.task}",
        "可继续让模型探索；批准计划请用 /exit-plan <计划内容>，或让模型调用 exit_plan_mode。",
    ])
