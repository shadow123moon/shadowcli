"""HITL 与 ToolRegistry 的集成层。

对照 Java com.paicli.hitl.HitlToolRegistry 的取舍：
- Java 继承 ToolRegistry 覆写 executeTool
  Python 用 *组合* —— 持有内部 registry，转发查询、拦截 execute
- Python 原 ToolRegistry 没有 execute 方法，所以 gate 顺势补一个 execute(name, args) 入口
- Audit log 用可注入 hook（Python 端尚无 audit 子系统）
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Protocol

from . import policy
from .handler import HitlHandler
from .request import ApprovalRequest
from .result import ApprovalResult

# 审计 hook：(tool_name, args, result, reason) → None
AuditHook = Callable[[str, Dict[str, Any], ApprovalResult, str], None]


class _RegistryLike(Protocol):
    """复刻 tool_registry.ToolRegistry 的最小契约。"""

    def get(self, name: str) -> Any: ...
    def get_all_definitions(self) -> List[Dict[str, Any]]: ...


class HitlToolRegistry:
    """ToolRegistry 的 HITL 包装器。

    用法::

        base = ToolRegistry()
        base.register(WriteFileTool())
        gate = HitlToolRegistry(base, TerminalHitlHandler(enabled=True))
        gate.execute("write_file", {"path": "/tmp/x", "content": "..."})
    """

    def __init__(
        self,
        inner: _RegistryLike,
        handler: HitlHandler,
        audit_hook: AuditHook | None = None,
    ) -> None:
        self._inner = inner
        self._handler = handler
        self._audit = audit_hook

    # ---------- 转发原 registry API ----------
    def get(self, name: str) -> Any:
        return self._inner.get(name)

    def get_all_definitions(self) -> List[Dict[str, Any]]:
        return self._inner.get_all_definitions()

    def register(self, tool: Any) -> None:
        register = getattr(self._inner, "register", None)
        if register is None:
            raise AttributeError("inner registry 不支持 register()")
        register(tool)

    @property
    def handler(self) -> HitlHandler:
        return self._handler

    # ---------- 核心：审批后再执行 ----------
    def execute(self, name: str, arguments: Dict[str, Any]) -> str:
        if not self._handler.enabled or not policy.requires_approval(name,arguments):
            return self._inner.get(name).execute(arguments)

        server = policy.mcp_server_name(name)
        if (self._handler.is_approved_all_by_tool(name)
                or self._handler.is_approved_all_by_server(server)):
            return self._inner.get(name).execute(arguments)

        request = ApprovalRequest(tool_name=name, arguments=arguments)
        result = self._handler.request_approval(request)

        if result.is_rejected:
            reason = result.reason or "用户拒绝了此操作"
            self._record_audit(name, arguments, result, reason)
            return f"[HITL] 操作已被拒绝：{reason}"
        if result.is_skipped:
            self._record_audit(name, arguments, result, "用户跳过")
            return "[HITL] 操作已被跳过"

        effective = result.effective_arguments(arguments)
        return self._inner.get(name).execute(effective)

    def _record_audit(
        self,
        name: str,
        args: Dict[str, Any],
        result: ApprovalResult,
        reason: str,
    ) -> None:
        if self._audit is not None:
            self._audit(name, args, result, reason)


def with_hitl(
    registry: _RegistryLike,
    handler: HitlHandler,
    audit_hook: AuditHook | None = None,
) -> HitlToolRegistry:
    """便捷工厂：包装一个 registry。"""
    return HitlToolRegistry(registry, handler, audit_hook)
