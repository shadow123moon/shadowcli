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
import logging
import threading
from io import StringIO

from ui import (
    print_buffer,
    print_execution_phase,
    print_parallel_batch,
    print_step_skipped,
)
from .execution_phase import ExecutionPhase
from .plan_types import ExecutionStep, PlanReviewFn, StepStatus
from .planning_phase import PlanningPhase
from .roles import AgentRole
from .sub_agent import ChatFn, SubAgent

log = logging.getLogger(__name__)

DEFAULT_WORKER_COUNT = 2


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
        self.planning = PlanningPhase(
            self.planner,
            plan_review_handler=plan_review_handler,
        )
        self.execution = ExecutionPhase(self.cancel)

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

        planning_result = self.planning.run(user_input, memory_context=memory_context)
        if not planning_result.ok:
            return planning_result.error
        steps = planning_result.steps

        # 3. 执行阶段
        log.info("[计划] 第二阶段：开始执行 %d 个步骤", len(steps))
        print_execution_phase()
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
                await self.execution.run_step(step, worker, context, out=None)
                worker.clear_history()
            else:
                # 多步：并行 + 缓冲 + 顺序 flush
                print_parallel_batch(batch_index, len(executable), self.worker_count)
                await self._run_batch_parallel(
                    executable, steps, memory_context=memory_context
                )

        # 4. 因前置失败而无法执行的残留步骤（显式提示）
        for step in steps:
            if step.is_pending:
                print_step_skipped(step.id, step.description)

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

    def _get_executable_steps(self, steps: list[ExecutionStep]) -> list[ExecutionStep]:
        status_map = {s.id: s.status for s in steps}
        return [
            s for s in steps
            if s.is_pending
            and all(status_map.get(dep) == StepStatus.COMPLETED for dep in s.dependencies)
        ]

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
                    await self.execution.run_step(
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
                print_buffer(content)
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

