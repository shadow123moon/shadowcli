from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from extensions.tool_runtime import BeforeExecuteHook

from .events import EventBus


@dataclass
class HookManager:
    event_bus: EventBus | None = None
    before_tool_execute_hooks: list[BeforeExecuteHook] = field(default_factory=list)
    _attached_tool_runtime: Any | None = field(default=None, init=False, repr=False)
    _default_tool_hooks_installed: bool = field(default=False, init=False, repr=False)

    def on_before_execute(self, hook: BeforeExecuteHook) -> None:
        self.before_tool_execute_hooks.append(hook)

    def attach_tool_runtime(self, runtime: Any) -> None:
        if self._attached_tool_runtime is runtime:
            return
        self._attached_tool_runtime = runtime
        runtime.on_before_execute(self.run_before_tool_execute)
        self._publish("hooks.tool_runtime.attached")

    def install_default_tool_hooks(self) -> None:
        if self._default_tool_hooks_installed:
            return
        self._default_tool_hooks_installed = True

        from tooling import register_freshness_guard

        register_freshness_guard(self)

        approval_mode = os.getenv("PAICLI_APPROVAL", "off").lower()
        if os.getenv("PAICLI_HITL") == "1":
            approval_mode = "human"

        if approval_mode in {"human", "hitl"}:
            from extensions import hitl

            hitl.register(self)
        elif approval_mode in {"ai", "reviewer"}:
            from extensions import reviewer

            reviewer.register(self)

        self._publish("hooks.default_tool_hooks.installed", approval_mode=approval_mode)

    def run_before_tool_execute(self, name: str, arguments: dict[str, Any], tool: Any) -> dict[str, Any] | None:
        for hook in self.before_tool_execute_hooks:
            result = hook(name, arguments, tool)
            if result and result.get("block"):
                return result
        return None

    def _publish(self, event_type: str, **payload: Any) -> None:
        if self.event_bus is not None:
            self.event_bus.publish(event_type, **payload)
