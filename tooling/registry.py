import json
from typing import Any, Dict, List

from .base import Tool


class ToolRegistry:
    """工具注册中心：只负责注册、查找和直接执行工具。"""

    def __init__(self):
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> "ToolRegistry":
        self._tools[tool.name] = tool
        return self

    def get(self, name: str) -> Tool:
        return self._tools[name]

    def execute(self, name: str, arguments: Dict[str, Any]) -> str:
        tool = self.get(name)
        return tool.execute(arguments)

    def get_all_definitions(self) -> List[Dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": _canonicalize_schema(tool.parameters),
                },
            }
            for _, tool in sorted(self._tools.items())
        ]


def _canonicalize_schema(value: Any, *, parent_key: str = "") -> Any:
    if isinstance(value, dict):
        return {
            str(key): _canonicalize_schema(value[key], parent_key=str(key))
            for key in sorted(value)
        }
    if isinstance(value, list):
        items = [_canonicalize_schema(item) for item in value]
        if parent_key == "required":
            return sorted(items, key=_stable_json)
        return items
    return value


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
