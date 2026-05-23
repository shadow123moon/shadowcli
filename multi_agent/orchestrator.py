"""AgentOrchestrator - Multi-Agent 系统的主控（编排器）。

主从架构：
- planner       : 拆任务为 JSON 计划
- workers (N)   : 池化的多个 Worker，并发执行批次内的独立步骤
- reviewer      : 审查 Worker 结果，不通过则带反馈重做（最多 2 次重试）

关键工程细节：
- asyncio.Semaphore 限制并发，asyncio.Queue 维护 Worker 池（避免同一 Worker 被并发占用）
- 并行步骤独立 StringIO 缓冲，按 step_id 顺序 flush 到 stdout（防止输出交错）
- JSON 解析二级兜底：标准解析失败时进入关键词分支（含否定→拒绝，无肯定→拒绝）
- 接 MemoryManager：写用户输入和最终结果到短期记忆
- 接 threading.Event：在 critical points 检查取消

Pythonic 要点：
- async def 全链路 + asyncio.gather 并行
- @dataclass + @property（is_completed / is_pending）替代 getter
- 模块级常量（NEGATIVE_KEYWORDS / POSITIVE_KEYWORDS）替代 Java 私有 static field
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

from .messages import AgentMessage
from .roles import AgentRole
from .sub_agent import ChatFn, SubAgent

log = logging.getLogger(__name__)

MAX_RETRIES_PER_STEP = 2
DEFAULT_WORKER_COUNT = 2

# 关键词兜底（JSON 解析失败时用）
NEGATIVE_KEYWORDS = (
    "未通过", "不通过", "不合格", "有问题",
    '"approved": false', '"approved":false',
)
POSITIVE_KEYWORDS = (
    "通过", "合格",
    '"approved": true', '"approved":true',
)


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
    ):
        self.chat = chat
        self.tool_registry = tool_registry
        self.memory_manager = memory_manager
        self.cancel = cancel or threading.Event()
        self.worker_count = max(1, worker_count)

        self.planner = SubAgent(
            "planner", AgentRole.PLANNER, chat, tool_registry,
            memory_manager=memory_manager, cancel=self.cancel,
        )
        self.workers = [
            SubAgent(
                f"worker-{i + 1}", AgentRole.WORKER, chat, tool_registry,
                memory_manager=memory_manager, cancel=self.cancel,
            )
            for i in range(self.worker_count)
        ]
        self.reviewer = SubAgent(
            "reviewer", AgentRole.REVIEWER, chat, tool_registry,
            memory_manager=memory_manager, cancel=self.cancel,
        )

    # —— 主入口 ——
    async def run(self, user_input: str) -> str:
        """运行多 Agent 协作任务。"""
        log.info("Multi-Agent run started: inputLen=%d", len(user_input or ""))
        if self.memory_manager is not None:
            self.memory_manager.add_user(user_input)
        if self.cancel.is_set():
            return "⏹️ 已取消"

        # 1. 规划
        print("📋 第一阶段：规划")
        print("🧑‍💼 规划者正在分析任务...\n")
        plan_msg = await self.planner.execute(
            AgentMessage.task("orchestrator", f"请为以下任务制定执行计划：\n{user_input}")
        )
        self.planner.clear_history()

        if plan_msg.is_error():
            return f"❌ 规划阶段失败：{plan_msg.content}"
        if plan_msg.is_empty():
            return "❌ 规划失败：规划者未能生成有效计划"

        # 2. 解析计划
        steps = self._parse_plan(plan_msg.content)
        if not steps:
            return f"❌ 规划失败：无法解析执行计划\n原始输出:\n{plan_msg.content}"

        print("📋 执行计划")
        print(self._summarize_steps(steps) + "\n")

        # 3. 执行阶段
        print("⚡ 第二阶段：执行")
        retry_count: dict[str, int] = {}
        single_cursor = 0
        batch_index = 0

        while True:
            if self.cancel.is_set():
                return "⏹️ 已取消"
            executable = self._get_executable_steps(steps)
            if not executable:
                break
            batch_index += 1

            if len(executable) == 1:
                # 单步：直接 print，串行
                step = executable[0]
                worker = self.workers[single_cursor % len(self.workers)]
                single_cursor += 1
                context = self._build_step_context(steps, step)
                await self._run_step(step, retry_count, worker, self.reviewer, context, out=None)
                worker.clear_history()
            else:
                # 多步：并行 + 缓冲 + 顺序 flush
                print(
                    f"⚡ 批次 #{batch_index}：{len(executable)} 个独立步骤并行执行"
                    f"（最多 {self.worker_count} 个并发 Worker）\n"
                )
                await self._run_batch_parallel(executable, steps, retry_count)

        # 4. 因前置失败而无法执行的残留步骤（显式提示）
        for step in steps:
            if step.is_pending:
                print(f"⏭️ 步骤 [{step.id}] 因前置步骤失败被跳过: {step.description}")

        # 5. 汇总并写回 Memory
        final = self._build_final_result(steps)
        if self.memory_manager is not None:
            self.memory_manager.add_assistant(f"[多Agent结果] {final}")
        return final

    # —— 容器协议 ——
    def __iter__(self):
        """直接迭代 orchestrator 拿到所有 SubAgent。"""
        yield self.planner
        yield from self.workers
        yield self.reviewer

    def __len__(self) -> int:
        return 2 + len(self.workers)  # planner + reviewer + workers

    # —— JSON 解析 ——
    def _parse_plan(self, plan_json: str) -> list[ExecutionStep]:
        """解析规划者输出的 JSON。容错 + id 重编号。"""
        try:
            cleaned = re.sub(r"```json\s*", "", plan_json)
            cleaned = re.sub(r"```\s*", "", cleaned).strip()
            data = json.loads(cleaned)
        except Exception as exc:
            log.error("Failed to parse plan JSON: %s", exc)
            return []

        # 兼容 steps / tasks 两种字段
        steps_data = data.get("steps") or data.get("tasks") or []
        if not isinstance(steps_data, list) or not steps_data:
            log.warning("Plan JSON has no 'steps' or 'tasks' array")
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

    def _parse_review_approval(self, review_content: str) -> bool:
        """解析审查者的 approved。保守策略：解析失败默认拒绝。

        二级兜底：JSON 解析失败时进入关键词分支
        - 含否定关键词 → 拒绝
        - 无肯定关键词 → 拒绝
        - 含肯定关键词 → 通过
        """
        if not review_content:
            log.warning("Reviewer returned empty content, defaulting to rejected")
            return False
        try:
            cleaned = re.sub(r"```json\s*", "", review_content)
            cleaned = re.sub(r"```\s*", "", cleaned).strip()
            data = json.loads(cleaned)
            approved = data.get("approved")
            if approved is None:
                log.warning("Reviewer JSON missing 'approved' field, defaulting to rejected")
                return False
            return bool(approved)
        except Exception:
            # 关键词兜底
            lower = review_content.lower()
            if any(neg.lower() in lower for neg in NEGATIVE_KEYWORDS):
                return False
            if not any(pos.lower() in lower for pos in POSITIVE_KEYWORDS):
                log.warning("Reviewer output unparseable, no explicit approval, defaulting to rejected")
                return False
            return True

    def _parse_review_issues(self, review_content: str) -> str:
        """解析审查反馈的具体问题。优先 issues > suggestions > summary。"""
        if not review_content:
            return ""
        try:
            cleaned = re.sub(r"```json\s*", "", review_content)
            cleaned = re.sub(r"```\s*", "", cleaned).strip()
            data = json.loads(cleaned)
            for key in ("issues", "suggestions"):
                items = data.get(key)
                if isinstance(items, list) and items:
                    return "\n".join(f"- {item}" for item in items)
            summary = data.get("summary")
            if summary:
                return str(summary)
        except Exception:
            pass
        return "审查未通过，请改进执行结果"

    # —— 步骤执行 ——
    async def _run_step(
        self,
        step: ExecutionStep,
        retry_count: dict[str, int],
        worker: SubAgent,
        reviewer: SubAgent,
        context: str,
        *,
        out: StringIO | None,
    ) -> None:
        """执行单步：Worker 执行 → Reviewer 审查 → 必要时重试。"""
        _emit(out, f"🛠️ {worker.name} 执行步骤 [{step.id}]: {step.description}")
        if self.cancel.is_set():
            step.status = StepStatus.FAILED
            step.result = "用户取消"
            return

        task_msg = AgentMessage.task("orchestrator", step.description)
        result = await worker.execute(task_msg, context=context, out=out)

        if self.cancel.is_set():
            step.status = StepStatus.FAILED
            step.result = "用户取消"
            return
        if result.is_error():
            step.status = StepStatus.FAILED
            step.result = result.content
            _emit(out, f"❌ 步骤 [{step.id}] 执行失败：{result.content}\n")
            return
        if result.is_empty():
            step.status = StepStatus.FAILED
            step.result = "执行结果为空"
            _emit(out, f"❌ 步骤 [{step.id}] 执行失败：结果为空\n")
            return

        # 审查
        _emit(out, f"🔍 {reviewer.name} 正在审查步骤 [{step.id}]...")
        review = await reviewer.review(step.description, result.content, out=out)
        reviewer.clear_history()

        # 审查 LLM 失败：保留执行结果，不算失败
        if review.is_error():
            log.warning("Reviewer failed for step %s: %s", step.id, review.content)
            _emit(out, f"⚠️ 步骤 [{step.id}] 审查 LLM 调用失败，保留当前执行结果\n")
            step.status = StepStatus.COMPLETED
            step.result = result.content
            return

        approved = self._parse_review_approval(review.content)
        accepted = result.content

        if approved:
            step.status = StepStatus.COMPLETED
            step.result = accepted
            _emit(out, f"✅ 步骤 [{step.id}] 审查通过\n")
            return

        # 重试
        retries = retry_count.get(step.id, 0)
        issues = self._parse_review_issues(review.content)
        log.info("Step %s rejected (retry %d/%d): %s", step.id, retries, MAX_RETRIES_PER_STEP, issues)

        while not approved and retries < MAX_RETRIES_PER_STEP:
            retries += 1
            retry_count[step.id] = retries
            _emit(out, f"⚠️ 步骤 [{step.id}] 审查未通过，正在重试...")
            _emit(out, f"   反馈: {issues}\n")

            feedback_context = f"{context}\n\n之前的执行结果被审查拒绝，原因：\n{issues}"
            retry_result = await worker.execute(task_msg, context=feedback_context, out=out)

            if retry_result.is_error():
                log.warning("Step %s retry %d failed at LLM: %s", step.id, retries, retry_result.content)
                issues = f"重试时 LLM 调用失败: {retry_result.content}"
                continue
            if retry_result.is_empty():
                accepted = "执行结果为空"
                issues = "执行结果为空"
                continue

            accepted = retry_result.content
            retry_review = await reviewer.review(step.description, accepted, out=out)
            reviewer.clear_history()

            if retry_review.is_error():
                # 审查再次失败：保留执行结果
                log.warning("Reviewer retry failed for step %s: %s", step.id, retry_review.content)
                approved = True
                break

            approved = self._parse_review_approval(retry_review.content)
            issues = self._parse_review_issues(retry_review.content)

        step.status = StepStatus.COMPLETED  # 即使最终未通过，也保留结果（与 paicli 行为一致）
        step.result = accepted
        if approved:
            _emit(out, f"✅ 步骤 [{step.id}] 重试后审查通过\n")
        else:
            _emit(out, f"⚠️ 步骤 [{step.id}] 超过最大重试次数，保留当前结果\n")

    async def _run_batch_parallel(
        self,
        batch: list[ExecutionStep],
        all_steps: list[ExecutionStep],
        retry_count: dict[str, int],
    ) -> None:
        """并行执行一批互不依赖的步骤。

        关键工程点：
        - asyncio.Queue 维护 Worker 池：每步 await get() / 完成后 put_nowait()，
          保证同一 Worker 不会被两个步骤并发占用
        - asyncio.Semaphore 限制并发到 worker_count
        - 每步独立 StringIO 缓冲，gather 完成后按 step_id 顺序 flush 到 stdout
          → 用户看到的输出顺序稳定，不会交错
        - 并行路径创建独立 reviewer 实例避免对话历史竞争
        """
        worker_pool: asyncio.Queue[SubAgent] = asyncio.Queue()
        for worker in self.workers:
            worker_pool.put_nowait(worker)

        buffers: dict[str, StringIO] = {step.id: StringIO() for step in batch}
        semaphore = asyncio.Semaphore(self.worker_count)

        async def run_one(step: ExecutionStep) -> None:
            async with semaphore:
                worker = await worker_pool.get()
                local_reviewer = SubAgent(
                    f"reviewer-{step.id}", AgentRole.REVIEWER, self.chat, self.tool_registry,
                    memory_manager=self.memory_manager, cancel=self.cancel,
                )
                try:
                    context = self._build_step_context(all_steps, step)
                    await self._run_step(
                        step, retry_count, worker, local_reviewer, context,
                        out=buffers[step.id],
                    )
                except Exception as exc:
                    log.error("Parallel step %s failed unexpectedly", step.id, exc_info=True)
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

    # —— 上下文构建 ——
    def _build_step_context(self, steps: list[ExecutionStep], current: ExecutionStep) -> str:
        lines = ["总任务上下文："]
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
