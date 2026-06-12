from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .base import Tool
from .registry import ToolRegistry

BeforeExecuteHook = Callable[[str, dict[str, Any], Tool], dict[str, Any] | None]


class ToolExecutionBlocked(RuntimeError):
    """Raised when a tool hook blocks execution with a hard stop."""


class ToolRuntime:
    def __init__(self, registry: ToolRegistry):
        self.registry = registry
        self.before_execute_hooks: list[BeforeExecuteHook] = []

    def on_before_execute(self, hook: BeforeExecuteHook) -> None:
        self.before_execute_hooks.append(hook)

    def execute(self, name: str, arguments: dict[str, Any]) -> str:
        tool = self.registry.get(name)
        for hook in self.before_execute_hooks:
            result = hook(name, arguments, tool)
            if result and result.get("block"):
                reason = result.get("reason", "未知原因")
                if result.get("hard_stop", True):
                    raise ToolExecutionBlocked(reason)
                return f"操作被拒绝的原因：{reason}"

        return self.registry.execute(name, arguments)

    def get_all_definitions(self) -> list[dict]:
        return self.registry.get_all_definitions()

    def get(self, name: str) -> Tool:
        return self.registry.get(name)
