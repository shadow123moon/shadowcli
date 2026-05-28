from __future__ import annotations

from collections.abc import Iterable

from memory_pythonic.entry import MemoryEntry
from memory_pythonic.retrieval import search_long_only

from .store import Session


class ContextBuilder:
    """Build ephemeral LLM context from session sidecars and long-term facts."""

    def __init__(
        self,
        *,
        session: Session,
        long_term: Iterable[MemoryEntry] | None = None,
        long_term_limit: int = 8,
    ):
        self.session = session
        self.long_term = long_term or []
        self.long_term_limit = long_term_limit

    def build(self, query: str = "") -> str:
        sections: list[str] = []
        summary = self._summary_text()
        if summary:
            sections.extend(["## 会话摘要", summary, ""])

        facts = search_long_only(self.long_term, query, limit=self.long_term_limit)
        if facts:
            sections.append("## 相关长期记忆")
            sections.extend(f"- [{entry.type.name}] {entry.content}" for entry in facts)
            sections.append("")

        return "\n".join(sections).rstrip()

    def _summary_text(self) -> str:
        path = self.session.path / "summary.md"
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8").strip()
