"""MemoryManager：把所有组件用门面整合起来。

Pythonic 要点：
- keyword-only 构造参数         *, chat / profile / long_term / long_term_path
- @property + setter for chat   懒加载 + 可注入
- 简短方法名                    add_user / add_tool / find / remember / forget_short
                                而不是 addUserMessage / clear_conversation
- __repr__ 替代 status report
- _add 私有辅助方法消除重复
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from .budget import ContextProfile, TokenBudget
from .compress import ChatFn, compact_history, compress_memory
from .entry import MemoryEntry, MemoryType
from .long_term import LongTermMemory
from .retrieval import build_context, search
from .short_term import ConversationMemory

if TYPE_CHECKING:
    from model import Message

log = logging.getLogger(__name__)

MAX_TOOL_RESULT_CHARS = 500


def _default_chat() -> ChatFn:
    """延迟加载默认 chat 函数。"""
    from llm_client import chat
    return chat


class MemoryManager:
    """Memory 门面：写入 / 检索 / 压缩 / 状态。"""

    def __init__(
        self,
        *,
        chat: ChatFn | None = None,
        profile: ContextProfile | None = None,
        long_term: LongTermMemory | None = None,
        long_term_path: Path | None = None,
    ):
        self._profile = profile or ContextProfile()
        self._chat = chat

        self.short_term = ConversationMemory(self._profile.short_term_budget)
        self.long_term = long_term or LongTermMemory(long_term_path)
        self.budget = TokenBudget(self._profile.max_context_window)

    # —— 配置 ——
    @property
    def chat(self) -> ChatFn:
        """LLM chat 函数；首次访问时懒加载 llm_client.chat。"""
        if self._chat is None:
            self._chat = _default_chat()
        return self._chat

    @chat.setter
    def chat(self, fn: ChatFn) -> None:
        self._chat = fn

    @property
    def profile(self) -> ContextProfile:
        return self._profile

    @profile.setter
    def profile(self, p: ContextProfile) -> None:
        self._profile = p
        self.short_term.max_tokens = p.short_term_budget
        self.budget = TokenBudget(p.max_context_window)

    # —— 写入 ——
    def add_user(self, content: str) -> None:
        self._add("user", content, MemoryType.CONVERSATION, {"source": "user"})

    def add_assistant(self, content: str) -> None:
        if content:
            self._add("assistant", content, MemoryType.CONVERSATION, {"source": "assistant"})

    def add_tool(self, tool_name: str, result: str) -> None:
        truncated = (
            f"{result[:MAX_TOOL_RESULT_CHARS]}...(已截断)"
            if len(result) > MAX_TOOL_RESULT_CHARS
            else result
        )
        self._add(
            "tool",
            f"[{tool_name}] {truncated}",
            MemoryType.TOOL_RESULT,
            {"source": "tool", "toolName": tool_name},
        )

    def remember(self, fact: str) -> None:
        """保存稳定事实到长期记忆。"""
        self.long_term.store(MemoryEntry(
            id=f"fact-{uuid.uuid4().hex[:8]}",
            content=fact,
            type=MemoryType.FACT,
            metadata={"source": "fact"},
        ))

    def _add(
        self,
        prefix: str,
        content: str,
        mtype: MemoryType,
        metadata: dict[str, str],
    ) -> None:
        self.short_term.store(MemoryEntry(
            id=f"{prefix}-{uuid.uuid4().hex[:8]}",
            content=content,
            type=mtype,
            metadata=metadata,
        ))
        self.maybe_compress()

    # —— 检索 ——
    def find(self, query: str, *, limit: int = 5) -> list[MemoryEntry]:
        """从短期 + 长期中按相关度检索。"""
        return search(self.short_term, self.long_term, query, limit=limit)

    def context_for(self, query: str, *, max_tokens: int = 500) -> str:
        """构造用于注入 LLM system prompt 的相关长期记忆片段。"""
        return build_context(self.long_term, query, max_tokens=max_tokens)

    # —— Token 统计 ——
    def record_usage(self, input_tokens: int, output_tokens: int, *, cached: int = 0) -> None:
        self.budget.record(input_tokens, output_tokens, cached=cached)

    # —— 压缩 ——
    def maybe_compress(self) -> bool:
        """短期记忆占用到阈值就触发 Map-Reduce 压缩。"""
        if not self.budget.needs_compression(
            self.short_term, self._profile.compression_trigger
        ):
            return False

        before = self.short_term.total_tokens
        log.info(
            "short-term compress triggered at %.0f%%",
            self._profile.compression_trigger * 100,
        )
        summary = compress_memory(self.short_term, self.chat)
        if summary:
            log.info(
                "short-term compressed: %d → %d tokens, preview='%s'",
                before, self.short_term.total_tokens, summary[:100],
            )
            return True
        return False

    def maybe_compact_history(
        self,
        history: list[Message],
        trigger_tokens: int | None = None,
    ) -> bool:
        """按需压缩外部传入的 conversation_history（消息列表）。"""
        if trigger_tokens is None:
            trigger_tokens = int(
                self.budget.available_for_conversation
                * self._profile.compression_trigger
            )
        return compact_history(history, self.chat, trigger_tokens=trigger_tokens)

    # —— 清理 ——
    def forget_short(self) -> None:
        self.short_term.clear()

    def forget_long(self) -> None:
        self.long_term.clear()

    def __repr__(self) -> str:
        return (
            f"MemoryManager({self._profile})\n"
            f"  short_term: {self.short_term!r}\n"
            f"  long_term : {self.long_term!r}\n"
            f"  budget    : {self.budget}"
        )
