from __future__ import annotations

from pathlib import Path

from skills import SkillRoot

from .manifest import (
    PLUGIN_MANIFEST,
    LoadedPlugin,
    PluginDiagnostic,
    PluginManifest,
    PluginSkillContribution,
    read_plugin_manifest,
)


PLUGIN_ROOT = "plugins"


class PluginManager:
    """Load manifest-declared plugin contributions.

    Phase 3 only exposes skill contributions. Hooks, MCP servers, runtime
    extensions, and app metadata stay out of this loader until later phases.
    """

    def __init__(self, root: Path | str, *, plugins_dir: str = PLUGIN_ROOT):
        self.root = Path(root)
        self.plugins_root = self.root / plugins_dir
        self._loaded: list[LoadedPlugin] | None = None
        self._diagnostics: list[PluginDiagnostic] | None = None

    def list_plugins(self) -> list[LoadedPlugin]:
        self._ensure_loaded()
        assert self._loaded is not None
        return list(self._loaded)

    def skill_roots(self) -> list[SkillRoot]:
        roots = []
        for plugin in self.list_plugins():
            roots.extend(plugin.skill_roots)
        return roots

    def diagnostics(self) -> list[PluginDiagnostic]:
        self._ensure_loaded()
        assert self._diagnostics is not None
        return list(self._diagnostics)

    def _ensure_loaded(self) -> None:
        if self._loaded is not None and self._diagnostics is not None:
            return

        plugins: list[LoadedPlugin] = []
        diagnostics: list[PluginDiagnostic] = []
        if not self.plugins_root.exists():
            self._loaded = plugins
            self._diagnostics = diagnostics
            return

        for plugin_root in sorted(path for path in self.plugins_root.iterdir() if path.is_dir()):
            manifest_path = plugin_root / PLUGIN_MANIFEST
            if not manifest_path.exists():
                continue

            manifest, manifest_diagnostics = read_plugin_manifest(plugin_root)
            diagnostics.extend(manifest_diagnostics)
            if manifest is None:
                continue

            skill_roots = _skill_roots_for_plugin(plugin_root, manifest, diagnostics)
            plugins.append(LoadedPlugin(root=plugin_root, manifest=manifest, skill_roots=skill_roots))

        self._loaded = plugins
        self._diagnostics = diagnostics


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
