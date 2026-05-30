from __future__ import annotations

import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Generic, TypeVar


SlashCommand = tuple[str, str]
T = TypeVar("T")


@dataclass(frozen=True)
class SelectOption(Generic[T]):
    value: T
    label: str
    description: str = ""


SLASH_COMMANDS: tuple[SlashCommand, ...] = (
    ("/help", "显示帮助"),
    ("/tools", "列出已注册工具"),
    ("/plan", "单 Agent 计划执行"),
    ("/memory", "显示长期记忆状态"),
    ("/new", "开启新对话"),
    ("/resume", "选择并恢复历史对话"),
    ("/remember", "写入一条长期记忆"),
    ("/tree", "显示当前对话树"),
    ("/jump", "跳转到旧消息节点"),
    ("/compact", "压缩当前会话分支"),
    ("/quit", "退出"),
)


def build_prompt() -> Callable[[], str]:
    """Return the best available terminal prompt function."""
    if not _can_use_prompt_toolkit():
        return lambda: input("\n> ")

    try:
        from prompt_toolkit.completion import Completer, Completion
        from prompt_toolkit import PromptSession
        from prompt_toolkit.filters import Condition
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.shortcuts import CompleteStyle
        from prompt_toolkit.styles import Style
    except ImportError:
        return lambda: input("\n> ")

    key_bindings = KeyBindings()

    class SlashCommandCompleter(Completer):
        def get_completions(self, document, complete_event):
            _ = complete_event
            text = document.text_before_cursor
            for command, description in _current_matches(text):
                yield Completion(
                    command,
                    start_position=-len(text),
                    display=command,
                    display_meta=description,
                )

    @Condition
    def slash_completion_open() -> bool:
        from prompt_toolkit.application import get_app

        return bool(_current_matches(get_app().current_buffer.text))

    @key_bindings.add("enter", filter=slash_completion_open)
    def _(event) -> None:
        completion_state = event.current_buffer.complete_state
        completion = completion_state.current_completion if completion_state is not None else None
        if completion is not None:
            event.current_buffer.apply_completion(completion)
        else:
            matches = _current_matches(event.current_buffer.text)
            if matches:
                command, _ = matches[0]
                event.current_buffer.text = command
                event.current_buffer.cursor_position = len(command)
        event.current_buffer.validate_and_handle()

    style = Style.from_dict({
        "completion-menu.completion": "bg:#0d2538 #8ca4aa",
        "completion-menu.completion.current": "bg:#1a3a4f #c586c0 bold",
        "completion-menu.meta.completion": "bg:#0d2538 #6f878d",
        "completion-menu.meta.completion.current": "bg:#1a3a4f #c586c0",
    })

    session = PromptSession(
        completer=SlashCommandCompleter(),
        complete_while_typing=True,
        complete_style=CompleteStyle.COLUMN,
        key_bindings=key_bindings,
        style=style,
    )

    def prompt() -> str:
        return session.prompt("\n> ")

    return prompt


def select_from_menu(
    title: str,
    options: Sequence[SelectOption[T]],
    *,
    prompt: str = "选择",
    max_visible: int = 14,
    output: Callable[[str], None] | None = None,
    input_func: Callable[[str], str] | None = None,
) -> T | None:
    if not options:
        return None

    if not _can_use_prompt_toolkit():
        return _select_from_menu_fallback(
            title,
            options,
            prompt=prompt,
            output=output,
            input_func=input_func or input,
        )

    try:
        from prompt_toolkit.application import Application
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.layout import Layout, Window
        from prompt_toolkit.layout.controls import FormattedTextControl
        from prompt_toolkit.layout.dimension import Dimension
        from prompt_toolkit.styles import Style
    except ImportError:
        return _select_from_menu_fallback(
            title,
            options,
            prompt=prompt,
            output=output,
            input_func=input_func or input,
        )

    selected_index = 0
    visible_count = max(1, min(max_visible, len(options)))
    height = _select_menu_height(len(options), visible_count, bool(title))

    def fragments():
        return _select_menu_fragments(
            title,
            options,
            selected_index=selected_index,
            max_visible=visible_count,
        )

    key_bindings = KeyBindings()

    @key_bindings.add("down")
    def _(event) -> None:
        nonlocal selected_index
        selected_index = (selected_index + 1) % len(options)
        event.app.invalidate()

    @key_bindings.add("up")
    def _(event) -> None:
        nonlocal selected_index
        selected_index = (selected_index - 1) % len(options)
        event.app.invalidate()

    @key_bindings.add("enter")
    def _(event) -> None:
        event.app.exit(result=options[selected_index].value)

    @key_bindings.add("escape")
    @key_bindings.add("c-c")
    def _(event) -> None:
        event.app.exit(result=None)

    style = Style.from_dict({
        "select-menu.title": "#8ca4aa bold",
        "select-menu.hint": "#6f878d",
        "select-menu.item": "#8ca4aa",
        "select-menu.detail": "#6f878d",
        "select-menu.current": "#c586c0 bold",
        "select-menu.current-detail": "#c586c0",
    })
    control = FormattedTextControl(fragments, focusable=True)
    window = Window(
        content=control,
        height=Dimension.exact(height),
        dont_extend_height=True,
        always_hide_cursor=True,
    )
    app = Application(
        layout=Layout(window),
        key_bindings=key_bindings,
        full_screen=False,
        erase_when_done=False,
        mouse_support=False,
        style=style,
    )
    try:
        return app.run()
    except (EOFError, KeyboardInterrupt):
        return None


def _should_show_menu(text: str) -> bool:
    if not text.startswith("/"):
        return False
    if "\n" in text:
        return False
    return " " not in text


def _current_matches(text: str) -> list[SlashCommand]:
    if not _should_show_menu(text):
        return []
    return list(_matching_commands(text, SLASH_COMMANDS))


def _matching_commands(prefix: str, commands: Iterable[SlashCommand]) -> Iterable[SlashCommand]:
    for command, description in commands:
        if command.startswith(prefix):
            yield command, description


def _can_use_prompt_toolkit() -> bool:
    return bool(sys.stdin.isatty() and sys.stdout.isatty())


def _select_from_menu_fallback(
    title: str,
    options: Sequence[SelectOption[T]],
    *,
    prompt: str,
    output: Callable[[str], None] | None,
    input_func: Callable[[str], str],
) -> T | None:
    write = output or print
    if title:
        write(title)
    for index, option in enumerate(options, start=1):
        suffix = f"  {option.description}" if option.description else ""
        write(f"  {index:>2}. {option.label}{suffix}")
    write("输入编号，回车取消。")

    while True:
        try:
            choice = input_func(f"{prompt}> ").strip()
        except (EOFError, KeyboardInterrupt):
            return None
        if not choice:
            return None
        if choice.isdigit():
            index = int(choice)
            if 1 <= index <= len(options):
                return options[index - 1].value
        write(f"无效选择: {choice}")


def _select_menu_height(total: int, visible_count: int, has_title: bool) -> int:
    height = visible_count + 1
    if has_title:
        height += 1
    if total > visible_count:
        height += 2
    return height


def _select_menu_fragments(
    title: str,
    options: Sequence[SelectOption[T]],
    *,
    selected_index: int,
    max_visible: int,
):
    start, end = _visible_range(selected_index, len(options), max_visible)
    fragments = []
    if title:
        fragments.extend([("class:select-menu.title", title), ("", "\n")])
    fragments.extend([("class:select-menu.hint", "↑/↓ 选择 · Enter 确认 · Esc 取消"), ("", "\n")])
    if start > 0:
        fragments.extend([("class:select-menu.hint", "   ..."), ("", "\n")])

    for index in range(start, end):
        option = options[index]
        current = index == selected_index
        item_style = "class:select-menu.current" if current else "class:select-menu.item"
        detail_style = "class:select-menu.current-detail" if current else "class:select-menu.detail"
        fragments.append((item_style, "   " + option.label))
        if option.description:
            fragments.append((detail_style, "  " + option.description))
        fragments.append(("", "\n"))

    if end < len(options):
        fragments.extend([("class:select-menu.hint", "   ..."), ("", "\n")])
    if fragments and fragments[-1][1] == "\n":
        fragments.pop()
    return fragments


def _visible_range(selected_index: int, total: int, max_visible: int) -> tuple[int, int]:
    if total <= max_visible:
        return 0, total
    half = max_visible // 2
    start = selected_index - half
    start = max(0, min(start, total - max_visible))
    return start, start + max_visible
