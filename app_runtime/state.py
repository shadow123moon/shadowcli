from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from plugin_runtime import PluginStateStore


@dataclass
class AppStateStore:
    cwd: Path
    plugin_state: PluginStateStore

    @classmethod
    def create(cls, cwd: Path | str) -> "AppStateStore":
        project_cwd = Path(cwd)
        return cls(cwd=project_cwd, plugin_state=PluginStateStore(project_cwd))

    def enabled_plugins(self) -> set[str]:
        return self.plugin_state.enabled()

    def set_plugin_enabled(self, name: str, enabled: bool) -> None:
        if enabled:
            self.plugin_state.enable(name)
        else:
            self.plugin_state.disable(name)
