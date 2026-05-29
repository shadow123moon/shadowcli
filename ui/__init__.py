"""UI 层 - 统一的用户输出/输入接口。

所有面向用户的终端输出都走这里，不放业务逻辑。
CLI 和扩展可以从这里导入终端渲染函数；agent 层只产出事件，不导入 UI。
"""
from .renderer import BranchNavigationChoice, Renderer
from .terminal import (
    TerminalRenderer,
    ask_approval_advice,
    ask_approval_choice,
    ask_branch_navigation_choice,
    print_approval_request,
    print_cancel_requested,
    print_cancelled,
    print_command_result,
    print_content_delta,
    print_message,
    print_tool_start,
    render_agent_event,
)

__all__ = [
    "BranchNavigationChoice",
    "Renderer",
    "TerminalRenderer",
    "ask_approval_advice",
    "ask_approval_choice",
    "ask_branch_navigation_choice",
    "print_approval_request",
    "print_cancel_requested",
    "print_cancelled",
    "print_command_result",
    "print_content_delta",
    "print_message",
    "print_tool_start",
    "render_agent_event",
]
