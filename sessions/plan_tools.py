"""Plan mode tools for agent interaction."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict

from tooling.base import Tool


@dataclass(frozen=True)
class PlanProposal:
    """A plan proposal from the agent."""
    plan: str
    reason: str = ""


ConfirmPlan = Callable[[PlanProposal], bool]


class ExitPlanModeTool(Tool):
    """Tool for agent to propose exiting plan mode with a plan.

    This tool allows the agent to actively propose exiting plan mode
    by submitting a plan for user approval. The plan is only accepted
    if the user confirms it.
    """

    category = "plan"
    effect = "write"  # Modifies plan mode state
    concurrency_safe = False
    result_kind = "text"
    guidance = (
        "exit_plan_mode 工具用于在完成计划后主动提出退出 plan mode。"
        "只在你已经充分探索代码、理解需求、并形成清晰的实施计划后调用。"
        "提交的计划应该具体、可执行，包含明确的步骤和文件列表。"
        "工具会请求用户确认计划，确认后才会退出 plan mode。"
    )

    approval_required = True
    approval_level = "🟡 中等"
    approval_reason = "将提交计划并退出 plan mode，需要用户确认计划内容"

    def __init__(self, *, confirm_plan: ConfirmPlan, on_plan_approved: Callable[[str], None]):
        """Initialize the tool.

        Args:
            confirm_plan: Callback to confirm plan with user
            on_plan_approved: Callback to execute when plan is approved (receives plan text)
        """
        self.confirm_plan = confirm_plan
        self.on_plan_approved = on_plan_approved

    @property
    def name(self) -> str:
        return "exit_plan_mode"

    @property
    def description(self) -> str:
        return (
            "提出退出 plan mode 并提交实施计划。"
            "用户确认后会退出 plan mode 并记录已批准的计划。"
        )

    @property
    def parameters(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "plan": {
                    "type": "string",
                    "description": (
                        "完整的实施计划，包含具体步骤、涉及的文件、实现方法等。"
                        "计划应该清晰、具体、可执行。"
                    ),
                },
                "reason": {
                    "type": "string",
                    "description": "为什么现在适合退出 plan mode（可选）",
                },
            },
            "required": ["plan"],
        }

    def execute(self, arguments: Dict) -> str:
        plan_text = arguments.get("plan", "").strip()
        reason = arguments.get("reason", "").strip()

        if not plan_text:
            return "错误: plan 参数不能为空。"

        proposal = PlanProposal(plan=plan_text, reason=reason)

        # 请求用户确认
        if not self.confirm_plan(proposal):
            return "用户未确认计划，仍处于 plan mode。你可以继续探索或修改计划后重新提交。"

        # 用户确认，执行退出
        self.on_plan_approved(plan_text)
        return f"✓ 计划已批准并记录。已退出 plan mode，可以开始实施。\n\n已批准计划:\n{plan_text}"
