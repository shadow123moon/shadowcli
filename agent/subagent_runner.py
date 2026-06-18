from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from typing import Any

from llm import Message


DEFAULT_SUBAGENT_MAX_CHARS = 20000
DEFAULT_FORK_TIMEOUT_SECONDS = 120.0

ToolAllowed = Callable[[Any], bool]


class ReadOnlyRuntimeView:
    def __init__(self, parent_runtime: Any, *, tool_allowed: ToolAllowed):
        self.parent_runtime = parent_runtime
        self.tool_allowed = tool_allowed
        self.registry = self

    def get(self, name: str):
        tool = self.parent_runtime.get(name)
        if not self.tool_allowed(tool):
            raise KeyError(name)
        return tool

    def get_all_definitions(self) -> list[dict]:
        return [
            definition
            for definition in self.parent_runtime.get_all_definitions()
            if _definition_visible(definition, self.parent_runtime, self.tool_allowed)
        ]

    def execute(self, name: str, arguments: dict[str, Any], **context) -> str:
        self.get(name)
        return self.parent_runtime.execute(name, arguments, **context)


def run_subagent(
    *,
    name: str,
    system_prompt: str,
    task: str,
    parent_runtime: Any,
    chat_stream_fn: Any,
    agent_loop_factory: Any,
    tool_allowed: ToolAllowed,
    conversation_history: list[Message] | None = None,
    cancel: threading.Event | None = None,
    max_chars: int = DEFAULT_SUBAGENT_MAX_CHARS,
) -> str:
    runtime = ReadOnlyRuntimeView(parent_runtime, tool_allowed=tool_allowed)
    loop = agent_loop_factory(
        name=name,
        system_prompt=system_prompt,
        chat=chat_stream_fn,
        tool_registry=runtime,
        conversation_history=conversation_history or [],
        use_tools=True,
        plan_mode_active=lambda: True,
        cancel=cancel,
    )

    content_parts: list[str] = []
    for event in loop.execute(Message(role="user", content=task), allow_tools=True):
        if event.type == "content":
            content_parts.append(str(event.data))
        elif event.type == "error":
            return f"{name}_agent 执行失败: {event.data}"
        elif event.type == "done":
            break

    result = "".join(content_parts).strip()
    if not result:
        return f"{name}_agent 未返回内容。"
    if len(result) > max_chars:
        return result[:max_chars] + "\n...(已截断)"
    return result


def run_forked_subagents(
    *,
    tasks: list[str],
    system_prompt: str,
    parent_messages: list[Message],
    parent_runtime: Any,
    chat_stream_fn: Any,
    agent_loop_factory: Any,
    tool_allowed: ToolAllowed,
    cancel: threading.Event | None = None,
    timeout_seconds: float | None = None,
) -> list[str]:
    results = [""] * len(tasks)
    run_cancel = cancel or threading.Event()
    executor = ThreadPoolExecutor(max_workers=len(tasks))
    futures = {
        executor.submit(
            run_subagent,
            name=f"explore-{index + 1}",
            system_prompt=system_prompt,
            task=task,
            parent_runtime=parent_runtime,
            chat_stream_fn=chat_stream_fn,
            agent_loop_factory=agent_loop_factory,
            tool_allowed=tool_allowed,
            conversation_history=fork_history(parent_messages),
            cancel=run_cancel,
        ): index
        for index, task in enumerate(tasks)
    }
    pending = set(futures)
    deadline = time.monotonic() + (timeout_seconds or fork_timeout_seconds())

    try:
        while pending:
            if run_cancel.is_set():
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                run_cancel.set()
                break
            done, pending = wait(
                pending,
                timeout=min(0.05, remaining),
                return_when=FIRST_COMPLETED,
            )
            for future in done:
                index = futures[future]
                try:
                    results[index] = future.result()
                except Exception as exc:
                    results[index] = f"explore_agent 执行失败: {exc}"

        if pending:
            run_cancel.set()
            for future in pending:
                future.cancel()
                index = futures[future]
                results[index] = "explore_agent 已取消或超时。"
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    return results


def fork_history(messages: Any) -> list[Message]:
    return sanitize_fork_prefix(list(messages or []))


def sanitize_fork_prefix(messages: list[Message]) -> list[Message]:
    sanitized: list[Message] = []
    expected_tool_ids: set[str] = set()
    pending_assistant_index: int | None = None

    for message in messages:
        if expected_tool_ids:
            if message.role == "tool" and message.tool_call_id in expected_tool_ids:
                sanitized.append(message)
                expected_tool_ids.remove(str(message.tool_call_id))
                if not expected_tool_ids:
                    pending_assistant_index = None
                continue
            return sanitized[:pending_assistant_index]

        if message.role == "tool":
            return sanitized

        sanitized.append(message)
        if message.role == "assistant" and message.tool_calls:
            expected_tool_ids = {tool_call.id for tool_call in message.tool_calls if tool_call.id}
            pending_assistant_index = len(sanitized) - 1
            if not expected_tool_ids:
                return sanitized[:pending_assistant_index]

    if expected_tool_ids and pending_assistant_index is not None:
        return sanitized[:pending_assistant_index]
    return sanitized


def fork_timeout_seconds() -> float:
    raw = os.environ.get("SHADOWCLI_FORK_AGENT_TIMEOUT_SECONDS")
    if not raw:
        return DEFAULT_FORK_TIMEOUT_SECONDS
    try:
        return max(0.1, float(raw))
    except ValueError:
        return DEFAULT_FORK_TIMEOUT_SECONDS


def _definition_visible(definition: dict, runtime: Any, tool_allowed: ToolAllowed) -> bool:
    function = definition.get("function")
    if not isinstance(function, dict):
        return False
    name = function.get("name")
    if not name:
        return False
    try:
        return tool_allowed(runtime.get(str(name)))
    except KeyError:
        return False
