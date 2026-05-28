from __future__ import annotations

from dataclasses import asdict, dataclass


SESSION_VERSION = 1


@dataclass
class ProjectMeta:
    version: int
    project_key: str
    name: str
    cwd: str
    created_at: str
    updated_at: str

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> ProjectMeta:
        return cls(
            version=int(data.get("version", SESSION_VERSION)),
            project_key=str(data["project_key"]),
            name=str(data["name"]),
            cwd=str(data["cwd"]),
            created_at=str(data["created_at"]),
            updated_at=str(data["updated_at"]),
        )


@dataclass
class SessionMeta:
    version: int
    session_id: str
    title: str | None
    created_at: str
    updated_at: str
    model: str | None = None
    provider: str | None = None
    message_count: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> SessionMeta:
        return cls(
            version=int(data.get("version", SESSION_VERSION)),
            session_id=str(data["session_id"]),
            title=data.get("title"),
            created_at=str(data["created_at"]),
            updated_at=str(data["updated_at"]),
            model=data.get("model"),
            provider=data.get("provider"),
            message_count=int(data.get("message_count", 0)),
        )
