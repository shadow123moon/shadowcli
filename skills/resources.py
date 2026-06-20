from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .types import LoadedSkill


RESOURCE_DIRS = ("references", "scripts", "templates", "assets")
_RESOURCE_REF_RE = re.compile(
    r"(?<![\w./\\-])("
    + "|".join(re.escape(name) for name in RESOURCE_DIRS)
    + r")[/\\]([^\s`'\"()\[\]{}<>]+)"
)


@dataclass(frozen=True)
class SkillResource:
    path: str
    kind: str
    source: str


def list_skill_resources(skill: LoadedSkill) -> list[SkillResource]:
    """Return the discoverable resources inside a skill package."""
    resources: dict[str, SkillResource] = {}
    skill_dir = skill.definition.path.parent

    for relative_path in _body_resource_paths(skill.body):
        path = _resolve_resource_path(skill_dir, relative_path)
        if path is not None and path.is_file():
            resources.setdefault(
                _display_path(skill_dir, path),
                SkillResource(
                    path=_display_path(skill_dir, path),
                    kind=_resource_kind(skill_dir, path),
                    source="body-reference",
                ),
            )

    for directory in RESOURCE_DIRS:
        root = skill_dir / directory
        if not root.is_dir():
            continue
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            display = _display_path(skill_dir, path)
            resources.setdefault(
                display,
                SkillResource(path=display, kind=_resource_kind(skill_dir, path), source="directory-scan"),
            )

    return [resources[key] for key in sorted(resources)]


def format_skill_resource_index(skill: LoadedSkill) -> str:
    resources = list_skill_resources(skill)
    if not resources:
        return ""

    lines = [
        "## Skill Resources",
        "当前 skill 还有以下资源可按需读取；不要猜资源内容，需要时调用 read_skill_resource(path)。",
    ]
    for resource in resources:
        lines.append(f"- {resource.path} ({resource.kind})")
    return "\n".join(lines)


def read_skill_resource(skill: LoadedSkill, resource_path: str) -> str:
    skill_dir = skill.definition.path.parent.resolve()
    normalized = _normalize_relative_path(resource_path)
    if normalized is None:
        raise PermissionError("skill resource path must be relative")

    path = (skill_dir / normalized).resolve()
    if not _is_relative_to(path, skill_dir):
        raise PermissionError("skill resource path escapes the active skill directory")
    if path.parts[len(skill_dir.parts)] not in RESOURCE_DIRS:
        raise PermissionError("skill resource must be inside references/scripts/templates/assets")
    if not path.exists():
        raise FileNotFoundError(f"skill resource not found: {resource_path}")
    if not path.is_file():
        raise IsADirectoryError(f"skill resource is not a file: {resource_path}")

    return path.read_text(encoding="utf-8", errors="replace")


def _body_resource_paths(body: str) -> list[str]:
    paths: list[str] = []
    for match in _RESOURCE_REF_RE.finditer(body):
        relative = f"{match.group(1)}/{match.group(2).rstrip('.,;:')}"
        if relative not in paths:
            paths.append(relative)
    return paths


def _resolve_resource_path(skill_dir: Path, resource_path: str) -> Path | None:
    normalized = _normalize_relative_path(resource_path)
    if normalized is None:
        return None
    path = (skill_dir / normalized).resolve()
    skill_root = skill_dir.resolve()
    if not _is_relative_to(path, skill_root):
        return None
    return path


def _normalize_relative_path(path: str) -> Path | None:
    text = str(path or "").strip().replace("\\", "/")
    if not text:
        return None
    candidate = Path(text)
    if candidate.is_absolute() or ".." in candidate.parts:
        return None
    return candidate


def _display_path(skill_dir: Path, path: Path) -> str:
    return path.resolve().relative_to(skill_dir.resolve()).as_posix()


def _resource_kind(skill_dir: Path, path: Path) -> str:
    relative = path.resolve().relative_to(skill_dir.resolve())
    first = relative.parts[0] if relative.parts else ""
    if first in RESOURCE_DIRS:
        return first[:-1] if first.endswith("s") else first
    return "resource"


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
