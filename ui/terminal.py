"""统一的终端输出层。

所有用户可见输出都走这里，方便：
- 统一样式
- 未来切换到事件总线 / TUI 库（rich 等）
- 避免业务模块反向依赖 cli_app
"""
from typing import TextIO

from .renderer import BranchNavigationChoice

COMMAND_OUTPUT_PREVIEW_CHARS = 4000


class TerminalRenderer:
    def message(self, message: str) -> None:
        print_message(message)

    def agent_event(self, event, *, agent_name: str = "react") -> None:
        render_agent_event(event, agent_name=agent_name)

    def cancel_requested(self) -> None:
        print_cancel_requested()

    def branch_navigation_choice(self, plan=None) -> BranchNavigationChoice:
        return ask_branch_navigation_choice(plan)


def _write(message: str, out: TextIO | None = None, *, end: str = "\n", flush: bool = False) -> None:
    if out is not None:
        out.write(message + end)
        return
    print(message, end=end, flush=flush)


def print_message(message: str) -> None:
    print(message)


def print_content_delta(text: str, out: TextIO | None = None) -> None:
    _write(text, out, end="", flush=True)


def print_tool_start(tool_name: str, out: TextIO | None = None) -> None:
    _write(f"\n🛠️ {tool_name}", out, flush=True)


def print_command_result(
    agent_name: str,
    tool_name: str,
    result: str,
    out: TextIO | None = None,
) -> None:
    if tool_name != "bash":
        return
    text = result or ""
    if len(text) > COMMAND_OUTPUT_PREVIEW_CHARS:
        text = (
            text[:COMMAND_OUTPUT_PREVIEW_CHARS]
            + f"\n...（输出过长，已截断，共 {len(result)} 字）"
        )
    _write(f"📤 [{agent_name}] {tool_name} 结果:\n{text}", out)


def render_agent_event(event, *, agent_name: str = "react", out: TextIO | None = None) -> None:
    if event.type == "content":
        print_content_delta(event.data, out)
        return
    if event.type == "tool_call_start":
        print_tool_start(event.data["name"], out)
        return
    if event.type == "tool_result":
        print_command_result(agent_name, event.data["name"], event.data["result"], out)
        return
    if event.type == "error":
        _write(f"\n[ERROR] {event.data}", out)
        return
    if event.type == "done":
        reason = event.data.get("reason") if event.data else None
        if reason == "cancelled":
            print_cancelled()


def print_cancel_requested() -> None:
    print("\n\n⚠️ 检测到 Ctrl+C，正在停止...", flush=True)


def print_cancelled() -> None:
    print("\n\n⚠️ 已取消", flush=True)


def print_approval_request(level: str, tool_name: str, risk: str, arguments: dict) -> None:
    print(f"\n⚠️ {level} {tool_name}")
    print(f"   风险: {risk}")
    print(f"   参数: {arguments}")


def ask_approval_choice() -> str:
    return input("允许执行？[y/n/c]: ").strip().lower()


def ask_approval_advice() -> str:
    return input("补充说明: ").strip()


def ask_branch_navigation_choice(plan=None, out: TextIO | None = None) -> BranchNavigationChoice:
    _ = plan
    _write("跳转到旧消息？", out)
    _write("  1. 直接跳转，不总结当前分支", out)
    _write("  2. 总结当前分支后跳转", out)
    _write("  3. 取消", out)

    while True:
        choice = input("选择 [1/2/3]: ").strip()
        if choice == "1":
            return BranchNavigationChoice.DIRECT
        if choice == "2":
            return BranchNavigationChoice.SUMMARIZE
        if choice == "3":
            return BranchNavigationChoice.CANCEL
        _write("请输入 1、2 或 3。", out)
