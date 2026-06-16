from __future__ import annotations

from typing import Any, Callable


PlanModeActive = Callable[[], bool]


def register_plan_mode_guard(runtime: Any, is_plan_mode_active: PlanModeActive) -> None:
    def hook(name, _arguments, tool):
        if not is_plan_mode_active():
            return None
        if getattr(tool, "effect", "write") == "read":
            return None
        return {
            "block": True,
            "hard_stop": False,
            "reason": (
                f"plan mode 只允许只读工具，已拒绝 {name}。"
                "请先完成计划，并让用户用 /exit-plan <计划内容> 批准后再执行修改。"
            ),
        }

    runtime.on_before_execute(hook)
