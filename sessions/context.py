from __future__ import annotations

from collections.abc import Callable, Iterable

from .manager import SessionManager

ContextProvider = Callable[[], str]


class RuntimeContextBuilder:
    """Build ephemeral LLM context from the current session branch and facts."""

    def __init__(
        self,
        *,
        session: SessionManager,
        long_term: Iterable[str] | None = None,
        long_term_limit: int = 8,
        extra_context_provider: ContextProvider | None = None,
    ):
        self.session = session
        self.long_term = long_term or []
        self.long_term_limit = long_term_limit
        self.extra_context_provider = extra_context_provider or _empty_context

    def build(self, query: str = "") -> str:
        sections: list[str] = []
        summary = self._summary_text()
        if summary:
            sections.extend(["## 分支摘要", summary, ""])

        facts = _search_facts(self.long_term, query, limit=self.long_term_limit)
        if facts:
            sections.append("## 相关长期记忆")
            sections.extend(f"- {fact}" for fact in facts)
            sections.append("")

        extra_context = self.extra_context_provider().strip()
        if extra_context:
            sections.extend([extra_context, ""])

        return "\n".join(sections).rstrip()

    def _summary_text(self) -> str:
        return self.session.summary_text()


def _empty_context() -> str:
    return ""


def _search_facts(
    long_term: Iterable[str],
    query: str,
    *,
    limit: int,
) -> list[str]:
    search = getattr(long_term, "search", None)
    if callable(search):
        return list(search(query, limit=limit))
    facts = [str(fact).strip() for fact in long_term if str(fact).strip()]
    if limit <= 0:
        return []
    return facts[-limit:]
