from __future__ import annotations

import logging
from pathlib import Path
import threading
from typing import TYPE_CHECKING

from dotenv import load_dotenv

from app_runtime import AppRuntime
from app_runtime.agent_execution import run_agent_once as runtime_run_agent_once
from mcp_integration import load_mcp_config
from memory import build_long_term_memory
from plugin_runtime import PluginManager
from sessions import RuntimeContextBuilder, SessionStore
from .constants import BANNER
from .router import ReplRouter
from .terminal_input import build_prompt
from ui import Renderer, TerminalRenderer

if TYPE_CHECKING:
    from agent import ReactAgent

log = logging.getLogger(__name__)


def run_once(
    agent: ReactAgent,
    user_input: str,
    *,
    runtime_context_builder: RuntimeContextBuilder | None = None,
    renderer: Renderer | None = None,
    cancel: threading.Event | None = None,
    journal=None,
    turn_id: str | None = None,
) -> str:
    renderer = renderer or TerminalRenderer()
    return runtime_run_agent_once(
        agent,
        user_input,
        runtime_context_builder=runtime_context_builder,
        renderer=renderer,
        cancel=cancel,
        journal=journal,
        turn_id=turn_id,
    )


def repl(renderer: Renderer | None = None) -> int:
    renderer = renderer or TerminalRenderer()
    load_dotenv()
    cwd = Path.cwd()
    app_runtime = AppRuntime.create(
        cwd,
        session_store=SessionStore(),
        long_term_builder=build_long_term_memory,
    )
    _log_plugin_diagnostics(app_runtime.skill_manager.plugin_manager)

    try:
        mcp_loaded, mcp_failed = app_runtime.load_mcp_tools(load_mcp_config())
        _render_mcp_status(renderer, mcp_loaded=mcp_loaded, mcp_failed=mcp_failed)

        router = ReplRouter(
            app_runtime=app_runtime,
            renderer=renderer,
            run_interactive_in_worker=True,
        )

        renderer.message(BANNER)
        prompt = build_prompt()

        while True:
            try:
                line = prompt().strip()
            except EOFError:
                router.wait_current(timeout=30)
                break
            except KeyboardInterrupt:
                if router.cancel_current(reason="ctrl_c"):
                    renderer.cancel_requested()
                    continue
                break

            if not router.route(line):
                router.wait_current(timeout=30)
                break
    finally:
        log.debug("Shutting down MCP servers...")
        app_runtime.shutdown()

    return 0


def _log_plugin_diagnostics(plugin_manager: PluginManager) -> None:
    for diagnostic in plugin_manager.diagnostics():
        log.warning("[插件] %s: %s", diagnostic.plugin_path, diagnostic.message)


def _render_mcp_status(renderer: Renderer, *, mcp_loaded: int, mcp_failed: int) -> None:
    if mcp_loaded > 0:
        renderer.message(f"✓ 已加载 {mcp_loaded} 个 MCP server")
    if mcp_failed > 0:
        renderer.message(f"✗ {mcp_failed} 个 MCP server 启动失败")
