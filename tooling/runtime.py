from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import json
import threading
from typing import Any

from .base import Tool
from .registry import ToolRegistry

BeforeExecuteHook = Callable[[str, dict[str, Any], Tool], dict[str, Any] | None]


class ToolExecutionBlocked(RuntimeError):
    """Raised when a tool hook blocks execution with a hard stop."""


@dataclass
class ToolExecutionContext:
    cancel: threading.Event | None = None
    journal: Any | None = None
    turn_id: str | None = None
    tool_call_id: str | None = None


class ToolRuntime:
    def __init__(self, registry: ToolRegistry):
        self.registry = registry
        self.before_execute_hooks: list[BeforeExecuteHook] = []

    def on_before_execute(self, hook: BeforeExecuteHook) -> None:
        self.before_execute_hooks.append(hook)

    def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        cancel: threading.Event | None = None,
        journal: Any | None = None,
        turn_id: str | None = None,
        tool_call_id: str | None = None,
    ) -> str:
        tool = self.registry.get(name)
        for hook in self.before_execute_hooks:
            result = hook(name, arguments, tool)
            if result and result.get("block"):
                reason = result.get("reason", "未知原因")
                if result.get("hard_stop", True):
                    raise ToolExecutionBlocked(reason)
                return f"操作被拒绝的原因：{reason}"

        context = ToolExecutionContext(
            cancel=cancel,
            journal=journal,
            turn_id=turn_id,
            tool_call_id=tool_call_id,
        )
        started = False
        if journal is not None and getattr(tool, "effect", "write") != "read":
            started = True
            journal.append(
                "tool_started",
                turn_id=turn_id,
                tool_call_id=tool_call_id,
                name=name,
                effect=getattr(tool, "effect", "write"),
                args_preview=_preview_arguments(arguments),
            )
        try:
            execute_with_context = getattr(tool, "execute_with_context", None)
            if callable(execute_with_context):
                result_text = execute_with_context(arguments, context)
            else:
                result_text = tool.execute(arguments)
        except Exception:
            if started:
                journal.append(
                    "tool_finished",
                    turn_id=turn_id,
                    tool_call_id=tool_call_id,
                    name=name,
                    status="error",
                )
            raise

        if started:
            status = "cancelled_or_unknown" if cancel is not None and cancel.is_set() else "finished"
            journal.append(
                "tool_finished",
                turn_id=turn_id,
                tool_call_id=tool_call_id,
                name=name,
                status=status,
            )
        return result_text

    def get_all_definitions(self) -> list[dict]:
        return self.registry.get_all_definitions()

    def get(self, name: str) -> Tool:
        return self.registry.get(name)


def _preview_arguments(arguments: dict[str, Any], limit: int = 240) -> str:
    try:
        text = json.dumps(arguments, ensure_ascii=False, sort_keys=True)
    except TypeError:
        text = str(arguments)
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[:limit] + "..."
