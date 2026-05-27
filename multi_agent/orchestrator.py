"""AgentOrchestrator - Multi-Agent 系统的主控（编排器）。

主从架构：
- planner       : 拆任务为 JSON 计划
- workers (N)   : 池化的多个 Worker，并发执行批次内的独立步骤

关键工程细节：
- asyncio.Semaphore 限制并发，asyncio.Queue 维护 Worker 池（避免同一 Worker 被并发占用）
- 并行步骤独立 StringIO 缓冲，按 step_id 顺序 flush 到 stdout（防止输出交错）
- 接 MemoryManager：写用户输入和最终结果到短期记忆
- 接 threading.Event：在 critical points 检查取消

Pythonic 要点：
- async def 全链路 + asyncio.gather 并行
- @dataclass + @property（is_completed / is_pending）替代 getter
- f-string + walrus :=
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
from dataclasses import dataclass, field
from enum import Enum
from io import StringIO
from typing import Callable

from .roles import AgentRole
from .sub_agent import ChatFn, SubAgent, _emit_command_result

log = logging.getLogger(__name__)

DEFAULT_WORKER_COUNT = 2


class PlanReviewDecision(Enum):
    """计划审查决策。"""
    EXECUTE = "execute"       # 直接执行
    SUPPLEMENT = "supplement" # 补充要求，重新规划
    CANCEL = "cancel"         # 取消


def parse_plan_review_input(user_input: str) -> tuple[PlanReviewDecision, str]:
    """解析用户对计划的审查输入。

    - 空字符串 / y / yes / run  → EXECUTE
    - cancel / esc              → CANCEL
    - 其他任意文字              → SUPPLEMENT（文字作为补充要求）
    """
    trimmed = user_input.strip()
    if trimmed == "" or trimmed.lower() in ("y", "yes", "run"):
        return PlanReviewDecision.EXECUTE, ""
    if trimmed.lower() in ("cancel", "esc"):
        return PlanReviewDecision.CANCEL, ""
    return PlanReviewDecision.SUPPLEMENT, trimmed


# 计划审查回调：接收 (goal, steps)，返回 (decision, feedback)
PlanReviewFn = Callable[[str, list["ExecutionStep"]], tuple[PlanReviewDecision, str]]


class StepStatus(Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass
class ExecutionStep:
    """执行计划中的一个步骤。"""

    id: str
    description: str
    type: str = "COMMAND"
    dependencies: list[str] = field(default_factory=list)
    status: StepStatus = StepStatus.PENDING
    result: str = ""

    @property
    def is_completed(self) -> bool:
        return self.status == StepStatus.COMPLETED

    @property
    def is_pending(self) -> bool:
        return self.status == StepStatus.PENDING

    @property
    def is_failed(self) -> bool:
        return self.status == StepStatus.FAILED


class AgentOrchestrator:
    """Multi-Agent 编排器。"""

    def __init__(
        self,
        chat: ChatFn,
        tool_registry,
        *,
        memory_manager=None,
        worker_count: int = DEFAULT_WORKER_COUNT,
        cancel: threading.Event | None = None,
        plan_review_handler: PlanReviewFn | None = None,
    ):
        self.chat = chat
        self.tool_registry = tool_registry
        self.memory_manager = memory_manager
        self.cancel = cancel or threading.Event()
        self.worker_count = max(1, worker_count)
        self._plan_review_handler = plan_review_handler

        self.planner = SubAgent(
            "planner", AgentRole.PLANNER, chat, tool_registry,
            cancel=self.cancel,
        )
        self.workers = [
            SubAgent(
                f"worker-{i + 1}", AgentRole.WORKER, chat, tool_registry,
                cancel=self.cancel,
            )
            for i in range(self.worker_count)
        ]

    # —— 主入口 ——
    async def run(self, user_input: str) -> str:
        """运行多 Agent 协作任务。"""
        log.info("[计划] 开始多 Agent 任务，输入 %d 字，执行器数量 %d", len(user_input or ""), self.worker_count)
        memory_context = ""
        if self.memory_manager is not None:
            memory_context = self.memory_manager.context_for(user_input)
            log.info(
                "[计划] 直接记忆上下文%s，长度 %d 字",
                "可用" if memory_context else "为空",
                len(memory_context),
            )
            self.memory_manager.add_user(user_input)
        if self.cancel.is_set():
            log.info("[计划] 任务在开始阶段被取消")
            return "⏹️ 已取消"

        # 1. 规划
        log.info("[计划] 第一阶段：开始生成执行计划")
        print("📋 第一阶段：规划")
        print("🧑‍💼 规划者正在分析任务...\n")

        # 流式执行规划
        from llm.types import Message
        plan_content_parts = []
        task_msg = Message(role="user", content=f"请为以下任务制定执行计划：\n{user_input}")
        for event in self.planner.execute(task_msg, context=memory_context):
            if event.type == "content":
                plan_content_parts.append(event.data)
                print(event.data, end="", flush=True)
            elif event.type == "done":
                reason = event.data.get("reason") if event.data else None
                if reason == "cancelled":
                    return "⏹️ 已取消"
                break

        plan_content = "".join(plan_content_parts)
        self.planner.clear_history()
        log.info(
            "[计划] 第一阶段完成：规划输出 %d 字",
            len(plan_content),
        )

        if not plan_content:
            return "❌ 规划失败：规划者未能生成有效计划"

        # 2. 解析计划 + 审查循环
        steps = self._parse_plan(plan_content)
        log.info("[计划] 解析出 %d 个执行步骤", len(steps))
        if not steps:
            return f"❌ 规划失败：无法解析执行计划\n原始输出:\n{plan_content}"

        print("📋 执行计划")
        print(self._summarize_steps(steps) + "\n")

        # 计划审查（如果配置了 handler）
        if self._plan_review_handler is not None:
            current_goal = user_input
            while True:
                decision, feedback = self._plan_review_handler(current_goal, steps)
                if decision == PlanReviewDecision.EXECUTE:
                    break
                if decision == PlanReviewDecision.CANCEL:
                    log.info("[计划] 用户取消计划")
                    return "⏹️ 已取消本次计划执行。"
                # SUPPLEMENT：补充要求，重新规划
                log.info("[计划] 用户补充要求：%s", feedback)
                print("📝 已收到补充要求，正在重新规划...\n")
                current_goal = f"{user_input}\n补充要求：{feedback}"

                # 流式重新规划
                replan_content_parts = []
                replan_task = Message(role="user", content=f"请为以下任务制定执行计划：\n{current_goal}")
                for event in self.planner.execute(replan_task, context=memory_context):
                    if event.type == "content":
                        replan_content_parts.append(event.data)
                        print(event.data, end="", flush=True)
                    elif event.type == "done":
                        reason = event.data.get("reason") if event.data else None
                        if reason == "cancelled":
                            return "⏹️ 已取消"
                        break

                replan_content = "".join(replan_content_parts)
                self.planner.clear_history()

                if not replan_content:
                    return "❌ 重新规划失败：规划者未能生成有效计划"

                steps = self._parse_plan(replan_content)
                if not steps:
                    return f"❌ 重新规划失败：无法解析执行计划\n原始输出:\n{replan_content}"
                print("📋 新执行计划")
                print(self._summarize_steps(steps) + "\n")

        # 3. 执行阶段
        log.info("[计划] 第二阶段：开始执行 %d 个步骤", len(steps))
        print("⚡ 第二阶段：执行")
        single_cursor = 0
        batch_index = 0

        while True:
            if self.cancel.is_set():
                log.info("[计划] 任务在执行阶段被取消")
                return "⏹️ 已取消"
            executable = self._get_executable_steps(steps)
            if not executable:
                break
            batch_index += 1
            log.info(
                "[计划] 执行批次 #%d，步骤=%s，%s",
                batch_index,
                ",".join(step.id for step in executable),
                "并行执行" if len(executable) > 1 else "串行执行",
            )

            if len(executable) == 1:
                # 单步：直接 print，串行
                step = executable[0]
                worker = self.workers[single_cursor % len(self.workers)]
                single_cursor += 1
                context = self._build_step_context(steps, step, memory_context=memory_context)
                await self._run_step(step, worker, context, out=None)
                worker.clear_history()
            else:
                # 多步：并行 + 缓冲 + 顺序 flush
                print(
                    f"⚡ 批次 #{batch_index}：{len(executable)} 个独立步骤并行执行"
                    f"（最多 {self.worker_count} 个并发 Worker）\n"
                )
                await self._run_batch_parallel(
                    executable, steps, memory_context=memory_context
                )

        # 4. 因前置失败而无法执行的残留步骤（显式提示）
        for step in steps:
            if step.is_pending:
                print(f"⏭️ 步骤 [{step.id}] 因前置步骤失败被跳过: {step.description}")

        # 5. 汇总并写回 Memory
        final = self._build_final_result(steps)
        if self.memory_manager is not None:
            self.memory_manager.add_assistant(f"[多Agent结果] {final}")
        log.info(
            "[计划] 任务完成：总步骤 %d，完成 %d，失败 %d，待执行 %d，最终结果 %d 字",
            len(steps),
            sum(1 for s in steps if s.status == StepStatus.COMPLETED),
            sum(1 for s in steps if s.status == StepStatus.FAILED),
            sum(1 for s in steps if s.status == StepStatus.PENDING),
            len(final),
        )
        return final

    # —— 容器协议 ——
    def __iter__(self):
        """直接迭代 orchestrator 拿到所有 SubAgent。"""
        yield self.planner
        yield from self.workers

    def __len__(self) -> int:
        return 1 + len(self.workers)

    # —— JSON 解析 ——
    def _parse_plan(self, plan_json: str) -> list[ExecutionStep]:
        """解析规划者输出的 JSON。容错 + id 重编号。"""
        try:
            cleaned = re.sub(r"```json\s*", "", plan_json)
            cleaned = re.sub(r"```\s*", "", cleaned).strip()
            data = json.loads(cleaned)
        except Exception as exc:
            log.error("[计划] 解析计划 JSON 失败：%s", exc)
            return []

        # 兼容 steps / tasks 两种字段
        steps_data = data.get("steps") or data.get("tasks") or []
        if not isinstance(steps_data, list) or not steps_data:
            log.warning("[计划] 规划结果里没有 steps/tasks 数组")
            return []

        # 第一遍：创建并重编号（防止规划者给出不规范的 id）
        steps: list[ExecutionStep] = []
        id_mapping: dict[str, str] = {}
        for i, s in enumerate(steps_data, 1):
            original_id = str(s.get("id", f"original_{i}"))
            new_id = f"step_{i}"
            id_mapping[original_id] = new_id
            steps.append(ExecutionStep(
                id=new_id,
                description=str(s.get("description", "")),
                type=str(s.get("type", "COMMAND")),
                dependencies=[],
            ))

        # 第二遍：把依赖里的旧 id 翻译成新 id
        for i, s in enumerate(steps_data):
            deps = s.get("dependencies") or []
            if isinstance(deps, list):
                steps[i].dependencies = [id_mapping.get(str(d), str(d)) for d in deps]

        return steps

    def _get_executable_steps(self, steps: list[ExecutionStep]) -> list[ExecutionStep]:
        status_map = {s.id: s.status for s in steps}
        return [
            s for s in steps
            if s.is_pending
            and all(status_map.get(dep) == StepStatus.COMPLETED for dep in s.dependencies)
        ]

    # —— 步骤执行 ——
    async def _run_step(
        self,
        step: ExecutionStep,
        worker: SubAgent,
        context: str,
        *,
        out: StringIO | None,
    ) -> None:
        """执行单步：Worker 流式执行后直接记录结果。"""
        log.info(
            "[计划] 开始步骤 %s，执行器=%s，依赖 %d 个",
            step.id,
            worker.name,
            len(step.dependencies),
        )
        _emit(out, f"🛠️ {worker.name} 执行步骤 [{step.id}]: {step.description}")
        if self.cancel.is_set():
            step.status = StepStatus.FAILED
            step.result = "用户取消"
            log.info("[计划] 步骤 %s 被取消", step.id)
            return
        worker._current_step_label = f"{step.id} {step.description}"

        # 流式执行
        from llm.types import Message
        content_parts = []
        task_msg = Message(role="user", content=step.description)

        try:
            for event in worker.execute(task_msg, context=context):
                if self.cancel.is_set():
                    step.status = StepStatus.FAILED
                    step.result = "用户取消"
                    log.info("[计划] 步骤 %s 被取消", step.id)
                    return

                if event.type == "content":
                    content_parts.append(event.data)
                    if out is not None:
                        out.write(event.data)
                    else:
                        print(event.data, end="", flush=True)
                elif event.type == "tool_call_start":
                    msg = f"\n🛠️ {event.data['name']}"
                    if out is not None:
                        out.write(msg)
                    else:
                        print(msg, flush=True)
                elif event.type == "tool_result":
                    _emit_command_result(out, worker.name, event.data["name"], event.data["result"])
                elif event.type == "done":
                    reason = event.data.get("reason") if event.data else None
                    if reason == "cancelled":
                        step.status = StepStatus.FAILED
                        step.result = "用户取消"
                        _emit(out, f"❌ 步骤 [{step.id}] 被取消\n")
                        log.info("[计划] 步骤 %s 被取消", step.id)
                        return
                    elif reason == "blocked":
                        step.status = StepStatus.FAILED
                        step.result = "工具调用被拒绝"
                        _emit(out, f"❌ 步骤 [{step.id}] 执行失败：工具调用被拒绝\n")
                        log.info("[计划] 步骤 %s 执行失败：工具调用被拒绝", step.id)
                        return
                    break

            result = "".join(content_parts)
            if not result:
                step.status = StepStatus.FAILED
                step.result = "执行结果为空"
                _emit(out, f"❌ 步骤 [{step.id}] 执行失败：结果为空\n")
                log.info("[计划] 步骤 %s 执行失败：结果为空", step.id)
                return

            step.status = StepStatus.COMPLETED
            step.result = result
            _emit(out, f"✅ 步骤 [{step.id}] 执行完成\n")
            log.info("[计划] 步骤 %s 完成", step.id)

        except Exception as exc:
            step.status = StepStatus.FAILED
            step.result = f"执行失败: {exc}"
            _emit(out, f"❌ 步骤 [{step.id}] 执行失败：{exc}\n")
            log.error("[计划] 步骤 %s 执行失败：%s", step.id, exc)

    async def _run_batch_parallel(
        self,
        batch: list[ExecutionStep],
        all_steps: list[ExecutionStep],
        *,
        memory_context: str = "",
    ) -> None:
        """并行执行一批互不依赖的步骤。

        关键工程点：
        - asyncio.Queue 维护 Worker 池：每步 await get() / 完成后 put_nowait()，
          保证同一 Worker 不会被两个步骤并发占用
        - asyncio.Semaphore 限制并发到 worker_count
        - 每步独立 StringIO 缓冲，gather 完成后按 step_id 顺序 flush 到 stdout
          → 用户看到的输出顺序稳定，不会交错
        """
        worker_pool: asyncio.Queue[SubAgent] = asyncio.Queue()
        for worker in self.workers:
            worker_pool.put_nowait(worker)
        log.info(
            "[计划] 并行批次开始，步骤=%s，执行器数量 %d",
            ",".join(step.id for step in batch),
            self.worker_count,
        )

        buffers: dict[str, StringIO] = {step.id: StringIO() for step in batch}
        semaphore = asyncio.Semaphore(self.worker_count)

        async def run_one(step: ExecutionStep) -> None:
            async with semaphore:
                worker = await worker_pool.get()
                try:
                    context = self._build_step_context(
                        all_steps, step, memory_context=memory_context
                    )
                    await self._run_step(
                        step, worker, context,
                        out=buffers[step.id],
                    )
                except Exception as exc:
                    log.error("[计划] 并行步骤 %s 异常失败", step.id, exc_info=True)
                    step.status = StepStatus.FAILED
                    step.result = f"并行执行异常: {exc}"
                    buffers[step.id].write(f"❌ 步骤 [{step.id}] 并行执行异常: {exc}\n")
                finally:
                    worker.clear_history()
                    worker_pool.put_nowait(worker)

        await asyncio.gather(*(run_one(step) for step in batch), return_exceptions=True)

        # 按 batch 内 step_id 的原始顺序 flush 各步骤的缓冲输出
        for step in batch:
            content = buffers[step.id].getvalue()
            if content:
                print(content, end="")
        log.info("[计划] 并行批次完成，步骤=%s", ",".join(step.id for step in batch))

    # —— 上下文构建 ——
    def _build_step_context(
        self,
        steps: list[ExecutionStep],
        current: ExecutionStep,
        *,
        memory_context: str = "",
    ) -> str:
        lines = []
        if memory_context:
            lines.append(memory_context)
            lines.append("")
        lines.append("总任务上下文：")
        for s in steps:
            if s.is_completed and s.id in current.dependencies:
                preview = s.result[:500] + "..." if len(s.result) > 500 else s.result
                lines.append(f"已完成的依赖步骤 [{s.id}]: {s.description}")
                if preview:
                    lines.append(f"结果：{preview}\n")
        return "\n".join(lines)

    def _summarize_steps(self, steps: list[ExecutionStep]) -> str:
        lines = []
        for s in steps:
            deps = ", ".join(s.dependencies) if s.dependencies else "无"
            icon = "✅" if s.is_completed else "⏳"
            lines.append(f"  {icon} [{s.id}] {s.description} (依赖: {deps})")
        return "\n".join(lines)

    def _build_final_result(self, steps: list[ExecutionStep]) -> str:
        all_completed = all(s.is_completed for s in steps)
        has_failed = any(s.is_failed for s in steps)

        if all_completed:
            header = "✅ 多 Agent 协作任务完成！\n"
        elif has_failed:
            header = "⚠️ 多 Agent 协作任务未完全完成，存在失败步骤。\n"
        else:
            header = "⚠️ 多 Agent 协作任务部分完成，仍有未执行步骤。\n"

        lines = [header, "📋 执行总结："]
        for s in steps:
            icon = {
                StepStatus.COMPLETED: "✅",
                StepStatus.FAILED: "❌",
                StepStatus.PENDING: "⏳",
                StepStatus.RUNNING: "🔄",
            }[s.status]
            lines.append(f"[{s.id}] {icon} {s.description}")
            if s.result:
                preview = s.result[:120] + "..." if len(s.result) > 120 else s.result
                lines.append(f"   结果: {preview}")
        return "\n".join(lines)

    def __repr__(self) -> str:
        return (
            f"AgentOrchestrator(workers={self.worker_count}, "
            f"memory={'on' if self.memory_manager else 'off'})"
        )


def _emit(out: StringIO | None, msg: str) -> None:
    """写到缓冲（并行批次）或 stdout（单步串行）。"""
    if out is not None:
        out.write(msg + "\n")
    else:
        print(msg)
