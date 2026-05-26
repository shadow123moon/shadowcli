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
from .entry import MemoryEntry, MemoryType, estimate_tokens
from .long_term import LongTermMemory
from .retrieval import search, search_long_only
from .short_term import ConversationMemory

if TYPE_CHECKING:
    from llm import Message

log = logging.getLogger(__name__)

MAX_TOOL_RESULT_CHARS = 500
DEFAULT_MEMORY_CONTEXT_TOKENS = 800
DEFAULT_RECENT_SHORT_TERM_LIMIT = 8
DEFAULT_LONG_TERM_LIMIT = 8


def _source_label(source: str | None) -> str:
    return {
        "user": "用户",
        "assistant": "助手",
        "tool": "工具",
        "fact": "事实",
    }.get(source or "", source or "未知")


def _default_chat() -> ChatFn:
    """延迟加载默认 chat 函数。"""
    from llm.client import chat
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
        before = len(self.long_term)
        self.long_term.store(MemoryEntry(
            id=f"fact-{uuid.uuid4().hex[:8]}",
            content=fact,
            type=MemoryType.FACT,
            metadata={"source": "fact"},
        ))
        log.info(
            "[记忆-长期] 写入事实，内容 %d 字；当前长期记忆 %d 条%s",
            len(fact or ""),
            len(self.long_term),
            "（重复，未新增）" if len(self.long_term) == before else "",
        )

    def _add(
        self,
        prefix: str,
        content: str,
        mtype: MemoryType,
        metadata: dict[str, str],
    ) -> None:
        entry = MemoryEntry(
            id=f"{prefix}-{uuid.uuid4().hex[:8]}",
            content=content,
            type=mtype,
            metadata=metadata,
        )
        self.short_term.store(entry)
        log.info(
            "[记忆-短期] 写入%s消息，类型=%s，内容 %d 字；当前 %d 条，%d/%d tokens",
            _source_label(metadata.get("source", prefix)),
            mtype.name,
            len(content or ""),
            len(self.short_term),
            self.short_term.total_tokens,
            self.short_term.max_tokens,
        )
        self.maybe_compress()

    # —— 检索 ——
    def find(self, query: str, *, limit: int = 5) -> list[MemoryEntry]:
        """从短期 + 长期中按相关度检索。"""
        return search(self.short_term, self.long_term, query, limit=limit)

    def context_for(
        self,
        query: str = "",
        *,
        max_tokens: int = DEFAULT_MEMORY_CONTEXT_TOKENS,
        recent_limit: int = DEFAULT_RECENT_SHORT_TERM_LIMIT,
        long_term_limit: int = DEFAULT_LONG_TERM_LIMIT,
    ) -> str:
        """构造用于注入 LLM 的短期最近对话 + 长期事实片段。"""
        lines = [
            "## 记忆上下文",
            "以下是记忆中保存的历史信息，仅在当前用户明确需要时使用；",
            "如果用户没有明确要求继续或修改之前任务，不要主动继续历史任务。",
            "",
        ]
        used = 0
        seen: set[str] = set()
        counts = {"短期": 0, "长期": 0}

        def append_entries(title: str, entries: list[MemoryEntry], origin: str | None = None) -> None:
            nonlocal used
            section_lines: list[str] = []
            for entry in entries:
                if entry.id in seen:
                    continue
                label_origin = origin or ("长期" if entry.id in self.long_term else "短期")
                label_source = entry.metadata.get("source") or entry.type.name.lower()
                line = f"- [{label_origin}/{label_source}] {entry.content}"
                token_count = entry.token_count or estimate_tokens(entry.content)
                if used + token_count > max_tokens:
                    break
                section_lines.append(line)
                seen.add(entry.id)
                counts[label_origin] = counts.get(label_origin, 0) + 1
                used += token_count
            if section_lines:
                lines.append(title)
                lines.extend(section_lines)
                lines.append("")

        recent_short = list(self.short_term)[-recent_limit:]
        append_entries("### 最近短期记忆", recent_short, "短期")
        long_term_entries = search_long_only(self.long_term, query, limit=long_term_limit)
        append_entries("### 相关长期记忆", long_term_entries, "长期")

        context = "\n".join(lines).rstrip() if seen else ""
        log.info(
            "[记忆] 构造直接上下文%s：查询 %d 字，包含 %d 条（短期 %d，长期 %d），约 %d tokens，生成 %d 字",
            "成功" if context else "为空",
            len(query or ""),
            len(seen),
            counts.get("短期", 0),
            counts.get("长期", 0),
            used,
            len(context),
        )
        return context

    # —— Token 统计 ——
    def record_usage(self, input_tokens: int, output_tokens: int, *, cached: int = 0) -> None:
        self.budget.record(input_tokens, output_tokens, cached=cached)

    # —— 压缩 ——
    def maybe_compress(self) -> bool:
        """短期记忆占用到阈值就触发 Map-Reduce 压缩。"""
        if not self.budget.needs_compression(
            self.short_term, self._profile.compression_trigger
        ):
            log.debug(
                "[记忆-短期] 暂不压缩：当前 %d tokens，触发阈值 %.0f%%",
                self.short_term.total_tokens,
                self._profile.compression_trigger * 100,
            )
            return False

        before = self.short_term.total_tokens
        log.info(
            "[记忆-短期] 开始压缩：当前 %d tokens，触发阈值 %.0f%%",
            before,
            self._profile.compression_trigger * 100,
        )
        summary = compress_memory(self.short_term, self.chat)
        if summary:
            log.info(
                "[记忆-短期] 压缩完成：%d -> %d tokens，摘要 %d 字",
                before,
                self.short_term.total_tokens,
                len(summary),
            )
            return True
        log.info("[记忆-短期] 跳过压缩：可压缩条目不足")
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
