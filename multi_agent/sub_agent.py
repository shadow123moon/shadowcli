"""Legacy multi-agent role wrapper around the shared single-agent loop."""
from __future__ import annotations

import threading
from typing import Callable

from agent.agent_loop import (
    AgentLoop,
    _is_tool_error_result,
    _preview,
    _tool_action,
)
from agent.prompts import react_agent_prompt
from llm import Message

from .roles import AgentRole

ChatFn = Callable[..., object]


PLANNER_PROMPT = """你是一个任务规划专家。请将用户需求拆解为可执行的步骤，输出 JSON 格式：
{
  "summary": "任务摘要",
  "steps": [
    {
      "id": "step_1",
      "description": "具体操作描述",
      "type": "FILE_READ | FILE_WRITE | COMMAND | ANALYSIS | VERIFICATION",
      "reads": ["会读取的文件或目录路径，未知则为空数组"],
      "writes": ["会修改或创建的文件路径，纯分析则为空数组"],
      "dependencies": []
    }
  ]
}

字段规则：
- reads/writes 是声明式边界，尽量写具体路径；无法确定就填 []。
- dependencies 只表示数据依赖：只有当前步骤必须使用前置步骤输出时才填写。
- 不要为了保持顺序让 step_n 默认依赖 step_n-1。

依赖关系必须用 step_id 引用其他步骤的 id。直接输出 JSON，不要其他说明。"""


def _worker_prompt(tools_desc: str) -> str:
    return f"""你是一个任务执行者，只完成当前步骤。

可用工具：
{tools_desc}

需要事实就调用工具；信息足够就直接回答。
完成后简短说明：做了什么、关键结果、失败原因（如果有）。"""


class SubAgent(AgentLoop):
    """Compatibility wrapper for legacy planner/worker roles."""

    def __init__(
        self,
        name: str,
        role: AgentRole,
        chat: ChatFn,
        tool_registry,
        *,
        cancel: threading.Event | None = None,
        conversation_history: list[Message] | None = None,
    ):
        self.role = role
        super().__init__(
            name=name,
            system_prompt=_build_system_prompt(role, tool_registry),
            chat=chat,
            tool_registry=tool_registry,
            cancel=cancel,
            conversation_history=conversation_history,
            use_tools=role in {AgentRole.WORKER, AgentRole.REACT},
        )

    def __repr__(self) -> str:
        return f"SubAgent(name={self.name!r}, role={self.role.name}, history={len(self.conversation_history)})"


def _build_system_prompt(role: AgentRole, tool_registry) -> str:
    if role == AgentRole.PLANNER:
        return PLANNER_PROMPT

    defs = tool_registry.get_all_definitions()
    tools_desc = "\n".join(
        f"- {d['function']['name']}: {d['function']['description']}" for d in defs
    )
    if role == AgentRole.REACT:
        return react_agent_prompt(tools_desc)
    return _worker_prompt(tools_desc)


__all__ = [
    "ChatFn",
    "PLANNER_PROMPT",
    "SubAgent",
    "_is_tool_error_result",
    "_preview",
    "_tool_action",
    "_worker_prompt",
    "react_agent_prompt",
]
