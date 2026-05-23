"""短期记忆 ConversationMemory：FIFO 淘汰 + 待压缩列表。

Pythonic 要点：
- 容器协议             __len__ / __iter__ / __contains__ / __getitem__
                       让外界用 `for e in mem` / `len(mem)` / `id in mem` / `mem[id]`
- @property + setter   替代 get_xxx() / set_xxx()
- walrus :=            紧凑的"赋值并判断"
- __repr__             替代 get_status_summary
"""
from __future__ import annotations

from collections.abc import Iterator

from .entry import MemoryEntry


class ConversationMemory:
    """短期记忆：超 token 预算时 FIFO 淘汰最旧条目到 pending_compress。"""

    def __init__(self, max_tokens: int = 40_000):
        if max_tokens <= 0:
            raise ValueError("max_tokens must be positive")
        # python 3.7+ dict 已保证插入顺序
        self._entries: dict[str, MemoryEntry] = {}
        self._max_tokens = max_tokens
        self._current_tokens = 0
        self.pending_compress: list[MemoryEntry] = []

    # —— 容器协议 ——
    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self) -> Iterator[MemoryEntry]:
        return iter(self._entries.values())

    def __contains__(self, entry_id: str) -> bool:
        return entry_id in self._entries

    def __getitem__(self, entry_id: str) -> MemoryEntry:
        return self._entries[entry_id]

    # —— 写入 / 删除 ——
    def store(self, entry: MemoryEntry) -> None:
        self._entries[entry.id] = entry
        self._current_tokens += entry.token_count
        while self._current_tokens > self._max_tokens and len(self._entries) > 1:
            self._evict_oldest()

    def delete(self, entry_id: str) -> bool:
        if (removed := self._entries.pop(entry_id, None)) is None:
            return False
        self._current_tokens -= removed.token_count
        return True

    def clear(self) -> None:
        self._entries.clear()
        self._current_tokens = 0
        self.pending_compress.clear()

    # —— 检索 ——
    def search(self, query: str, limit: int = 5) -> list[MemoryEntry]:
        """按相关度评分检索短期记忆(走统一的 retrieval.rank 链路)。"""
        from .retrieval import rank
        return [e for _, e in rank(self, query, limit=limit)]

    # —— 容量管理 ——
    @property
    def total_tokens(self) -> int:
        return self._current_tokens

    @property
    def max_tokens(self) -> int:
        return self._max_tokens

    @max_tokens.setter
    def max_tokens(self, value: int) -> None:
        if value <= 0:
            raise ValueError("max_tokens must be positive")
        self._max_tokens = value
        while self._current_tokens > value and len(self._entries) > 1:
            self._evict_oldest()

    @property
    def usage_ratio(self) -> float:
        return self._current_tokens / self._max_tokens if self._max_tokens > 0 else 0.0

    # —— 压缩相关 ——
    def inject_summary(self, summary: MemoryEntry) -> None:
        """压缩完成后回注摘要：清空待压缩列表，把摘要插入主表。"""
        self.pending_compress.clear()
        self._entries[summary.id] = summary
        self._current_tokens += summary.token_count

    def _evict_oldest(self) -> None:
        oldest_id = next(iter(self._entries))
        oldest = self._entries.pop(oldest_id)
        self._current_tokens -= oldest.token_count
        self.pending_compress.append(oldest)

    def __repr__(self) -> str:
        return (
            f"ConversationMemory({len(self)} entries, "
            f"{self._current_tokens}/{self._max_tokens} tokens, "
            f"{self.usage_ratio:.0%} used, {len(self.pending_compress)} pending)"
        )
