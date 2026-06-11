from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from plugin_runtime import PluginManager
from skills import (
    SkillContextBuilder,
    SkillDefinition,
    SkillRegistry,
    SkillSelection,
    SkillSelector,
    auto_skills_enabled,
)

from .events import EventBus
from .state import AppStateStore


@dataclass
class SkillManager:
    cwd: Path
    plugin_manager: PluginManager
    registry: SkillRegistry
    state_store: AppStateStore
    event_bus: EventBus | None = None

    @classmethod
    def create(
        cls,
        cwd: Path | str,
        *,
        state_store: AppStateStore | None = None,
        event_bus: EventBus | None = None,
    ) -> "SkillManager":
        project_cwd = Path(cwd)
        store = state_store or AppStateStore.create(project_cwd)
        plugin_manager, registry = build_plugin_skill_registry(project_cwd, state_store=store)
        return cls(
            cwd=project_cwd,
            plugin_manager=plugin_manager,
            registry=registry,
            state_store=store,
            event_bus=event_bus,
        )

    def refresh(self) -> SkillRegistry:
        self.plugin_manager, self.registry = build_plugin_skill_registry(self.cwd, state_store=self.state_store)
        self._publish("skills.refreshed", cwd=self.cwd)
        return self.registry

    def plugin_status(self) -> tuple[list[Any], list[Any]]:
        return self.plugin_manager.list_plugins(), self.plugin_manager.diagnostics()

    def set_plugin_enabled(self, name: str, enabled: bool) -> bool:
        known = {plugin.manifest.id for plugin in self.plugin_manager.list_plugins()}
        if name not in known:
            return False

        self.state_store.set_plugin_enabled(name, enabled)
        self.refresh()
        self._publish("plugin.enabled" if enabled else "plugin.disabled", name=name)
        return True

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


def build_plugin_skill_registry(
    cwd: Path | str,
    *,
    state_store: AppStateStore | None = None,
) -> tuple[PluginManager, SkillRegistry]:
    project_cwd = Path(cwd)
    store = state_store or AppStateStore.create(project_cwd)
    plugin_manager = PluginManager(project_cwd, enabled_plugins=store.enabled_plugins())
    registry = SkillRegistry(project_cwd, extra_roots=plugin_manager.skill_roots())
    return plugin_manager, registry
