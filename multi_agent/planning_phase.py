"""PlanningPhase - 规划阶段：生成、解析和审查执行计划。"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from llm.types import Message
from ui import (
    print_content_delta,
    print_plan_start,
    print_plan_steps,
    print_replan,
)

from .plan_types import ExecutionStep, PlanReviewDecision, PlanReviewFn
from .sub_agent import SubAgent

log = logging.getLogger(__name__)


@dataclass
class PlanningResult:
    """规划阶段的结果。"""

    steps: list[ExecutionStep]
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


class PlanningPhase:
    """规划阶段：调用 planner、解析 JSON、处理计划审查。"""

    def __init__(
        self,
        planner: SubAgent,
        *,
        plan_review_handler: PlanReviewFn | None = None,
    ):
        self.planner = planner
        self._plan_review_handler = plan_review_handler

    def run(self, user_input: str, *, memory_context: str = "") -> PlanningResult:
        """生成可执行步骤；失败时返回 error。"""
        log.info("[计划] 第一阶段：开始生成执行计划")
        print_plan_start()

        plan_content = self._run_planner(user_input, memory_context=memory_context)
        if plan_content is None:
            return PlanningResult([], "⏹️ 已取消")
        if not plan_content:
            return PlanningResult([], "❌ 规划失败：规划者未能生成有效计划")

        steps = _parse_plan(plan_content)
        log.info("[计划] 解析出 %d 个执行步骤", len(steps))
        if not steps:
            return PlanningResult([], f"❌ 规划失败：无法解析执行计划\n原始输出:\n{plan_content}")

        print_plan_steps(_summarize_steps(steps))

        if self._plan_review_handler is None:
            return PlanningResult(steps)

        current_goal = user_input
        while True:
            decision, feedback = self._plan_review_handler(current_goal, steps)
            if decision == PlanReviewDecision.EXECUTE:
                return PlanningResult(steps)
            if decision == PlanReviewDecision.CANCEL:
                log.info("[计划] 用户取消计划")
                return PlanningResult([], "⏹️ 已取消本次计划执行。")

            log.info("[计划] 用户补充要求：%s", feedback)
            print_replan()
            current_goal = f"{user_input}\n补充要求：{feedback}"

            replan_content = self._run_planner(current_goal, memory_context=memory_context)
            if replan_content is None:
                return PlanningResult([], "⏹️ 已取消")
            if not replan_content:
                return PlanningResult([], "❌ 重新规划失败：规划者未能生成有效计划")

            steps = _parse_plan(replan_content)
            if not steps:
                return PlanningResult([], f"❌ 重新规划失败：无法解析执行计划\n原始输出:\n{replan_content}")
            print_plan_steps(_summarize_steps(steps), title="📋 新执行计划")

    def _run_planner(self, goal: str, *, memory_context: str = "") -> str | None:
        """流式调用 planner；取消时返回 None。"""
        content_parts: list[str] = []
        task_msg = Message(role="user", content=f"请为以下任务制定执行计划：\n{goal}")
        for event in self.planner.execute(task_msg, context=memory_context):
            if event.type == "content":
                content_parts.append(event.data)
                print_content_delta(event.data)
            elif event.type == "done":
                reason = event.data.get("reason") if event.data else None
                if reason == "cancelled":
                    return None
                break

        content = "".join(content_parts)
        self.planner.clear_history()
        log.info("[计划] 第一阶段完成：规划输出 %d 字", len(content))
        return content


def _parse_plan(plan_json: str) -> list[ExecutionStep]:
    """解析规划者输出的 JSON。容错 + id 重编号。"""
    try:
        cleaned = re.sub(r"```json\s*", "", plan_json)
        cleaned = re.sub(r"```\s*", "", cleaned).strip()
        data = json.loads(cleaned)
    except Exception as exc:
        log.error("[计划] 解析计划 JSON 失败：%s", exc)
        return []

    steps_data = data.get("steps") or data.get("tasks") or []
    if not isinstance(steps_data, list) or not steps_data:
        log.warning("[计划] 规划结果里没有 steps/tasks 数组")
        return []

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
            reads=_as_str_list(s.get("reads")),
            writes=_as_str_list(s.get("writes")),
            dependencies=[],
        ))

    for i, s in enumerate(steps_data):
        deps = _as_str_list(s.get("dependencies"))
        steps[i].dependencies = [id_mapping.get(str(d), str(d)) for d in deps]

    return steps


def _as_str_list(value) -> list[str]:
    if value is None or value == "":
        return []
    if not isinstance(value, list):
        value = [value]
    return [str(item) for item in value if str(item)]


def _summarize_steps(steps: list[ExecutionStep]) -> str:
    lines = []
    for s in steps:
        deps = ", ".join(s.dependencies) if s.dependencies else "无"
        icon = "✅" if s.is_completed else "⏳"
        boundaries = []
        if s.reads:
            boundaries.append(f"读: {', '.join(s.reads)}")
        if s.writes:
            boundaries.append(f"写: {', '.join(s.writes)}")
        boundary_text = f"；{'; '.join(boundaries)}" if boundaries else ""
        lines.append(f"  {icon} [{s.id}] {s.description} (依赖: {deps}{boundary_text})")
    return "\n".join(lines)
