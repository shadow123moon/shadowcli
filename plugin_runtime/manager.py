from __future__ import annotations

import os
from pathlib import Path

from skills import SkillRoot

from .manifest import (
    LoadedPlugin,
    PluginContributions,
    PluginDiagnostic,
    PluginManifest,
    PluginSkillContribution,
    find_plugin_manifest_path,
    read_plugin_manifest,
)
from .state import PluginStateStore


PLUGIN_ROOT = "plugins"
PLUGIN_ROOTS_ENV = "SHADOWCLI_PLUGIN_ROOTS"


class PluginManager:
    """Load manifest-declared plugin contributions.

    Phase 3 only exposes skill contributions. Hooks, MCP servers, runtime
    extensions, and app metadata stay out of this loader until later phases.
    """

    def __init__(
        self,
        root: Path | str,
        *,
        plugins_dir: str = PLUGIN_ROOT,
        extra_plugin_roots: list[Path | str] | None = None,
        enabled_plugins: set[str] | None = None,
    ):
        self.root = Path(root)
        self.plugins_root = self.root / plugins_dir
        self.extra_plugin_roots = [Path(path).expanduser() for path in extra_plugin_roots or []]
        self.enabled_plugins = enabled_plugins
        self._loaded: list[LoadedPlugin] | None = None
        self._diagnostics: list[PluginDiagnostic] | None = None

    def list_plugins(self) -> list[LoadedPlugin]:
        self._ensure_loaded()
        assert self._loaded is not None
        return list(self._loaded)

    def contributions(self) -> PluginContributions:
        skill_roots = []
        for plugin in self.list_plugins():
            if plugin.enabled:
                skill_roots.extend(plugin.contributions.skill_roots)
        return PluginContributions(skill_roots=skill_roots)

    def diagnostics(self) -> list[PluginDiagnostic]:
        self._ensure_loaded()
        assert self._diagnostics is not None
        return list(self._diagnostics)

    def _ensure_loaded(self) -> None:
        if self._loaded is not None and self._diagnostics is not None:
            return

        plugins: list[LoadedPlugin] = []
        diagnostics: list[PluginDiagnostic] = []
        enabled_plugins = self._enabled_plugins()
        plugin_roots = self._plugin_roots()
        if not plugin_roots:
            self._loaded = plugins
            self._diagnostics = diagnostics
            return

        for plugin_root in plugin_roots:
            if find_plugin_manifest_path(plugin_root) is None:
                continue

            manifest, manifest_diagnostics = read_plugin_manifest(plugin_root)
            diagnostics.extend(manifest_diagnostics)
            if manifest is None:
                continue

            contributions = PluginContributions(
                skill_roots=_skill_roots_for_plugin(plugin_root, manifest, diagnostics),
            )
            plugins.append(LoadedPlugin(
                root=plugin_root,
                manifest=manifest,
                contributions=contributions,
                enabled=manifest.id in enabled_plugins,
            ))

        self._loaded = plugins
        self._diagnostics = diagnostics

    def _plugin_roots(self) -> list[Path]:
        roots: list[Path] = []
        if self.plugins_root.exists():
            roots.extend(sorted(path for path in self.plugins_root.iterdir() if path.is_dir()))
        roots.extend(self.extra_plugin_roots)
        roots.extend(_env_plugin_roots(os.getenv(PLUGIN_ROOTS_ENV, "")))
        return _dedupe_paths(roots)

    def _enabled_plugins(self) -> set[str]:
        if self.enabled_plugins is not None:
            return set(self.enabled_plugins)
        return PluginStateStore(self.root).enabled()


def _env_plugin_roots(value: str) -> list[Path]:
    roots = []
    for item in (part.strip() for part in value.split(os.pathsep)):
        if item:
            roots.append(Path(item).expanduser())
    return roots


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    seen = set()
    deduped = []
    for path in paths:
        key = path.resolve() if path.exists() else path.absolute()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(path)
    return deduped


def _skill_roots_for_plugin(
    plugin_root: Path,
    manifest: PluginManifest,
    diagnostics: list[PluginDiagnostic],
) -> list[SkillRoot]:
    roots = []
    for index, contribution in enumerate(manifest.skills):
        resolved = _resolve_contribution_path(plugin_root, contribution, index, diagnostics)
        if resolved is None:
            continue
        roots.append(SkillRoot(source=f"plugin:{manifest.id}", path=resolved))
    return roots


def _resolve_contribution_path(
    plugin_root: Path,
    contribution: PluginSkillContribution,
    index: int,
    diagnostics: list[PluginDiagnostic],
) -> Path | None:
    if not contribution.path.startswith("./"):
        diagnostics.append(PluginDiagnostic(
            plugin_path=plugin_root,
            message=f"skills[{index}].path must start with './'",
        ))
        return None

    relative = Path(contribution.path)
    if relative.is_absolute():
        diagnostics.append(PluginDiagnostic(
            plugin_path=plugin_root,
            message=f"skills[{index}].path must be relative",
        ))
        return None

    plugin_base = plugin_root.resolve()
    resolved = (plugin_root / relative).resolve()
    try:
        resolved.relative_to(plugin_base)
    except ValueError:
        diagnostics.append(PluginDiagnostic(
            plugin_path=plugin_root,
            message=f"skills[{index}].path points outside plugin root",
        ))
        return None
    if not resolved.is_dir():
        diagnostics.append(PluginDiagnostic(
            plugin_path=plugin_root,
            message=f"skills[{index}].path must point to a directory",
        ))
        return None
    return resolved
