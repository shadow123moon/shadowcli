"""Single-agent ReAct loop with tool execution and runtime message history."""
from __future__ import annotations

import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from llm import FunctionCall, Message, ToolCall, chat_stream
from tooling.runtime import ToolExecutionBlocked

from .budget import AgentBudget, ExitReason
from .prompts import filter_tool_definitions_for_model

log = logging.getLogger(__name__)
TOOL_ACTION_PREVIEW_CHARS = 50
TOOL_ERROR_PREFIXES = (
    "工具执行失败",
    "工具调用被拒绝",
    "操作被拒绝",
    "命令执行失败",
    "命令超时",
    "grep 失败",
    "搜索失败",
    "抓取失败",
    "编辑失败",
)
MAX_PARALLEL_TOOL_CALLS = 8

ChatFn = Callable[..., object]
MessageSink = Callable[[Message], None]


def _preview(text: str, limit: int = 160) -> str:
    compact = " ".join((text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[:limit] + "..."


def _is_tool_error_result(result: str | None) -> bool:
    text = (result or "").lstrip()
    return any(text.startswith(prefix) for prefix in TOOL_ERROR_PREFIXES)


class AgentLoop:
    """Reusable ReAct loop for one agent identity."""

    def __init__(
        self,
        name: str,
        system_prompt: str,
        chat: ChatFn,
        tool_registry,
        *,
        cancel: threading.Event | None = None,
        conversation_history: list[Message] | None = None,
        on_message_appended: MessageSink | None = None,
        use_tools: bool = True,
    ):
        self.name = name
        self.chat = chat
        self.tool_registry = tool_registry
        self.cancel = cancel or threading.Event()
        self.conversation_history = conversation_history if conversation_history is not None else []
        self.on_message_appended = on_message_appended
        self.use_tools = use_tools
        self._system_prompt = system_prompt
        self._current_step_label: str | None = None
        self._reset_system_prompt()

    def execute(self, task: Message, context: str = "", allow_tools: bool = True):
        """Execute one task and yield StreamEvent objects."""
        from llm.client import StreamEvent

        task_index = len(self.conversation_history)
        self._append_message(Message(role="user", content=task.content))
        budget = AgentBudget.from_env()

        for _turn in range(budget.hard_max_iterations):
            budget.begin_iteration()
            if self.cancel.is_set():
                yield StreamEvent("content", "\n⏹️ 用户取消")
                yield StreamEvent("done", {"reason": "cancelled"})
                return

            tools_schema = None
            if allow_tools and self.use_tools:
                tools_schema = filter_tool_definitions_for_model(
                    self.tool_registry.get_all_definitions(),
                    task.content,
                )
                if not tools_schema:
                    tools_schema = None

            content_parts: list[str] = []
            tool_calls_data: list[dict] = []
            usage_data: dict | None = None

            try:
                for event in chat_stream(
                    self._messages_for_model(task_index, context),
                    tools=tools_schema,
                    cancel=self.cancel,
                ):
                    if self.cancel.is_set():
                        yield StreamEvent("content", "\n⏹️ 用户取消")
                        yield StreamEvent("done", {"reason": "cancelled"})
                        return

                    if event.type == "content":
                        content_parts.append(event.data)
                        yield event
                    elif event.type == "tool_call":
                        tool_calls_data.append(event.data)
                    elif event.type == "done":
                        if event.data:
                            if event.data.get("usage"):
                                usage_data = event.data["usage"]
                            if event.data.get("reason") == "cancelled":
                                yield event
                                return
                    elif event.type == "error":
                        yield event
                        return
            except Exception as exc:
                log.exception("[Agent:%s] LLM 调用失败", self.name)
                yield StreamEvent("error", f"LLM 调用失败: {exc}")
                yield StreamEvent("done", {"reason": "error"})
                return

            response_msg = Message(
                role="assistant",
                content="".join(content_parts) or None,
                tool_calls=[
                    ToolCall(
                        id=tc["id"],
                        type=tc["type"],
                        function=FunctionCall(
                            name=tc["name"],
                            arguments=tc["arguments"],
                        ),
                    )
                    for tc in tool_calls_data
                ]
                if tool_calls_data
                else None,
            )
            self._append_message(response_msg)
            _record_usage(budget, usage_data)
            budget.record_tool_calls(response_msg.tool_calls)

            if budget.is_token_budget_exceeded():
                yield from _budget_exit_events(self.name, budget, ExitReason.TOKEN_BUDGET_EXCEEDED)
                return

            if not tool_calls_data:
                yield StreamEvent("done", {"reason": "finished"})
                return

            exit_reason = budget.check()
            if exit_reason != ExitReason.WITHIN_BUDGET:
                yield from _budget_exit_events(self.name, budget, exit_reason)
                return

            tool_done_reason = yield from self._execute_tool_calls(tool_calls_data)
            if tool_done_reason:
                yield StreamEvent("done", {"reason": tool_done_reason})
                return

        yield StreamEvent("content", f"\n⚠️ 达到最大轮数 {budget.hard_max_iterations}")
        yield StreamEvent("done", {"reason": "max_turns"})

    def clear_history(self) -> None:
        system_msg = self.conversation_history[0]
        self.conversation_history.clear()
        self.conversation_history.append(system_msg)
        self._current_step_label = None

    def _reset_system_prompt(self) -> None:
        existing = [message for message in self.conversation_history if message.role != "system"]
        self.conversation_history.clear()
        self.conversation_history.append(Message(role="system", content=self._system_prompt))
        self.conversation_history.extend(existing)

    def _messages_for_model(self, task_index: int, context: str) -> list[Message]:
        if not context:
            return self.conversation_history
        messages = list(self.conversation_history)
        task = messages[task_index]
        messages[task_index] = Message(
            role=task.role,
            content=f"{context}\n\n当前任务：{task.content}",
            tool_calls=task.tool_calls,
            tool_call_id=task.tool_call_id,
        )
        return messages

    def _append_message(self, message: Message) -> None:
        self.conversation_history.append(message)
        if self.on_message_appended is not None and message.role != "system":
            self.on_message_appended(message)

    def _display_name(self) -> str:
        if not self._current_step_label:
            return self.name
        return f"{self.name} [{_preview(self._current_step_label, TOOL_ACTION_PREVIEW_CHARS)}]"

    def _execute_tool_calls(self, tool_calls_data: list[dict]):
        pending_reads: list[dict] = []
        for tc in tool_calls_data:
            if self.cancel.is_set():
                yield from _cancel_events()
                return "cancelled"

            if _is_parallel_read_tool(tc["name"], self.tool_registry):
                pending_reads.append(tc)
                continue

            done_reason = yield from self._flush_parallel_read_calls(pending_reads)
            pending_reads = []
            if done_reason:
                return done_reason

            done_reason = yield from self._execute_serial_tool_call(tc)
            if done_reason:
                return done_reason

        return (yield from self._flush_parallel_read_calls(pending_reads))

    def _flush_parallel_read_calls(self, tool_calls_data: list[dict]):
        if not tool_calls_data:
            return None

        from llm.client import StreamEvent

        for tc in tool_calls_data:
            if self.cancel.is_set():
                yield from _cancel_events()
                return "cancelled"
            yield StreamEvent("tool_call_start", {"name": tc["name"], "args": tc["arguments"]})

        result_cache: dict[int, str] = {}
        blocked_indexes: set[int] = set()
        worker_count = min(len(tool_calls_data), MAX_PARALLEL_TOOL_CALLS)
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                index: executor.submit(self._exec_one, _tool_call_from_data(tc))
                for index, tc in enumerate(tool_calls_data)
            }
            for index, future in futures.items():
                try:
                    result_cache[index] = future.result()
                except ToolExecutionBlocked as exc:
                    result_cache[index] = f"工具调用被拒绝: {exc}"
                    blocked_indexes.add(index)

        for index, tc in enumerate(tool_calls_data):
            result = result_cache[index]
            yield StreamEvent("tool_result", {"name": tc["name"], "result": result})
            if index not in blocked_indexes:
                self._append_message(Message(role="tool", content=result, tool_call_id=tc["id"]))

        if blocked_indexes:
            return "blocked"
        return None

    def _execute_serial_tool_call(self, tc: dict):
        from llm.client import StreamEvent

        if self.cancel.is_set():
            yield from _cancel_events()
            return "cancelled"

        yield StreamEvent("tool_call_start", {"name": tc["name"], "args": tc["arguments"]})
        tool_call_obj = _tool_call_from_data(tc)

        try:
            result = self._exec_one(tool_call_obj)
        except ToolExecutionBlocked as exc:
            result = f"工具调用被拒绝: {exc}"
            yield StreamEvent("tool_result", {"name": tc["name"], "result": result})
            return "blocked"

        yield StreamEvent("tool_result", {"name": tc["name"], "result": result})
        self._append_message(Message(role="tool", content=result, tool_call_id=tc["id"]))
        return None

    def _exec_one(self, tool_call) -> str:
        try:
            args = json.loads(tool_call.function.arguments)
            display_name = self._display_name()
            result = self.tool_registry.execute(tool_call.function.name, args)
            if _is_tool_error_result(result):
                log.warning(
                    "[工具错误] %s 调用 %s：%s",
                    display_name,
                    tool_call.function.name,
                    _preview(result, 800),
                )
            return result
        except ToolExecutionBlocked:
            log.warning("[工具] %s 调用 %s 被拒绝", self._display_name(), tool_call.function.name)
            raise
        except Exception as exc:
            log.exception("[工具] %s 调用 %s 失败", self._display_name(), tool_call.function.name)
            return f"工具执行失败: {exc}"

    def __repr__(self) -> str:
        return f"AgentLoop(name={self.name!r}, history={len(self.conversation_history)})"


def _record_usage(budget: AgentBudget, usage: dict | None) -> None:
    if not usage:
        return
    input_tokens = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
    details = usage.get("prompt_tokens_details") or usage.get("input_tokens_details") or {}
    cached = int(details.get("cached_tokens") or usage.get("cached_input_tokens") or 0)
    budget.record_tokens(input_tokens, output_tokens, cached=cached)


def _tool_call_from_data(tc: dict) -> ToolCall:
    return ToolCall(
        id=tc["id"],
        type="function",
        function=FunctionCall(name=tc["name"], arguments=tc["arguments"]),
    )


def _is_parallel_read_tool(name: str, registry) -> bool:
    try:
        tool = registry.get(name)
    except (AttributeError, KeyError):
        return False
    return getattr(tool, "effect", "write") == "read" and bool(getattr(tool, "concurrency_safe", False))


def _cancel_events():
    from llm.client import StreamEvent

    yield StreamEvent("content", "\n⏹️ 用户取消")


def _budget_exit_events(agent_name: str, budget: AgentBudget, reason: ExitReason):
    from llm.client import StreamEvent

    message = budget.describe_exit(reason)
    log.warning("[Agent:%s] %s", agent_name, message)
    yield StreamEvent("content", f"\n⚠️ {message}")
    yield StreamEvent("done", {"reason": _budget_done_reason(reason)})


def _budget_done_reason(reason: ExitReason) -> str:
    return {
        ExitReason.TOKEN_BUDGET_EXCEEDED: "token_budget_exceeded",
        ExitReason.STAGNATION_DETECTED: "stagnation_detected",
        ExitReason.HARD_ITERATION_LIMIT: "hard_iteration_limit",
    }.get(reason, "finished")
