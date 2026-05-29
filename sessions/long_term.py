from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path


DEFAULT_LONG_TERM_NAME = "long_term.md"


class TextLongTermMemory:
    """Plain markdown bullet list for user-approved long-term facts."""

    def __init__(self, storage_path: Path):
        self._path = Path(storage_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._facts = _read_facts(self._path)
        if not self._path.exists():
            self._write()

    def __len__(self) -> int:
        return len(self._facts)

    def __iter__(self) -> Iterator[str]:
        return iter(self._facts)

    @property
    def storage_path(self) -> Path:
        return self._path

    def remember(self, fact: str) -> None:
        normalized = _normalize_fact(fact)
        if not normalized or normalized in self._facts:
            return
        self._facts.append(normalized)
        self._write()

    def search(self, query: str, limit: int = 5) -> list[str]:
        if limit <= 0:
            return []

        terms = _query_terms(query)
        matches = [
            fact for fact in self._facts
            if terms and any(term in fact.lower() for term in terms)
        ]
        if matches:
            return matches[:limit]

        return self._facts[-limit:]

    def _write(self) -> None:
        content = "".join(f"- {fact}\n" for fact in self._facts)
        self._path.write_text(content, encoding="utf-8")


def _read_facts(path: Path) -> list[str]:
    if not path.exists():
        return []
    facts: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            fact = _normalize_fact(stripped[2:])
        elif stripped.startswith("* "):
            fact = _normalize_fact(stripped[2:])
        else:
            fact = ""
        if fact and fact not in facts:
            facts.append(fact)
    return facts


def _normalize_fact(fact: str) -> str:
    return " ".join((fact or "").strip().split())


def _query_terms(query: str) -> list[str]:
    text = (query or "").strip().lower()
    if not text:
        return []
    terms = [term for term in re.split(r"\W+", text) if term]
    return terms or [text]
