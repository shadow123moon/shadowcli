from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from skills import (
    SkillContextBuilder,
    SkillDefinition,
    SkillRegistry,
    SkillSelection,
    SkillSelector,
    SkillRoot,
    auto_skills_enabled,
)
from skills.sources import dedupe_roots, env_skill_roots

from .events import EventBus
from .state import AppStateStore


SKILL_ROOT = Path(".agents") / "skills"
SKILL_ROOTS_ENV = "SHADOWCLI_SKILL_ROOTS"


@dataclass
class SkillManager:
    cwd: Path
    registry: SkillRegistry
    state_store: AppStateStore
    event_bus: EventBus | None = None

    @classmethod
    def create(
        cls,
        cwd: Path | str,
        *,
        skill_roots: list[SkillRoot] | None = None,
        state_store: AppStateStore | None = None,
        event_bus: EventBus | None = None,
    ) -> "SkillManager":
        project_cwd = Path(cwd)
        store = state_store or AppStateStore.create(project_cwd)
        roots = build_skill_roots(project_cwd) if skill_roots is None else skill_roots
        registry = SkillRegistry(project_cwd, roots=roots)
        return cls(
            cwd=project_cwd,
            registry=registry,
            state_store=store,
            event_bus=event_bus,
        )

    def refresh(self, *, skill_roots: list[SkillRoot] | None = None) -> SkillRegistry:
        roots = build_skill_roots(self.cwd) if skill_roots is None else skill_roots
        self.registry = SkillRegistry(self.cwd, roots=roots)
        self._publish("skills.refreshed", cwd=self.cwd)
        return self.registry

    def build_context(self, name: str, base: Any, *, arguments: str) -> SkillContextBuilder:
        loaded_skill = self.registry.load(name)
        return SkillContextBuilder(base=base, skill=loaded_skill, arguments=arguments)

    def build_context_for_definition(
        self,
        definition: SkillDefinition,
        base: Any,
        *,
        arguments: str,
    ) -> SkillContextBuilder:
        loaded_skill = self.registry.load_definition(definition)
        return SkillContextBuilder(base=base, skill=loaded_skill, arguments=arguments)

    def select_auto_skill(
        self,
        user_input: str,
        *,
        selector: SkillSelector | None = None,
        chat_fn: Callable[..., Any] | None = None,
    ) -> SkillSelection | None:
        if not auto_skills_enabled():
            return None

        active_selector = selector or (
            SkillSelector(self.registry, chat_fn=chat_fn) if chat_fn is not None else SkillSelector(self.registry)
        )
        selection = active_selector.select(user_input)
        if selection is None or selection.skill is None:
            return None
        return selection

    def _publish(self, event_type: str, **payload: Any) -> None:
        if self.event_bus is not None:
            self.event_bus.publish(event_type, **payload)


def build_skill_roots(cwd: Path | str, *, plugin_roots: list[SkillRoot] | None = None) -> list[SkillRoot]:
    project_cwd = Path(cwd)
    roots = [
        SkillRoot(source="project", path=project_cwd / SKILL_ROOT),
    ]
    roots.extend(plugin_roots or [])
    roots.extend(env_skill_roots(os.getenv(SKILL_ROOTS_ENV, "")))
    roots.append(SkillRoot(source="global", path=Path.home() / ".agents" / "skills"))
    return dedupe_roots(roots)
