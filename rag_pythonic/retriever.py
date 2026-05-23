"""代码检索器：语义 + 关键词的混合检索。

对照 Java 版的核心打分逻辑（完整保留）：
1. 语义检索（base 相似度 0..1） + 关键词检索（base 0.3 + name/file/content 加分）
2. 同 key 合并：取两路最高分，再 +0.1 双重命中奖励（每 key 只加一次）
3. 类型加分：method +0.15, class +0.10
4. 同文件限流：最多 2 条 / 文件，避免一个长文件刷屏

Pythonic 要点：
- dataclasses.replace        改 SearchResult 一个字段就回写
- collections.OrderedDict    保序去重
- 模块级函数 + EmbedFn 注入   不绑死单一 embedding 客户端
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from .embedding import EmbedFn, mock_embed
from .store import SearchResult, VectorStore
from .tokenizer import tokenize

# 类型加分（与 Java 版一致）
_TYPE_BOOST = {"method": 0.15, "class": 0.10}

# 双重命中奖励
_DUAL_MATCH_BONUS = 0.1

# 关键词命中各位置的加分
_KW_BONUS_NAME = 0.3
_KW_BONUS_FILE = 0.1
_KW_BONUS_CONTENT = 0.1


class CodeRetriever:
    """语义 + 关键词混合检索的统一入口。"""

    def __init__(self, store: VectorStore, embed_fn: EmbedFn | None = None):
        """
        :param store: 已索引好的 VectorStore
        :param embed_fn: 把 query 转向量的函数；默认用 mock_embed
        """
        self.store = store
        self.embed_fn: EmbedFn = embed_fn or mock_embed

    # ---------- 单路检索 ----------
    def semantic_search(self, query: str, top_k: int) -> list[SearchResult]:
        return self.store.search(self.embed_fn(query), top_k)

    def keyword_search(self, keyword: str) -> list[SearchResult]:
        return self.store.search_by_keyword(keyword)

    # ---------- 混合检索 ----------
    def hybrid_search(self, query: str, top_k: int) -> list[SearchResult]:
        merged: dict[str, SearchResult] = {}
        bonused: set[str] = set()

        # 1. 语义检索：拉宽到 2*topK，保留更多候选给关键词加分用
        semantic_limit = max(top_k * 2, 10)
        for r in self.semantic_search(query, semantic_limit):
            _merge(merged, r, bonused)

        # 2. 关键词检索：每个 token 都查一次
        for kw in tokenize(query):
            for r in self.keyword_search(kw):
                _merge(merged, _boost_keyword(r, kw), bonused)

        # 3. 类型加分
        ranked: list[SearchResult] = []
        for r in merged.values():
            boost = _TYPE_BOOST.get(r.chunk_type, 0.0)
            ranked.append(r if boost == 0.0 else replace(r, similarity=r.similarity + boost))

        ranked.sort(key=lambda x: x.similarity, reverse=True)
        return _limit_per_file(ranked, top_k=top_k, max_per_file=2)


def _merge(merged: dict[str, SearchResult], candidate: SearchResult, bonused: set[str]) -> None:
    """同 key 合并：保留最高分，第一次同时命中两路再 +0.1。"""
    key = f"{candidate.file_path}#{candidate.name}"
    existing = merged.get(key)
    if existing is None:
        merged[key] = candidate
        return

    best = max(existing.similarity, candidate.similarity)
    if key not in bonused:
        best += _DUAL_MATCH_BONUS
        bonused.add(key)
    merged[key] = replace(candidate, similarity=best)


def _boost_keyword(result: SearchResult, keyword: str) -> SearchResult:
    """关键词命中位置加分：name 命中最强（类/方法名直接匹配）。"""
    kw = keyword.lower()
    bonus = 0.0
    if kw in result.name.lower():
        bonus += _KW_BONUS_NAME
    if kw in result.file_path.lower():
        bonus += _KW_BONUS_FILE
    if kw in result.content.lower():
        bonus += _KW_BONUS_CONTENT
    if bonus == 0.0:
        return result
    return replace(result, similarity=result.similarity + bonus)


def _limit_per_file(sorted_results: list[SearchResult], *, top_k: int, max_per_file: int) -> list[SearchResult]:
    """同一文件最多 max_per_file 条，总数 ≤ top_k。"""
    out: list[SearchResult] = []
    counts: dict[str, int] = {}
    for r in sorted_results:
        if counts.get(r.file_path, 0) >= max_per_file:
            continue
        out.append(r)
        counts[r.file_path] = counts.get(r.file_path, 0) + 1
        if len(out) >= top_k:
            break
    return out
