from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Any

from agent import ReactAgent
from llm import Message, chat as default_chat, chat_stream as default_chat_stream
from memory import DEFAULT_LONG_TERM_NAME, TextLongTermMemory
from mcp_integration import McpServerManager, McpToolWrapper, load_mcp_config
from plan_mode import PlanModeState, register_plan_mode_guard
from plan_mode.agents import ExploreAgentTool, PlanAgentTool
from plugin_runtime import PluginManager
from sessions import NavigationPlan, SessionStore
from sessions.summarizer import generate_branch_summary
from tooling.defaults import build_default_tool_runtime, format_tool_list

from .agent_execution import run_agent_once as default_run_agent_once
from .events import EventBus
from .hooks import HookManager
from .session import PreparedAgentRun, SessionRuntime
from .skills import SkillManager, build_skill_roots
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
    plugin_manager: PluginManager
    hook_manager: HookManager
    session_runtime: SessionRuntime
    skill_manager: SkillManager
    task_runtime: TaskRuntime
    chat_fn: ChatFn
    chat_stream_fn: ChatFn
    mcp_manager: McpServerManager | None = None
    plan_mode_state: PlanModeState | None = None

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
        chat_stream_fn: ChatFn | None = None,
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
        plugin_manager = PluginManager(project_cwd, enabled_plugins=state_store.enabled_plugins())
        hook_manager = HookManager(event_bus=bus)
        hook_manager.install_default_tool_hooks()
        hook_manager.attach_tool_runtime(runtime_tools)
        skill_manager = SkillManager.create(
            project_cwd,
            skill_roots=build_skill_roots(
                project_cwd,
                plugin_roots=plugin_manager.contributions().skill_roots,
            ),
            state_store=state_store,
            event_bus=bus,
        )
        session_runtime = SessionRuntime(long_term_memory=memory)
        task_runtime = TaskRuntime()
        plan_state = PlanModeState()
        runtime = cls(
            cwd=project_cwd,
            tool_runtime=runtime_tools,
            session_store=store,
            long_term_memory=memory,
            event_bus=bus,
            state_store=state_store,
            plugin_manager=plugin_manager,
            hook_manager=hook_manager,
            session_runtime=session_runtime,
            skill_manager=skill_manager,
            task_runtime=task_runtime,
            chat_fn=chat_fn or default_chat,
            chat_stream_fn=chat_stream_fn or default_chat_stream,
            mcp_manager=mcp_manager,
            plan_mode_state=plan_state,
        )
        register_plan_mode_guard(runtime.tool_runtime, lambda: runtime.plan_mode_state.active if runtime.plan_mode_state else False)
        runtime.tool_runtime.registry.register(
            ExploreAgentTool(parent_runtime=runtime.tool_runtime, chat_stream_fn=runtime.chat_stream)
        )
        runtime.tool_runtime.registry.register(
            PlanAgentTool(parent_runtime=runtime.tool_runtime, chat_stream_fn=runtime.chat_stream)
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
            chat_stream_fn=self.chat_stream,
            conversation_messages=conversation_messages,
            on_message_appended=on_message_appended,
            plan_mode_active=lambda: self.plan_mode_state.active if self.plan_mode_state else False,
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

    def chat_stream(self, *args: Any, **kwargs: Any) -> Any:
        """Stream the configured LLM function through the runtime entrypoint."""
        return self.chat_stream_fn(*args, **kwargs)

    def build_branch_summary(self, plan: NavigationPlan) -> str:
        """Summarize the branch that will be left during session navigation."""
        return generate_branch_summary(plan, chat_fn=self.chat)

    def plugin_status(self) -> tuple[list[Any], list[Any]]:
        """Return loaded plugins and plugin diagnostics."""
        return self.plugin_manager.list_plugins(), self.plugin_manager.diagnostics()

    def set_plugin_enabled(self, name: str, enabled: bool) -> bool:
        """Enable or disable a plugin, then rebuild plugin-backed skill roots."""
        known = {plugin.manifest.id for plugin in self.plugin_manager.list_plugins()}
        if name not in known:
            return False

        self.state_store.set_plugin_enabled(name, enabled)
        self.refresh_plugins()
        self.event_bus.publish("plugin.enabled" if enabled else "plugin.disabled", name=name)
        return True

    def refresh_plugins(self) -> None:
        """Reload plugin contributions and refresh managers that consume them."""
        self.plugin_manager = PluginManager(self.cwd, enabled_plugins=self.state_store.enabled_plugins())
        self.skill_manager.refresh(
            skill_roots=build_skill_roots(
                self.cwd,
                plugin_roots=self.plugin_manager.contributions().skill_roots,
            ),
        )

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
