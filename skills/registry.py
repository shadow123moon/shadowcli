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
class SkillDiagnostic:
    skill_path: Path
    message: str


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
    when_to_use: str = ""


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
        self._diagnostics: list[SkillDiagnostic] | None = None

    def list(self) -> list[SkillDefinition]:
        skills = []
        diagnostics: list[SkillDiagnostic] = []
        for skill_root in self.roots:
            skills.extend(_read_root(skill_root, diagnostics))
        self._diagnostics = diagnostics
        return skills

    def diagnostics(self) -> list[SkillDiagnostic]:
        if self._diagnostics is None:
            self.list()
        assert self._diagnostics is not None
        return list(self._diagnostics)

    def find(self, name: str) -> SkillDefinition | None:
        normalized = name.strip()
        if not normalized:
            return None

        skills = self.list()
        namespaced = _parse_namespaced_skill(normalized)
        if namespaced is not None:
            source, skill_name = namespaced
            source_candidates = {source}
            if not source.startswith("plugin:"):
                source_candidates.add(f"plugin:{source}")
            return _find_in_skills(
                [skill for skill in skills if skill.source in source_candidates],
                skill_name,
            )

        return _find_in_skills(skills, normalized)

    def load(self, name: str) -> LoadedSkill:
        definition = self.find(name)
        if definition is None:
            raise KeyError(f"skill not found: {name}")

        return self.load_definition(definition)

    def load_definition(self, definition: SkillDefinition) -> LoadedSkill:
        raw_content = _read_skill_file(definition.path)
        _, body = _split_frontmatter(raw_content)

        # 重写插件 skill 里的相对路径引用
        if definition.source.startswith("plugin:"):
            body = _rewrite_skill_paths(body, definition.path.parent, definition.root)

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


def _read_root(root: SkillRoot, diagnostics: list[SkillDiagnostic]) -> list[SkillDefinition]:
    skills_root = root.path
    if not skills_root.exists():
        return []

    skills = []
    try:
        skill_dirs = sorted(path for path in skills_root.iterdir() if path.is_dir())
    except OSError as exc:
        diagnostics.append(_diagnostic(skills_root, f"failed to read skill root: {exc}"))
        return []

    for skill_dir in skill_dirs:
        try:
            entrypoint = _skill_entrypoint(skill_dir)
            if entrypoint is None:
                continue
            skills.append(_read_definition(
                entrypoint,
                directory_name=skill_dir.name,
                source=root.source,
                root=root.path,
            ))
        except (OSError, UnicodeError) as exc:
            diagnostics.append(_diagnostic(skill_dir, f"failed to read skill: {exc}"))
    return skills


def _skill_entrypoint(skill_dir: Path) -> Path | None:
    preferred = skill_dir / SKILL_ENTRYPOINT
    if preferred.exists() and preferred.name in {path.name for path in skill_dir.iterdir() if path.is_file()}:
        return preferred

    for path in sorted(item for item in skill_dir.iterdir() if item.is_file()):
        if path.name.lower() == SKILL_ENTRYPOINT.lower():
            return path
    return None


def _read_definition(
    path: Path,
    *,
    directory_name: str,
    source: str,
    root: Path,
) -> SkillDefinition:
    raw_content = _read_skill_file(path)
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
        when_to_use=str(metadata.get("when_to_use") or metadata.get("when-to-use") or ""),
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


def _parse_namespaced_skill(name: str) -> tuple[str, str] | None:
    source, separator, skill_name = name.partition(":")
    if not separator or not source.strip() or not skill_name.strip():
        return None
    return source.strip(), skill_name.strip()


def _find_in_skills(skills: list[SkillDefinition], name: str) -> SkillDefinition | None:
    for skill in skills:
        if skill.name == name:
            return skill
    for skill in skills:
        if skill.directory_name == name:
            return skill
    return None


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


def _rewrite_skill_paths(body: str, skill_dir: Path, plugin_root: Path | None) -> str:
    """重写插件 skill 中的相对路径引用

    将 `skills/xxx` 和 `scripts/xxx` 替换成从项目根目录的相对路径。

    例如：
    - `skills/brainstorming/visual-companion.md`
      → `plugins/superpowers/skills/brainstorming/visual-companion.md`
    - `scripts/start-server.sh`
      → `plugins/superpowers/skills/brainstorming/scripts/start-server.sh`
    """
    import re

    # 获取从项目根到 skill 目录的相对路径
    if plugin_root is None:
        return body

    try:
        # 计算 skill_dir 相对于当前工作目录的路径
        from pathlib import Path
        cwd = Path.cwd()
        skill_rel = skill_dir.relative_to(cwd)
        from_root = str(skill_rel).replace("\\", "/")
    except (ValueError, AttributeError):
        # 如果无法计算相对路径，返回原内容
        return body

    # 替换 markdown 代码块里的 `skills/skill_name/xxx`
    # 原文：`skills/brainstorming/visual-companion.md`
    # 目标：`plugins/superpowers/skills/brainstorming/visual-companion.md`
    # 提取 skill_name
    skill_name = skill_dir.name

    def replace_skills(match):
        # match.group(1) = "brainstorming/visual-companion.md"
        # 去掉开头的 skill_name/
        rest = match.group(1)
        if rest.startswith(f"{skill_name}/"):
            rest = rest[len(skill_name)+1:]
        return f'`{from_root}/{rest}`'

    body = re.sub(r'`skills/([^`]+)`', replace_skills, body)

    # 替换 bash 命令里的 scripts/
    # 例如：scripts/start-server.sh
    def replace_scripts(match):
        return f'{match.group(1)}{from_root}/scripts/'

    body = re.sub(r'(\s|^)scripts/', replace_scripts, body, flags=re.MULTILINE)

    return body


def _parse_frontmatter(text: str) -> dict[str, Any]:
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


def _read_skill_file(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def _diagnostic(path: Path, message: str) -> SkillDiagnostic:
    return SkillDiagnostic(skill_path=path, message=message)
