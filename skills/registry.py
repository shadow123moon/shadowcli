from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SKILL_ENTRYPOINT = "SKILL.md"
SKILL_ROOT = Path(".agents") / "skills"
SKILL_ROOTS_ENV = "PAICLI_SKILL_ROOTS"


@dataclass(frozen=True)
class SkillRoot:
    source: str
    path: Path


@dataclass(frozen=True)
class SkillDefinition:
    name: str
    description: str
    path: Path
    directory_name: str
    source: str = "project"
    root: Path | None = None
    disable_model_invocation: bool = False
    argument_hint: str = ""


@dataclass(frozen=True)
class LoadedSkill:
    definition: SkillDefinition
    raw_content: str
    body: str


class SkillRegistry:
    """Discover and load repo-scoped agent skills."""

    def __init__(
        self,
        root: Path | str,
        *,
        roots: list[SkillRoot] | None = None,
        extra_roots: list[SkillRoot] | None = None,
    ):
        self.root = Path(root)
        self.roots = roots if roots is not None else default_skill_roots(self.root, extra_roots=extra_roots)

    def list(self) -> list[SkillDefinition]:
        skills = []
        for skill_root in self.roots:
            skills.extend(_read_root(skill_root))
        return skills

    def find(self, name: str) -> SkillDefinition | None:
        normalized = name.strip()
        if not normalized:
            return None

        for skill in self.list():
            if skill.name == normalized:
                return skill
        for skill in self.list():
            if skill.directory_name == normalized:
                return skill
        return None

    def load(self, name: str) -> LoadedSkill:
        definition = self.find(name)
        if definition is None:
            raise KeyError(f"skill not found: {name}")

        raw_content = definition.path.read_text(encoding="utf-8")
        _, body = _split_frontmatter(raw_content)
        return LoadedSkill(
            definition=definition,
            raw_content=raw_content,
            body=body,
        )


def default_skill_roots(root: Path, *, extra_roots: list[SkillRoot] | None = None) -> list[SkillRoot]:
    project_root = Path(root)
    roots = [
        SkillRoot(source="project", path=project_root / SKILL_ROOT),
    ]

    roots.extend(extra_roots or [])
    roots.extend(_env_skill_roots(os.getenv(SKILL_ROOTS_ENV, "")))
    roots.append(SkillRoot(source="global", path=Path.home() / ".agents" / "skills"))
    return _dedupe_roots(roots)


def _read_root(root: SkillRoot) -> list[SkillDefinition]:
    skills_root = root.path
    if not skills_root.exists():
        return []

    skills = []
    for skill_dir in sorted(path for path in skills_root.iterdir() if path.is_dir()):
        entrypoint = skill_dir / SKILL_ENTRYPOINT
        if entrypoint.exists():
            skills.append(_read_definition(
                entrypoint,
                directory_name=skill_dir.name,
                source=root.source,
                root=root.path,
            ))
    return skills


def _read_definition(
    path: Path,
    *,
    directory_name: str,
    source: str,
    root: Path,
) -> SkillDefinition:
    raw_content = path.read_text(encoding="utf-8")
    frontmatter, body = _split_frontmatter(raw_content)
    metadata = _parse_frontmatter(frontmatter)
    return SkillDefinition(
        name=str(metadata.get("name") or directory_name),
        description=str(metadata.get("description") or _first_paragraph(body)),
        path=path,
        directory_name=directory_name,
        source=source,
        root=root,
        disable_model_invocation=bool(metadata.get("disable-model-invocation", False)),
        argument_hint=str(metadata.get("argument-hint") or ""),
    )


def _env_skill_roots(value: str) -> list[SkillRoot]:
    roots: list[SkillRoot] = []
    for index, item in enumerate(part.strip() for part in value.split(os.pathsep)):
        if not item:
            continue
        source, path = _parse_root_spec(item, default_source=f"external:{index + 1}")
        roots.append(SkillRoot(source=source, path=Path(path).expanduser()))
    return roots


def _parse_root_spec(spec: str, *, default_source: str) -> tuple[str, str]:
    if "=" not in spec:
        return default_source, spec
    source, path = spec.split("=", 1)
    source = source.strip() or default_source
    return source, path.strip()


def _dedupe_roots(roots: list[SkillRoot]) -> list[SkillRoot]:
    seen = set()
    deduped = []
    for root in roots:
        key = (root.source, root.path.expanduser())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(root)
    return deduped


def _split_frontmatter(text: str) -> tuple[str, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return "", text

    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            frontmatter = "\n".join(lines[1:index])
            body = "\n".join(lines[index + 1:]).lstrip("\n")
            return frontmatter, body
    return "", text


def _parse_frontmatter(text: str) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or ":" not in stripped:
            continue

        key, raw_value = stripped.split(":", 1)
        key = key.strip()
        value = _parse_scalar(raw_value.strip())
        metadata[key] = value
    return metadata


def _parse_scalar(value: str) -> str | bool:
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if (
        len(value) >= 2
        and value[0] == value[-1]
        and value[0] in {'"', "'"}
    ):
        return value[1:-1]
    return value


def _first_paragraph(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""
