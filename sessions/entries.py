from __future__ import annotations

from dataclasses import dataclass, field

from llm import FunctionCall, Message, ToolCall


EntryDetails = dict[str, list[str]]


def empty_details() -> EntryDetails:
    return {"read_files": [], "modified_files": []}


@dataclass
class MessageEntry:
    id: str
    parent_id: str | None
    timestamp: str
    message: Message
    type: str = field(init=False, default="message")


@dataclass
class CompactionEntry:
    id: str
    parent_id: str | None
    timestamp: str
    summary: str
    first_kept_entry_id: str
    tokens_before: int
    details: EntryDetails = field(default_factory=empty_details)
    type: str = field(init=False, default="compaction")


@dataclass
class BranchSummaryEntry:
    id: str
    parent_id: str | None
    timestamp: str
    from_id: str | None
    to_id: str | None
    common_ancestor_id: str | None
    summary: str
    details: EntryDetails = field(default_factory=empty_details)
    type: str = field(init=False, default="branch_summary")


SessionEntry = MessageEntry | CompactionEntry | BranchSummaryEntry


def entry_to_dict(entry: SessionEntry) -> dict:
    if isinstance(entry, MessageEntry):
        data = {
            "type": entry.type,
            "id": entry.id,
            "parent_id": entry.parent_id,
            "timestamp": entry.timestamp,
            "role": entry.message.role,
            "content": entry.message.content,
        }
        if entry.message.tool_calls:
            data["tool_calls"] = [_tool_call_to_dict(tool_call) for tool_call in entry.message.tool_calls]
        if entry.message.tool_call_id:
            data["tool_call_id"] = entry.message.tool_call_id
        return data

    if isinstance(entry, CompactionEntry):
        return {
            "type": entry.type,
            "id": entry.id,
            "parent_id": entry.parent_id,
            "timestamp": entry.timestamp,
            "summary": entry.summary,
            "first_kept_entry_id": entry.first_kept_entry_id,
            "tokens_before": entry.tokens_before,
            "details": _normalize_details(entry.details),
        }

    return {
        "type": entry.type,
        "id": entry.id,
        "parent_id": entry.parent_id,
        "timestamp": entry.timestamp,
        "from_id": entry.from_id,
        "to_id": entry.to_id,
        "common_ancestor_id": entry.common_ancestor_id,
        "summary": entry.summary,
        "details": _normalize_details(entry.details),
    }


def entry_from_dict(data: dict) -> SessionEntry | None:
    entry_type = data.get("type")
    if entry_type == "message":
        return MessageEntry(
            id=str(data["id"]),
            parent_id=data.get("parent_id"),
            timestamp=str(data.get("timestamp") or data.get("created_at") or ""),
            message=Message(
                role=str(data["role"]),
                content=data.get("content"),
                tool_calls=[_tool_call_from_dict(item) for item in data.get("tool_calls") or []] or None,
                tool_call_id=data.get("tool_call_id"),
            ),
        )
    if entry_type == "compaction":
        return CompactionEntry(
            id=str(data["id"]),
            parent_id=data.get("parent_id"),
            timestamp=str(data.get("timestamp") or ""),
            summary=str(data.get("summary") or ""),
            first_kept_entry_id=str(data.get("first_kept_entry_id") or ""),
            tokens_before=int(data.get("tokens_before") or 0),
            details=_normalize_details(data.get("details")),
        )
    if entry_type == "branch_summary":
        return BranchSummaryEntry(
            id=str(data["id"]),
            parent_id=data.get("parent_id"),
            timestamp=str(data.get("timestamp") or ""),
            from_id=data.get("from_id"),
            to_id=data.get("to_id"),
            common_ancestor_id=data.get("common_ancestor_id"),
            summary=str(data.get("summary") or ""),
            details=_normalize_details(data.get("details")),
        )
    return None


def _tool_call_to_dict(tool_call: ToolCall | dict) -> dict:
    if isinstance(tool_call, dict):
        return tool_call
    return {
        "id": tool_call.id,
        "type": tool_call.type,
        "function": {
            "name": tool_call.function.name,
            "arguments": tool_call.function.arguments,
        },
    }


def _tool_call_from_dict(data: dict) -> ToolCall:
    function = data.get("function") or {}
    return ToolCall(
        id=data["id"],
        type=data.get("type", "function"),
        function=FunctionCall(
            name=function.get("name", ""),
            arguments=function.get("arguments", ""),
        ),
    )


def _normalize_details(details: dict | None) -> EntryDetails:
    raw = details or {}
    return {
        "read_files": [str(item) for item in raw.get("read_files") or []],
        "modified_files": [str(item) for item in raw.get("modified_files") or []],
    }
