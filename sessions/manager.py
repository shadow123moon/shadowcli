from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from llm import Message

from .entries import (
    BranchSummaryEntry,
    CompactionEntry,
    EntryDetails,
    MessageEntry,
    SessionEntry,
    empty_details,
)
from .repository import SessionRepository
from .types import DEFAULT_SESSION_TITLE, SessionMeta, title_from_text


@dataclass
class NavigationPlan:
    from_id: str | None
    to_id: str | None
    common_ancestor_id: str | None
    leaving_entries: list[SessionEntry]


class SessionManager:
    """Runtime facade for one append-only conversation tree."""

    def __init__(
        self,
        *,
        path: Path,
        cwd: Path,
        meta: SessionMeta,
        repository: SessionRepository | None = None,
    ):
        self.path = Path(path)
        self.cwd = Path(cwd)
        self.meta = meta
        self.repository = repository or SessionRepository(self.path)
        state = self.repository.load()
        self._entries = state.entries
        self.leaf_id = state.leaf_id

    def append_message(self, message: Message) -> MessageEntry:
        entry = MessageEntry(
            id=_new_entry_id(),
            parent_id=self.leaf_id,
            timestamp=_now_iso(),
            message=message,
        )
        self._append_entry(entry)
        self.meta.message_count += 1
        if (not self.meta.title or self.meta.title == DEFAULT_SESSION_TITLE) and message.role == "user":
            title = title_from_text(message.content)
            if title:
                self.meta.title = title
        self._persist_meta(entry.timestamp)
        return entry

    def append_tool_result(self, tool_call_id: str, content: str) -> MessageEntry:
        return self.append_message(Message(role="tool", content=content, tool_call_id=tool_call_id))

    def append_compaction(
        self,
        *,
        summary: str,
        first_kept_entry_id: str,
        tokens_before: int,
        details: EntryDetails | None = None,
    ) -> CompactionEntry:
        entry = CompactionEntry(
            id=_new_entry_id(),
            parent_id=self.leaf_id,
            timestamp=_now_iso(),
            summary=summary,
            first_kept_entry_id=first_kept_entry_id,
            tokens_before=tokens_before,
            details=details or empty_details(),
        )
        self._append_entry(entry)
        self._persist_meta(entry.timestamp)
        return entry

    def branch_to(self, target_id: str | None) -> None:
        self._validate_entry_id(target_id)
        self.leaf_id = target_id
        self.repository.append_leaf(self.leaf_id)
        self._persist_meta(_now_iso())

    def branch_to_with_summary(
        self,
        target_id: str | None,
        *,
        summary: str,
        details: EntryDetails | None = None,
    ) -> BranchSummaryEntry:
        plan = self.plan_navigation(target_id)
        entry = BranchSummaryEntry(
            id=_new_entry_id(),
            parent_id=target_id,
            timestamp=_now_iso(),
            from_id=plan.from_id,
            to_id=target_id,
            common_ancestor_id=plan.common_ancestor_id,
            summary=summary,
            details=details or empty_details(),
        )
        self._entries.append(entry)
        self.repository.append_entry(entry)
        self.leaf_id = entry.id
        self.repository.append_leaf(self.leaf_id)
        self._persist_meta(entry.timestamp)
        return entry

    def plan_navigation(self, target_id: str | None) -> NavigationPlan:
        self._validate_entry_id(target_id)
        common = self._common_ancestor(self.leaf_id, target_id)
        leaving_entries = self._entries_after(common, self.leaf_id)
        return NavigationPlan(
            from_id=self.leaf_id,
            to_id=target_id,
            common_ancestor_id=common,
            leaving_entries=leaving_entries,
        )

    def get_branch(self, leaf_id: str | None = None) -> list[SessionEntry]:
        current_id = self.leaf_id if leaf_id is None else leaf_id
        if current_id is None:
            return []

        by_id = self._entry_map()
        branch: list[SessionEntry] = []
        while current_id is not None:
            entry = by_id.get(current_id)
            if entry is None:
                break
            branch.append(entry)
            current_id = entry.parent_id
        branch.reverse()
        return branch

    def messages(self) -> list[Message]:
        branch = self.get_branch()
        start_index = self._message_start_index_after_compaction(branch)
        return [
            entry.message
            for entry in branch[start_index:]
            if isinstance(entry, MessageEntry)
        ]

    def summary_text(self) -> str:
        sections: list[str] = []
        for entry in self.get_branch():
            if isinstance(entry, CompactionEntry):
                sections.append(entry.summary.strip())
            elif isinstance(entry, BranchSummaryEntry):
                sections.append(_format_branch_summary(entry))
        return "\n\n".join(section for section in sections if section)

    def all_entries(self) -> list[SessionEntry]:
        return list(self._entries)

    def get_leaf_id(self) -> str | None:
        return self.leaf_id

    def close(self) -> None:
        return None

    def __enter__(self) -> SessionManager:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.close()
        return False

    def _append_entry(self, entry: SessionEntry) -> None:
        self._entries.append(entry)
        self.leaf_id = entry.id
        self.repository.append_entry(entry)
        self.repository.append_leaf(self.leaf_id)

    def _entry_map(self) -> dict[str, SessionEntry]:
        return {entry.id: entry for entry in self._entries}

    def _validate_entry_id(self, entry_id: str | None) -> None:
        if entry_id is not None and entry_id not in self._entry_map():
            raise KeyError(f"session entry not found: {entry_id}")

    def _common_ancestor(self, left_id: str | None, right_id: str | None) -> str | None:
        if left_id is None or right_id is None:
            return None

        left_ancestors = set(self._ancestor_ids(left_id))
        current_id: str | None = right_id
        by_id = self._entry_map()
        while current_id is not None:
            if current_id in left_ancestors:
                return current_id
            current = by_id.get(current_id)
            current_id = current.parent_id if current is not None else None
        return None

    def _ancestor_ids(self, entry_id: str | None) -> list[str]:
        ids: list[str] = []
        by_id = self._entry_map()
        current_id = entry_id
        while current_id is not None:
            entry = by_id.get(current_id)
            if entry is None:
                break
            ids.append(current_id)
            current_id = entry.parent_id
        return ids

    def _entries_after(self, ancestor_id: str | None, leaf_id: str | None) -> list[SessionEntry]:
        branch = self.get_branch(leaf_id)
        if ancestor_id is None:
            return branch
        for index, entry in enumerate(branch):
            if entry.id == ancestor_id:
                return branch[index + 1:]
        return branch

    def _message_start_index_after_compaction(self, branch: list[SessionEntry]) -> int:
        for index in range(len(branch) - 1, -1, -1):
            entry = branch[index]
            if isinstance(entry, CompactionEntry):
                for kept_index, kept in enumerate(branch):
                    if kept.id == entry.first_kept_entry_id:
                        return kept_index
                return index + 1
        return 0

    def _persist_meta(self, updated_at: str) -> None:
        self.meta.updated_at = updated_at
        meta_path = self.path / "meta.json"
        meta_path.write_text(
            self.meta_to_json(),
            encoding="utf-8",
        )

    def meta_to_json(self) -> str:
        import json

        return json.dumps(self.meta.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _format_branch_summary(entry: BranchSummaryEntry) -> str:
    lines = [entry.summary.strip()]
    read_files = entry.details.get("read_files") or []
    modified_files = entry.details.get("modified_files") or []
    if read_files:
        lines.append("读取文件: " + ", ".join(read_files))
    if modified_files:
        lines.append("修改文件: " + ", ".join(modified_files))
    return "\n".join(line for line in lines if line)


def _new_entry_id() -> str:
    return uuid4().hex[:12]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
