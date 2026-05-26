"""Agent 间通信消息 - Multi-Agent 协作的基本通信单元。

消息类型：
- TASK      : 主控分配给子代理的任务
- RESULT    : 子代理返回的执行结果
- ERROR     : 子代理遭遇系统级错误（如 LLM 调用失败）

Pythonic 要点：
- @dataclass(slots=True)             省内存
- @classmethod 静态工厂                替代 Java 静态方法
- is_error() 短谓词                    替代外部判 type == ERROR
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .roles import AgentRole


class MessageType(Enum):
    TASK = "TASK"
    RESULT = "RESULT"
    ERROR = "ERROR"


@dataclass(slots=True)
class AgentMessage:
    """Agent 间通信消息。"""

    from_agent: str
    from_role: AgentRole | None
    content: str
    type: MessageType

    @classmethod
    def task(cls, from_agent: str, content: str) -> AgentMessage:
        return cls(from_agent, None, content, MessageType.TASK)

    @classmethod
    def result(cls, from_agent: str, role: AgentRole, content: str) -> AgentMessage:
        return cls(from_agent, role, content, MessageType.RESULT)

    @classmethod
    def error(cls, from_agent: str, role: AgentRole | None, content: str) -> AgentMessage:
        return cls(from_agent, role, content, MessageType.ERROR)

    def is_error(self) -> bool:
        return self.type == MessageType.ERROR

    def is_empty(self) -> bool:
        return not self.content or not self.content.strip()
