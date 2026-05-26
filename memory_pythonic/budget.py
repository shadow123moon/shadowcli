"""上下文窗口预算 + 模型 profile。

Pythonic 要点：
- @dataclass 整个类      自动 __init__ / __repr__ / __eq__
- @property              替代 getXxx() / setXxx() 方法
- _MODEL_PROFILES 字典   替代 if/elif/else 长链
- keyword-only 参数      防止位置参数顺序写错
- TYPE_CHECKING import   避免运行时循环依赖
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .entry import estimate_tokens

if TYPE_CHECKING:
    from llm import Message

    from .short_term import ConversationMemory


@dataclass
class ContextProfile:
    """模型上下文策略：窗口大小 / 短期预算 / 压缩阈值。"""

    max_context_window: int = 131_072
    short_term_budget: int = 40_000
    compression_trigger: float = 0.9

    def __str__(self) -> str:
        return (
            f"window={self.max_context_window}, "
            f"shortTermBudget={self.short_term_budget}, "
            f"compressAt={self.compression_trigger:.0%}"
        )


# 模型名前缀 → ContextProfile 映射；按前缀长度降序匹配（特例优先）。
_MODEL_PROFILES: dict[str, ContextProfile] = {
    "gpt-4-turbo": ContextProfile(128_000, 40_000),
    "gpt-4-1106": ContextProfile(128_000, 40_000),
    "gpt-4-0125": ContextProfile(128_000, 40_000),
    "gpt-4o": ContextProfile(128_000, 40_000),
    "gpt-4.1": ContextProfile(128_000, 40_000),
    "gpt-4": ContextProfile(8_192, 5_000),
    "gpt-3.5": ContextProfile(16_385, 8_000),
    "claude": ContextProfile(200_000, 60_000),
    "glm-4": ContextProfile(128_000, 40_000),
    "glm4": ContextProfile(128_000, 40_000),
    "deepseek": ContextProfile(64_000, 20_000),
    "kimi": ContextProfile(128_000, 40_000),
    "moonshot": ContextProfile(128_000, 40_000),
}


def profile_for_model(model_name: str | None) -> ContextProfile:
    """按模型名前缀匹配获取 profile，未识别返回默认值。"""
    if not model_name:
        return ContextProfile()
    name = model_name.lower()
    for prefix, profile in _MODEL_PROFILES.items():
        if prefix in name:
            return profile
    return ContextProfile()


@dataclass
class TokenBudget:
    """累计 token 用量统计 + 压缩触发判定。"""

    context_window: int
    reserved_system: int = 500
    reserved_tools: int = 800
    reserved_response: int = 2_000

    total_input: int = 0
    total_output: int = 0
    total_cached: int = 0
    call_count: int = 0

    @property
    def available_for_conversation(self) -> int:
        return (
            self.context_window
            - self.reserved_system
            - self.reserved_tools
            - self.reserved_response
        )

    def fits(self, messages: Iterable[Message]) -> bool:
        return estimate_messages_tokens(messages) <= self.available_for_conversation

    def needs_compression(self, memory: ConversationMemory, trigger: float = 0.9) -> bool:
        budget = min(memory.max_tokens, self.available_for_conversation)
        return memory.total_tokens >= budget * trigger

    def record(self, input_tokens: int, output_tokens: int, *, cached: int = 0) -> None:
        self.total_input += input_tokens
        self.total_output += output_tokens
        self.total_cached += max(0, cached)
        self.call_count += 1

    def __str__(self) -> str:
        avg = self.total_input / self.call_count if self.call_count else 0
        return (
            f"calls={self.call_count}, in={self.total_input}, out={self.total_output}, "
            f"cached={self.total_cached}, avg_in={avg:.0f}, "
            f"window={self.context_window} (avail={self.available_for_conversation})"
        )


def estimate_messages_tokens(messages: Iterable[Message] | None) -> int:
    """估算 message 列表的总 token 数。"""
    if not messages:
        return 0
    msgs = list(messages)
    total = sum(
        estimate_tokens(m.content)
        + sum(estimate_tokens(tc.function.arguments) for tc in (m.tool_calls or []))
        for m in msgs
    )
    return total + len(msgs) * 4  # role / separator 开销
