"""相关性检索：函数式风格，无需类的状态。

Pythonic 要点：
- 模块级函数 + Iterable 入参   不绑死 ConversationMemory / LongTermMemory，
                              传任何"可迭代 MemoryEntry"都行（duck typing）
- keyword-only 参数            *, limit / boost 避免位置错位
- 函数式 sorted + key=         一行做评分排序
- relevance_score 独立暴露     调试 / 测试 / 复用都方便
"""
from __future__ import annotations

import time
from collections.abc import Iterable

from .entry import MemoryEntry, estimate_tokens
from .tokenizer import tokenize


def relevance_score(
    entry: MemoryEntry,
    query: str,
    *,
    include_metadata: bool = False,
) -> float:
    """关键词匹配 + 时间衰减（24h 内从 1.0 线性衰到 0.5）。

    include_metadata=True 时把 metadata.values() 也加入可搜索文本，
    用于长期记忆这种带结构化标签的条目。
    """
    if not query:
        return 0.0

    haystack = entry.content.lower()
    if include_metadata and entry.metadata:
        haystack += " " + " ".join(str(v).lower() for v in entry.metadata.values())
    q = query.lower()

    # 1. 精确子串匹配
    if q in haystack:
        return 1.0

    # 2. 关键词命中率
    query_tokens = tokenize(q)
    if not query_tokens:
        return 0.0
    matched = sum(1 for tok in query_tokens if tok in haystack)
    if matched == 0:
        return 0.0
    keyword_score = matched / len(query_tokens)

    # 3. 时间衰减
    age_hours = max(0.0, time.time() - entry.timestamp.timestamp()) / 3600
    time_decay = max(0.5, 1.0 - age_hours / 24)

    return keyword_score * time_decay


def rank(
    entries: Iterable[MemoryEntry],
    query: str,
    *,
    boost: float = 1.0,
    limit: int = 5,
    include_metadata: bool = False,
) -> list[tuple[float, MemoryEntry]]:
    """对给定记忆按相关度评分并取 topN，可乘加权 boost。"""
    scored = [
        (relevance_score(e, query, include_metadata=include_metadata) * boost, e)
        for e in entries
    ]
    scored = [(s, e) for s, e in scored if s > 0]
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[:limit]


def search(
    short_term: Iterable[MemoryEntry],
    long_term: Iterable[MemoryEntry],
    query: str,
    *,
    limit: int = 5,
) -> list[MemoryEntry]:
    """从短期 + 长期检索，长期权重 ×1.2（更精炼），长期同时匹配 metadata。"""
    combined = rank(short_term, query, boost=1.0, limit=limit * 2) + \
        rank(long_term, query, boost=1.2, limit=limit * 2, include_metadata=True)
    combined.sort(key=lambda x: x[0], reverse=True)
    return [e for _, e in combined[:limit]]


def search_long_only(
    long_term: Iterable[MemoryEntry],
    query: str,
    *,
    limit: int = 5,
) -> list[MemoryEntry]:
    """仅检索长期记忆，用于 system prompt 注入避免短期重复。

    短期对话已经在 message history 里，如果再注入"相关记忆"
    会让模型把当前请求误读成历史事实。
    """
    return [e for _, e in rank(long_term, query, boost=1.2, limit=limit, include_metadata=True)]


def build_context(
    long_term: Iterable[MemoryEntry],
    query: str,
    *,
    max_tokens: int = 500,
) -> str:
    """构造用于注入 LLM 的"相关长期记忆"片段。"""
    relevant = search_long_only(long_term, query, limit=10)
    if not relevant:
        return ""

    lines = ["## 相关长期记忆", ""]
    used = 0
    for entry in relevant:
        tc = entry.token_count or estimate_tokens(entry.content)
        if used + tc > max_tokens:
            break
        lines.append(f"- [{entry.type.name}] {entry.content}")
        used += tc
    lines.append("")
    return "\n".join(lines)
