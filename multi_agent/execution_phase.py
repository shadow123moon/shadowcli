"""ExecutionPhase - 执行阶段：单步执行 Worker。

职责单一：
- 只负责执行一个步骤（单步）
- 流式消费 Worker 的事件，更新 step 状态
- 把输出写到 stdout 或缓冲（out 参数）

并行批次的调度逻辑留在 orchestrator，本类不关心。
"""
from __future__ import annotations

import logging
import threading
from io import StringIO

from llm.types import Message
from ui import (
    print_command_result,
    print_content_delta,
    print_step_cancelled,
    print_step_done,
    print_step_failed,
    print_step_start,
    print_tool_start,
)

from .plan_types import ExecutionStep, StepStatus
from .sub_agent import SubAgent

log = logging.getLogger(__name__)


class ExecutionPhase:
    """执行阶段：单步执行 Worker，更新 step 状态。"""

    def __init__(self, cancel: threading.Event):
        self.cancel = cancel

    async def run_step(
        self,
        step: ExecutionStep,
        worker: SubAgent,
        context: str,
        *,
        out: StringIO | None = None,
    ) -> None:
        """执行单步：Worker 流式执行后直接记录结果。"""
        log.info(
            "[计划] 开始步骤 %s，执行器=%s，依赖 %d 个",
            step.id,
            worker.name,
            len(step.dependencies),
        )
        print_step_start(worker.name, step.id, step.description, out)
        if self.cancel.is_set():
            step.status = StepStatus.FAILED
            step.result = "用户取消"
            log.info("[计划] 步骤 %s 被取消", step.id)
            return
        worker._current_step_label = f"{step.id} {step.description}"

        # 流式执行
        content_parts: list[str] = []
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
                    print_content_delta(event.data, out)
                elif event.type == "tool_call_start":
                    print_tool_start(event.data["name"], out)
                elif event.type == "tool_result":
                    print_command_result(worker.name, event.data["name"], event.data["result"], out)
                elif event.type == "done":
                    reason = event.data.get("reason") if event.data else None
                    if reason == "cancelled":
                        step.status = StepStatus.FAILED
                        step.result = "用户取消"
                        print_step_cancelled(step.id, out)
                        log.info("[计划] 步骤 %s 被取消", step.id)
                        return
                    elif reason == "blocked":
                        step.status = StepStatus.FAILED
                        step.result = "工具调用被拒绝"
                        print_step_failed(step.id, "工具调用被拒绝", out)
                        log.info("[计划] 步骤 %s 执行失败：工具调用被拒绝", step.id)
                        return
                    break

            result = "".join(content_parts)
            if not result:
                step.status = StepStatus.FAILED
                step.result = "执行结果为空"
                print_step_failed(step.id, "结果为空", out)
                log.info("[计划] 步骤 %s 执行失败：结果为空", step.id)
                return

            step.status = StepStatus.COMPLETED
            step.result = result
            print_step_done(step.id, out)
            log.info("[计划] 步骤 %s 完成", step.id)

        except Exception as exc:
            step.status = StepStatus.FAILED
            step.result = f"执行失败: {exc}"
            print_step_failed(step.id, str(exc), out)
            log.error("[计划] 步骤 %s 执行失败：%s", step.id, exc)
