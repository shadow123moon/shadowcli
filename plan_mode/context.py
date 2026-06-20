from __future__ import annotations

from .state import PlanModeState


def plan_mode_context(state: PlanModeState) -> str:
    if state.active:
        plan_file_lines = [
            "## Plan File",
            f"- 计划文件路径: {state.plan_file_path}",
            "- 最终计划会在用户批准后写入该文件；当前阶段不要修改业务文件。",
            "",
        ] if state.plan_file_path else []
        return "\n".join([
            "## 当前模式: Plan Mode",
            f"任务: {state.task}",
            "",
            "你现在处于只读计划模式。目标是充分理解任务并提交可执行计划，不要实现或修改业务文件。",
            "",
            *plan_file_lines,
            "## Plan Workflow",
            "### Phase 1: 理解与探索",
            "- 先确认用户目标、约束和成功标准。",
            "- 使用只读工具阅读相关代码、搜索现有实现和测试入口。",
            "- 范围不确定、涉及多个模块或需要并行查证时，用 fork_explore_agents 拆分边界；单点问题用 explore_agent。",
            "",
            "### Phase 2: 方案设计",
            "- 基于探索结果调用 plan_agent 生成方案草案，复杂任务可让多个 plan_agent 从不同角度设计。",
            "- 方案要优先复用现有函数、模块和项目风格，避免凭空发明新架构。",
            "",
            "### Phase 3: 审查与澄清",
            "- 回读关键文件，确认方案和用户意图一致。",
            "- 如仍有需求歧义或关键取舍，先向用户提问；不要把疑问藏进计划。",
            "",
            "### Phase 4: 最终计划",
            "- 输出推荐方案，不罗列所有备选方案。",
            "- 包含要修改的文件、每处改什么、复用哪些现有函数/工具、风险点和验证方式。",
            "- 计划应足够具体，后续执行模型可以直接照着实施。",
            "",
            "### Phase 5: 请求批准",
            "- 计划完成后必须调用 exit_plan_mode 工具请求用户确认，或让用户执行 /exit-plan <计划内容>。",
            "- 不要用普通文本问“是否可以开始”；批准计划只能通过 exit_plan_mode 或 /exit-plan 完成。",
        ])
    if state.approved_plan:
        lines = [
            "## 已批准计划",
            state.approved_plan,
        ]
        if state.plan_file_path:
            lines.extend(["", f"计划文件: {state.plan_file_path}"])
        return "\n".join(lines)
    return ""


def format_plan_mode_status(state: PlanModeState) -> str:
    if not state.active:
        return "当前未处于 plan mode。用法: /plan <任务>"
    return "\n".join([
        "当前处于 plan mode。",
        f"任务: {state.task}",
        "可继续让模型探索；批准计划请用 /exit-plan <计划内容>，或让模型调用 exit_plan_mode。",
    ])
