from __future__ import annotations

from llm import FunctionCall, Message, ToolCall

from .types import SESSION_VERSION


def session_header(session_id: str, cwd: str, created_at: str) -> dict:
    return {
        "type": "session_header",
        "version": SESSION_VERSION,
        "session_id": session_id,
        "cwd": cwd,
        "created_at": created_at,
    }


def message_to_entry(message: Message, timestamp: str) -> dict:
    entry = {
        "type": "message",
        "role": message.role,
        "content": message.content,
        "timestamp": timestamp,
    }
    if message.tool_calls:
        entry["tool_calls"] = [
            {
                "id": tc.id,
                "type": tc.type,
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                },
            }
            for tc in message.tool_calls
        ]
    if message.tool_call_id:
        entry["tool_call_id"] = message.tool_call_id
    return entry


def entry_to_message(entry: dict) -> Message | None:
    if entry.get("type") != "message":
        return None

    tool_calls = None
    if entry.get("tool_calls"):
        tool_calls = [
            ToolCall(
                id=tc["id"],
                type=tc.get("type", "function"),
                function=FunctionCall(
                    name=tc["function"]["name"],
                    arguments=tc["function"].get("arguments", ""),
                ),
            )
            for tc in entry["tool_calls"]
        ]

    return Message(
        role=entry["role"],
        content=entry.get("content"),
        tool_calls=tool_calls,
        tool_call_id=entry.get("tool_call_id"),
    )
