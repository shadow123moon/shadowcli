from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .registry import LoadedSkill


class ContextBuilder(Protocol):
    def build(self, query: str = "") -> str:
        ...


@dataclass(frozen=True)
class SkillContextBuilder:
    base: ContextBuilder
    skill: LoadedSkill
    arguments: str

    def build(self, query: str = "") -> str:
        parts = [
            self.base.build(query),
            format_skill_context(self.skill, self.arguments),
        ]
        return "\n\n".join(part for part in parts if part).rstrip()


def format_skill_context(skill: LoadedSkill, arguments: str) -> str:
    body = skill.body.replace("$ARGUMENTS", arguments).strip()
    lines = [
        "## 当前 Skill",
        f"- name: {skill.definition.name}",
        f"- source: {skill.definition.source}",
        f"- path: {skill.definition.path}",
    ]
    if arguments:
        lines.append(f"- arguments: {arguments}")
    if body:
        lines.extend(["", "### Skill Instructions", body])
    return "\n".join(lines)
