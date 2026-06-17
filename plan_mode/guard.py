from __future__ import annotations

from typing import Any, Callable

from .policy import is_plan_mode_tool_allowed


PlanModeActive = Callable[[], bool]


def register_plan_mode_guard(runtime: Any, is_plan_mode_active: PlanModeActive) -> None:
    if not hasattr(runtime, "on_before_execute"):
        raise TypeError(
            f"runtime 必须实现 on_before_execute 方法，但收到 {type(runtime).__name__}"
        )
    if not callable(runtime.on_before_execute):
        raise TypeError("runtime.on_before_execute 必须是可调用对象")

    def plan_mode_hook(name: str, arguments: dict, tool: Any) -> dict[str, Any] | None:
        if not is_plan_mode_active():
            return None

        allowed, reason = is_plan_mode_tool_allowed(name, arguments, tool)
        if allowed:
            return None

        return {
            "block": True,
            "hard_stop": False,
            "reason": reason or f"plan mode 下禁止执行 {name}",
        }

    runtime.on_before_execute(plan_mode_hook)
