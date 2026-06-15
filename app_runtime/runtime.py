from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Any

from agent import ReactAgent
from llm import Message, chat as default_chat
from memory import DEFAULT_LONG_TERM_NAME, TextLongTermMemory
from mcp_integration import McpServerManager, McpToolWrapper, load_mcp_config
from sessions import NavigationPlan, SessionStore
from sessions.summarizer import generate_branch_summary
from tooling.defaults import build_default_tool_runtime, format_tool_list

from .agent_execution import run_agent_once as default_run_agent_once
from .events import EventBus
from .hooks import HookManager
from .session import PreparedAgentRun, SessionRuntime
from .skills import SkillManager
from .state import AppStateStore
from .tasks import TaskRuntime


LongTermBuilder = Callable[[Path], Any]
ChatFn = Callable[..., Any]
log = logging.getLogger(__name__)


def _configure_logging_once() -> None:
    """配置日志（幂等，只在首次调用时生效）。"""
    from cli_app.logging_config import configure_logging
    configure_logging()


@dataclass
class AppRuntime:
    """Owns the live runtime resources used by the CLI turn loop."""

    cwd: Path
    tool_runtime: Any
    session_store: SessionStore
    long_term_memory: Any
    event_bus: EventBus
    state_store: AppStateStore
    hook_manager: HookManager
    session_runtime: SessionRuntime
    skill_manager: SkillManager
    task_runtime: TaskRuntime
    chat_fn: ChatFn
    mcp_manager: McpServerManager | None = None

    @classmethod
    def create(
        cls,
        cwd: Path | str,
        *,
        tool_runtime: Any | None = None,
        session_store: SessionStore | None = None,
        long_term_memory: Any | None = None,
        long_term_builder: LongTermBuilder | None = None,
        event_bus: EventBus | None = None,
        chat_fn: ChatFn | None = None,
        mcp_manager: McpServerManager | None = None,
    ) -> "AppRuntime":
        """Build the runtime container without starting external MCP servers."""
        _configure_logging_once()
        project_cwd = Path(cwd)
        runtime_tools = tool_runtime or build_default_tool_runtime()
        store = session_store or SessionStore()
        memory = long_term_memory
        if memory is None:
            builder = long_term_builder or TextLongTermMemory
            memory = builder(store.project_dir(project_cwd) / DEFAULT_LONG_TERM_NAME)

        bus = event_bus or EventBus()
        state_store = AppStateStore.create(project_cwd)
        hook_manager = HookManager(event_bus=bus)
        hook_manager.install_default_tool_hooks()
        hook_manager.attach_tool_runtime(runtime_tools)
        skill_manager = SkillManager.create(project_cwd, state_store=state_store, event_bus=bus)
        session_runtime = SessionRuntime(long_term_memory=memory)
        task_runtime = TaskRuntime()
        runtime = cls(
            cwd=project_cwd,
            tool_runtime=runtime_tools,
            session_store=store,
            long_term_memory=memory,
            event_bus=bus,
            state_store=state_store,
            hook_manager=hook_manager,
            session_runtime=session_runtime,
            skill_manager=skill_manager,
            task_runtime=task_runtime,
            chat_fn=chat_fn or default_chat,
            mcp_manager=mcp_manager,
        )
        runtime.event_bus.publish("runtime.created", cwd=project_cwd)
        return runtime

    def build_agent(
        self,
        *,
        conversation_messages: list[Message] | None = None,
        on_message_appended: Callable[[Message], None] | None = None,
    ) -> ReactAgent:
        """Create a ReAct agent bound to this runtime's tool runtime and chat entrypoint."""
        return ReactAgent(
            self.tool_runtime,
            chat=self.chat,
            conversation_messages=conversation_messages,
            on_message_appended=on_message_appended,
        )

    def run_agent_once(self, agent: ReactAgent, user_input: str, **kwargs: Any) -> str:
        """Execute one agent turn using the shared app-runtime execution path."""
        return default_run_agent_once(agent, user_input, **kwargs)

    def list_tools(self) -> str:
        """Return a user-facing list of tools currently registered in the runtime."""
        return format_tool_list(self.tool_runtime)

    def chat(self, *args: Any, **kwargs: Any) -> Any:
        """Call the configured LLM function through the runtime entrypoint."""
        return self.chat_fn(*args, **kwargs)

    def build_branch_summary(self, plan: NavigationPlan) -> str:
        """Summarize the branch that will be left during session navigation."""
        return generate_branch_summary(plan, chat_fn=self.chat)

    def load_mcp_tools(self, configs: dict[str, Any] | None = None) -> tuple[int, int]:
        """Start configured MCP servers and register their tools into the tool runtime."""
        mcp_configs = load_mcp_config() if configs is None else configs
        manager = self.mcp_manager or McpServerManager()
        self.mcp_manager = manager
        loaded = 0
        failed = 0

        for name, config in mcp_configs.items():
            if config.disabled:
                log.debug("MCP server '%s' is disabled, skipping", name)
                continue

            try:
                tools = manager.start_server_sync(name, config)
                for tool_def in tools:
                    wrapper = McpToolWrapper(name, tool_def, manager)
                    self.tool_runtime.registry.register(wrapper)
                loaded += 1
                log.debug("MCP server '%s' loaded (%d tools)", name, len(tools))
            except Exception:
                failed += 1
                log.exception("MCP server '%s' failed", name)

        self.event_bus.publish("mcp.tools_loaded", loaded=loaded, failed=failed)
        return loaded, failed

    def shutdown(self) -> None:
        """Release runtime-owned external resources such as MCP server processes."""
        if self.mcp_manager is None:
            return
        self.mcp_manager.shutdown()
        self.event_bus.publish("runtime.shutdown")
