from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path


DEFAULT_LONG_TERM_NAME = "memory"
DEFAULT_LONG_TERM_PATH = Path("agent_memory") / DEFAULT_LONG_TERM_NAME
ENTRYPOINT_NAME = "MEMORY.md"
DEFAULT_MEMORY_TYPE = "project"
MEMORY_TYPES = ("user", "project", "feedback", "reference")
TYPE_DESCRIPTIONS = {
    "user": "User preferences, collaboration style, durable user context",
    "project": "Project background and decisions not derivable from source",
    "feedback": "User corrections and validated working preferences",
    "reference": "External resources, systems, dashboards, and links",
}


class TextLongTermMemory:
    """Structured markdown memory directory for user-approved long-term facts."""

    def __init__(self, storage_path: Path):
        self._path = _normalize_storage_path(Path(storage_path))
        ensure_memory_storage(self._path)
        self._facts_by_type = _read_structured_facts(self._path)

    def __len__(self) -> int:
        return len(self._facts())

    def __iter__(self) -> Iterator[str]:
        return iter(self._facts())

    @property
    def storage_path(self) -> Path:
        return self._path

    def remember(self, fact: str, *, memory_type: str | None = None) -> None:
        normalized = _normalize_fact(fact)
        target_type = _normalize_memory_type(memory_type)
        if not normalized or normalized in self._facts():
            return
        self._facts_by_type[target_type].append(normalized)
        self._write_type(target_type)
        _write_index(self._path)

    def search(self, query: str, limit: int = 5) -> list[str]:
        if limit <= 0:
            return []

        terms = _query_terms(query)
        facts = self._facts()
        matches = [
            fact for fact in facts
            if terms and any(term in fact.lower() for term in terms)
        ]
        if matches:
            return matches[:limit]

        return facts[-limit:]

    def _facts(self) -> list[str]:
        return [
            fact
            for memory_type in MEMORY_TYPES
            for fact in self._facts_by_type.get(memory_type, [])
        ]

    def _write_type(self, memory_type: str) -> None:
        _write_type_file(
            self._path / f"{memory_type}.md",
            memory_type,
            self._facts_by_type[memory_type],
        )


def build_long_term_memory(long_term_path: Path | None = None) -> TextLongTermMemory:
    return TextLongTermMemory(long_term_path or DEFAULT_LONG_TERM_PATH)


def ensure_memory_storage(memory_dir: Path) -> None:
    memory_dir = Path(memory_dir)
    memory_dir.mkdir(parents=True, exist_ok=True)
    _write_index(memory_dir)
    for memory_type in MEMORY_TYPES:
        path = memory_dir / f"{memory_type}.md"
        if not path.exists():
            _write_type_file(path, memory_type, [])


def _normalize_storage_path(storage_path: Path) -> Path:
    if storage_path.suffix:
        raise ValueError("memory storage path must be a directory")
    return storage_path


def _read_structured_facts(memory_dir: Path) -> dict[str, list[str]]:
    return {
        memory_type: _read_dash_bullet_facts(memory_dir / f"{memory_type}.md")
        for memory_type in MEMORY_TYPES
    }


def _write_index(memory_dir: Path) -> None:
    lines = ["# Memory Index", ""]
    for memory_type in MEMORY_TYPES:
        lines.append(
            f"- [{memory_type}]({memory_type}.md) - {TYPE_DESCRIPTIONS[memory_type]}"
        )
    (memory_dir / ENTRYPOINT_NAME).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_type_file(path: Path, memory_type: str, facts: list[str]) -> None:
    header = [
        "---",
        f"name: {memory_type}",
        f"description: {TYPE_DESCRIPTIONS[memory_type]}",
        f"type: {memory_type}",
        "---",
        "",
    ]
    body = [f"- {fact}" for fact in facts]
    path.write_text("\n".join(header + body).rstrip() + "\n", encoding="utf-8")


def _read_dash_bullet_facts(path: Path) -> list[str]:
    if not path.exists():
        return []
    facts: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            fact = _normalize_fact(stripped[2:])
        else:
            fact = ""
        if fact and fact not in facts:
            facts.append(fact)
    return facts


def _normalize_memory_type(memory_type: str | None) -> str:
    if memory_type is None:
        return DEFAULT_MEMORY_TYPE
    normalized = memory_type.strip().lower()
    if normalized not in MEMORY_TYPES:
        raise ValueError(f"unknown memory type: {memory_type}")
    return normalized


def _normalize_fact(fact: str) -> str:
    return " ".join((fact or "").strip().split())


def _query_terms(query: str) -> list[str]:
    text = (query or "").strip().lower()
    if not text:
        return []
    terms = [term for term in re.split(r"\W+", text) if term]
    return terms or [text]
