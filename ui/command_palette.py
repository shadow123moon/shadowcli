"""Command palette and interactive selection for TUI."""
from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList
from textual.widgets.option_list import Option

from sessions.types import DEFAULT_SESSION_TITLE
from ui.tree_model import TreeDisplayNode, TreeFilterMode, build_tree_nodes

if TYPE_CHECKING:
    from sessions.entries import SessionEntry
    from sessions.types import SessionMeta


class CommandPalette(ModalScreen[str]):
    """Command palette - shows when user types '/'."""

    CSS = """
    CommandPalette {
        align: center middle;
    }

    #palette_container {
        width: 60;
        height: auto;
        max-height: 20;
        background: #0d2538;
        border: solid #1a3a4f;
        padding: 1;
    }

    #palette_title {
        color: #5a8fa8;
        text-style: bold;
        margin-bottom: 1;
    }

    OptionList {
        height: auto;
        max-height: 15;
        background: #0a1e2e;
        border: none;
    }

    OptionList > .option-list--option {
        background: #0a1e2e;
        color: #7a9aaa;
    }

    OptionList > .option-list--option-highlighted {
        background: #1a3a4f;
        color: #a8c8d8;
    }
    """

    COMMANDS = [
        ("/help", "Show help message"),
        ("/resume", "Resume a saved conversation"),
        ("/tree", "Show session tree and jump to node"),
        ("/compact", "Compact current session"),
        ("/clear", "Clear conversation display"),
        ("/quit", "Exit application"),
    ]

    def compose(self) -> ComposeResult:
        with Container(id="palette_container"):
            yield Label("Commands", id="palette_title")
            options = [Option(f"{cmd}  [dim]{desc}[/dim]", id=cmd) for cmd, desc in self.COMMANDS]
            yield OptionList(*options)

    def on_mount(self) -> None:
        self.query_one(OptionList).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """User selected a command."""
        self.dismiss(event.option_id)

    def on_key(self, event) -> None:
        """Handle Escape to cancel."""
        if event.key == "escape":
            self.dismiss(None)


class SessionTreeSelector(ModalScreen[str | None]):
    """Pi-style interactive session tree selector."""

    CSS = """
    SessionTreeSelector {
        align: center middle;
    }

    #tree_container {
        width: 88;
        height: auto;
        max-height: 32;
        background: #0d2538;
        border: solid #1a3a4f;
        padding: 1;
    }

    #tree_title {
        color: #5a8fa8;
        text-style: bold;
        margin-bottom: 1;
    }

    OptionList {
        height: auto;
        max-height: 24;
        background: #0a1e2e;
        border: none;
    }

    OptionList > .option-list--option {
        background: #0a1e2e;
        color: #7a9aaa;
    }

    OptionList > .option-list--option-highlighted {
        background: #1a3a4f;
        color: #a8c8d8;
    }

    #tree_help {
        color: #5a7a8a;
        margin-bottom: 1;
    }

    #tree_search {
        color: #7a9aaa;
        margin-bottom: 1;
    }
    """

    def __init__(self, entries: list[SessionEntry], current_leaf_id: str | None):
        super().__init__()
        self.entries = entries
        self.current_leaf_id = current_leaf_id
        self.filter_mode = TreeFilterMode.NO_TOOLS
        self.query = ""

    def compose(self) -> ComposeResult:
        with Container(id="tree_container"):
            yield Label("Session Tree", id="tree_title")
            yield Label(self._help_text(), id="tree_help")
            yield Label(self._search_text(), id="tree_search")
            yield OptionList(*self._build_options(), id="tree_options")

    def _build_options(self) -> list[Option]:
        nodes = self._display_nodes()
        if not nodes:
            return [Option("(no matching entries)", id="")]
        return [Option(self._format_node(node), id=node.entry_id) for node in nodes]

    def _display_nodes(self) -> list[TreeDisplayNode]:
        return build_tree_nodes(
            self.entries,
            self.current_leaf_id,
            filter_mode=self.filter_mode,
            query=self.query,
        )

    def _format_node(self, node: TreeDisplayNode) -> str:
        indent = self._indent_for(node)
        marker = "-> " if node.is_current_leaf else "*  " if node.is_current_branch else "   "
        label = f"{indent}{marker}{node.label}"
        return f"[bold]{label}[/bold]" if node.is_current_leaf else label

    @staticmethod
    def _indent_for(node: TreeDisplayNode) -> str:
        if node.depth <= 0:
            return ""
        return "   " * (node.depth - 1) + "|- "

    def _help_text(self) -> str:
        return "↑/↓ move • enter jump • esc cancel • type search • backspace clear • 1 default • 2 no-tools • 3 users • 4 all"

    def _search_text(self) -> str:
        return f"filter={self.filter_mode.value}  search={self.query or '(empty)'}"

    def on_mount(self) -> None:
        option_list = self.query_one("#tree_options", OptionList)
        option_list.focus()

        # Highlight current node
        if self.current_leaf_id:
            try:
                option_list.highlighted = self._current_index()
            except ValueError:
                pass

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """User selected a node."""
        if not event.option_id:
            return
        self.dismiss(event.option_id)

    def on_key(self, event) -> None:
        """Handle Escape, filtering, and search."""
        if event.key == "escape":
            self.dismiss(None)
            event.stop()
            return
        if event.key == "backspace":
            self.query = self.query[:-1]
            self._refresh_options()
            event.stop()
            return
        if event.character in {"1", "2", "3", "4"}:
            self.filter_mode = {
                "1": TreeFilterMode.DEFAULT,
                "2": TreeFilterMode.NO_TOOLS,
                "3": TreeFilterMode.USER_ONLY,
                "4": TreeFilterMode.ALL,
            }[event.character]
            self._refresh_options()
            event.stop()
            return
        if event.character and not event.character.isspace():
            self.query += event.character
            self._refresh_options()
            event.stop()

    def _refresh_options(self) -> None:
        self.query_one("#tree_search", Label).update(self._search_text())
        option_list = self.query_one("#tree_options", OptionList)
        option_list.clear_options()
        option_list.add_options(self._build_options())
        if option_list.option_count:
            option_list.highlighted = min(self._current_index(fallback=0), option_list.option_count - 1)

    def _current_index(self, fallback: int | None = None) -> int:
        for index, node in enumerate(self._display_nodes()):
            if node.entry_id == self.current_leaf_id:
                return index
        if fallback is not None:
            return fallback
        raise ValueError("current leaf is not visible")


class SessionResumeSelector(ModalScreen[str | None]):
    """Interactive saved conversation selector."""

    CSS = """
    SessionResumeSelector {
        align: center middle;
    }

    #resume_container {
        width: 88;
        height: auto;
        max-height: 28;
        background: #0d2538;
        border: solid #1a3a4f;
        padding: 1;
    }

    #resume_title {
        color: #5a8fa8;
        text-style: bold;
        margin-bottom: 1;
    }

    OptionList {
        height: auto;
        max-height: 22;
        background: #0a1e2e;
        border: none;
    }

    OptionList > .option-list--option {
        background: #0a1e2e;
        color: #7a9aaa;
    }

    OptionList > .option-list--option-highlighted {
        background: #1a3a4f;
        color: #a8c8d8;
    }
    """

    def __init__(self, sessions: list[SessionMeta], current_session_id: str | None = None):
        super().__init__()
        self.sessions = sessions
        self.current_session_id = current_session_id

    def compose(self) -> ComposeResult:
        with Container(id="resume_container"):
            yield Label("Resume Conversation", id="resume_title")
            yield OptionList(*self._build_options(), id="resume_options")

    def _build_options(self) -> list[Option]:
        if not self.sessions:
            return [Option("(no saved conversations)", id="")]
        return [Option(self._format_session(meta), id=meta.session_id) for meta in self.sessions]

    def _format_session(self, meta: SessionMeta) -> str:
        marker = "-> " if meta.session_id == self.current_session_id else "   "
        title = _session_title(meta)
        updated = meta.updated_at.replace("T", " ")[:19]
        count = f"{meta.message_count} messages"
        return f"{marker}{title}  [dim]{count} · {updated}[/dim]"

    def on_mount(self) -> None:
        option_list = self.query_one("#resume_options", OptionList)
        option_list.focus()
        if self.current_session_id:
            for index, meta in enumerate(self.sessions):
                if meta.session_id == self.current_session_id:
                    option_list.highlighted = index
                    break

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if not event.option_id:
            return
        self.dismiss(event.option_id)

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss(None)


def _session_title(meta: SessionMeta) -> str:
    title = (meta.title or "").strip()
    if not title or title == meta.session_id or title.isdigit():
        return DEFAULT_SESSION_TITLE
    return title
