from __future__ import annotations

from .command_tools import BashTool
from .file_tools import EditTool, FindTool, GrepTool, LsTool, ReadTool, WriteTool
from .registry import ToolRegistry
from .runtime import ToolRuntime
from .web_tools import WebFetchTool, WebSearchTool


def build_default_tool_runtime() -> ToolRuntime:
    registry = ToolRegistry()
    for tool in (
        ReadTool(),
        WriteTool(),
        EditTool(),
        BashTool(),
        LsTool(),
        GrepTool(),
        FindTool(),
        WebSearchTool(),
        WebFetchTool(),
    ):
        registry.register(tool)
    return ToolRuntime(registry)


def format_tool_list(runtime: ToolRuntime) -> str:
    definitions = runtime.get_all_definitions()
    if not definitions:
        return "(无已注册工具)"
    lines = ["已注册工具:"]
    for definition in definitions:
        function = definition["function"]
        lines.append(f"  - {function['name']}: {function['description']}")
    return "\n".join(lines)
