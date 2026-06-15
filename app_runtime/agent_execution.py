from __future__ import annotations

import inspect
import logging
import threading
from typing import Any

from agent import ReactAgent
from sessions import RuntimeContextBuilder

log = logging.getLogger(__name__)

PLAN_COMMAND = "/plan"


def run_agent_once(
    agent: ReactAgent,
    user_input: str,
    *,
    runtime_context_builder: RuntimeContextBuilder | None = None,
    renderer: Any,
    cancel: threading.Event | None = None,
    journal=None,
    turn_id: str | None = None,
) -> str:
    try:
        plan_input = _parse_plan_command(user_input)
        if plan_input is not None:
            if not plan_input:
                renderer.message("用法: /plan <任务>")
                return ""
            context = runtime_context_builder.build(plan_input) if runtime_context_builder is not None else ""
            return _run_agent_events(
                agent,
                _single_agent_plan_prompt(plan_input),
                context=context,
                renderer=renderer,
                cancel=cancel,
                journal=journal,
                turn_id=turn_id,
            )

        context = runtime_context_builder.build(user_input) if runtime_context_builder is not None else ""
        return _run_agent_events(
            agent,
            user_input,
            context=context,
            renderer=renderer,
            cancel=cancel,
            journal=journal,
            turn_id=turn_id,
        )
    except Exception as exc:
        log.exception("[入口] 执行失败")
        renderer.message(f"\n[ERROR] 执行失败: {exc}")
        return ""


def _parse_plan_command(line: str) -> str | None:
    stripped = line.strip()
    if stripped == PLAN_COMMAND:
        return ""
    if stripped.startswith(PLAN_COMMAND + " "):
        return stripped[len(PLAN_COMMAND):].strip()
    return None


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
    renderer: Any,
    cancel: threading.Event | None = None,
    journal=None,
    turn_id: str | None = None,
) -> str:
    content_parts: list[str] = []
    try:
        for event in _agent_events(
            agent,
            user_input,
            context=context,
            cancel=cancel,
            journal=journal,
            turn_id=turn_id,
        ):
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


def _agent_events(
    agent: ReactAgent,
    user_input: str,
    *,
    context: str,
    cancel: threading.Event | None,
    journal,
    turn_id: str | None,
):
    events = agent.events
    try:
        signature = inspect.signature(events)
    except (TypeError, ValueError):
        yield from events(user_input, context=context, cancel=cancel, journal=journal, turn_id=turn_id)
        return
    accepts_context_kwargs = any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        or parameter_name in {"cancel", "journal", "turn_id"}
        for parameter_name, parameter in signature.parameters.items()
    )
    if accepts_context_kwargs:
        yield from events(user_input, context=context, cancel=cancel, journal=journal, turn_id=turn_id)
    else:
        yield from events(user_input, context=context)
