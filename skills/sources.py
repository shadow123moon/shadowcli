from __future__ import annotations

import os
from pathlib import Path

from .types import SkillRoot


SKILL_ROOT = Path(".agents") / "skills"
SKILL_ROOTS_ENV = "SHADOWCLI_SKILL_ROOTS"


def default_skill_roots(root: Path, *, extra_roots: list[SkillRoot] | None = None) -> list[SkillRoot]:
    project_root = Path(root)
    roots = [
        SkillRoot(source="project", path=project_root / SKILL_ROOT),
    ]

    roots.extend(extra_roots or [])
    roots.extend(env_skill_roots(os.getenv(SKILL_ROOTS_ENV, "")))
    roots.append(SkillRoot(source="global", path=Path.home() / ".agents" / "skills"))
    return dedupe_roots(roots)


def env_skill_roots(value: str) -> list[SkillRoot]:
    roots: list[SkillRoot] = []
    for index, item in enumerate(part.strip() for part in value.split(os.pathsep)):
        if not item:
            continue
        source, path = parse_root_spec(item, default_source=f"external:{index + 1}")
        roots.append(SkillRoot(source=source, path=Path(path).expanduser()))
    return roots


def parse_root_spec(spec: str, *, default_source: str) -> tuple[str, str]:
    if "=" not in spec:
        return default_source, spec
    source, path = spec.split("=", 1)
    source = source.strip() or default_source
    return source, path.strip()


def dedupe_roots(roots: list[SkillRoot]) -> list[SkillRoot]:
    seen = set()
    deduped = []
    for root in roots:
        key = (root.source, root.path.expanduser())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(root)
    return deduped
