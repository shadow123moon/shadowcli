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
                    "parameters": tool.parameters,
                },
            }
            for tool in self._tools.values()
        ]
