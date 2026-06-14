from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


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
