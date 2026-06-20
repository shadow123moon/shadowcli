from __future__ import annotations

from typing import Any

from tooling import Tool

from .resources import read_skill_resource


class SkillResourceTool(Tool):
    category = "skill"
    effect = "read"
    concurrency_safe = True
    result_kind = "text"
    guidance = "读取当前激活 skill 包内的 references/scripts/templates/assets 资源；不要用它读取项目文件。"

    @property
    def name(self) -> str:
        return "read_skill_resource"

    @property
    def description(self) -> str:
        return "读取当前激活 skill 的附加资源文件，只能访问该 skill 内的 references/scripts/templates/assets。"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "资源相对路径，例如 references/rules.md 或 scripts/check.py。",
                }
            },
            "required": ["path"],
            "additionalProperties": False,
        }

    def execute(self, arguments: dict[str, Any]) -> str:
        return "没有激活的 skill，无法读取 skill resource。"

    def execute_with_context(self, arguments: dict[str, Any], context: Any) -> str:
        skill = getattr(context, "active_skill", None)
        if skill is None:
            return "没有激活的 skill，无法读取 skill resource。"

        path = str(arguments.get("path") or "").strip()
        if not path:
            return "缺少 path 参数。"

        try:
            return read_skill_resource(skill, path)
        except (FileNotFoundError, IsADirectoryError, PermissionError) as exc:
            return f"读取 skill resource 失败: {exc}"
