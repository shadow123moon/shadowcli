from __future__ import annotations

from typing import Any, Dict

from agent.agent_loop import AgentLoop
from llm import Message
from tooling.base import Tool

from .policy import PLAN_MODE_CONTROL, PLAN_MODE_READ, PLAN_MODE_SHELL, is_plan_mode_tool_visible


_SUBAGENT_MAX_CHARS = 20000


class ExploreAgentTool(Tool):
    category = "plan"
    effect = "control"
    plan_mode = "control"
    plan_mode_only = True
    concurrency_safe = False
    result_kind = "text"
    guidance = (
        "explore_agent 用于在 plan mode 下派一个只读子 agent 探索代码。"
        "它只能读文件、搜索和执行受限只读 shell，不能修改文件或退出 plan mode。"
    )

    def __init__(self, *, parent_runtime: Any, chat_stream_fn: Any):
        self.parent_runtime = parent_runtime
        self.chat_stream_fn = chat_stream_fn

    @property
    def name(self) -> str:
        return "explore_agent"

    @property
    def description(self) -> str:
        return "派一个只读 ExploreAgent 探索代码结构、相关文件和风险点，并返回摘要。"

    @property
    def parameters(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "探索任务，例如：查 session/runtime 相关文件和现有模式。",
                },
            },
            "required": ["task"],
        }

    def execute(self, arguments: Dict) -> str:
        task = str(arguments.get("task") or "").strip()
        if not task:
            return "错误: task 参数不能为空。"
        return _run_plan_subagent(
            name="explore",
            system_prompt=_explore_system_prompt(),
            task=task,
            parent_runtime=self.parent_runtime,
            chat_stream_fn=self.chat_stream_fn,
        )


class PlanAgentTool(Tool):
    category = "plan"
    effect = "control"
    plan_mode = "control"
    plan_mode_only = True
    concurrency_safe = False
    result_kind = "text"
    guidance = (
        "plan_agent 用于在 plan mode 下派一个只读子 agent 设计实施方案。"
        "它基于给定背景提出计划，不修改文件，不退出 plan mode。"
    )

    def __init__(self, *, parent_runtime: Any, chat_stream_fn: Any):
        self.parent_runtime = parent_runtime
        self.chat_stream_fn = chat_stream_fn

    @property
    def name(self) -> str:
        return "plan_agent"

    @property
    def description(self) -> str:
        return "派一个只读 PlanAgent 设计实现方案、步骤、风险和验证方式，并返回计划草案。"

    @property
    def parameters(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "需要规划的任务或目标。",
                },
                "context": {
                    "type": "string",
                    "description": "已知探索结果、约束或相关文件，可选。",
                },
            },
            "required": ["task"],
        }

    def execute(self, arguments: Dict) -> str:
        task = str(arguments.get("task") or "").strip()
        context = str(arguments.get("context") or "").strip()
        if not task:
            return "错误: task 参数不能为空。"
        content = task if not context else f"{task}\n\n已知背景:\n{context}"
        return _run_plan_subagent(
            name="plan",
            system_prompt=_plan_system_prompt(),
            task=content,
            parent_runtime=self.parent_runtime,
            chat_stream_fn=self.chat_stream_fn,
        )


class _ReadOnlyRuntimeView:
    def __init__(self, parent_runtime: Any):
        self.parent_runtime = parent_runtime
        self.registry = self

    def get(self, name: str):
        tool = self.parent_runtime.get(name)
        if not _subagent_tool_allowed(tool):
            raise KeyError(name)
        return tool

    def get_all_definitions(self) -> list[dict]:
        return [
            definition
            for definition in self.parent_runtime.get_all_definitions()
            if _definition_visible(definition, self.parent_runtime)
        ]

    def execute(self, name: str, arguments: dict[str, Any], **context) -> str:
        self.get(name)
        return self.parent_runtime.execute(name, arguments, **context)


def _run_plan_subagent(*, name: str, system_prompt: str, task: str, parent_runtime: Any, chat_stream_fn: Any) -> str:
    runtime = _ReadOnlyRuntimeView(parent_runtime)
    loop = AgentLoop(
        name=name,
        system_prompt=system_prompt,
        chat=chat_stream_fn,
        tool_registry=runtime,
        conversation_history=[],
        use_tools=True,
        plan_mode_active=lambda: True,
    )

    content_parts: list[str] = []
    for event in loop.execute(Message(role="user", content=task), allow_tools=True):
        if event.type == "content":
            content_parts.append(str(event.data))
        elif event.type == "error":
            return f"{name}_agent 执行失败: {event.data}"
        elif event.type == "done":
            break

    result = "".join(content_parts).strip()
    if not result:
        return f"{name}_agent 未返回内容。"
    if len(result) > _SUBAGENT_MAX_CHARS:
        return result[:_SUBAGENT_MAX_CHARS] + "\n...(已截断)"
    return result


def _subagent_tool_allowed(tool: Any) -> bool:
    capability = getattr(tool, "plan_mode", None)
    if capability in {PLAN_MODE_CONTROL}:
        return False
    return is_plan_mode_tool_visible(tool) and getattr(tool, "effect", "write") in {
        PLAN_MODE_READ,
        PLAN_MODE_SHELL,
        "execute",
    }


def _definition_visible(definition: dict, runtime: Any) -> bool:
    function = definition.get("function")
    if not isinstance(function, dict):
        return False
    name = function.get("name")
    if not name:
        return False
    try:
        return _subagent_tool_allowed(runtime.get(str(name)))
    except KeyError:
        return False


def _explore_system_prompt() -> str:
    return "\n".join([
        "你是 ShadowCLI 的 ExploreAgent，只做只读代码探索。",
        "目标：查找相关文件、现有模式、依赖关系、风险点，并给主 agent 一个紧凑摘要。",
        "禁止修改文件，禁止提出最终实施承诺，禁止调用任何计划退出工具。",
        "输出格式：",
        "1. 相关文件",
        "2. 现有设计",
        "3. 风险/未知点",
        "4. 建议主 agent 下一步查看什么",
    ])


def _plan_system_prompt() -> str:
    return "\n".join([
        "你是 ShadowCLI 的 PlanAgent，只做方案设计。",
        "目标：基于任务和已知背景，产出可执行计划草案。",
        "禁止修改文件，禁止调用任何计划退出工具。",
        "输出必须包含：",
        "1. 推荐方案",
        "2. 具体步骤",
        "3. 涉及文件/模块",
        "4. 风险和取舍",
        "5. 验证方式",
    ])
