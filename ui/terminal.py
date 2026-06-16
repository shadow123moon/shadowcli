"""统一的终端输出层。"""
import json
import sys
from typing import Any, TextIO

from .renderer import BranchNavigationChoice

try:
    from rich.console import Console
    from rich.markdown import Heading, Markdown
    from rich.text import Text
    from rich.theme import Theme

    _RICH_AVAILABLE = True
except ImportError:
    Console = None
    Heading = None
    Markdown = None
    Text = None
    Theme = None
    _RICH_AVAILABLE = False

TOOL_ARGUMENT_PREVIEW_CHARS = 200
TOOL_RESULT_PREVIEW_CHARS = 150

TOOL_ICONS = {
    "read": "📄",
    "write": "✏️",
    "edit": "✏️",
    "bash": "▶",
    "grep": "🔍",
    "find": "🔍",
    "ls": "📁",
    "web_search": "🌐",
    "web_fetch": "🌐",
}

TOOL_RESULT_ERROR_PREFIXES = (
    "工具执行失败",
    "工具调用被拒绝",
    "操作被拒绝",
    "命令执行失败",
    "命令超时",
    "读取失败",
    "写入失败",
    "编辑失败",
    "grep 失败",
    "搜索失败",
    "抓取失败",
    "文件不存在",
    "路径不存在",
    "这是目录不是文件",
    "文件太大",
    "这是二进制文件",
)


if _RICH_AVAILABLE:
    _TERMINAL_THEME = Theme({
        "markdown.code": "cyan",
        "repr.filename": "cyan",
        "repr.path": "cyan",
    })

    class _LeftHeading(Heading):  # type: ignore[misc]
        def __rich_console__(self, console, options):  # type: ignore[no-untyped-def]
            text = self.text
            text.justify = "left"
            yield text

    class _AssistantMarkdown(Markdown):  # pyright: ignore[reportGeneralTypeIssues]
        elements = {**Markdown.elements, "heading_open": _LeftHeading}  # type: ignore[misc]

else:
    _TERMINAL_THEME = None
    _AssistantMarkdown = None  # type: ignore[assignment]


class TerminalRenderer:
    def __init__(self):
        self._content_parts: list[str] = []
        self._pending_tool_contexts: list[dict[str, Any]] = []

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
            tool_name = event.data["name"]
            arguments = event.data.get("args")
            self._remember_tool_context(tool_name, arguments)
            print_tool_start(tool_name, arguments)
            return
        if event.type == "tool_result":
            tool_name = event.data["name"]
            context = self._pop_tool_context(tool_name)
            print_tool_result(tool_name, event.data["result"], context=context)
            return
        if event.type == "error":
            self._flush_content()
            if _rich_tty():
                _console().print(f"\n[red bold]✗ Error:[/red bold] {event.data}")
            else:
                _write(f"\n✗ Error: {event.data}")
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

    def _remember_tool_context(self, tool_name: str, arguments: str | dict[str, Any] | None) -> None:
        self._pending_tool_contexts.append({
            "name": tool_name,
            "args": _coerce_tool_arguments(arguments),
        })

    def _pop_tool_context(self, tool_name: str) -> dict[str, Any]:
        for index, context in enumerate(self._pending_tool_contexts):
            if context.get("name") == tool_name:
                return self._pending_tool_contexts.pop(index)
        return {"name": tool_name, "args": {}}


def _stream_is_tty(out: TextIO | None = None) -> bool:
    stream = out or sys.stdout
    isatty = getattr(stream, "isatty", None)
    return bool(isatty and isatty())


def _rich_tty(out: TextIO | None = None) -> bool:
    return bool(_RICH_AVAILABLE and Console is not None and _stream_is_tty(out))


def _console(out: TextIO | None = None):
    return Console(
        file=out or sys.stdout,
        force_terminal=_stream_is_tty(out),
        theme=_TERMINAL_THEME,
        soft_wrap=False,
    )


def _write(message: str, out: TextIO | None = None, *, end: str = "\n", flush: bool = False) -> None:
    if out is not None:
        out.write(message + end)
        return
    print(message, end=end, flush=flush)


def print_message(message: str) -> None:
    print(message)


def print_assistant_content(text: str, out: TextIO | None = None) -> None:
    cleaned = (text or "").strip("\n")
    if not cleaned:
        return
    if _RICH_AVAILABLE and _AssistantMarkdown is not None and Console is not None:
        _console(out).print(_AssistantMarkdown(cleaned, justify="left", code_theme="ansi_dark"))
        return
    _write(_plain_markdown_text(cleaned), out)


def _plain_markdown_text(text: str) -> str:
    return text.replace("`", "").replace("**", "")


def print_tool_start(
    tool_name: str,
    arguments: str | dict[str, Any] | None = None,
    out: TextIO | None = None,
) -> None:
    icon = TOOL_ICONS.get(tool_name, "🔧")
    detail = format_tool_call_detail(tool_name, arguments)

    if _rich_tty(out):
        line = Text(f"\n{icon} ")
        line.append(tool_name, "dim")
        if detail:
            line.append(" ")
            line.append(detail, "dim cyan")
        _console(out).print(line)
        return

    suffix = f" {detail}" if detail else ""
    _write(f"\n{icon} {tool_name}{suffix}", out, flush=True)


def format_tool_call_detail(tool_name: str, arguments: str | dict[str, Any] | None) -> str:
    args = _coerce_tool_arguments(arguments)
    if not args:
        return ""

    if tool_name == "bash":
        return _preview_argument(str(args.get("command") or ""))

    ordered_keys = _preferred_argument_keys(tool_name, args)
    if not ordered_keys:
        return ""

    return " ".join(f"{key}={_preview_argument(str(args[key]))}" for key in ordered_keys)


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


def print_tool_result(
    tool_name: str,
    result: str,
    out: TextIO | None = None,
    *,
    context: dict[str, Any] | None = None,
) -> None:
    summary = format_tool_result_summary(tool_name, result)
    if not summary and _should_show_successful_tool_result(tool_name, result, context):
        _print_successful_tool_result(result, out, context=context)
        return
    if not summary:
        return

    if _rich_tty(out):
        _console(out).print(f"  [red]✗[/red] [dim red]{summary}[/dim red]")
    else:
        _write(f"  ✗ {summary}", out)


def format_tool_result_summary(tool_name: str, result: str) -> str:
    _ = tool_name
    text = result or ""
    compact = " ".join(text.split())
    if not compact or not _is_tool_result_error(compact):
        return ""
    if len(compact) <= TOOL_RESULT_PREVIEW_CHARS:
        return compact
    return f"已折叠 {len(text)} 字，预览: {compact[:TOOL_RESULT_PREVIEW_CHARS]}..."


def _is_tool_result_error(compact_result: str) -> bool:
    return any(compact_result.startswith(prefix) for prefix in TOOL_RESULT_ERROR_PREFIXES)


def _should_show_successful_tool_result(
    tool_name: str,
    result: str,
    context: dict[str, Any] | None,
) -> bool:
    if tool_name != "bash":
        return False
    if not (result or "").strip() or result.strip() == "命令执行成功（无输出）":
        return False
    return _is_git_diff_command(_tool_context_command(context))


def _print_successful_tool_result(
    result: str,
    out: TextIO | None = None,
    *,
    context: dict[str, Any] | None = None,
) -> None:
    text = result.rstrip("\n")
    if not text:
        return

    command = _tool_context_command(context)
    if _rich_tty(out) and Text is not None:
        if _is_git_diff_stat_command(command) and Text is not None:
            _console(out).print(_diff_stat_text(text))
            return
        _console(out).print(_diff_text(text))
        return

    _write(text, out)


def _tool_context_command(context: dict[str, Any] | None) -> str:
    if not context:
        return ""
    args = context.get("args")
    if not isinstance(args, dict):
        return ""
    return str(args.get("command") or "")


def _is_git_diff_command(command: str) -> bool:
    compact = " ".join(command.lower().split())
    return compact == "git diff" or compact.startswith("git diff ")


def _is_git_diff_stat_command(command: str) -> bool:
    compact = " ".join(command.lower().split())
    return _is_git_diff_command(compact) and " --stat" in f" {compact} "


def _diff_stat_text(result: str):
    if Text is None:
        return result
    text = Text()
    for line_index, line in enumerate(result.splitlines()):
        if line_index:
            text.append("\n")
        for char in line:
            if char == "+":
                text.append(char, "bold green")
            elif char == "-":
                text.append(char, "dim red")
            else:
                text.append(char)
    return text


def _diff_text(result: str):
    if Text is None:
        return result
    text = Text()
    for line_index, line in enumerate(result.splitlines()):
        if line_index:
            text.append("\n")
        text.append(line, _diff_line_style(line))
    return text


def _diff_line_style(line: str) -> str:
    if line.startswith("+") and not line.startswith("+++"):
        return "bold green"
    if line.startswith("-") and not line.startswith("---"):
        return "dim red"
    if line.startswith("@@"):
        return "yellow"
    if line.startswith(("diff --git", "index ", "---", "+++")):
        return "dim cyan"
    return ""


def print_cancel_requested() -> None:
    if _rich_tty():
        _console().print("\n[yellow]⚠ 正在停止...[/yellow]")
        sys.stdout.flush()
    else:
        print("\n⚠️ 检测到 Ctrl+C，正在停止...", flush=True)


def print_cancelled() -> None:
    if _rich_tty():
        _console().print("\n[yellow]⚠ 已取消[/yellow]")
        sys.stdout.flush()
    else:
        print("\n⚠️ 已取消", flush=True)


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


def ask_memory_confirmation(suggestion, out: TextIO | None = None) -> bool:
    _write(f"建议保存长期记忆 [{suggestion.memory_type}]:", out)
    _write(str(suggestion.text), out)
    reason = str(getattr(suggestion, "reason", "") or "").strip()
    if reason:
        _write(f"原因: {reason}", out)
    choice = input("保存吗？[y/N]: ").strip().lower()
    return choice in {"y", "yes"}


def ask_plan_confirmation(proposal, out: TextIO | None = None) -> bool:
    """Ask user to confirm a plan proposal.

    Args:
        proposal: PlanProposal with plan text and optional reason
        out: Output stream (default: sys.stdout)

    Returns:
        True if user confirms, False otherwise
    """
    _write("", out)
    _write("🎯 模型提出退出 plan mode 并提交计划:", out)
    _write("", out)
    _write(str(proposal.plan), out)
    _write("", out)
    reason = str(getattr(proposal, "reason", "") or "").strip()
    if reason:
        _write(f"原因: {reason}", out)
        _write("", out)
    choice = input("批准计划并退出 plan mode？[y/N]: ").strip().lower()
    return choice in {"y", "yes"}
