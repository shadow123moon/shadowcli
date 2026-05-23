"""审批 UI 契约。

对照 Java com.paicli.hitl.HitlHandler 的取舍：
- Java interface ↔ Python typing.Protocol（结构子类型，不强制继承）
- 用 @runtime_checkable 让 isinstance 检查可用，方便测试桩对接
- enabled 用属性而非 getter/setter
- 不写 SwitchableHitlHandler —— 目前只有 Terminal 一种 UI，
  YAGNI；将来加 TUI 再补
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from .request import ApprovalRequest
from .result import ApprovalResult


@runtime_checkable
class HitlHandler(Protocol):
    enabled: bool

    def request_approval(self, request: ApprovalRequest) -> ApprovalResult: ...
    def is_approved_all_by_tool(self, tool_name: str) -> bool: ...
    def is_approved_all_by_server(self, server_name: str | None) -> bool: ...
    def clear_approved_all(self) -> None: ...
