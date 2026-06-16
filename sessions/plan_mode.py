from __future__ import annotations

from dataclasses import dataclass
from typing import Any


DEFAULT_MODE = "default"
PLAN_MODE = "plan"


@dataclass
class PlanModeState:
    mode: str = DEFAULT_MODE
    pre_mode: str | None = None
    task: str = ""
    approved_plan: str = ""

    @property
    def active(self) -> bool:
        return self.mode == PLAN_MODE

    def enter(self, task: str) -> None:
        normalized = _normalize_text(task)
        if not normalized:
            raise ValueError("plan task is required")
        if not self.active:
            self.pre_mode = self.mode
        self.mode = PLAN_MODE
        self.task = normalized
        self.approved_plan = ""

    def exit(self, plan: str) -> None:
        """退出 plan mode 并保存已批准的计划。

        原子更新所有状态字段，减少不一致窗口期。

        Args:
            plan: 已批准的计划内容

        Raises:
            ValueError: 如果 plan 为空
        """
        normalized = _normalize_text(plan)
        if not normalized:
            raise ValueError("approved plan is required")

        # 先构建新状态，再一次性应用（减少不一致窗口期）
        new_state = {
            "mode": self.pre_mode or DEFAULT_MODE,
            "pre_mode": None,
            "task": "",
            "approved_plan": normalized,
        }
        self.__dict__.update(new_state)

    def reset(self) -> None:
        self.mode = DEFAULT_MODE
        self.pre_mode = None
        self.task = ""
        self.approved_plan = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "pre_mode": self.pre_mode,
            "task": self.task,
            "approved_plan": self.approved_plan,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "PlanModeState":
        if not isinstance(data, dict):
            return cls()
        mode = str(data.get("mode") or DEFAULT_MODE)
        if mode not in {DEFAULT_MODE, PLAN_MODE}:
            mode = DEFAULT_MODE
        pre_mode = data.get("pre_mode")
        return cls(
            mode=mode,
            pre_mode=str(pre_mode) if pre_mode else None,
            task=_normalize_text(data.get("task")),
            approved_plan=_normalize_text(data.get("approved_plan")),
        )


def plan_mode_context(state: PlanModeState) -> str:
    if state.active:
        return "\n".join([
            "## 当前模式: Plan Mode",
            f"任务: {state.task}",
            "",
            "你现在处于只读计划模式。",
            "- 目标是探索代码、提出方案、澄清问题，不要实现或修改文件。",
            "- 可以使用 read/ls/grep/find/web 等只读工具。",
            "- 不要调用 write/edit/bash/propose_memory/MCP 等可能产生副作用的工具；这些工具会被运行时拒绝。",
            "- 计划完成后，让用户执行 /exit-plan <计划内容> 批准并退出计划模式。",
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
        "可继续让模型探索；批准计划请用 /exit-plan <计划内容>。",
    ])


def _normalize_text(value: str | None) -> str:
    """规范化文本中的空白字符。

    Args:
        value: 输入文本或 None

    Returns:
        规范化后的文本，None 或空字符串返回空字符串

    Raises:
        TypeError: 如果输入不是 str 或 None
    """
    if value is None:
        return ""
    if not isinstance(value, str):
        raise TypeError(f"Expected str or None, got {type(value).__name__}")
    return " ".join(value.strip().split())
