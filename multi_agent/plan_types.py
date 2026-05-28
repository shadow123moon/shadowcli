"""Plan 相关的数据结构和工具函数。

从 orchestrator.py 抽取出来，让编排器只关注编排逻辑。

包含：
- PlanReviewDecision : 计划审查决策（执行/补充/取消）
- parse_plan_review_input : 解析用户的审查输入
- PlanReviewFn : 审查回调函数的类型签名
- StepStatus : 步骤状态
- ExecutionStep : 步骤数据类
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable


class PlanReviewDecision(Enum):
    """计划审查决策。"""
    EXECUTE = "execute"       # 直接执行
    SUPPLEMENT = "supplement" # 补充要求，重新规划
    CANCEL = "cancel"         # 取消


def parse_plan_review_input(user_input: str) -> tuple[PlanReviewDecision, str]:
    """解析用户对计划的审查输入。

    - 空字符串 / y / yes / run  → EXECUTE
    - cancel / esc              → CANCEL
    - 其他任意文字              → SUPPLEMENT（文字作为补充要求）
    """
    trimmed = user_input.strip()
    if trimmed == "" or trimmed.lower() in ("y", "yes", "run"):
        return PlanReviewDecision.EXECUTE, ""
    if trimmed.lower() in ("cancel", "esc"):
        return PlanReviewDecision.CANCEL, ""
    return PlanReviewDecision.SUPPLEMENT, trimmed


class StepStatus(Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass
class ExecutionStep:
    """执行计划中的一个步骤。"""

    id: str
    description: str
    type: str = "COMMAND"
    reads: list[str] = field(default_factory=list)
    writes: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    status: StepStatus = StepStatus.PENDING
    result: str = ""

    @property
    def is_completed(self) -> bool:
        return self.status == StepStatus.COMPLETED

    @property
    def is_pending(self) -> bool:
        return self.status == StepStatus.PENDING

    @property
    def is_failed(self) -> bool:
        return self.status == StepStatus.FAILED


# 计划审查回调：接收 (goal, steps)，返回 (decision, feedback)
PlanReviewFn = Callable[[str, list[ExecutionStep]], tuple[PlanReviewDecision, str]]
