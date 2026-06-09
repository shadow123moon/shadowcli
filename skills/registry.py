from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


SKILL_ENTRYPOINT = "SKILL.md"
SKILL_ROOT = Path(".agents") / "skills"


@dataclass(frozen=True)
class SkillDefinition:
    name: str
    description: str
    path: Path
    directory_name: str
    disable_model_invocation: bool = False
    argument_hint: str = ""


@dataclass(frozen=True)
class LoadedSkill:
    definition: SkillDefinition
    raw_content: str
    body: str


class SkillRegistry:
    """Discover and load repo-scoped agent skills."""

    def __init__(self, root: Path | str):
        self.root = Path(root)

    def list(self) -> list[SkillDefinition]:
        skills_root = self.root / SKILL_ROOT
        if not skills_root.exists():
            return []

        skills = []
        for skill_dir in sorted(path for path in skills_root.iterdir() if path.is_dir()):
            entrypoint = skill_dir / SKILL_ENTRYPOINT
            if entrypoint.exists():
                skills.append(_read_definition(entrypoint, directory_name=skill_dir.name))
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


def _read_definition(path: Path, *, directory_name: str) -> SkillDefinition:
    raw_content = path.read_text(encoding="utf-8")
    frontmatter, body = _split_frontmatter(raw_content)
    metadata = _parse_frontmatter(frontmatter)
    return SkillDefinition(
        name=str(metadata.get("name") or directory_name),
        description=str(metadata.get("description") or _first_paragraph(body)),
        path=path,
        directory_name=directory_name,
        disable_model_invocation=bool(metadata.get("disable-model-invocation", False)),
        argument_hint=str(metadata.get("argument-hint") or ""),
    )


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
