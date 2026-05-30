import os
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
    register_freshness_guard,
)

from .constants import DEFAULT_LONG_TERM_PATH


def build_registry() -> ToolRuntime:
    """构造工具运行时。

    PAICLI_APPROVAL=off/human/ai 控制工具级审批策略。
    兼容旧变量：PAICLI_HITL=1 等价于 PAICLI_APPROVAL=human。
    """
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
    runtime = ToolRuntime(registry)

    # 编辑前必须先 read、且文件未被外部改动（核心防护，默认开启）
    register_freshness_guard(runtime)

    approval_mode = os.getenv("PAICLI_APPROVAL", "off").lower()
    if os.getenv("PAICLI_HITL") == "1":
        approval_mode = "human"

    if approval_mode in {"human", "hitl"}:
        from extensions import hitl
        hitl.register(runtime)
    elif approval_mode in {"ai", "reviewer"}:
        from extensions import reviewer
        reviewer.register(runtime)

    return runtime


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
