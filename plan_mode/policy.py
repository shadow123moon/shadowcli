from __future__ import annotations

import shlex
from typing import Any


PLAN_MODE_READ = "read"
PLAN_MODE_CONTROL = "control"
PLAN_MODE_SHELL = "shell"
PLAN_MODE_DENY = "deny"

_VISIBLE_CAPABILITIES = {PLAN_MODE_READ, PLAN_MODE_CONTROL, PLAN_MODE_SHELL}
_SHELL_BLOCK_MARKERS = (
    "\n",
    "\r",
    ";",
    "|",
    "&&",
    "||",
    ">",
    "<",
)
_SHELL_BLOCK_WORDS = {
    "add-content",
    "clear-content",
    "copy-item",
    "del",
    "erase",
    "mkdir",
    "move-item",
    "new-item",
    "out-file",
    "remove-item",
    "ren",
    "rename-item",
    "rm",
    "rmdir",
    "set-content",
    "tee-object",
}


def tool_plan_mode_capability(tool: Any) -> str:
    explicit = getattr(tool, "plan_mode", None)
    if explicit:
        return str(explicit)
    if getattr(tool, "effect", "write") == PLAN_MODE_READ:
        return PLAN_MODE_READ
    return PLAN_MODE_DENY


def is_plan_mode_tool_visible(tool: Any) -> bool:
    return tool_plan_mode_capability(tool) in _VISIBLE_CAPABILITIES


def is_plan_mode_tool_allowed(name: str, arguments: dict[str, Any], tool: Any) -> tuple[bool, str | None]:
    capability = tool_plan_mode_capability(tool)
    if capability in {PLAN_MODE_READ, PLAN_MODE_CONTROL}:
        return True, None
    if capability == PLAN_MODE_SHELL:
        command = str(arguments.get("command") or "")
        allowed, reason = is_read_only_shell_command(command)
        if allowed:
            return True, None
        return False, (
            f"plan mode 只允许只读 shell 命令，已拒绝 {name}: {reason}。"
            "允许的 shell 范围包括 git status 和 git diff；其他探索请优先使用 read/ls/grep/find。"
        )

    effect = getattr(tool, "effect", "write")
    return False, (
        f"plan mode 只允许只读工具或计划控制工具，已拒绝 {name}（effect={effect}, plan_mode={capability}）。"
        "请先完成计划，并让用户用 /exit-plan <计划内容> 批准后再执行修改。"
    )


def filter_tool_definitions_for_mode(
    definitions: list[dict],
    registry: Any,
    *,
    plan_mode_active: bool,
) -> list[dict]:
    filtered: list[dict] = []
    for definition in definitions:
        name = _definition_name(definition)
        if not name:
            continue
        tool = _get_tool(registry, name)
        if plan_mode_active:
            if tool is not None and is_plan_mode_tool_visible(tool):
                filtered.append(definition)
        elif tool is None or not getattr(tool, "plan_mode_only", False):
            filtered.append(definition)
    return filtered


def is_read_only_shell_command(command: str) -> tuple[bool, str]:
    stripped = command.strip()
    if not stripped:
        return False, "命令为空"

    lowered = stripped.lower()
    for marker in _SHELL_BLOCK_MARKERS:
        if marker in stripped:
            return False, f"包含 shell 组合或重定向符号 {marker!r}"
    for word in _SHELL_BLOCK_WORDS:
        if _contains_shell_word(lowered, word):
            return False, f"包含可能写入系统的命令 {word}"

    try:
        parts = shlex.split(stripped, posix=False)
    except ValueError as exc:
        return False, f"命令解析失败: {exc}"

    normalized = [_strip_quotes(part).lower() for part in parts if _strip_quotes(part)]
    if len(normalized) < 2:
        return False, "只允许 git status 或 git diff"
    if normalized[0] != "git":
        return False, "只允许 git status 或 git diff"

    subcommand = normalized[1]
    if subcommand == "status":
        return True, ""
    if subcommand == "diff":
        blocked_flags = ("--output", "--ext-diff")
        for part in normalized[2:]:
            if any(part == flag or part.startswith(f"{flag}=") for flag in blocked_flags):
                return False, f"git diff 参数 {part} 可能产生副作用"
        return True, ""
    return False, "只允许 git status 或 git diff"


def _definition_name(definition: dict) -> str | None:
    function = definition.get("function")
    if not isinstance(function, dict):
        return None
    name = function.get("name")
    return str(name) if name else None


def _get_tool(registry: Any, name: str) -> Any | None:
    get = getattr(registry, "get", None)
    if callable(get):
        try:
            return get(name)
        except KeyError:
            return None
    nested = getattr(registry, "registry", None)
    get = getattr(nested, "get", None)
    if callable(get):
        try:
            return get(name)
        except KeyError:
            return None
    return None


def _strip_quotes(value: str) -> str:
    return value.strip().strip("\"'")


def _contains_shell_word(text: str, word: str) -> bool:
    separators = " \t(){}[]"
    start = 0
    while True:
        index = text.find(word, start)
        if index < 0:
            return False
        before = text[index - 1] if index > 0 else " "
        after_index = index + len(word)
        after = text[after_index] if after_index < len(text) else " "
        if before in separators and after in separators:
            return True
        start = index + len(word)
