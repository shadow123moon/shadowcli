from __future__ import annotations

import logging
from pathlib import Path

from dotenv import load_dotenv

from agent import ReactAgent
from mcp_integration import load_mcp_config, McpServerManager, McpToolWrapper
from sessions import ContextBuilder, Session, SessionStore

from .commands import (
    format_memory_status,
    handle_remember,
    parse_plan_command,
    parse_remember_command,
)
from .constants import BANNER, HELP, MEMORY_COMMAND
from .factories import build_agent, build_memory, build_registry, list_tools
from .logging_config import configure_logging
from ui import print_message

log = logging.getLogger(__name__)


def run_once(
    agent: ReactAgent,
    user_input: str,
    *,
    plan_log_dir: Path | None = None,
    session: Session | None = None,
    context_builder: ContextBuilder | None = None,
) -> None:
    _ = plan_log_dir
    try:
        start_index = len(getattr(agent, "session_messages", []))
        plan_input = parse_plan_command(user_input)
        if plan_input is not None:
            if not plan_input:
                print_message("用法: /plan <任务>")
                return
            log.info("[入口] 识别为单 Agent 计划模式，任务长度 %d 字", len(plan_input))
            context = context_builder.build(plan_input) if context_builder is not None else ""
            result = agent.run(_single_agent_plan_prompt(plan_input), context=context)
            log.info("[入口] 单 Agent 计划模式完成，输出长度 %d 字", len(result or ""))
        else:
            log.info("[入口] 识别为普通对话，进入 React 模式，输入长度 %d 字", len(user_input))
            context = context_builder.build(user_input) if context_builder is not None else ""
            result = agent.run(user_input, context=context)
            # React 模式：已经流式打印，不再重复输出
            log.info("[入口] React 模式完成，输出长度 %d 字", len(result or ""))
        _append_new_session_messages(session, getattr(agent, "session_messages", []), start_index)
    except Exception as e:
        log.debug("[入口] 执行失败详情", exc_info=True)
        print_message(f"\n[ERROR] 执行失败: {e}")
        return


def _single_agent_plan_prompt(task: str) -> str:
    return "\n".join([
        "请用单 Agent 计划执行模式处理下面的任务。",
        "先给出简短执行计划，再按计划调用必要工具完成，最后总结结果。",
        "",
        f"任务：{task}",
    ])


def repl() -> int:
    load_dotenv()
    configure_logging()
    runtime = build_registry()
    cwd = Path.cwd()
    session_store = SessionStore()
    session = session_store.open_recent(cwd) or session_store.create(cwd)
    memory = build_memory(session_store.project_dir(cwd) / "long_term.json")

    # MCP 集成
    mcp_manager = McpServerManager()
    mcp_configs = load_mcp_config()

    mcp_loaded = 0
    mcp_failed = 0
    for name, config in mcp_configs.items():
        if config.disabled:
            log.info(f"MCP server '{name}' is disabled, skipping")
            continue

        try:
            tools = mcp_manager.start_server_sync(name, config)
            for tool_def in tools:
                wrapper = McpToolWrapper(name, tool_def, mcp_manager)
                runtime.registry.register(wrapper)
            mcp_loaded += 1
            log.info(f"✓ MCP server '{name}' loaded ({len(tools)} tools)")
        except Exception as e:
            mcp_failed += 1
            log.error(f"✗ MCP server '{name}' failed: {e}")

    if mcp_loaded > 0:
        print_message(f"✓ 已加载 {mcp_loaded} 个 MCP server")
    if mcp_failed > 0:
        print_message(f"✗ {mcp_failed} 个 MCP server 启动失败")

    agent = build_agent(runtime, memory, session_messages=session.messages())
    context_builder = ContextBuilder(session=session, long_term=memory.long_term)

    print_message(BANNER)

    try:
        while True:
            try:
                line = input("\n> ").strip()
            except (EOFError, KeyboardInterrupt):
                print_message("\n再见。")
                break

            if not line:
                continue
            if line in ("/quit", "/exit", "/q"):
                print_message("再见。")
                break
            if line == "/help":
                print_message(HELP)
                continue
            if line == "/tools":
                print_message(list_tools(runtime))
                continue
            if line == MEMORY_COMMAND:
                print_message(format_memory_status(memory))
                continue
            if parse_remember_command(line) is not None:
                print_message(handle_remember(memory, line))
                continue
            if parse_plan_command(line) is not None:
                run_once(agent, line, session=session, context_builder=context_builder)
                continue
            if line.startswith("/"):
                print_message(f"未知命令: {line}  (输入 /help 查看)")
                continue

            run_once(agent, line, session=session, context_builder=context_builder)
    finally:
        # 清理 MCP 资源
        log.info("Shutting down MCP servers...")
        mcp_manager.shutdown()

    return 0


def _append_new_session_messages(
    session: Session | None,
    messages,
    start_index: int,
) -> None:
    if session is None:
        return
    for message in messages[start_index:]:
        if message.role == "system":
            continue
        session.append_message(message)
