"""SubAgent - 可配置角色的轻量 Agent，含完整 ReAct 循环。

与简单版的关键差异：
- execute 是 async，内含完整 while 循环：调 LLM → 有 tool_calls 就执行工具
  → 工具结果回灌 history → 继续，直到收到最终 content
- 工具调用并行执行（asyncio.gather + asyncio.to_thread 包装 sync 工具）
- AgentBudget 三道防护防死循环
- 接 MemoryManager 在 LLM 调用前压缩历史
- 接 threading.Event 做取消（在 await 点轮询 is_set()）

Pythonic 要点：
- async def execute 全链路 async
- asyncio.to_thread 包装 sync chat / 工具
- asyncio.gather 并行执行多个工具调用
- walrus :=
- keyword-only 参数
- __repr__ 替代状态打印
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
from io import StringIO
from typing import Callable

from model import Message

from .budget import AgentBudget, ExitReason
from .messages import AgentMessage
from .roles import AgentRole

log = logging.getLogger(__name__)

# LLM chat 函数签名：chat(messages, tools=None, ...) -> ChatResponse-like
ChatFn = Callable[..., object]


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
依赖关系必须用 step_id 引用其他步骤的 id。直接输出 JSON，不要其他说明。"""


REVIEWER_PROMPT = """你是一个质量检查专家。请以 JSON 输出审查结果：
{
  "approved": true/false,
  "summary": "审查总结",
  "issues": ["问题 1", "问题 2"],
  "suggestions": ["建议 1"]
}
approved=true 表示通过，false 表示需要重做。直接输出 JSON。"""


def _worker_prompt(tools_desc: str) -> str:
    return f"""你是一个任务执行专家。根据任务步骤调用合适的工具完成。

可用工具：
{tools_desc}

完成后直接输出执行结果，不要再调用工具。如果任务无需工具，直接给出分析结果。"""


class SubAgent:
    """单角色 Agent。独立对话历史，共享 LLM 客户端和工具注册表。"""

    def __init__(
        self,
        name: str,
        role: AgentRole,
        chat: ChatFn,
        tool_registry,
        *,
        memory_manager=None,
        cancel: threading.Event | None = None,
    ):
        self.name = name
        self.role = role
        self._chat = chat
        self.tool_registry = tool_registry
        self.memory_manager = memory_manager
        self.cancel = cancel or threading.Event()
        self.conversation_history: list[Message] = []
        self._reset_system_prompt()

    # —— 公开 API ——
    async def execute(
        self,
        task: AgentMessage,
        *,
        context: str = "",
        out: StringIO | None = None,
    ) -> AgentMessage:
        """执行任务（含 ReAct 循环）。

        :param task: 任务消息，content 是任务描述
        :param context: 可选前置上下文（如依赖步骤的执行结果）
        :param out: 可选输出缓冲，None 时直接 print；并行任务用 StringIO 缓冲后统一打印
        :return: AgentMessage（RESULT 或 ERROR）
        """
        log.info("[%s] executing task: type=%s", self.name, task.type.name)
        user_content = task.content if not context else f"{context}\n\n当前任务：{task.content}"
        self.conversation_history.append(Message(role="user", content=user_content))

        budget = AgentBudget.from_env()

        while True:
            # 三道保险阀
            if (reason := budget.check()) != ExitReason.WITHIN_BUDGET:
                msg = budget.describe_exit(reason)
                log.warning("[%s] exit by budget: %s", self.name, msg)
                return AgentMessage.error(self.name, self.role, msg)

            # 取消检查（threading.Event 在 await 点之间轮询）
            if self.cancel.is_set():
                return AgentMessage.error(self.name, self.role, "用户取消")

            budget.begin_iteration()

            # 调 LLM 前压缩历史
            if self.memory_manager is not None:
                try:
                    self.memory_manager.maybe_compact_history(self.conversation_history)
                except Exception as exc:
                    log.warning("[%s] history compact failed: %s", self.name, exc)

            # 调 LLM（sync chat 用 to_thread 包装）
            tools = self.tool_registry.get_all_definitions() if self._uses_tools() else None
            try:
                response = await asyncio.to_thread(
                    self._chat, self.conversation_history, tools=tools
                )
            except Exception as exc:
                log.error("[%s] LLM call failed: %s", self.name, exc)
                return AgentMessage.error(self.name, self.role, f"LLM 调用失败: {exc}")

            # 累计 token 用量
            budget.record_tokens(
                getattr(response, "prompt_tokens", 0),
                getattr(response, "completion_tokens", 0),
            )

            tool_calls = getattr(response, "tool_calls", None) or []
            content = getattr(response, "content", "") or ""

            if tool_calls:
                # 有工具调用：执行工具，结果回灌 history，继续循环
                budget.record_tool_calls(tool_calls)
                _emit(out, f"🛠️ [{self.name}] 调用 {len(tool_calls)} 个工具")

                self.conversation_history.append(
                    Message(role="assistant", content=content, tool_calls=tool_calls)
                )
                tool_results = await self._execute_tool_calls(tool_calls)
                for tc, result in tool_results:
                    self.conversation_history.append(
                        Message(role="tool", content=result, tool_call_id=tc.id)
                    )
                continue

            # 没有工具调用：最终结果
            self.conversation_history.append(Message(role="assistant", content=content))
            _emit(out, f"✅ [{self.name}] 完成")
            return AgentMessage.result(self.name, self.role, content)

    async def review(
        self,
        original_task: str,
        execution_result: str,
        *,
        out: StringIO | None = None,
    ) -> AgentMessage:
        """检查执行结果（Reviewer 专用，本质是带特殊 prompt 的 execute）。"""
        review_input = f"原始任务：{original_task}\n\n执行结果：\n{execution_result}"
        return await self.execute(AgentMessage.task("orchestrator", review_input), out=out)

    def clear_history(self) -> None:
        """清空对话历史，保留系统提示。用于处理下一个独立任务。"""
        system_msg = self.conversation_history[0]
        self.conversation_history.clear()
        self.conversation_history.append(system_msg)

    # —— 内部 ——
    def _uses_tools(self) -> bool:
        """只有 Worker 调工具，Planner / Reviewer 只输出分析。"""
        return self.role == AgentRole.WORKER

    def _reset_system_prompt(self) -> None:
        self.conversation_history.clear()
        self.conversation_history.append(Message(role="system", content=self._build_system_prompt()))

    def _build_system_prompt(self) -> str:
        if self.role == AgentRole.PLANNER:
            return PLANNER_PROMPT
        if self.role == AgentRole.REVIEWER:
            return REVIEWER_PROMPT
        # Worker: 把可用工具列入提示词
        defs = self.tool_registry.get_all_definitions()
        tools_desc = "\n".join(
            f"- {d['function']['name']}: {d['function']['description']}" for d in defs
        )
        return _worker_prompt(tools_desc)

    async def _execute_tool_calls(self, tool_calls) -> list[tuple[object, str]]:
        """并行执行多个工具调用（每个工具是 sync，用 to_thread 包装并行）。"""
        if not tool_calls:
            return []
        coros = [asyncio.to_thread(self._exec_one, tc) for tc in tool_calls]
        results = await asyncio.gather(*coros)
        return list(zip(tool_calls, results))

    def _exec_one(self, tool_call) -> str:
        """执行单个工具调用。失败时返回错误字符串，不抛异常。"""
        try:
            tool = self.tool_registry.get(tool_call.function.name)
            args = json.loads(tool_call.function.arguments)
            return tool.execute(args)
        except Exception as exc:
            log.error("[%s] tool '%s' failed: %s", self.name, tool_call.function.name, exc)
            return f"工具执行失败: {exc}"

    def __repr__(self) -> str:
        return f"SubAgent(name={self.name!r}, role={self.role.name}, history={len(self.conversation_history)})"


def _emit(out: StringIO | None, msg: str) -> None:
    """写到缓冲或 stdout。并行批次用缓冲，单步用 None 直 print。"""
    if out is not None:
        out.write(msg + "\n")
    else:
        print(msg)
