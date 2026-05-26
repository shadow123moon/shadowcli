"""Agent 角色定义 - PLANNER / WORKER / REACT。

Pythonic 要点：
- @property 暴露 display_name / description
- tuple 作为 enum value，property 解包
"""
from __future__ import annotations

from enum import Enum


class AgentRole(Enum):
    """Multi-Agent 系统中的角色分工。"""

    PLANNER = ("规划者", "负责分析用户任务，制定执行计划，将复杂任务拆解为可执行的子任务")
    WORKER = ("执行者", "负责执行具体任务步骤，调用工具完成文件操作、命令执行等操作")
    REACT = ("通用助手", "能够根据需要调用工具完成任务，也能直接进行日常对话")

    @property
    def display_name(self) -> str:
        return self.value[0]

    @property
    def description(self) -> str:
        return self.value[1]
