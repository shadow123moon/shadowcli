"""审批决策结果。

对照 Java com.paicli.hitl.ApprovalResult 的取舍：
- Java record + 静态工厂方法 ↔ Python @dataclass(frozen, slots) + @classmethod
- Java 的 isXxx() getter ↔ Python @property
- Java 把 modifiedArguments 存 String(JSON)；Python 直接存 dict，避免反复 parse
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class Decision(Enum):
    APPROVED = "approved"
    APPROVED_ALL = "approved_all"
    APPROVED_ALL_BY_SERVER = "approved_all_by_server"
    REJECTED = "rejected"
    MODIFIED = "modified"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class ApprovalResult:
    decision: Decision
    modified_arguments: dict[str, Any] | None = None
    reason: str | None = None

    # ---------- 工厂 ----------
    @classmethod
    def approve(cls) -> "ApprovalResult":
        return cls(Decision.APPROVED)

    @classmethod
    def approve_all(cls) -> "ApprovalResult":
        return cls(Decision.APPROVED_ALL)

    @classmethod
    def approve_all_by_server(cls) -> "ApprovalResult":
        return cls(Decision.APPROVED_ALL_BY_SERVER)

    @classmethod
    def reject(cls, reason: str | None = None) -> "ApprovalResult":
        return cls(Decision.REJECTED, reason=reason)

    @classmethod
    def modify(cls, arguments: dict[str, Any]) -> "ApprovalResult":
        return cls(Decision.MODIFIED, modified_arguments=arguments)

    @classmethod
    def skip(cls) -> "ApprovalResult":
        return cls(Decision.SKIPPED)

    # ---------- 查询 ----------
    @property
    def is_approved(self) -> bool:
        return self.decision in {
            Decision.APPROVED,
            Decision.APPROVED_ALL,
            Decision.APPROVED_ALL_BY_SERVER,
            Decision.MODIFIED,
        }

    @property
    def is_rejected(self) -> bool:
        return self.decision is Decision.REJECTED

    @property
    def is_skipped(self) -> bool:
        return self.decision is Decision.SKIPPED

    @property
    def is_approved_all_by_tool(self) -> bool:
        return self.decision is Decision.APPROVED_ALL

    @property
    def is_approved_all_by_server(self) -> bool:
        return self.decision is Decision.APPROVED_ALL_BY_SERVER

    def effective_arguments(self, original: dict[str, Any]) -> dict[str, Any]:
        """MODIFIED 返回用户修改后的参数；其他决策返回原参数。"""
        if self.decision is Decision.MODIFIED and self.modified_arguments is not None:
            return self.modified_arguments
        return original
