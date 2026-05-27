from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from dotenv import load_dotenv

from agent import ReactAgent
from multi_agent import AgentOrchestrator

from .commands import (
    format_memory_status,
    handle_remember,
    parse_plan_command,
    parse_remember_command,
)
from .constants import BANNER, HELP, MEMORY_COMMAND
from .factories import build_agent, build_memory, build_plan_agent, build_registry, list_tools
from .logging_config import configure_logging
from .plan_logs import PlanLogSession
from .terminal_ui import print_final_result, print_message

log = logging.getLogger(__name__)


def run_once(
    agent: ReactAgent,
    plan_agent: AgentOrchestrator,
    user_input: str,
    *,
    plan_log_dir: Path | None = None,
) -> None:
    plan_log_path: Path | None = None
    try:
        plan_input = parse_plan_command(user_input)
        if plan_input is not None:
            if not plan_input:
                print_message("用法: /plan <任务>")
                return
            with PlanLogSession(plan_input, plan_log_dir) as plan_log:
                plan_log_path = plan_log.path
                log.info("[入口] 识别为计划模式，任务长度 %d 字", len(plan_input))
                result = asyncio.run(plan_agent.run(plan_input))
                title = "计划模式结果:"
                log.info("[入口] 准备输出%s，内容长度 %d 字", title, len(result or ""))
                print_final_result(title, result, plan_log_path)
        else:
            log.info("[入口] 识别为普通对话，进入 React 模式，输入长度 %d 字", len(user_input))
            result = agent.run(user_input)
            # React 模式：已经流式打印，不再重复输出
            log.info("[入口] React 模式完成，输出长度 %d 字", len(result or ""))
    except Exception as e:
        log.debug("[入口] 执行失败详情", exc_info=True)
        print_message(f"\n[ERROR] 执行失败: {e}")
        return


def repl() -> int:
    load_dotenv()
    configure_logging()
    registry = build_registry()
    memory = build_memory()
    agent = build_agent(registry, memory)
    plan_agent = build_plan_agent(registry, memory)

    print_message(BANNER)

    while True:
        try:
            line = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print_message("\n再见。")
            return 0

        if not line:
            continue
        if line in ("/quit", "/exit", "/q"):
            print_message("再见。")
            return 0
        if line == "/help":
            print_message(HELP)
            continue
        if line == "/tools":
            print_message(list_tools(registry))
            continue
        if line == MEMORY_COMMAND:
            print_message(format_memory_status(memory))
            continue
        if parse_remember_command(line) is not None:
            print_message(handle_remember(memory, line))
            continue
        if parse_plan_command(line) is not None:
            run_once(agent, plan_agent, line)
            continue
        if line.startswith("/"):
            print_message(f"未知命令: {line}  (输入 /help 查看)")
            continue

        run_once(agent, plan_agent, line)
