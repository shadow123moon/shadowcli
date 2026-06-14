from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .ids import new_session_id, project_key_for
from .entries import MessageEntry
from .manager import SessionManager
from .repository import SessionRepository
from .types import DEFAULT_SESSION_TITLE, ProjectMeta, SESSION_VERSION, SessionMeta, title_from_text


DEFAULT_SESSION_ROOT = Path.home() / ".shadowcli" / "sessions"


class SessionStore:
    """Project-scoped session directory manager."""

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
    ) -> SessionManager:
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
        repository = SessionRepository(path)
        repository.initialize(
            session_id=session_id,
            cwd=str(Path(cwd).expanduser().resolve()),
            created_at=created_at,
        )
        return SessionManager(
            path=path,
            cwd=Path(cwd).expanduser().resolve(),
            meta=meta,
            repository=repository,
        )

    def open(self, cwd: Path, session_id: str) -> SessionManager:
        project_dir = self.project_dir(cwd)
        path = project_dir / "conversations" / session_id
        if not path.exists():
            raise FileNotFoundError(f"session not found: {session_id}")
        meta = _load_session_meta(path)
        return SessionManager(
            path=path,
            cwd=Path(cwd).expanduser().resolve(),
            meta=meta,
            repository=SessionRepository(path),
        )

    def open_recent(self, cwd: Path) -> SessionManager | None:
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
                metas.append(_load_session_meta(meta_path.parent))
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

        return project_dir


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


def _load_session_meta(path: Path) -> SessionMeta:
    meta_path = path / "meta.json"
    meta = SessionMeta.from_dict(_read_json(meta_path))
    if not meta.title:
        meta.title = _infer_session_title(path)
        _write_json(meta_path, meta.to_dict())
    return meta


def _infer_session_title(path: Path) -> str:
    state = SessionRepository(path).load()
    for entry in state.entries:
        if isinstance(entry, MessageEntry) and entry.message.role == "user":
            title = title_from_text(entry.message.content)
            if title:
                return title
    return DEFAULT_SESSION_TITLE
