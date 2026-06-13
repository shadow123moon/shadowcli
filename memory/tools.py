from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Dict

from tooling.base import Tool

from .long_term import MEMORY_TYPES


@dataclass(frozen=True)
class MemoryProposal:
    memory_type: str
    text: str
    reason: str = ""


ConfirmMemory = Callable[[MemoryProposal], bool]


class ProposeMemoryTool(Tool):
    category = "memory"
    effect = "write"
    concurrency_safe = False
    result_kind = "text"
    guidance = (
        "ShadowCLI propose_memory 工具只用于提出长期记忆候选；"
        "只保存跨会话仍然有用的用户偏好、项目背景、纠正反馈或外部资料。"
        "不要保存临时任务状态、工具日志、会话压缩摘要、模型猜测或重复内容。"
        "工具会先请求用户确认，不能直接写入 memory 文件。"
    )

    def __init__(self, memory: Any, *, confirm_memory: ConfirmMemory):
        self.memory = memory
        self.confirm_memory = confirm_memory

    @property
    def name(self) -> str:
        return "propose_memory"

    @property
    def description(self) -> str:
        return (
            "提出一条长期记忆候选。只在信息跨会话仍有价值时使用；"
            "用户确认后才会保存到结构化 memory。"
        )

    @property
    def parameters(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "enum": list(MEMORY_TYPES),
                    "description": "长期记忆类型：user/project/feedback/reference",
                },
                "text": {
                    "type": "string",
                    "description": "要保存的长期事实，必须简短、明确、跨会话仍有用",
                },
                "reason": {
                    "type": "string",
                    "description": "为什么这条信息值得长期保存",
                },
            },
            "required": ["type", "text"],
        }

    def execute(self, arguments: Dict) -> str:
        memory_type = _normalize_memory_type(arguments.get("type"))
        if memory_type is None:
            allowed = "/".join(MEMORY_TYPES)
            return f"长期记忆建议失败: 未知记忆类型，请使用 {allowed}"

        text = _normalize_text(arguments.get("text"))
        if not text:
            return "长期记忆建议失败: text 不能为空"

        if text in {str(fact).strip() for fact in self.memory}:
            return f"已存在长期记忆，未重复保存: {text}"

        reason = _normalize_text(arguments.get("reason"))
        proposal = MemoryProposal(memory_type, text, reason)
        if not self.confirm_memory(proposal):
            return "已跳过长期记忆。"

        self.memory.remember(text, memory_type=memory_type)
        return f"已保存长期记忆 [{memory_type}]: {text}"


def _normalize_memory_type(value: Any) -> str | None:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in MEMORY_TYPES else None


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())
