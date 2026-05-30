from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum

from sessions.entries import BranchSummaryEntry, CompactionEntry, MessageEntry, SessionEntry


class TreeFilterMode(str, Enum):
    DEFAULT = "default"
    NO_TOOLS = "no-tools"
    USER_ONLY = "user-only"
    ALL = "all"


@dataclass(frozen=True)
class TreeDisplayNode:
    entry_id: str
    parent_id: str | None
    depth: int
    label: str
    search_text: str
    entry: SessionEntry
    is_current_leaf: bool = False
    is_current_branch: bool = False


def build_tree_nodes(
    entries: list[SessionEntry],
    current_leaf_id: str | None,
    *,
    filter_mode: TreeFilterMode | str = TreeFilterMode.DEFAULT,
    query: str = "",
) -> list[TreeDisplayNode]:
    """Build pi-style flat tree rows from append-only session entries."""
    mode = TreeFilterMode(filter_mode)
    by_id = {entry.id: entry for entry in entries}
    active_path = _active_path_ids(by_id, current_leaf_id)
    visible_entries = [
        entry
        for entry in entries
        if _passes_filter(entry, mode, current_leaf_id)
        and _matches_query(entry, query)
    ]
    visible_ids = {entry.id for entry in visible_entries}
    visible_depths = _visible_depths(visible_entries, by_id, visible_ids)

    return [
        TreeDisplayNode(
            entry_id=entry.id,
            parent_id=_nearest_visible_parent_id(entry, by_id, visible_ids),
            depth=visible_depths.get(entry.id, 0),
            label=_entry_label(entry),
            search_text=_entry_search_text(entry),
            entry=entry,
            is_current_leaf=entry.id == current_leaf_id,
            is_current_branch=entry.id in active_path,
        )
        for entry in visible_entries
    ]


def _active_path_ids(by_id: dict[str, SessionEntry], leaf_id: str | None) -> set[str]:
    ids: set[str] = set()
    current_id = leaf_id
    while current_id is not None:
        entry = by_id.get(current_id)
        if entry is None:
            break
        ids.add(entry.id)
        current_id = entry.parent_id
    return ids


def _passes_filter(entry: SessionEntry, mode: TreeFilterMode, current_leaf_id: str | None) -> bool:
    if mode == TreeFilterMode.ALL:
        return True
    if mode == TreeFilterMode.USER_ONLY:
        return isinstance(entry, MessageEntry) and entry.message.role == "user"
    if mode == TreeFilterMode.NO_TOOLS:
        return not _is_tool_plumbing(entry)
    if entry.id == current_leaf_id:
        return True
    return not _is_tool_plumbing(entry)


def _is_tool_plumbing(entry: SessionEntry) -> bool:
    if not isinstance(entry, MessageEntry):
        return False
    if entry.message.role == "tool":
        return True
    if entry.message.role == "assistant" and entry.message.tool_calls and not (entry.message.content or "").strip():
        return True
    return False


def _matches_query(entry: SessionEntry, query: str) -> bool:
    tokens = [token for token in query.lower().split() if token]
    if not tokens:
        return True
    text = _entry_search_text(entry).lower()
    return all(token in text for token in tokens)


def _visible_depths(
    visible_entries: list[SessionEntry],
    by_id: dict[str, SessionEntry],
    visible_ids: set[str],
) -> dict[str, int]:
    depths: dict[str, int] = {}
    for entry in visible_entries:
        parent_id = _nearest_visible_parent_id(entry, by_id, visible_ids)
        depths[entry.id] = 0 if parent_id is None else depths.get(parent_id, 0) + 1
    return depths


def _nearest_visible_parent_id(
    entry: SessionEntry,
    by_id: dict[str, SessionEntry],
    visible_ids: set[str],
) -> str | None:
    parent_id = entry.parent_id
    while parent_id is not None:
        if parent_id in visible_ids:
            return parent_id
        parent = by_id.get(parent_id)
        parent_id = parent.parent_id if parent is not None else None
    return None


def _entry_label(entry: SessionEntry) -> str:
    short_id = entry.id[:8]
    if isinstance(entry, MessageEntry):
        role = entry.message.role
        if entry.message.tool_calls:
            names = ", ".join(call.function.name for call in entry.message.tool_calls)
            return f"[{short_id}] assistant: [{names}]"
        return f"[{short_id}] {role}: {_preview(entry.message.content or '')}"
    if isinstance(entry, CompactionEntry):
        return f"[{short_id}] compaction: {entry.tokens_before} tokens"
    if isinstance(entry, BranchSummaryEntry):
        return f"[{short_id}] branch summary: {_preview(entry.summary)}"
    return f"[{short_id}] {getattr(entry, 'type', 'entry')}"


def _entry_search_text(entry: SessionEntry) -> str:
    if isinstance(entry, MessageEntry):
        parts = [entry.message.role, entry.message.content or ""]
        if entry.message.tool_calls:
            parts.extend(call.function.name for call in entry.message.tool_calls)
            parts.extend(_safe_arguments(call.function.arguments) for call in entry.message.tool_calls)
        return " ".join(parts)
    if isinstance(entry, CompactionEntry):
        return f"compaction {entry.summary}"
    if isinstance(entry, BranchSummaryEntry):
        return f"branch summary {entry.summary}"
    return str(getattr(entry, "type", "entry"))


def _safe_arguments(arguments: str) -> str:
    try:
        parsed = json.loads(arguments)
    except json.JSONDecodeError:
        return arguments
    return json.dumps(parsed, ensure_ascii=False)


def _preview(text: str, limit: int = 80) -> str:
    compact = " ".join(str(text).split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."
