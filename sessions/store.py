from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from llm import Message

from .codec import entry_to_message, message_to_entry, session_header
from .ids import new_session_id, project_key_for
from .types import ProjectMeta, SESSION_VERSION, SessionMeta


DEFAULT_SESSION_ROOT = Path.home() / ".pai_cli" / "sessions"


class SessionStore:
    def __init__(self, root: Path = DEFAULT_SESSION_ROOT):
        self.root = Path(root)

    def project_dir(self, cwd: Path) -> Path:
        return self.root / project_key_for(cwd)

    def create(
        self,
        cwd: Path,
        *,
        title: str | None = None,
        model: str | None = None,
        provider: str | None = None,
    ) -> Session:
        project_dir = self._ensure_project(cwd)
        session_id = new_session_id()
        created_at = _now_iso()
        path = project_dir / "conversations" / session_id
        path.mkdir(parents=True, exist_ok=False)

        meta = SessionMeta(
            version=SESSION_VERSION,
            session_id=session_id,
            title=title,
            created_at=created_at,
            updated_at=created_at,
            model=model,
            provider=provider,
            message_count=0,
        )
        _write_json(path / "meta.json", meta.to_dict())
        (path / "summary.md").write_text("", encoding="utf-8")
        _append_jsonl(
            path / "messages.jsonl",
            session_header(session_id, str(Path(cwd).expanduser().resolve()), created_at),
        )
        return Session(path=path, cwd=Path(cwd).expanduser().resolve(), meta=meta)

    def open(self, cwd: Path, session_id: str) -> Session:
        project_dir = self.project_dir(cwd)
        path = project_dir / "conversations" / session_id
        if not path.exists():
            raise FileNotFoundError(f"session not found: {session_id}")
        meta = SessionMeta.from_dict(_read_json(path / "meta.json"))
        return Session(path=path, cwd=Path(cwd).expanduser().resolve(), meta=meta)

    def open_recent(self, cwd: Path) -> Session | None:
        sessions = self.list(cwd)
        if not sessions:
            return None
        return self.open(cwd, sessions[0].session_id)

    def list(self, cwd: Path) -> list[SessionMeta]:
        conversations = self.project_dir(cwd) / "conversations"
        if not conversations.exists():
            return []

        metas: list[SessionMeta] = []
        for meta_path in conversations.glob("*/meta.json"):
            try:
                metas.append(SessionMeta.from_dict(_read_json(meta_path)))
            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                continue
        return sorted(metas, key=lambda meta: meta.updated_at, reverse=True)

    def _ensure_project(self, cwd: Path) -> Path:
        abs_cwd = Path(cwd).expanduser().resolve()
        project_dir = self.project_dir(abs_cwd)
        conversations = project_dir / "conversations"
        conversations.mkdir(parents=True, exist_ok=True)

        project_path = project_dir / "project.json"
        now = _now_iso()
        if project_path.exists():
            project = ProjectMeta.from_dict(_read_json(project_path))
            project.updated_at = now
        else:
            project = ProjectMeta(
                version=SESSION_VERSION,
                project_key=project_key_for(abs_cwd),
                name=abs_cwd.name or "root",
                cwd=str(abs_cwd),
                created_at=now,
                updated_at=now,
            )
        _write_json(project_path, project.to_dict())

        long_term_path = project_dir / "long_term.json"
        if not long_term_path.exists():
            _write_json(long_term_path, [])

        return project_dir


class Session:
    def __init__(self, *, path: Path, cwd: Path, meta: SessionMeta):
        self.path = Path(path)
        self.cwd = Path(cwd)
        self.meta = meta

    def append_message(self, message: Message) -> None:
        now = _now_iso()
        _append_jsonl(self.path / "messages.jsonl", message_to_entry(message, now))
        self.meta.message_count += 1
        self.meta.updated_at = now
        _write_json(self.path / "meta.json", self.meta.to_dict())

    def append_tool_result(self, tool_call_id: str, content: str) -> None:
        self.append_message(Message(role="tool", content=content, tool_call_id=tool_call_id))

    def messages(self) -> list[Message]:
        path = self.path / "messages.jsonl"
        if not path.exists():
            return []

        messages: list[Message] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            message = entry_to_message(entry)
            if message is not None:
                messages.append(message)
        return messages

    def close(self) -> None:
        return None

    def __enter__(self) -> Session:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.close()
        return False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _append_jsonl(path: Path, entry: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
        fp.flush()
