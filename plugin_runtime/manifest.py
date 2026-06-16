from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from skills import SkillRoot


PLUGIN_MANIFEST = "plugin.json"
CODEX_PLUGIN_DIR = ".codex-plugin"
PLUGIN_NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@dataclass(frozen=True)
class PluginDiagnostic:
    plugin_path: Path
    message: str


@dataclass(frozen=True)
class PluginSkillContribution:
    path: str


@dataclass(frozen=True)
class PluginManifest:
    id: str
    name: str
    version: str
    description: str
    skills: list[PluginSkillContribution]


@dataclass(frozen=True)
class PluginContributions:
    skill_roots: list[SkillRoot]


@dataclass(frozen=True)
class LoadedPlugin:
    root: Path
    manifest: PluginManifest
    contributions: PluginContributions
    enabled: bool = False


def find_plugin_manifest_path(plugin_root: Path) -> Path | None:
    manifest_path = plugin_root / CODEX_PLUGIN_DIR / PLUGIN_MANIFEST
    if manifest_path.exists():
        return manifest_path
    return None


def read_plugin_manifest(plugin_root: Path) -> tuple[PluginManifest | None, list[PluginDiagnostic]]:
    manifest_path = find_plugin_manifest_path(plugin_root)
    if manifest_path is None:
        return None, [_diagnostic(plugin_root, "plugin manifest not found")]

    try:
        raw = manifest_path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except Exception as exc:
        return None, [_diagnostic(plugin_root, f"failed to read plugin.json: {exc}")]

    if not isinstance(data, dict):
        return None, [_diagnostic(plugin_root, "plugin.json must contain a JSON object")]

    diagnostics: list[PluginDiagnostic] = []
    name = _required_string(data, "name", plugin_root, diagnostics)
    version = _required_string(data, "version", plugin_root, diagnostics)
    if name is not None and not PLUGIN_NAME_PATTERN.fullmatch(name):
        diagnostics.append(_diagnostic(plugin_root, "name must be kebab-case"))
        name = None
    if name is None or version is None:
        return None, diagnostics

    manifest = PluginManifest(
        id=name,
        name=name,
        version=version,
        description=_optional_string(data, "description", "", plugin_root, diagnostics),
        skills=_read_skill_contributions(data.get("skills", []), plugin_root, diagnostics),
    )
    return manifest, diagnostics


def _read_skill_contributions(
    raw_skills: Any,
    plugin_root: Path,
    diagnostics: list[PluginDiagnostic],
) -> list[PluginSkillContribution]:
    if raw_skills is None:
        return []
    if isinstance(raw_skills, str):
        if raw_skills.strip():
            return [PluginSkillContribution(path=raw_skills.strip())]
        diagnostics.append(_diagnostic(plugin_root, "skills must not be empty"))
        return []
    if not isinstance(raw_skills, list):
        diagnostics.append(_diagnostic(plugin_root, "skills must be a string or list"))
        return []

    skills = []
    for index, item in enumerate(raw_skills):
        if isinstance(item, str):
            path = item.strip()
            if not path:
                diagnostics.append(_diagnostic(plugin_root, f"skills[{index}] must be a non-empty string"))
                continue
            skills.append(PluginSkillContribution(path=path))
            continue
        if not isinstance(item, dict):
            diagnostics.append(_diagnostic(plugin_root, f"skills[{index}] must be a string or object"))
            continue
        path = item.get("path")
        if not isinstance(path, str) or not path.strip():
            diagnostics.append(_diagnostic(plugin_root, f"skills[{index}].path must be a non-empty string"))
            continue
        skills.append(PluginSkillContribution(path=path.strip()))
    return skills


def _required_string(
    data: dict[str, Any],
    key: str,
    plugin_root: Path,
    diagnostics: list[PluginDiagnostic],
) -> str | None:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        diagnostics.append(_diagnostic(plugin_root, f"{key} must be a non-empty string"))
        return None
    return value.strip()


def _optional_string(
    data: dict[str, Any],
    key: str,
    default: str,
    plugin_root: Path,
    diagnostics: list[PluginDiagnostic],
) -> str:
    value = data.get(key, default)
    if value is None:
        return default
    if not isinstance(value, str):
        diagnostics.append(_diagnostic(plugin_root, f"{key} must be a string"))
        return default
    return value.strip()


def _diagnostic(plugin_root: Path, message: str) -> PluginDiagnostic:
    return PluginDiagnostic(plugin_path=plugin_root, message=message)
