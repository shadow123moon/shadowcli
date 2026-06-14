from __future__ import annotations


def parse_namespaced_skill(name: str) -> tuple[str, str] | None:
    source, separator, skill_name = name.partition(":")
    if not separator or not source.strip() or not skill_name.strip():
        return None
    return source.strip(), skill_name.strip()


def source_candidates_for_reference(source: str) -> set[str]:
    candidates = {source}
    if not source.startswith("plugin:"):
        candidates.add(f"plugin:{source}")
    return candidates
