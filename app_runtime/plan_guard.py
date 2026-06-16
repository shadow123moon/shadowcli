from __future__ import annotations

from typing import Any, Callable


PlanModeActive = Callable[[], bool]


def register_plan_mode_guard(runtime: Any, is_plan_mode_active: PlanModeActive) -> None:
    """注册 plan mode 运行时守卫，拦截非只读工具。

    Args:
        runtime: 必须实现 on_before_execute(hook) 方法的 ToolRuntime
        is_plan_mode_active: 返回当前是否处于 plan mode 的回调

    Raises:
        TypeError: 如果 runtime 不支持 on_before_execute
    """
    if not hasattr(runtime, "on_before_execute"):
        raise TypeError(
            f"runtime 必须实现 on_before_execute 方法，但收到 {type(runtime).__name__}"
        )
    if not callable(runtime.on_before_execute):
        raise TypeError("runtime.on_before_execute 必须是可调用对象")

    def plan_mode_hook(name: str, _arguments: dict, tool: Any) -> dict[str, Any] | None:
        """在 plan mode 下只允许 effect="read" 的工具执行。"""
        if not is_plan_mode_active():
            return None

        # 显式检查 effect 属性，未定义时拒绝执行（安全优先）
        effect = getattr(tool, "effect", None)
        if effect is None:
            return {
                "block": True,
                "hard_stop": False,
                "reason": (
                    f"工具 {name} 未定义 effect 属性，plan mode 下禁止执行。"
                    "请确保所有工具都正确标记了 effect='read' 或 effect='write'。"
                ),
            }

        # 只有明确标记为 read 的工具才放行
        if effect == "read":
            return None

        return {
            "block": True,
            "hard_stop": False,
            "reason": (
                f"plan mode 只允许只读工具，已拒绝 {name}（effect={effect}）。"
                "请先完成计划，并让用户用 /exit-plan <计划内容> 批准后再执行修改。"
            ),
        }

    runtime.on_before_execute(plan_mode_hook)
