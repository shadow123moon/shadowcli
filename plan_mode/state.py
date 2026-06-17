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
        normalized = _normalize_text(plan)
        if not normalized:
            raise ValueError("approved plan is required")

        self.__dict__.update({
            "mode": self.pre_mode or DEFAULT_MODE,
            "pre_mode": None,
            "task": "",
            "approved_plan": normalized,
        })

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


def _normalize_text(value: str | None) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise TypeError(f"Expected str or None, got {type(value).__name__}")
    return " ".join(value.strip().split())
