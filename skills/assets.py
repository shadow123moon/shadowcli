from __future__ import annotations

import re
from pathlib import Path


def rewrite_plugin_skill_paths(body: str, skill_dir: Path, plugin_root: Path | None) -> str:
    """Rewrite relative resource references in plugin skill instructions."""
    if plugin_root is None:
        return body

    try:
        cwd = Path.cwd()
        skill_rel = skill_dir.relative_to(cwd)
        from_root = str(skill_rel).replace("\\", "/")
    except (ValueError, AttributeError):
        return body

    skill_name = skill_dir.name

    def replace_skills(match):
        rest = match.group(1)
        if rest.startswith(f"{skill_name}/"):
            rest = rest[len(skill_name) + 1:]
        return f"`{from_root}/{rest}`"

    body = re.sub(r"`skills/([^`]+)`", replace_skills, body)

    def replace_scripts(match):
        return f"{match.group(1)}{from_root}/scripts/"

    return re.sub(r"(\s|^)scripts/", replace_scripts, body, flags=re.MULTILINE)
