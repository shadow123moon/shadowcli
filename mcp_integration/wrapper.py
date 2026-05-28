"""MCP 工具包装器 - 适配到当前 Tool 接口"""
from __future__ import annotations
from typing import TYPE_CHECKING

from tooling import Tool
from .sanitizer import sanitize_schema

if TYPE_CHECKING:
    from .manager import McpServerManager


class McpToolWrapper(Tool):
    """MCP 工具包装器

    关键:
    - 实现同步 execute() 接口
    - 内部调用 manager.call_tool_sync()
    """

    def __init__(
        self,
        server_name: str,
        tool_def: dict,
        manager: McpServerManager,
    ):
        self.server_name = server_name
        self.tool_def = tool_def
        self.manager = manager

        self._name = f"mcp__{server_name}__{tool_def['name']}"
        self._description = tool_def.get("description", "")
        self._parameters = sanitize_schema(tool_def.get("inputSchema", {}))

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def parameters(self) -> dict:
        return self._parameters

    @property
    def approval_required(self) -> bool:
        return True  # MCP 工具默认需要审批

    @property
    def approval_level(self) -> str:
        return "🟡 中危"

    @property
    def approval_reason(self) -> str:
        return f"调用外部 MCP server '{self.server_name}' 的工具"

    def execute(self, arguments: dict) -> str:
        """同步执行(适配当前 Tool 接口)"""
        try:
            return self.manager.call_tool_sync(
                self.server_name,
                self.tool_def["name"],
                arguments,
                timeout=60,
            )
        except Exception as e:
            return f"MCP 工具调用失败: {e}"
