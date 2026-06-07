from __future__ import annotations

import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Generic, TypeVar


T = TypeVar("T")

@dataclass(frozen=True)
class SelectOption(Generic[T]):
    value: T
    label: str
    description: str = ""


def build_prompt() -> Callable[[], str]:
    """Return the standard REPL prompt function."""
    if _can_use_prompt_toolkit():
        try:
            return _build_prompt_toolkit_paste_prompt()
        except ImportError:
            pass
    return _build_plain_prompt()


def _build_plain_prompt() -> Callable[[], str]:
    return lambda: input("\n> ")


def _build_prompt_toolkit_paste_prompt() -> Callable[[], str]:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.keys import Keys

    key_bindings = KeyBindings()
    paste_index = 0
    pasted_texts: dict[str, str] = {}

    @key_bindings.add(Keys.BracketedPaste)
    def _(event) -> None:
        nonlocal paste_index
        text = _normalize_paste_text(event.data)
        if "\n" not in text:
            event.current_buffer.insert_text(text)
            return
        paste_index += 1
        placeholder = _paste_placeholder(paste_index, text)
        pasted_texts[placeholder] = text
        event.current_buffer.insert_text(placeholder)

    session = PromptSession(key_bindings=key_bindings, multiline=False)

    def prompt() -> str:
        nonlocal paste_index, pasted_texts
        paste_index = 0
        pasted_texts = {}
        line = session.prompt("\n> ")
        return _expand_paste_placeholders(line, pasted_texts)

    return prompt


def _normalize_paste_text(text: str) -> str:
    return (text or "").replace("\r\n", "\n").replace("\r", "\n")


def _paste_placeholder(index: int, text: str) -> str:
    return f"[Pasted text #{index} +{_paste_line_count(text)} lines]"


def _paste_line_count(text: str) -> int:
    lines = text.splitlines()
    return max(1, len(lines))


def _expand_paste_placeholders(line: str, pasted_texts: dict[str, str]) -> str:
    for placeholder, text in pasted_texts.items():
        line = line.replace(placeholder, text)
    return line


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
        erase_when_done=True,
        mouse_support=False,
        style=style,
    )
    try:
        return app.run()
    except (EOFError, KeyboardInterrupt):
        return None


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
