"""向量存储：内存版（dict + numpy）。

对照 Java 版的取舍：
- Java 用 SQLite 持久化 + JSON 序列化向量，启动时无成本，规模上千 chunk 也够。
- 这里改成内存 dict + numpy 矩阵：每次启动需要重新索引，但代码量小，
  原型 / 测试 / CI 更顺手。需要持久化时可以 pickle.dump(store._records, fp)。

Pythonic 要点：
- @dataclass(slots=True) for SearchResult / IndexStats   替代 Java record
- 容器协议 __len__ / __iter__ / __contains__
- numpy 一次 stack + 矩阵乘法                            替代 Java 逐条循环算余弦
- with VectorStore() 上下文 (no-op，与 Java AutoCloseable 形态一致)
"""
from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from .embedding import cosine_similarity, to_array

if TYPE_CHECKING:
    from .chunk import CodeChunk


@dataclass(slots=True)
class SearchResult:
    """检索结果。"""

    file_path: str
    chunk_type: str
    name: str
    content: str
    similarity: float


@dataclass(slots=True)
class IndexStats:
    chunk_count: int
    relation_count: int = 0  # 保留字段：原 Java 版统计关系图谱用


@dataclass(slots=True)
class _Record:
    """内部记录：CodeChunk + 它的向量（np.ndarray）。"""

    chunk: CodeChunk
    embedding: np.ndarray


class VectorStore:
    """内存向量存储 + 关键词检索。"""

    def __init__(self):
        # key = chunk.key()，重复 key 后插入覆盖前者
        self._records: dict[str, _Record] = {}

    # ---------- 容器协议 ----------
    def __len__(self) -> int:
        return len(self._records)

    def __iter__(self) -> Iterator[_Record]:
        return iter(self._records.values())

    def __contains__(self, key: str) -> bool:
        return key in self._records

    # ---------- 写入 ----------
    def clear(self) -> None:
        self._records.clear()

    def insert_chunks(self, entries: Iterable[tuple[CodeChunk, list[float]]]) -> None:
        """批量插入 (chunk, embedding) 对。"""
        for chunk, embedding in entries:
            self._records[chunk.key()] = _Record(chunk=chunk, embedding=to_array(embedding))

    # ---------- 检索 ----------
    def search(self, query_embedding: list[float] | np.ndarray, top_k: int) -> list[SearchResult]:
        """语义检索：返回相似度 TopK 的 chunk。"""
        if not self._records:
            return []

        query = to_array(query_embedding)
        scored: list[SearchResult] = []
        for record in self._records.values():
            sim = cosine_similarity(query, record.embedding)
            scored.append(SearchResult(
                file_path=record.chunk.file_path,
                chunk_type=record.chunk.chunk_type,
                name=record.chunk.name,
                content=record.chunk.content,
                similarity=sim,
            ))
        scored.sort(key=lambda r: r.similarity, reverse=True)
        return scored[:top_k]

    def search_by_keyword(self, keyword: str) -> list[SearchResult]:
        """关键词检索：name / content 子串匹配，固定 base 相似度 0.3。

        base 0.3 是为了让关键词命中加上后续 boost 后，最高约 0.8，不压过语义结果（max 1.0）。
        """
        if not keyword:
            return []
        kw = keyword.lower()
        results: list[SearchResult] = []
        for record in self._records.values():
            chunk = record.chunk
            if kw in chunk.name.lower() or kw in chunk.content.lower():
                results.append(SearchResult(
                    file_path=chunk.file_path,
                    chunk_type=chunk.chunk_type,
                    name=chunk.name,
                    content=chunk.content,
                    similarity=0.3,
                ))
        return results

    # ---------- 统计 ----------
    def stats(self) -> IndexStats:
        return IndexStats(chunk_count=len(self._records))

    # ---------- 上下文管理（API 兼容，无资源需释放） ----------
    def close(self) -> None:
        pass

    def __enter__(self) -> VectorStore:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"VectorStore({len(self)} chunks)"
