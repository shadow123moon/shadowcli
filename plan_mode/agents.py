from __future__ import annotations

from typing import Any, Dict

from agent.subagent_runner import fork_history, run_forked_subagents, run_subagent
from tooling.base import Tool

from .policy import PLAN_MODE_CONTROL, PLAN_MODE_READ, PLAN_MODE_SHELL, is_plan_mode_tool_visible


_MAX_FORK_TASKS = 4


class _SingleSubAgentTool(Tool):
    category = "plan"
    effect = "control"
    plan_mode = "control"
    plan_mode_only = True
    concurrency_safe = False
    result_kind = "text"

    agent_name = "subagent"

    def __init__(
        self,
        *,
        parent_runtime: Any,
        chat_stream_fn: Any,
        agent_loop_factory: Any,
        parent_messages_provider: Any | None = None,
    ):
        self.parent_runtime = parent_runtime
        self.chat_stream_fn = chat_stream_fn
        self.agent_loop_factory = agent_loop_factory
        self.parent_messages_provider = parent_messages_provider or _empty_parent_messages

    def execute(self, arguments: Dict) -> str:
        return self._execute(arguments, cancel=None)

    def execute_with_context(self, arguments: Dict, context) -> str:
        return self._execute(arguments, cancel=getattr(context, "cancel", None))

    def _execute(self, arguments: Dict, *, cancel) -> str:
        content = self._task_content(arguments)
        if not content:
            return "错误: task 参数不能为空。"
        return run_subagent(
            name=self.agent_name,
            system_prompt=self._system_prompt(),
            task=content,
            parent_runtime=self.parent_runtime,
            chat_stream_fn=self.chat_stream_fn,
            agent_loop_factory=self.agent_loop_factory,
            tool_allowed=_subagent_tool_allowed,
            conversation_history=fork_history(self.parent_messages_provider()),
            cancel=cancel,
        )

    def _task_content(self, arguments: Dict) -> str:
        raise NotImplementedError

    def _system_prompt(self) -> str:
        raise NotImplementedError


class ExploreAgentTool(_SingleSubAgentTool):
    agent_name = "explore"
    guidance = (
        "explore_agent 用于在 plan mode 下派一个只读子 agent 探索代码。"
        "它只能读文件、搜索和执行受限只读 shell，不能修改文件或退出 plan mode。"
    )

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

    def _task_content(self, arguments: Dict) -> str:
        return str(arguments.get("task") or "").strip()

    def _system_prompt(self) -> str:
        return _explore_system_prompt()


class PlanAgentTool(_SingleSubAgentTool):
    agent_name = "plan"
    guidance = (
        "plan_agent 用于在 plan mode 下派一个只读子 agent 设计实施方案。"
        "它基于给定背景提出计划，不修改文件，不退出 plan mode。"
    )

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

    def _task_content(self, arguments: Dict) -> str:
        task = str(arguments.get("task") or "").strip()
        context = str(arguments.get("context") or "").strip()
        return task if not context else f"{task}\n\n已知背景:\n{context}"

    def _system_prompt(self) -> str:
        return _plan_system_prompt()


class ForkExploreAgentsTool(Tool):
    category = "plan"
    effect = "control"
    plan_mode = "control"
    plan_mode_only = True
    concurrency_safe = False
    result_kind = "text"
    guidance = (
        "fork_explore_agents 用于在 plan mode 下并行派多个只读子 agent。"
        "每个子 agent 继承父会话前缀，只在尾部追加自己的探索任务。"
    )

    def __init__(
        self,
        *,
        parent_runtime: Any,
        chat_stream_fn: Any,
        agent_loop_factory: Any,
        parent_messages_provider: Any,
    ):
        self.parent_runtime = parent_runtime
        self.chat_stream_fn = chat_stream_fn
        self.agent_loop_factory = agent_loop_factory
        self.parent_messages_provider = parent_messages_provider

    @property
    def name(self) -> str:
        return "fork_explore_agents"

    @property
    def description(self) -> str:
        return "并行派 1-4 个只读 fork 子 agent 探索不同代码边界，并按任务顺序返回摘要。"

    @property
    def parameters(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "tasks": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "maxItems": _MAX_FORK_TASKS,
                    "description": "需要并行探索的任务列表，例如按 session/tooling/plan_mode 拆分。",
                },
            },
            "required": ["tasks"],
        }

    def execute(self, arguments: Dict) -> str:
        return self._execute(arguments, cancel=None)

    def execute_with_context(self, arguments: Dict, context) -> str:
        return self._execute(arguments, cancel=getattr(context, "cancel", None))

    def _execute(self, arguments: Dict, *, cancel) -> str:
        tasks = _normalize_fork_tasks(arguments.get("tasks"))
        if not tasks:
            return "错误: tasks 参数不能为空。"
        if len(tasks) > _MAX_FORK_TASKS:
            return f"错误: fork_explore_agents 最多支持 {_MAX_FORK_TASKS} 个并行任务。"

        parent_messages = fork_history(self.parent_messages_provider())
        results = run_forked_subagents(
            tasks=tasks,
            system_prompt=_explore_system_prompt(),
            parent_messages=parent_messages,
            parent_runtime=self.parent_runtime,
            chat_stream_fn=self.chat_stream_fn,
            agent_loop_factory=self.agent_loop_factory,
            tool_allowed=_subagent_tool_allowed,
            cancel=cancel,
        )
        return "\n\n".join(
            f"## {index + 1}. {task}\n{results[index]}"
            for index, task in enumerate(tasks)
        )


def _normalize_fork_tasks(raw_tasks: Any) -> list[str]:
    if not isinstance(raw_tasks, list):
        return []
    tasks: list[str] = []
    for task in raw_tasks:
        text = str(task or "").strip()
        if text:
            tasks.append(text)
    return tasks


def _empty_parent_messages() -> list[Any]:
    return []


def _subagent_tool_allowed(tool: Any) -> bool:
    capability = getattr(tool, "plan_mode", None)
    if capability in {PLAN_MODE_CONTROL}:
        return False
    return is_plan_mode_tool_visible(tool) and getattr(tool, "effect", "write") in {
        PLAN_MODE_READ,
        PLAN_MODE_SHELL,
        "execute",
    }


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
