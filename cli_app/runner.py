from __future__ import annotations

import logging
from pathlib import Path

from dotenv import load_dotenv

from agent import ReactAgent
from app_runtime import AppRuntime
from llm import chat
from mcp_integration import load_mcp_config, McpServerManager, McpToolWrapper
from plugin_runtime import PluginManager
from sessions import RuntimeContextBuilder, SessionStore
from sessions.summarizer import generate_branch_summary
from .commands import parse_plan_command
from .constants import BANNER
from .factories import build_agent, build_long_term_memory, build_registry, list_tools
from .router import ReplRouter
from .terminal_input import build_prompt
from ui import Renderer, TerminalRenderer

log = logging.getLogger(__name__)


def run_once(
    agent: ReactAgent,
    user_input: str,
    *,
    runtime_context_builder: RuntimeContextBuilder | None = None,
    renderer: Renderer | None = None,
) -> str:
    renderer = renderer or TerminalRenderer()
    try:
        plan_input = parse_plan_command(user_input)
        if plan_input is not None:
            if not plan_input:
                renderer.message("用法: /plan <任务>")
                return ""
            context = runtime_context_builder.build(plan_input) if runtime_context_builder is not None else ""
            return _run_agent_events(agent, _single_agent_plan_prompt(plan_input), context=context, renderer=renderer)
        else:
            context = runtime_context_builder.build(user_input) if runtime_context_builder is not None else ""
            return _run_agent_events(agent, user_input, context=context, renderer=renderer)
            # React 模式：已经流式打印，不再重复输出
    except Exception as e:
        log.exception("[入口] 执行失败")
        renderer.message(f"\n[ERROR] 执行失败: {e}")
        return ""


def _single_agent_plan_prompt(task: str) -> str:
    return "\n".join([
        "请用单 Agent 计划执行模式处理下面的任务。",
        "先给出简短执行计划，再按计划调用必要工具完成，最后总结结果。",
        "",
        f"任务：{task}",
    ])


def _run_agent_events(
    agent: ReactAgent,
    user_input: str,
    *,
    context: str = "",
    renderer: Renderer,
) -> str:
    content_parts: list[str] = []
    try:
        for event in agent.events(user_input, context=context):
            if event.type == "content":
                content_parts.append(event.data)
            renderer.agent_event(event, agent_name="react")
            if event.type == "done":
                break
    except KeyboardInterrupt:
        renderer.cancel_requested()
        agent.cancel()
        return "".join(content_parts) + "\n[已中止]"
    return "".join(content_parts)


def repl(renderer: Renderer | None = None) -> int:
    renderer = renderer or TerminalRenderer()
    load_dotenv()
    cwd = Path.cwd()
    app_runtime = AppRuntime.create(
        cwd,
        tool_runtime=build_registry(),
        session_store=SessionStore(),
        long_term_builder=build_long_term_memory,
    )
    _log_plugin_diagnostics(app_runtime.skill_manager.plugin_manager)

    mcp_manager = McpServerManager()
    try:
        mcp_loaded, mcp_failed = _load_mcp_tools(app_runtime.tool_runtime, mcp_manager)
        _render_mcp_status(renderer, mcp_loaded=mcp_loaded, mcp_failed=mcp_failed)

        router = ReplRouter(
            app_runtime=app_runtime,
            renderer=renderer,
            build_agent=build_agent,
            run_agent_once=run_once,
            list_tools=list_tools,
            chat_fn=chat,
            build_branch_summary=generate_branch_summary,
        )

        renderer.message(BANNER)
        prompt = build_prompt()

        while True:
            try:
                line = prompt().strip()
            except (EOFError, KeyboardInterrupt):
                break

            if not router.route(line):
                break
    finally:
        log.debug("Shutting down MCP servers...")
        mcp_manager.shutdown()

    return 0


def _log_plugin_diagnostics(plugin_manager: PluginManager) -> None:
    for diagnostic in plugin_manager.diagnostics():
        log.warning("[插件] %s: %s", diagnostic.plugin_path, diagnostic.message)


def _load_mcp_tools(runtime, mcp_manager: McpServerManager) -> tuple[int, int]:
    mcp_configs = load_mcp_config()
    mcp_loaded = 0
    mcp_failed = 0

    for name, config in mcp_configs.items():
        if config.disabled:
            log.debug("MCP server '%s' is disabled, skipping", name)
            continue

        try:
            tools = mcp_manager.start_server_sync(name, config)
            for tool_def in tools:
                wrapper = McpToolWrapper(name, tool_def, mcp_manager)
                runtime.registry.register(wrapper)
            mcp_loaded += 1
            log.debug("MCP server '%s' loaded (%d tools)", name, len(tools))
        except Exception:
            mcp_failed += 1
            log.exception("MCP server '%s' failed", name)

    return mcp_loaded, mcp_failed


def _render_mcp_status(renderer: Renderer, *, mcp_loaded: int, mcp_failed: int) -> None:
    if mcp_loaded > 0:
        renderer.message(f"✓ 已加载 {mcp_loaded} 个 MCP server")
    if mcp_failed > 0:
        renderer.message(f"✗ {mcp_failed} 个 MCP server 启动失败")
