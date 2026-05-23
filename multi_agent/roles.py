"""Agent 角色定义 - PLANNER / WORKER / REVIEWER。

Pythonic 要点：
- @property 暴露 display_name / description
- tuple 作为 enum value，property 解包
"""
from __future__ import annotations

from enum import Enum


class AgentRole(Enum):
    """Multi-Agent 系统中的三种角色分工。"""

    PLANNER = ("规划者", "负责分析用户任务，制定执行计划，将复杂任务拆解为可执行的子任务")
    WORKER = ("执行者", "负责执行具体任务步骤，调用工具完成文件操作、命令执行等操作")
    REVIEWER = ("检查者", "负责检查执行结果的质量和正确性，提供改进建议")

    @property
    def display_name(self) -> str:
        return self.value[0]

    @property
    def description(self) -> str:
        return self.value[1]
