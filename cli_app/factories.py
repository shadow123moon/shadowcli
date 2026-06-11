from collections.abc import Callable
from pathlib import Path

from agent import ReactAgent
from extensions.tool_runtime import ToolRuntime
from llm import Message
from sessions import TextLongTermMemory
from tooling import (
    BashTool,
    EditTool,
    FindTool,
    GrepTool,
    LsTool,
    ReadTool,
    ToolRegistry,
    WriteTool,
    WebSearchTool,
    WebFetchTool,
)

from .constants import DEFAULT_LONG_TERM_PATH


def build_registry(*, install_hooks: bool = False) -> ToolRuntime:
    """构造不带默认 hooks 的工具运行时，hooks 由 AppRuntime 安装。"""
    registry = ToolRegistry()
    registry.register(ReadTool())
    registry.register(WriteTool())
    registry.register(EditTool())
    registry.register(BashTool())
    registry.register(LsTool())
    registry.register(GrepTool())
    registry.register(FindTool())
    registry.register(WebSearchTool())
    registry.register(WebFetchTool())
    return ToolRuntime(registry)


def list_tools(registry: ToolRuntime) -> str:
    defs = registry.get_all_definitions()
    if not defs:
        return "(无已注册工具)"
    lines = ["已注册工具:"]
    for d in defs:
        fn = d["function"]
        lines.append(f"  - {fn['name']}: {fn['description']}")
    return "\n".join(lines)


def build_long_term_memory(long_term_path: Path | None = None) -> TextLongTermMemory:
    return TextLongTermMemory(long_term_path or DEFAULT_LONG_TERM_PATH)


def build_agent(
    registry: ToolRegistry,
    *,
    conversation_messages: list[Message] | None = None,
    on_message_appended: Callable[[Message], None] | None = None,
) -> ReactAgent:
    return ReactAgent(
        registry,
        conversation_messages=conversation_messages,
        on_message_appended=on_message_appended,
    )
