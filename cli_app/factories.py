import os
from pathlib import Path

from agent import ReactAgent
from extensions.tool_runtime import ToolRuntime
from llm.client import chat
from memory_pythonic import MemoryManager
from multi_agent import AgentOrchestrator, PlanReviewDecision, parse_plan_review_input
from tooling import (
    BashTool,
    EditTool,
    ExecuteCommandTool,
    FindTool,
    GrepTool,
    ListDirTool,
    LsTool,
    ReadFileTool,
    ReadTool,
    ToolRegistry,
    WriteFileTool,
    WriteTool,
    WebSearchTool,
    WebFetchTool
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
    registry.register(ReadFileTool())
    registry.register(WriteFileTool())
    registry.register(ListDirTool())
    registry.register(ExecuteCommandTool())
    registry.register(WebSearchTool())
    registry.register(WebFetchTool())
    runtime = ToolRuntime(registry)


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


def build_memory(long_term_path: Path | None = None) -> MemoryManager:
    return MemoryManager(long_term_path=long_term_path or DEFAULT_LONG_TERM_PATH)


def build_agent(registry: ToolRegistry, memory: MemoryManager | None = None) -> ReactAgent:
    return ReactAgent(registry, memory_manager=memory)


def default_plan_review_handler(
    goal: str,
    steps: list,
) -> tuple[PlanReviewDecision, str]:
    """默认的计划审查：展示计划，等用户输入。"""
    user_input = input("\n回车执行 / 输入补充要求 / cancel取消: ")
    return parse_plan_review_input(user_input)


def build_plan_agent(
    registry: ToolRegistry,
    memory: MemoryManager | None = None,
) -> AgentOrchestrator:
    return AgentOrchestrator(
        chat,
        registry,
        memory_manager=memory,
        plan_review_handler=default_plan_review_handler,
    )
