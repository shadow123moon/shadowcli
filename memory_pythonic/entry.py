"""数据基础：MemoryEntry / MemoryType / Memory Protocol / estimate_tokens。

Pythonic 要点：
- @dataclass(slots=True)         省内存、防笔误（写错字段名会 AttributeError）
- Protocol + runtime_checkable   结构子类型，不强制继承
- str | None                     PEP-604 联合类型（Python 3.10+）
- 模块级 estimate_tokens         不藏在类里
"""
from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Protocol, runtime_checkable


def estimate_tokens(text: str | None) -> int:
    """中文 1.5 字/token，其他字符 4 字/token。"""
    if not text:
        return 0
    chinese = sum(1 for c in text if "一" <= c <= "鿿")
    other = len(text) - chinese
    return max(1, int(chinese / 1.5 + other / 4 + 0.999))


class MemoryType(Enum):
    CONVERSATION = "CONVERSATION"
    FACT = "FACT"
    SUMMARY = "SUMMARY"
    TOOL_RESULT = "TOOL_RESULT"


@dataclass(slots=True)
class MemoryEntry:
    """一条记忆条目。token_count 在 __post_init__ 自动从 content 算出。"""

    id: str
    content: str
    type: MemoryType = MemoryType.CONVERSATION
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, str] = field(default_factory=dict)
    token_count: int = 0

    def __post_init__(self) -> None:
        if self.token_count <= 0:
            self.token_count = estimate_tokens(self.content)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "content": self.content,
            "type": self.type.value,
            "timestamp": self.timestamp.isoformat(),
            "metadata": dict(self.metadata),
            "tokenCount": self.token_count,
        }

    @classmethod
    def from_dict(cls, data: Mapping) -> MemoryEntry:
        ts = data.get("timestamp")
        if isinstance(ts, str) and ts:
            try:
                timestamp = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                timestamp = datetime.now(timezone.utc)
        elif isinstance(ts, (int, float)):
            timestamp = datetime.fromtimestamp(float(ts), tz=timezone.utc)
        else:
            timestamp = datetime.now(timezone.utc)

        return cls(
            id=str(data["id"]),
            content=str(data.get("content", "")),
            type=MemoryType(data.get("type", MemoryType.CONVERSATION.value)),
            timestamp=timestamp,
            metadata={str(k): str(v) for k, v in (data.get("metadata") or {}).items()},
            token_count=int(data.get("tokenCount", data.get("token_count", 0)) or 0),
        )


@runtime_checkable
class Memory(Protocol):
    """记忆存储的结构契约。

    实现这个 Protocol 不需要显式继承，只要类有这些方法即可（duck typing）。
    用 isinstance(x, Memory) 也能在运行时检查（因为 @runtime_checkable）。
    """

    def store(self, entry: MemoryEntry) -> None: ...
    def search(self, query: str, limit: int = 5) -> list[MemoryEntry]: ...
    def delete(self, entry_id: str) -> bool: ...
    def clear(self) -> None: ...

    def __contains__(self, entry_id: str) -> bool: ...
    def __getitem__(self, entry_id: str) -> MemoryEntry: ...
    def __iter__(self) -> Iterator[MemoryEntry]: ...
    def __len__(self) -> int: ...

    @property
    def total_tokens(self) -> int: ...
