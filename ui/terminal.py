"""统一的终端输出层。

所有用户可见输出都走这里，方便：
- 统一样式
- 未来切换到事件总线 / TUI 库（rich 等）
- 避免业务模块反向依赖 cli_app
"""
import json
from typing import Any, TextIO

from .renderer import BranchNavigationChoice

TOOL_ARGUMENT_PREVIEW_CHARS = 300
TOOL_RESULT_PREVIEW_CHARS = 180


class TerminalRenderer:
    def __init__(self):
        self._content_parts: list[str] = []

    def message(self, message: str) -> None:
        self._flush_content()
        print_message(message)

    def agent_event(self, event, *, agent_name: str = "react") -> None:
        _ = agent_name
        if event.type == "content":
            self._content_parts.append(event.data)
            return
        if event.type == "tool_call_start":
            self._flush_content()
            print_tool_start(event.data["name"], event.data.get("args"))
            return
        if event.type == "tool_result":
            print_tool_result(event.data["name"], event.data["result"])
            return
        if event.type == "error":
            self._flush_content()
            _write(f"\n[ERROR] {event.data}")
            return
        if event.type == "done":
            self._flush_content()
            reason = event.data.get("reason") if event.data else None
            if reason == "cancelled":
                print_cancelled()

    def cancel_requested(self) -> None:
        self._flush_content()
        print_cancel_requested()

    def branch_navigation_choice(self, plan=None) -> BranchNavigationChoice:
        self._flush_content()
        return ask_branch_navigation_choice(plan)

    def _flush_content(self) -> None:
        if not self._content_parts:
            return
        content = "".join(self._content_parts)
        self._content_parts = []
        print_assistant_content(content)


def _write(message: str, out: TextIO | None = None, *, end: str = "\n", flush: bool = False) -> None:
    if out is not None:
        out.write(message + end)
        return
    print(message, end=end, flush=flush)


def print_message(message: str) -> None:
    print(message)


def print_content_delta(text: str, out: TextIO | None = None) -> None:
    _write(text, out, end="", flush=True)


def print_assistant_content(text: str, out: TextIO | None = None) -> None:
    cleaned = (text or "").strip()
    if not cleaned:
        return
    if out is not None:
        _write(cleaned, out)
        return
    try:
        from rich.console import Console
        from rich.markdown import Markdown

        Console().print(Markdown(cleaned))
    except Exception:
        print_message(cleaned)


def print_tool_start(
    tool_name: str,
    arguments: str | dict[str, Any] | None = None,
    out: TextIO | None = None,
) -> None:
    detail = format_tool_call_detail(tool_name, arguments)
    suffix = f" {detail}" if detail else ""
    _write(f"\n[tool] {tool_name}{suffix}", out, flush=True)


def format_tool_call_detail(tool_name: str, arguments: str | dict[str, Any] | None) -> str:
    args = _coerce_tool_arguments(arguments)
    if not args:
        return ""

    if tool_name == "bash":
        return _preview_argument(str(args.get("command") or ""))

    ordered_keys = _preferred_argument_keys(tool_name, args)
    if not ordered_keys:
        return ""

    parts = [f"{key}={_preview_argument(str(args[key]))}" for key in ordered_keys]
    return " ".join(parts)


def _coerce_tool_arguments(arguments: str | dict[str, Any] | None) -> dict[str, Any]:
    if not arguments:
        return {}
    if isinstance(arguments, dict):
        return arguments
    try:
        parsed = json.loads(arguments)
    except (TypeError, json.JSONDecodeError):
        return {"raw": str(arguments)}
    return parsed if isinstance(parsed, dict) else {"raw": parsed}


def _preferred_argument_keys(tool_name: str, args: dict[str, Any]) -> list[str]:
    preferred = {
        "read": ["path"],
        "write": ["path"],
        "edit": ["path", "old_text", "new_text"],
        "ls": ["path"],
        "grep": ["pattern", "path", "include"],
        "find": ["name", "path", "type"],
        "web_search": ["query"],
        "web_fetch": ["url"],
    }.get(tool_name)
    if preferred is None:
        preferred = ["path", "command", "query", "url", "pattern", "name", "raw"]
    return [key for key in preferred if key in args and args[key] not in (None, "")]


def _preview_argument(value: str) -> str:
    compact = " ".join(value.split())
    if len(compact) <= TOOL_ARGUMENT_PREVIEW_CHARS:
        return compact
    return compact[:TOOL_ARGUMENT_PREVIEW_CHARS] + f"...（{len(compact)} 字）"


def print_tool_result(tool_name: str, result: str, out: TextIO | None = None) -> None:
    summary = format_tool_result_summary(tool_name, result)
    if summary:
        _write(f"       result: {summary}", out)


def print_command_result(agent_name: str, tool_name: str, result: str, out: TextIO | None = None) -> None:
    _ = agent_name
    print_tool_result(tool_name, result, out)


def format_tool_result_summary(tool_name: str, result: str) -> str:
    _ = tool_name
    text = result or ""
    compact = " ".join(text.split())
    if not compact:
        return "无输出"
    if len(compact) <= TOOL_RESULT_PREVIEW_CHARS:
        return compact
    return f"已折叠 {len(text)} 字，预览: {compact[:TOOL_RESULT_PREVIEW_CHARS]}..."


def render_agent_event(event, *, agent_name: str = "react", out: TextIO | None = None) -> bool:
    if event.type == "content":
        print_assistant_content(event.data, out)
        return bool(event.data)
    if event.type == "tool_call_start":
        print_tool_start(event.data["name"], event.data.get("args"), out)
        return False
    if event.type == "tool_result":
        print_command_result(agent_name, event.data["name"], event.data["result"], out)
        return False
    if event.type == "error":
        _write(f"\n[ERROR] {event.data}", out)
        return False
    if event.type == "done":
        reason = event.data.get("reason") if event.data else None
        if reason == "cancelled":
            print_cancelled()
        return False
    return False


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
