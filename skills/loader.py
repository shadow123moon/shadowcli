from __future__ import annotations

from pathlib import Path
from typing import Any

from .types import SkillDefinition, SkillDiagnostic, SkillRoot


SKILL_ENTRYPOINT = "SKILL.md"


def read_skill_root(root: SkillRoot, diagnostics: list[SkillDiagnostic]) -> list[SkillDefinition]:
    skills_root = root.path
    if not skills_root.exists():
        return []

    skills = []
    try:
        skill_dirs = sorted(path for path in skills_root.iterdir() if path.is_dir())
    except OSError as exc:
        diagnostics.append(skill_diagnostic(skills_root, f"failed to read skill root: {exc}"))
        return []

    for skill_dir in skill_dirs:
        try:
            entrypoint = skill_entrypoint(skill_dir)
            if entrypoint is None:
                continue
            skills.append(read_skill_definition(
                entrypoint,
                directory_name=skill_dir.name,
                source=root.source,
                root=root.path,
            ))
        except (OSError, UnicodeError) as exc:
            diagnostics.append(skill_diagnostic(skill_dir, f"failed to read skill: {exc}"))
    return skills


def skill_entrypoint(skill_dir: Path) -> Path | None:
    preferred = skill_dir / SKILL_ENTRYPOINT
    if preferred.exists() and preferred.name in {path.name for path in skill_dir.iterdir() if path.is_file()}:
        return preferred

    for path in sorted(item for item in skill_dir.iterdir() if item.is_file()):
        if path.name.lower() == SKILL_ENTRYPOINT.lower():
            return path
    return None


def read_skill_definition(
    path: Path,
    *,
    directory_name: str,
    source: str,
    root: Path,
) -> SkillDefinition:
    raw_content = read_skill_file(path)
    frontmatter, body = split_frontmatter(raw_content)
    metadata = parse_frontmatter(frontmatter)
    return SkillDefinition(
        name=str(metadata.get("name") or directory_name),
        description=str(metadata.get("description") or _first_paragraph(body)),
        path=path,
        directory_name=directory_name,
        source=source,
        root=root,
        disable_model_invocation=bool(metadata.get("disable-model-invocation", False)),
        argument_hint=str(metadata.get("argument-hint") or ""),
        when_to_use=str(metadata.get("when_to_use") or metadata.get("when-to-use") or ""),
    )


def split_frontmatter(text: str) -> tuple[str, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return "", text

    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            frontmatter = "\n".join(lines[1:index])
            body = "\n".join(lines[index + 1:]).lstrip("\n")
            return frontmatter, body
    return "", text


def parse_frontmatter(text: str) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or ":" not in stripped:
            index += 1
            continue

        key, raw_value = stripped.split(":", 1)
        key = key.strip()
        raw_value = raw_value.strip()
        if raw_value.startswith((">", "|")):
            block_lines, index = _consume_block_scalar(lines, index + 1)
            metadata[key] = _parse_block_scalar(raw_value, block_lines)
            continue

        metadata[key] = _parse_scalar(raw_value)
        index += 1
    return metadata


def read_skill_file(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def skill_diagnostic(path: Path, message: str) -> SkillDiagnostic:
    return SkillDiagnostic(skill_path=path, message=message)


def _consume_block_scalar(lines: list[str], start: int) -> tuple[list[str], int]:
    block_lines = []
    index = start
    while index < len(lines):
        line = lines[index]
        if line.strip() and not line.startswith((" ", "\t")):
            break
        block_lines.append(line.strip())
        index += 1
    return block_lines, index


def _parse_block_scalar(style: str, lines: list[str]) -> str:
    content_lines = [line for line in lines if line]
    if style.startswith("|"):
        return "\n".join(content_lines)
    return " ".join(content_lines)


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
