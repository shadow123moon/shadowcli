"""UI 层 - 统一的用户输出/输入接口。

所有面向用户的终端输出都走这里，不放业务逻辑。
其他模块可以安全地 from ui import ...，不会反向依赖 cli_app。
"""
from .terminal import (
    ask_approval_advice,
    ask_approval_choice,
    print_approval_request,
    print_buffer,
    print_cancel_requested,
    print_cancelled,
    print_command_result,
    print_content_delta,
    print_execution_phase,
    print_final_result,
    print_message,
    print_parallel_batch,
    print_plan_start,
    print_plan_steps,
    print_replan,
    print_step_cancelled,
    print_step_done,
    print_step_failed,
    print_step_skipped,
    print_step_start,
    print_tool_start,
)

__all__ = [
    "ask_approval_advice",
    "ask_approval_choice",
    "print_approval_request",
    "print_buffer",
    "print_cancel_requested",
    "print_cancelled",
    "print_command_result",
    "print_content_delta",
    "print_execution_phase",
    "print_final_result",
    "print_message",
    "print_parallel_batch",
    "print_plan_start",
    "print_plan_steps",
    "print_replan",
    "print_step_cancelled",
    "print_step_done",
    "print_step_failed",
    "print_step_skipped",
    "print_step_start",
    "print_tool_start",
]
