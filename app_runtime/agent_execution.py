from __future__ import annotations

import logging
import threading
from typing import Any

from agent import ReactAgent
from sessions import RuntimeContextBuilder

log = logging.getLogger(__name__)


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
        for event in agent.events(user_input, context=context, cancel=cancel, journal=journal, turn_id=turn_id):
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
