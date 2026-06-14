from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .entries import SessionEntry, entry_from_dict, entry_to_dict
from .types import SESSION_VERSION


@dataclass
class RepositoryState:
    header: dict | None
    entries: list[SessionEntry]
    leaf_id: str | None


class SessionRepository:
    """Append-only JSONL repository for one conversation tree."""

    def __init__(self, path: Path):
        self.path = Path(path)

    @property
    def messages_path(self) -> Path:
        return self.path / "messages.jsonl"

    def initialize(self, *, session_id: str, cwd: str, created_at: str) -> None:
        self.path.mkdir(parents=True, exist_ok=True)
        if self.messages_path.exists():
            return
        self._append_raw({
            "type": "session_header",
            "version": SESSION_VERSION,
            "session_id": session_id,
            "cwd": cwd,
            "created_at": created_at,
        })

    def load(self) -> RepositoryState:
        if not self.messages_path.exists():
            return RepositoryState(header=None, entries=[], leaf_id=None)

        header: dict | None = None
        entries: list[SessionEntry] = []
        leaf_id: str | None = None
        for line in self.messages_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            data = json.loads(line)
            entry_type = data.get("type")
            if entry_type == "session_header":
                header = data
            elif entry_type == "leaf":
                leaf_id = data.get("leaf_id")
            elif entry_type == "turn":
                for item in data.get("entries") or []:
                    entry = entry_from_dict(item)
                    if entry is not None:
                        entries.append(entry)
                leaf_id = data.get("leaf_id", leaf_id)
            else:
                entry = entry_from_dict(data)
                if entry is not None:
                    entries.append(entry)

        if leaf_id is None and entries:
            leaf_id = entries[-1].id
        return RepositoryState(header=header, entries=entries, leaf_id=leaf_id)

    def append_entry(self, entry: SessionEntry) -> None:
        self._append_raw(entry_to_dict(entry))

    def append_turn(self, entries: list[SessionEntry], leaf_id: str | None) -> None:
        self._append_raw({
            "type": "turn",
            "entries": [entry_to_dict(entry) for entry in entries],
            "leaf_id": leaf_id,
        })

    def append_leaf(self, leaf_id: str | None) -> None:
        self._append_raw({"type": "leaf", "leaf_id": leaf_id})

    def _append_raw(self, data: dict) -> None:
        self.messages_path.parent.mkdir(parents=True, exist_ok=True)
        with self.messages_path.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n")
            fp.flush()
