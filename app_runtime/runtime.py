from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sessions import SessionStore, TextLongTermMemory
from sessions.long_term import DEFAULT_LONG_TERM_NAME

from .events import EventBus
from .hooks import HookManager
from .session import PreparedAgentRun, SessionRuntime
from .skills import SkillManager
from .state import AppStateStore


LongTermBuilder = Callable[[Path], Any]


def _configure_logging_once() -> None:
    """配置日志（幂等，只在首次调用时生效）。"""
    from cli_app.logging_config import configure_logging
    configure_logging()


@dataclass
class AppRuntime:
    cwd: Path
    tool_runtime: Any
    session_store: SessionStore
    long_term_memory: Any
    event_bus: EventBus
    state_store: AppStateStore
    hook_manager: HookManager
    session_runtime: SessionRuntime
    skill_manager: SkillManager

    @classmethod
    def create(
        cls,
        cwd: Path | str,
        *,
        tool_runtime: Any,
        session_store: SessionStore | None = None,
        long_term_memory: Any | None = None,
        long_term_builder: LongTermBuilder | None = None,
        event_bus: EventBus | None = None,
    ) -> "AppRuntime":
        _configure_logging_once()
        project_cwd = Path(cwd)
        store = session_store or SessionStore()
        memory = long_term_memory
        if memory is None:
            builder = long_term_builder or TextLongTermMemory
            memory = builder(store.project_dir(project_cwd) / DEFAULT_LONG_TERM_NAME)

        bus = event_bus or EventBus()
        state_store = AppStateStore.create(project_cwd)
        hook_manager = HookManager(event_bus=bus)
        hook_manager.install_default_tool_hooks()
        hook_manager.attach_tool_runtime(tool_runtime)
        skill_manager = SkillManager.create(project_cwd, state_store=state_store, event_bus=bus)
        session_runtime = SessionRuntime(long_term_memory=memory)
        runtime = cls(
            cwd=project_cwd,
            tool_runtime=tool_runtime,
            session_store=store,
            long_term_memory=memory,
            event_bus=bus,
            state_store=state_store,
            hook_manager=hook_manager,
            session_runtime=session_runtime,
            skill_manager=skill_manager,
        )
        runtime.event_bus.publish("runtime.created", cwd=project_cwd)
        return runtime
