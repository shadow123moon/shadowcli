"""长期记忆 LongTermMemory：原子写入 + 内容去重。

Pythonic 要点：
- 容器协议                __len__ / __iter__ / __contains__ / __getitem__
- walrus :=               紧凑的 if-with-side-effect
- Path.read_text          替代 open + read 两步
- Path.unlink(missing_ok) 不再 try/except OSError
- 模块级辅助函数          _default_storage_dir 不是私有方法
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

from .entry import MemoryEntry, MemoryType

log = logging.getLogger(__name__)

DEFAULT_STORAGE_NAME = "long_term_memory.json"


def _default_storage_dir() -> Path:
    """PAICLI_MEMORY_DIR 环境变量 > ~/.paicli/memory。"""
    if (env := os.environ.get("PAICLI_MEMORY_DIR")) and env.strip():
        return Path(env)
    return Path.home() / ".paicli" / "memory"


class LongTermMemory:
    """长期记忆：内容相同视为重复，落盘走原子写。"""

    def __init__(self, storage: Path | None = None):
        """
        :param storage: 可以是目录（追加默认文件名）或具体 .json 文件路径；
                        None 则用 PAICLI_MEMORY_DIR 或 ~/.paicli/memory。
        """
        self._path = self._resolve(storage)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._entries: dict[str, MemoryEntry] = {}
        self._total_tokens = 0
        self._load()

    # —— 容器协议 ——
    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self) -> Iterator[MemoryEntry]:
        return iter(self._entries.values())

    def __contains__(self, entry_id: str) -> bool:
        return entry_id in self._entries

    def __getitem__(self, entry_id: str) -> MemoryEntry:
        return self._entries[entry_id]

    # —— 写入 ——
    def store(self, entry: MemoryEntry) -> None:
        normalized = entry.content.strip()
        if any(e.content.strip() == normalized for e in self):
            return  # 去重
        self._entries[entry.id] = entry
        self._total_tokens += entry.token_count
        self._save()

    def delete(self, entry_id: str) -> bool:
        if (removed := self._entries.pop(entry_id, None)) is None:
            return False
        self._total_tokens -= removed.token_count
        self._save()
        return True

    def clear(self) -> None:
        self._entries.clear()
        self._total_tokens = 0
        self._save()

    # —— 检索 ——
    def search(self, query: str, limit: int = 5) -> list[MemoryEntry]:
        """按相关度评分检索长期记忆,同时匹配 content 和 metadata。"""
        from .retrieval import rank
        return [e for _, e in rank(self, query, limit=limit, include_metadata=True)]

    def by_type(self, mem_type: MemoryType) -> list[MemoryEntry]:
        return [e for e in self if e.type == mem_type]

    # —— 属性 ——
    @property
    def total_tokens(self) -> int:
        return self._total_tokens

    @property
    def storage_path(self) -> Path:
        return self._path

    # —— 内部 ——
    @staticmethod
    def _resolve(storage: Path | None) -> Path:
        if storage is None:
            return _default_storage_dir() / DEFAULT_STORAGE_NAME
        path = Path(storage)
        # 目录或无后缀路径视为存储目录，否则视为完整文件路径
        return path / DEFAULT_STORAGE_NAME if path.is_dir() or path.suffix == "" else path

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("长期记忆加载失败: %s", exc)
            return

        if not isinstance(raw, list):
            log.warning("长期记忆文件格式异常（非数组），跳过加载")
            return

        for item in raw:
            try:
                entry = MemoryEntry.from_dict(item)
            except Exception as exc:
                log.warning("跳过无法解析的条目: %s", exc)
                continue
            self._entries[entry.id] = entry
            self._total_tokens += entry.token_count
        log.info("加载了 %d 条长期记忆", len(self))

    def _save(self) -> None:
        """原子写入：tempfile + os.replace。"""
        try:
            payload = [e.to_dict() for e in self]
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp_fd, tmp_path = tempfile.mkstemp(
                prefix=f"{self._path.name}.",
                suffix=".tmp",
                dir=str(self._path.parent),
            )
            try:
                with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False, indent=2)
                os.replace(tmp_path, self._path)
            except Exception:
                Path(tmp_path).unlink(missing_ok=True)
                raise
        except OSError as exc:
            log.warning("长期记忆持久化失败: %s", exc)

    def __repr__(self) -> str:
        counts: dict[str, int] = {}
        for e in self:
            counts[e.type.name] = counts.get(e.type.name, 0) + 1
        counts_str = ", ".join(f"{k}={v}" for k, v in counts.items()) or "empty"
        return (
            f"LongTermMemory({len(self)} entries, {self._total_tokens} tokens, {counts_str})"
        )
