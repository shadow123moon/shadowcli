from __future__ import annotations

import logging
from pathlib import Path
from collections.abc import Callable

from dotenv import load_dotenv

from agent import ReactAgent
from llm import chat
from mcp_integration import load_mcp_config, McpServerManager, McpToolWrapper
from sessions import NavigationPlan, RuntimeContextBuilder, SessionManager, SessionStore, compact_session
from sessions.summarizer import generate_branch_summary
from .commands import (
    format_compaction_result,
    format_session_tree,
    format_memory_status,
    handle_remember,
    parse_compact_command,
    parse_jump_command,
    parse_plan_command,
    parse_remember_command,
    parse_tree_command,
)
from .constants import BANNER, HELP, MEMORY_COMMAND
from .factories import build_agent, build_long_term_memory, build_registry, list_tools
from .logging_config import configure_logging
from ui import (
    BranchNavigationChoice,
    Renderer,
    TerminalRenderer,
    ask_branch_navigation_choice,
)

log = logging.getLogger(__name__)


def run_once(
    agent: ReactAgent,
    user_input: str,
    *,
    plan_log_dir: Path | None = None,
    runtime_context_builder: RuntimeContextBuilder | None = None,
    renderer: Renderer | None = None,
) -> None:
    _ = plan_log_dir
    renderer = renderer or TerminalRenderer()
    try:
        plan_input = parse_plan_command(user_input)
        if plan_input is not None:
            if not plan_input:
                renderer.message("用法: /plan <任务>")
                return
            context = runtime_context_builder.build(plan_input) if runtime_context_builder is not None else ""
            _run_agent_events(agent, _single_agent_plan_prompt(plan_input), context=context, renderer=renderer)
        else:
            context = runtime_context_builder.build(user_input) if runtime_context_builder is not None else ""
            _run_agent_events(agent, user_input, context=context, renderer=renderer)
            # React 模式：已经流式打印，不再重复输出
    except Exception as e:
        log.exception("[入口] 执行失败")
        renderer.message(f"\n[ERROR] 执行失败: {e}")
        return


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


def navigate_session_branch(
    session: SessionManager,
    target_id: str | None,
    *,
    choose_navigation: Callable[[NavigationPlan], BranchNavigationChoice | str] = ask_branch_navigation_choice,
    build_branch_summary: Callable[[NavigationPlan], str] | None = None,
) -> BranchNavigationChoice:
    plan = session.plan_navigation(target_id)
    choice = BranchNavigationChoice(choose_navigation(plan))

    if choice == BranchNavigationChoice.CANCEL:
        return choice
    if choice == BranchNavigationChoice.DIRECT:
        session.branch_to(target_id)
        return choice

    if build_branch_summary is None:
        raise ValueError("build_branch_summary is required when branch navigation chooses summary")
    summary = build_branch_summary(plan)
    session.branch_to_with_summary(target_id, summary=summary)
    return choice


def reload_agent_conversation(agent: ReactAgent, session: SessionManager) -> None:
    if hasattr(agent, "replace_conversation_messages"):
        agent.replace_conversation_messages(session.messages())


def maybe_compact_before_run(
    session: SessionManager,
    agent: ReactAgent,
    long_term,
    runtime_context_builder: RuntimeContextBuilder,
    renderer: Renderer,
) -> RuntimeContextBuilder:
    try:
        result = compact_session(session, force=False, chat_fn=chat)
    except Exception as e:
        log.exception("[会话压缩] 自动压缩失败")
        renderer.message(f"[WARN] 自动压缩失败，继续使用未压缩上下文: {e}")
        return runtime_context_builder

    if not result.compacted:
        return runtime_context_builder

    reload_agent_conversation(agent, session)
    renderer.message(format_compaction_result(result))
    return RuntimeContextBuilder(session=session, long_term=long_term)


def repl(renderer: Renderer | None = None) -> int:
    renderer = renderer or TerminalRenderer()
    load_dotenv()
    configure_logging()
    runtime = build_registry()
    cwd = Path.cwd()
    session_store = SessionStore()
    session = session_store.open_recent(cwd) or session_store.create(cwd)
    long_term = build_long_term_memory(session_store.project_dir(cwd) / "long_term.md")

    # MCP 集成
    mcp_manager = McpServerManager()
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
        except Exception as e:
            mcp_failed += 1
            log.exception("MCP server '%s' failed", name)

    if mcp_loaded > 0:
        renderer.message(f"✓ 已加载 {mcp_loaded} 个 MCP server")
    if mcp_failed > 0:
        renderer.message(f"✗ {mcp_failed} 个 MCP server 启动失败")

    agent = build_agent(
        runtime,
        conversation_messages=session.messages(),
        on_message_appended=session.append_message,
    )
    runtime_context_builder = RuntimeContextBuilder(session=session, long_term=long_term)

    renderer.message(BANNER)

    try:
        while True:
            try:
                line = input("\n> ").strip()
            except (EOFError, KeyboardInterrupt):
                renderer.message("\n再见。")
                break

            if not line:
                continue
            if line in ("/quit", "/exit", "/q"):
                renderer.message("再见。")
                break
            if line == "/help":
                renderer.message(HELP)
                continue
            if line == "/tools":
                renderer.message(list_tools(runtime))
                continue
            if line == MEMORY_COMMAND:
                renderer.message(format_memory_status(long_term))
                continue
            if parse_tree_command(line):
                renderer.message(format_session_tree(session))
                continue
            if parse_compact_command(line) is not None:
                result = compact_session(session, force=True, chat_fn=chat)
                if result.compacted:
                    reload_agent_conversation(agent, session)
                    runtime_context_builder = RuntimeContextBuilder(session=session, long_term=long_term)
                renderer.message(format_compaction_result(result))
                continue
            jump_target = parse_jump_command(line)
            if jump_target is not None:
                if not jump_target:
                    renderer.message("用法: /jump <entry_id>")
                    continue
                try:
                    choice = navigate_session_branch(
                        session,
                        jump_target,
                        choose_navigation=renderer.branch_navigation_choice,
                        build_branch_summary=generate_branch_summary,
                    )
                except KeyError:
                    renderer.message(f"未找到会话节点: {jump_target}")
                    continue
                if choice != BranchNavigationChoice.CANCEL:
                    reload_agent_conversation(agent, session)
                    runtime_context_builder = RuntimeContextBuilder(session=session, long_term=long_term)
                    renderer.message(f"已跳转到: {session.get_leaf_id()}")
                else:
                    renderer.message("已取消跳转。")
                continue
            if parse_remember_command(line) is not None:
                renderer.message(handle_remember(long_term, line))
                continue
            if parse_plan_command(line) is not None:
                runtime_context_builder = maybe_compact_before_run(
                    session,
                    agent,
                    long_term,
                    runtime_context_builder,
                    renderer,
                )
                run_once(agent, line, runtime_context_builder=runtime_context_builder, renderer=renderer)
                continue
            if line.startswith("/"):
                renderer.message(f"未知命令: {line}  (输入 /help 查看)")
                continue

            runtime_context_builder = maybe_compact_before_run(
                session,
                agent,
                long_term,
                runtime_context_builder,
                renderer,
            )
            run_once(agent, line, runtime_context_builder=runtime_context_builder, renderer=renderer)
    finally:
        # 清理 MCP 资源
        log.debug("Shutting down MCP servers...")
        mcp_manager.shutdown()

    return 0
