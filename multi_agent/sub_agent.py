"""SubAgent - 单角色 ReAct 执行器。

SubAgent 只维护本轮运行所需的 runtime messages：
LLM 流式输出 -> 收集完整 tool_call -> 执行工具 -> 将工具结果回灌消息栈
-> 继续下一轮，直到模型给出最终 content 或触发取消/预算保护。

会话记忆由 ReactAgent / AgentOrchestrator 在外层注入，SubAgent 不保存
MemoryManager，也不负责跨轮记忆或终端界面。
"""
from __future__ import annotations

import json
import logging
import threading
import time
from io import StringIO
from typing import Callable

from llm import Message, ToolCall, FunctionCall, chat_stream

from extensions.tool_runtime import ToolExecutionBlocked

from .budget import AgentBudget
from .roles import AgentRole

log = logging.getLogger(__name__)
COMMAND_OUTPUT_PREVIEW_CHARS = 4000
TOOL_ACTION_PREVIEW_CHARS = 50

# LLM chat 函数签名：chat(messages, tools=None, ...) -> ChatResponse-like
ChatFn = Callable[..., object]


def _preview(text: str, limit: int = 160) -> str:
    compact = " ".join((text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[:limit] + "..."


def _tool_action(tool_name: str, args: dict) -> str:
    if tool_name in {"execute_command", "bash"}:
        return f"执行命令：{_preview(args.get('command', ''), TOOL_ACTION_PREVIEW_CHARS)}"
    if tool_name in {"read_file", "read"}:
        return f"读取文件：{_preview(args.get('path', ''), TOOL_ACTION_PREVIEW_CHARS)}"
    if tool_name in {"write_file", "write"}:
        content = args.get("content", "")
        return f"写入文件：{_preview(args.get('path', ''), TOOL_ACTION_PREVIEW_CHARS)}，内容 {len(content or '')} 字"
    if tool_name == "edit":
        return f"编辑文件：{_preview(args.get('path', ''), TOOL_ACTION_PREVIEW_CHARS)}"
    if tool_name in {"list_dir", "ls"}:
        return f"列出目录：{_preview(args.get('path', ''), TOOL_ACTION_PREVIEW_CHARS)}"
    if tool_name == "grep":
        return f"搜索文本：{_preview(args.get('pattern', ''), TOOL_ACTION_PREVIEW_CHARS)}"
    if tool_name == "find":
        return f"查找文件：{_preview(args.get('name', ''), TOOL_ACTION_PREVIEW_CHARS)}"
    return f"参数：{_preview(json.dumps(args, ensure_ascii=False), TOOL_ACTION_PREVIEW_CHARS)}"


PLANNER_PROMPT = """你是一个任务规划专家。请将用户需求拆解为可执行的步骤，输出 JSON 格式：
{
  "summary": "任务摘要",
  "steps": [
    {
      "id": "step_1",
      "description": "具体操作描述",
      "type": "FILE_READ | FILE_WRITE | COMMAND | ANALYSIS | VERIFICATION",
      "dependencies": []
    }
  ]
}
规划要求：
- 每个步骤必须足够小，有单一明确交付物，适合一个 Worker 在有限工具调用内完成。
- 不要把多个文件的大规模实现合并成一个步骤；涉及多文件时拆成模型/路由/模板/样式/测试等独立步骤。
- 实现和验证应拆成不同步骤；不要在实现步骤里启动服务或跑完整验收。
- 如果任务很大，优先规划一个可展示的最小闭环，再把后续增强拆成独立步骤。

依赖关系必须用 step_id 引用其他步骤的 id。直接输出 JSON，不要其他说明。"""


def _worker_prompt(tools_desc: str) -> str:
    return f"""你是一个任务执行专家。根据任务步骤调用合适的工具完成。

可用工具：
{tools_desc}

执行要求：
- 优先使用 Pi 风格工具名：read / write / edit / bash / ls / grep / find。
- 只完成当前步骤描述的范围；不要主动扩展到后续计划步骤，也不要把未要求的增强继续塞进本步骤。
- 不要为了同一个目的反复调用等价命令；工具已经给出可用结果后，直接基于结果回答。
- 如果不知道应该读哪些文件，先用 grep / find / ls 定位，再用 read 读取当前完整文件。
- 如果调用了工具，最终结果要列明关键证据：读了哪些文件、写了哪些文件、执行了什么命令、关键输出是什么。
- 列目录时要列出实际看到的文件/目录名；读文件时要说明文件路径和核心发现；写文件时要说明修改路径和修改点。
- 如果工具失败，先阅读工具返回的完整错误信息。
- 如果错误原因明确，并且可以做出一个实质不同的修正，可以重试一次。
- 不要重复执行完全相同或仅形式不同的命令。
- 如果一次修正后仍失败，停止重试，说明失败原因和已尝试的命令。
- 关键验证已经通过后，立即输出最终结果；不要继续创建额外测试、启动服务或寻找新的优化点。

完成后直接输出执行结果，不要再调用工具。如果任务无需工具，直接给出分析结果。"""

def react_agent_prompt(tools_desc: str) -> str:
    return f"""你是一个通用的人工智能助手，可以灵活地处理日常对话和需要使用工具的任务。

原则：
- 如果是简单的问候、自我介绍或常识性问题，直接回答，不要调用工具。
- 如果需要读写文件、执行命令、创建项目等操作，才使用提供的工具。
- 优先使用 Pi 风格工具名：read / write / edit / bash / ls / grep / find。
- 如果用户问项目代码但没给具体文件，可先用 grep / find / ls 定位。
- 如果无法通过工具完成任务（例如查找用户名、偏好设置等），直接告诉用户你无法做到，不要反复尝试工具调用。
- 回答要简洁、友好。

可用工具：
{tools_desc}
    """
class SubAgent:
    """单角色 Agent。独立对话历史，共享 LLM 客户端和工具注册表。"""

    def __init__(
        self,
        name: str,
        role: AgentRole,
        chat: ChatFn,
        tool_registry,
        *,
        cancel: threading.Event | None = None,
    ):
        self.name = name
        self.role = role
        self.tool_registry = tool_registry
        self.cancel = cancel or threading.Event()
        self.conversation_history: list[Message] = []
        self._current_step_label: str | None = None
        self._reset_system_prompt()

    # —— 公开 API ——
    def execute(self, task: Message, context: str = "", allow_tools: bool = True):
        """执行任务（流式版本）。yield StreamEvent。

        :param task: 任务消息
        :param context: 可选前置上下文
        :param allow_tools: 是否允许调用工具（默认 True）

        注意：执行链路统一走 chat_stream，所有退出路径都 yield done 事件。
        """
        from llm.client import StreamEvent

        user_content = task.content if not context else f"{context}\n\n当前任务：{task.content}"
        self.conversation_history.append(Message(role="user", content=user_content))
        budget = AgentBudget.from_env()

        for _turn in range(budget.hard_max_iterations):
            # 检查取消
            if self.cancel.is_set():
                yield StreamEvent("content", "\n⏹️ 用户取消")
                yield StreamEvent("done", {"reason": "cancelled"})
                return

            # 构造工具 schema（根据 allow_tools 决定是否传递）
            tools_schema = None
            if allow_tools and self._uses_tools():
                tools_schema = self.tool_registry.get_all_definitions()

            # 累积本轮的 content 和 tool_calls
            content_parts: list[str] = []
            tool_calls_data: list[dict] = []

            # 流式调用 LLM；项目运行时统一走真实 chat_stream。
            try:
                for event in chat_stream(
                    self.conversation_history,
                    tools=tools_schema,
                    cancel=self.cancel,
                ):
                    if self.cancel.is_set():
                        yield StreamEvent("content", "\n⏹️ 用户取消")
                        yield StreamEvent("done", {"reason": "cancelled"})
                        return

                    if event.type == "content":
                        content_parts.append(event.data)
                        yield event  # 透传
                    elif event.type == "tool_call":
                        tool_calls_data.append(event.data)
                    elif event.type == "done":
                        # 处理 LLM 层的取消/错误
                        if event.data and event.data.get("reason") == "cancelled":
                            yield event
                            return
                    elif event.type == "error":
                        yield event
                        return
            except Exception as exc:
                log.error("[Agent:%s] LLM 调用失败：%s", self.name, exc)
                yield StreamEvent("error", f"LLM 调用失败: {exc}")
                yield StreamEvent("done", {"reason": "error"})
                return

            # 构造完整 Message 加入 history
            response_msg = Message(
                role="assistant",
                content="".join(content_parts) or None,
                tool_calls=[
                    ToolCall(
                        id=tc["id"],
                        type=tc["type"],
                        function=FunctionCall(
                            name=tc["name"],
                            arguments=tc["arguments"]
                        ),
                    )
                    for tc in tool_calls_data
                ]
                if tool_calls_data
                else None,
            )
            self.conversation_history.append(response_msg)

            # 没有 tool_calls，结束
            if not tool_calls_data:
                yield StreamEvent("done", {"reason": "finished"})
                return

            # 执行工具（带日志）
            for tc in tool_calls_data:
                if self.cancel.is_set():
                    yield StreamEvent("content", "\n⏹️ 用户取消")
                    yield StreamEvent("done", {"reason": "cancelled"})
                    return

                yield StreamEvent(
                    "tool_call_start", {"name": tc["name"], "args": tc["arguments"]}
                )

                # 使用原有的 _exec_one 执行工具（带完整日志）
                args = json.loads(tc["arguments"]) if tc["arguments"] else {}
                tool_call_obj = ToolCall(
                    id=tc["id"],
                    type="function",
                    function=FunctionCall(name=tc["name"], arguments=tc["arguments"])
                )

                try:
                    result = self._exec_one(tool_call_obj)
                    if "工具调用被拒绝" in result:
                        yield StreamEvent("tool_result", {"name": tc["name"], "result": result})
                        yield StreamEvent("done", {"reason": "blocked"})
                        return
                except ToolExecutionBlocked as exc:
                    result = f"工具调用被拒绝: {exc}"
                    yield StreamEvent("tool_result", {"name": tc["name"], "result": result})
                    yield StreamEvent("done", {"reason": "blocked"})
                    return

                yield StreamEvent("tool_result", {"name": tc["name"], "result": result})

                # 加入 history
                self.conversation_history.append(
                    Message(role="tool", content=result, tool_call_id=tc["id"])
                )

            # 继续下一轮

        # 超过轮数限制
        yield StreamEvent("content", f"\n⚠️ 达到最大轮数 {budget.hard_max_iterations}")
        yield StreamEvent("done", {"reason": "max_turns"})

    def clear_history(self) -> None:
        """清空对话历史，保留系统提示。用于处理下一个独立任务。"""
        system_msg = self.conversation_history[0]
        self.conversation_history.clear()
        self.conversation_history.append(system_msg)
        self._current_step_label = None
        log.debug("[Agent:%s] 已清理临时 history，仅保留系统提示", self.name)

    # —— 内部 ——
    def _uses_tools(self) -> bool:
        """只有 Worker 或 React 调工具，Planner 只输出分析。"""
        return self.role == AgentRole.WORKER or self.role == AgentRole.REACT

    def _reset_system_prompt(self) -> None:
        self.conversation_history.clear()
        self.conversation_history.append(Message(role="system", content=self._build_system_prompt()))

    def _display_name(self) -> str:
        if not self._current_step_label:
            return self.name
        return f"{self.name} [{_preview(self._current_step_label, TOOL_ACTION_PREVIEW_CHARS)}]"

    def _build_system_prompt(self) -> str:
        if self.role == AgentRole.PLANNER:
            return PLANNER_PROMPT
        # Worker: 把可用工具列入提示词
        defs = self.tool_registry.get_all_definitions()
        tools_desc = "\n".join(
            f"- {d['function']['name']}: {d['function']['description']}" for d in defs
        )
        if self.role == AgentRole.REACT:
            return react_agent_prompt(tools_desc=tools_desc)
        # 默认是 Worker
        return _worker_prompt(tools_desc)

    def _exec_one(self, tool_call) -> str:
        """执行单个工具调用。失败时返回错误字符串，不抛异常。"""
        try:
            args = json.loads(tool_call.function.arguments)
            display_name = self._display_name()
            log.info(
                "[工具] %s 调用 %s：%s",
                display_name,
                tool_call.function.name,
                _tool_action(tool_call.function.name, args),
            )
            log.debug(
                "[工具] %s 调用 %s，参数预览：%s",
                display_name,
                tool_call.function.name,
                _preview(tool_call.function.arguments),
            )
            started = time.perf_counter()
            result = self.tool_registry.execute(tool_call.function.name, args)
            elapsed = time.perf_counter() - started
            log.debug(
                "[工具] %s 调用 %s 完成，用时 %.2f 秒，结果 %d 字，预览：%s",
                display_name,
                tool_call.function.name,
                elapsed,
                len(result or ""),
                _preview(result),
            )
            return result
        except ToolExecutionBlocked:
            log.warning(
                "[工具] %s 调用 %s 被拒绝",
                self._display_name(),
                tool_call.function.name,
            )
            raise
        except Exception as exc:
            log.error("[工具] %s 调用 %s 失败：%s", self._display_name(), tool_call.function.name, exc)
            return f"工具执行失败: {exc}"

    def __repr__(self) -> str:
        return f"SubAgent(name={self.name!r}, role={self.role.name}, history={len(self.conversation_history)})"


def _emit(out: StringIO | None, msg: str) -> None:
    if out is not None:
        out.write(msg + "\n")
    else:
        print(msg)


def _emit_command_result(
    out: StringIO | None,
    agent_name: str,
    tool_name: str,
    result: str,
) -> None:
    if tool_name not in {"bash", "execute_command"}:
        return
    text = result or ""
    if len(text) > COMMAND_OUTPUT_PREVIEW_CHARS:
        text = (
            text[:COMMAND_OUTPUT_PREVIEW_CHARS]
            + f"\n...（输出过长，已截断；完整结果见计划日志，共 {len(result)} 字）"
        )
    _emit(out, f"📤 [{agent_name}] {tool_name} 结果:\n{text}")
