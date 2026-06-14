from __future__ import annotations

from pathlib import Path

from .assets import rewrite_plugin_skill_paths
from .loader import read_skill_file, read_skill_root, split_frontmatter
from .references import parse_namespaced_skill, source_candidates_for_reference
from .sources import default_skill_roots
from .types import LoadedSkill, SkillDefinition, SkillDiagnostic, SkillRoot


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
            skills.extend(read_skill_root(skill_root, diagnostics))
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
        namespaced = parse_namespaced_skill(normalized)
        if namespaced is not None:
            source, skill_name = namespaced
            return _find_in_skills(
                [skill for skill in skills if skill.source in source_candidates_for_reference(source)],
                skill_name,
            )

        return _find_in_skills(skills, normalized)

    def load(self, name: str) -> LoadedSkill:
        definition = self.find(name)
        if definition is None:
            raise KeyError(f"skill not found: {name}")

        return self.load_definition(definition)

    def load_definition(self, definition: SkillDefinition) -> LoadedSkill:
        raw_content = read_skill_file(definition.path)
        _, body = split_frontmatter(raw_content)

        # 重写插件 skill 里的相对路径引用
        if definition.source.startswith("plugin:"):
            body = rewrite_plugin_skill_paths(body, definition.path.parent, definition.root)

        return LoadedSkill(
            definition=definition,
            raw_content=raw_content,
            body=body,
        )


def _find_in_skills(skills: list[SkillDefinition], name: str) -> SkillDefinition | None:
    for skill in skills:
        if skill.name == name:
            return skill
    for skill in skills:
        if skill.directory_name == name:
            return skill
    return None
