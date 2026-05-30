"""Textual TUI for PaiCLI - Full-screen interactive interface."""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Input, RichLog, Static, Tree
from textual.widgets.tree import TreeNode
from textual.worker import Worker, WorkerState

from ui.renderer import BranchNavigationChoice
from ui.terminal import format_tool_call_detail, format_tool_result_summary

if TYPE_CHECKING:
    from agent.react_agent import ReactAgent
    from sessions.entries import MessageEntry, SessionEntry
    from sessions.manager import SessionManager
    from sessions.store import SessionStore


class StatusBar(Static):
    """Bottom status bar - Pi style minimal."""

    def __init__(self, agent_name: str = "react", model: str = "gpt-4", tokens: int = 0, cwd: Path | None = None):
        super().__init__()
        self.agent_name = agent_name
        self.model = model
        self.tokens = tokens
        self.cwd = Path(cwd or Path.cwd())

    def on_mount(self) -> None:
        self.update_status()

    def update_status(self, agent: str | None = None, model: str | None = None, tokens: int | None = None) -> None:
        if agent is not None:
            self.agent_name = agent
        if model is not None:
            self.model = model
        if tokens is not None:
            self.tokens = tokens

        # Pi-style minimal status: path | model | tokens
        status_text = Text()
        status_text.append(str(self.cwd), style="dim #5a8fa8")
        status_text.append(" | ", style="dim #3a5a68")
        status_text.append(self.model, style="#5a8fa8")
        status_text.append(" | ", style="dim #3a5a68")
        status_text.append(f"{self.tokens:,} tokens", style="dim #5a8fa8")

        self.update(status_text)


class ConversationPanel(Vertical):
    """Left panel showing conversation history."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._current_assistant_content: list[str] = []
        self._current_assistant_started = False
        self._current_tool_spinner: dict[str, object] | None = None

    def compose(self) -> ComposeResult:
        yield RichLog(highlight=True, markup=True, wrap=True, id="conversation_log")

    def add_user_message(self, content: str) -> None:
        """Render user message - Pi style minimal."""
        log = self.query_one("#conversation_log", RichLog)

        # Subtle separator line
        log.write(Text("─" * 80, style="dim #1a3a4f"))

        # User message in muted color, no border
        text = Text(content, style="#7a9aaa")
        log.write(text)
        log.write("")  # Spacing

    def start_assistant_message(self) -> None:
        """Start a new assistant message (streaming)."""
        self._current_assistant_content = []
        self._current_assistant_started = False

    def append_assistant_content(self, chunk: str) -> None:
        """Append content chunk to current assistant message (typewriter effect)."""
        self._current_assistant_content.append(chunk)
        log = self.query_one("#conversation_log", RichLog)

        # Typewriter effect - just append text, no borders
        if not self._current_assistant_started:
            self._current_assistant_started = True
            # First chunk - no label, just start writing
            log.write(Text(chunk, style="#a8c8d8"))
        else:
            # Subsequent chunks - continue on same line if possible
            log.write(chunk)

    def finish_assistant_message(self) -> None:
        """Finalize the current assistant message."""
        # Message already written incrementally, just reset state
        self._current_assistant_content = []
        self._current_assistant_started = False

    def add_assistant_message(self, content: str) -> None:
        """Render assistant message with green border and markdown (non-streaming)."""
        log = self.query_one("#conversation_log", RichLog)
        if content.strip():
            md = Markdown(content)
            panel = Panel(
                md,
                title="[bold green]Assistant[/bold green]",
                border_style="green",
                padding=(0, 1),
            )
            log.write(panel)

    def show_tool_call_start(self, tool_name: str, arguments: dict) -> None:
        """Show tool call with spinner - Pi style minimal."""
        log = self.query_one("#conversation_log", RichLog)

        text = Text()
        text.append("[tool] ", style="dim #5a7a8a")
        text.append(tool_name, style="bold #6a8a9a")
        detail = format_tool_call_detail(tool_name, arguments)
        if detail:
            text.append(f" {detail}", style="dim #5a7a8a")

        log.write(text)
        self._current_tool_spinner = {"name": tool_name}

    def show_tool_result(self, tool_name: str, result: str) -> None:
        """Show tool result - Pi style minimal."""
        log = self.query_one("#conversation_log", RichLog)

        text = Text()
        text.append("       result: ", style="dim #4a6a78")
        text.append(format_tool_result_summary(tool_name, result), style="dim #5a7a8a")
        log.write(text)
        log.write("")  # Spacing
        self._current_tool_spinner = None

    def add_tool_call(self, tool_name: str, arguments: dict) -> None:
        """Render tool call - Pi style minimal (non-streaming)."""
        log = self.query_one("#conversation_log", RichLog)

        text = Text()
        text.append("[tool] ", style="dim #5a7a8a")
        text.append(tool_name, style="bold #6a8a9a")
        detail = format_tool_call_detail(tool_name, arguments)
        if detail:
            text.append(f" {detail}", style="dim #5a7a8a")

        log.write(text)

    def add_tool_result(self, tool_name: str, result: str) -> None:
        """Render tool result - Pi style minimal (non-streaming)."""
        log = self.query_one("#conversation_log", RichLog)
        text = Text()
        text.append("       result: ", style="dim #4a6a78")
        text.append(format_tool_result_summary(tool_name, result), style="dim #5a7a8a")
        log.write(text)
        log.write("")  # Spacing

    def add_system_message(self, message: str, style: str = "cyan") -> None:
        """Render system message - Pi style minimal."""
        log = self.query_one("#conversation_log", RichLog)
        # Convert color names to hex
        color_map = {"cyan": "5a8fa8", "green": "6a9a7a", "red": "9a6a6a"}
        hex_color = color_map.get(style, "5a8fa8")
        text = Text(f"• {message}", style=f"dim #{hex_color}")
        log.write(text)
        log.write("")  # Spacing

    def clear_history(self) -> None:
        """Clear conversation log."""
        log = self.query_one("#conversation_log", RichLog)
        log.clear()


class SessionTreePanel(Vertical):
    """Right sidebar showing session tree."""

    def compose(self) -> ComposeResult:
        tree = Tree("Session Tree", id="session_tree")
        tree.show_root = True
        tree.show_guides = True
        yield tree

    def build_tree(self, entries: list[SessionEntry], current_leaf_id: str | None) -> None:
        """Build tree structure from session entries."""
        tree = self.query_one("#session_tree", Tree)
        tree.clear()
        tree.label = "Session Tree"

        if not entries:
            tree.root.add_leaf("(empty)")
            return

        # Build parent->children map
        children_map: dict[str | None, list[SessionEntry]] = {}
        entry_map: dict[str, SessionEntry] = {}

        for entry in entries:
            entry_map[entry.id] = entry
            parent_id = entry.parent_id
            if parent_id not in children_map:
                children_map[parent_id] = []
            children_map[parent_id].append(entry)

        # Recursive tree building
        def add_children(parent_node: TreeNode, parent_id: str | None) -> None:
            children = children_map.get(parent_id, [])
            for child in children:
                label = self._format_entry_label(child, current_leaf_id)
                child_node = parent_node.add(label, data=child.id)
                if child.id == current_leaf_id:
                    child_node.expand()
                add_children(child_node, child.id)

        add_children(tree.root, None)
        tree.root.expand()

    def _format_entry_label(self, entry: SessionEntry, current_leaf_id: str | None) -> str:
        """Format entry label for tree display."""
        from sessions.entries import BranchSummaryEntry, CompactionEntry, MessageEntry

        prefix = "→ " if entry.id == current_leaf_id else "  "
        short_id = entry.id[:6]

        if isinstance(entry, MessageEntry):
            role = entry.message.role
            content_preview = (entry.message.content or "")[:30].replace("\n", " ")
            if entry.message.tool_calls:
                tool_names = ", ".join(tc.function.name for tc in entry.message.tool_calls)
                return f"{prefix}[{short_id}] {role}: 🛠️ {tool_names}"
            return f"{prefix}[{short_id}] {role}: {content_preview}"

        if isinstance(entry, CompactionEntry):
            return f"{prefix}[{short_id}] 📦 Compaction ({entry.tokens_before} tokens)"

        if isinstance(entry, BranchSummaryEntry):
            return f"{prefix}[{short_id}] 🌿 Branch Summary"

        return f"{prefix}[{short_id}] {entry.type}"


class PaiCLIApp(App):
    """Main Textual TUI application - Pi-inspired minimal design."""

    CSS = """
    Screen {
        background: #0a1e2e;
    }

    ConversationPanel {
        height: 1fr;
        background: #0a1e2e;
        padding: 1 2;
    }

    #conversation_log {
        background: #0a1e2e;
        border: none;
    }

    SessionTreePanel {
        width: 30;
        height: 1fr;
        background: #0d2538;
        border-left: solid #1a3a4f;
        display: none;  /* Hidden by default, toggle with Ctrl+T */
    }

    #session_tree {
        background: #0d2538;
        border: none;
    }

    StatusBar {
        dock: bottom;
        height: 1;
        background: #0d2538;
        color: #5a8fa8;
    }

    Input {
        dock: bottom;
        height: 3;
        background: #0d2538;
        border: solid #1a3a4f;
        border-title-color: #5a8fa8;
    }

    Footer {
        display: none;  /* Hide default footer */
    }
    """

    BINDINGS = [
        ("ctrl+c", "cancel", "Cancel"),
        ("ctrl+q", "quit", "Quit"),
        ("ctrl+l", "clear", "Clear"),
        ("ctrl+t", "toggle_tree", "Tree"),
    ]

    def __init__(
        self,
        session_manager: SessionManager | None = None,
        agent: ReactAgent | None = None,
        runtime=None,
        long_term=None,
        startup_messages: list[tuple[str, str]] | None = None,
        session_store: SessionStore | None = None,
        cwd: Path | None = None,
    ):
        super().__init__()
        self.session_manager = session_manager
        self.agent = agent
        self.runtime = runtime
        self.long_term = long_term
        self.startup_messages = startup_messages or []
        self.session_store = session_store
        self.cwd = Path(cwd or getattr(session_manager, "cwd", Path.cwd()))
        self.cancel_event = threading.Event()
        self.current_worker: Worker | None = None
        self.status_bar = StatusBar(cwd=self.cwd)
        self.conversation = ConversationPanel()
        self.session_tree = SessionTreePanel()
        self.input_box = Input(placeholder="Type your message or /command...")

    def compose(self) -> ComposeResult:
        # Pi-style: main conversation with an optional tree side panel.
        with Horizontal(id="main_area"):
            yield self.conversation
            yield self.session_tree  # Hidden by default (CSS: display: none)
        yield self.input_box
        yield self.status_bar  # Bottom status bar

    def on_mount(self) -> None:
        """Initialize UI on mount."""
        self.title = "PaiCLI"
        self.input_box.focus()

        # 显示启动消息
        for message, style in self.startup_messages:
            self.conversation.add_system_message(message, style=style)

        if self.session_manager:
            self.load_session_history()
        else:
            self.conversation.add_system_message(
                "New conversation starts when you send a message. Use /resume to open a saved one.",
                style="cyan",
            )

    def load_session_history(self) -> None:
        """Load existing session history into conversation panel."""
        if not self.session_manager:
            return

        branch = self.session_manager.get_branch()
        for entry in branch:
            self._render_entry(entry)

        # Update session tree
        all_entries = self.session_manager.all_entries()
        current_leaf = self.session_manager.get_leaf_id()
        self.session_tree.build_tree(all_entries, current_leaf)

    def _render_entry(self, entry: SessionEntry) -> None:
        """Render a single session entry."""
        from sessions.entries import BranchSummaryEntry, CompactionEntry, MessageEntry

        if isinstance(entry, MessageEntry):
            msg = entry.message
            if msg.role == "user":
                self.conversation.add_user_message(msg.content or "")
            elif msg.role == "assistant":
                if msg.tool_calls:
                    for tc in msg.tool_calls:
                        try:
                            args = json.loads(tc.function.arguments)
                        except json.JSONDecodeError:
                            args = {"raw": tc.function.arguments}
                        self.conversation.add_tool_call(tc.function.name, args)
                if msg.content:
                    self.conversation.add_assistant_message(msg.content)
            elif msg.role == "tool":
                # Find corresponding tool call name (simplified)
                self.conversation.add_tool_result("tool", msg.content or "")

        elif isinstance(entry, CompactionEntry):
            self.conversation.add_system_message(
                f"📦 Compaction: {entry.summary[:50]}... ({entry.tokens_before} tokens)",
                style="dim cyan",
            )

        elif isinstance(entry, BranchSummaryEntry):
            self.conversation.add_system_message(
                f"🌿 Branch: {entry.summary[:50]}...",
                style="dim magenta",
            )

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle user input submission."""
        user_input = event.value.strip()
        if not user_input:
            return

        self.input_box.value = ""

        # Handle commands
        if user_input.startswith("/"):
            await self.handle_command(user_input)
            return

        if not self._ensure_session_for_message():
            return

        # Display user message
        self.conversation.add_user_message(user_input)

        # Stream agent response
        if self.agent:
            await self.stream_agent_task(user_input)
        else:
            self.conversation.add_system_message("No agent available.", style="red")

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle input changes - show command palette when typing '/'."""
        value = event.value

        # If user types '/' at the start, show command palette
        if value == "/":
            self.show_command_palette()

    def show_command_palette(self) -> None:
        """Show command palette overlay."""
        from ui.command_palette import CommandPalette

        async def handle_command_selection():
            result = await self.push_screen_wait(CommandPalette())
            if result:
                # User selected a command
                if result == "/tree":
                    await self.show_session_tree_selector()
                else:
                    # Execute the command
                    self.input_box.value = ""
                    await self.handle_command(result)
            else:
                # User cancelled
                self.input_box.value = ""

        self.run_worker(handle_command_selection())

    async def show_session_tree_selector(self) -> None:
        """Show interactive session tree selector."""
        if not self.session_manager:
            self.conversation.add_system_message("No session available.", style="red")
            return

        from ui.command_palette import SessionTreeSelector

        all_entries = self.session_manager.all_entries()
        current_leaf = self.session_manager.get_leaf_id()

        result = await self.push_screen_wait(SessionTreeSelector(all_entries, current_leaf))

        if result:
            # User selected a node - jump to it
            await self._handle_jump_command(result)

    def _ensure_session_for_message(self) -> bool:
        """Create a persisted session only when the user sends a real message."""
        if self.session_manager:
            if self.agent is None:
                self._rebuild_agent_for_session()
            return self.agent is not None

        if not self.session_store:
            self.conversation.add_system_message("No session store available.", style="red")
            return False

        session = self.session_store.create(self.cwd)
        self._attach_session(session, render_history=False)
        self.conversation.add_system_message(
            f"Started new conversation: {session.meta.session_id}",
            style="green",
        )
        return self.agent is not None

    def _attach_session(self, session: SessionManager, *, render_history: bool) -> None:
        self.session_manager = session
        self.cwd = session.cwd
        self.status_bar.cwd = session.cwd
        self.status_bar.update_status()
        self._rebuild_agent_for_session()
        self._refresh_tree_panel()
        if render_history:
            self.conversation.clear_history()
            self.load_session_history()

    def _rebuild_agent_for_session(self) -> None:
        if not self.session_manager or not self.runtime:
            return
        from cli_app.factories import build_agent

        self.agent = build_agent(
            self.runtime,
            conversation_messages=self.session_manager.messages(),
            on_message_appended=self.session_manager.append_message,
        )

    async def stream_agent_task(self, user_input: str) -> None:
        """Stream agent execution in background thread, bridge events to UI."""
        # Reset cancel event
        self.cancel_event.clear()
        context = self._build_context(user_input)

        # Start assistant message
        self.conversation.start_assistant_message()

        # Run agent in background worker
        self.current_worker = self.run_worker(
            self._agent_worker(user_input, context),
            name="agent_task",
            group="agent",
            exclusive=True,
        )

    def _build_context(self, user_input: str) -> str:
        if not self.session_manager or not self.long_term:
            return ""
        from sessions import RuntimeContextBuilder

        return RuntimeContextBuilder(session=self.session_manager, long_term=self.long_term).build(user_input)

    async def _agent_worker(self, user_input: str, context: str) -> None:
        """Worker that runs agent.events() in thread and bridges events."""

        def run_agent():
            """Run agent in thread, yield events."""
            try:
                for event in self.agent.events(user_input, context=context):
                    if self.cancel_event.is_set():
                        break
                    # Bridge event to main thread
                    self.call_from_thread(self._handle_stream_event, event)
            except Exception as exc:
                # Send error event
                from llm.client import StreamEvent
                error_event = StreamEvent("error", str(exc))
                self.call_from_thread(self._handle_stream_event, error_event)

        # Run in thread pool
        import asyncio
        await asyncio.to_thread(run_agent)

    def _handle_stream_event(self, event) -> None:
        """Handle StreamEvent in main thread (called via call_from_thread)."""
        if event.type == "content":
            # Append content chunk (typewriter effect)
            self.conversation.append_assistant_content(event.data)

        elif event.type == "tool_call_start":
            # Show spinner with tool name and args
            tool_name = event.data.get("name", "unknown")
            try:
                args = json.loads(event.data.get("args", "{}"))
            except json.JSONDecodeError:
                args = {"raw": event.data.get("args", "")}
            self.conversation.show_tool_call_start(tool_name, args)

        elif event.type == "tool_result":
            # Replace spinner with result
            tool_name = event.data.get("name", "unknown")
            result = event.data.get("result", "")
            self.conversation.show_tool_result(tool_name, result)

        elif event.type == "done":
            # Finalize assistant message
            reason = event.data.get("reason", "finished") if event.data else "finished"
            if reason == "cancelled":
                self.conversation.add_system_message("⏹️ Task cancelled", style="yellow")
            elif reason == "error":
                self.conversation.add_system_message("❌ Task failed", style="red")
            elif reason in ("token_budget_exceeded", "max_turns", "stagnation_detected"):
                self.conversation.add_system_message(f"⚠️ Task stopped: {reason}", style="yellow")

            self.current_worker = None
            self._refresh_tree_panel()

        elif event.type == "error":
            # Show error panel
            error_msg = event.data if isinstance(event.data, str) else str(event.data)
            panel = Panel(
                error_msg,
                title="[bold red]Error[/bold red]",
                border_style="red",
                padding=(0, 1),
            )
            log = self.conversation.query_one("#conversation_log", RichLog)
            log.write(panel)
            self.current_worker = None
            self._refresh_tree_panel()

    async def handle_command(self, command: str) -> None:
        """Handle slash commands."""
        cmd = command.lower().split()[0]

        if cmd == "/help":
            from cli_app.constants import HELP
            self.conversation.add_system_message(HELP, style="cyan")

        elif cmd == "/tree":
            if self.session_manager:
                await self.show_session_tree_selector()
                self._refresh_tree_panel()
            else:
                self.conversation.add_system_message("No session manager available.", style="red")

        elif cmd == "/resume":
            await self._handle_resume_command()

        elif cmd == "/clear":
            self.conversation.clear_history()

        elif cmd == "/compact":
            if self.session_manager:
                await self._handle_compact_command()
            else:
                self.conversation.add_system_message("No session manager available.", style="red")

        elif cmd.startswith("/jump"):
            if self.session_manager:
                await self._handle_jump_command(command)
            else:
                self.conversation.add_system_message("No session manager available.", style="red")

        elif cmd == "/tools":
            if self.runtime:
                from cli_app.factories import list_tools
                tools_list = list_tools(self.runtime)
                self.conversation.add_system_message(tools_list, style="cyan")
            else:
                self.conversation.add_system_message("No runtime available.", style="red")

        elif cmd == "/memory":
            if self.long_term:
                from cli_app.commands import format_memory_status
                status = format_memory_status(self.long_term)
                self.conversation.add_system_message(status, style="cyan")
            else:
                self.conversation.add_system_message("No long-term memory available.", style="red")

        elif cmd.startswith("/remember"):
            if self.long_term:
                from cli_app.commands import handle_remember
                result = handle_remember(self.long_term, command)
                self.conversation.add_system_message(result, style="cyan")
            else:
                self.conversation.add_system_message("No long-term memory available.", style="red")

        elif cmd == "/quit":
            self.exit()

        else:
            self.conversation.add_system_message(f"Unknown command: {cmd}", style="red")

    async def _handle_resume_command(self) -> None:
        """Handle /resume by letting the user choose a saved conversation."""
        if self.current_worker and self.current_worker.state == WorkerState.RUNNING:
            self.conversation.add_system_message("Wait for the current task to finish before resuming.", style="yellow")
            return
        if not self.session_store:
            self.conversation.add_system_message("No session store available.", style="red")
            return

        sessions = self.session_store.list(self.cwd)
        if not sessions:
            self.conversation.add_system_message("No saved conversations found.", style="yellow")
            return

        from ui.command_palette import SessionResumeSelector

        current_id = self.session_manager.meta.session_id if self.session_manager else None
        selected_id = await self.push_screen_wait(SessionResumeSelector(sessions, current_id))
        if not selected_id:
            self.conversation.add_system_message("Resume cancelled.", style="yellow")
            return

        try:
            session = self.session_store.open(self.cwd, selected_id)
        except FileNotFoundError:
            self.conversation.add_system_message(f"Session not found: {selected_id}", style="red")
            return

        self._attach_session(session, render_history=True)
        self.conversation.add_system_message(
            f"Resumed conversation: {session.meta.session_id}",
            style="green",
        )

    async def _handle_compact_command(self) -> None:
        """Handle /compact command."""
        from llm import chat
        from sessions.compaction import compact_session
        from cli_app.commands import format_compaction_result

        self.conversation.add_system_message("Compacting session...", style="yellow")

        try:
            result = compact_session(self.session_manager, force=True, chat_fn=chat)
            self.conversation.add_system_message(format_compaction_result(result), style="green")

            if result.compacted and self.agent:
                # Reload agent conversation
                from cli_app.runner import reload_agent_conversation
                reload_agent_conversation(self.agent, self.session_manager)
                self.conversation.add_system_message("Agent conversation reloaded.", style="dim green")
        except Exception as e:
            self.conversation.add_system_message(f"Compaction failed: {e}", style="red")

    async def _handle_jump_command(self, command_or_id: str) -> None:
        """Handle /jump <entry_id> command or direct entry_id."""
        from cli_app.commands import parse_jump_command
        from cli_app.runner import reload_agent_conversation
        from sessions.summarizer import generate_branch_summary

        # If it's a command string, parse it; otherwise use directly
        if command_or_id.startswith("/jump"):
            target_id = parse_jump_command(command_or_id)
        else:
            target_id = command_or_id

        if not target_id:
            self.conversation.add_system_message("Usage: /jump <entry_id>", style="yellow")
            return

        try:
            plan = self.session_manager.plan_navigation(target_id)
            choice = await self.ask_branch_navigation(plan)

            if choice == BranchNavigationChoice.CANCEL:
                self.conversation.add_system_message("Jump cancelled.", style="yellow")
                return

            if choice == BranchNavigationChoice.SUMMARIZE:
                self.conversation.add_system_message("Summarizing branch before jump...", style="yellow")
                summary = generate_branch_summary(plan)
                self.session_manager.branch_to_with_summary(target_id, summary=summary)
            else:
                self.session_manager.branch_to(target_id)

            if self.agent:
                reload_agent_conversation(self.agent, self.session_manager)

            self.conversation.clear_history()
            self.load_session_history()
            self.conversation.add_system_message(
                f"Jumped to: {self.session_manager.get_leaf_id()}",
                style="green",
            )
            self._refresh_tree_panel()
        except KeyError:
            self.conversation.add_system_message(f"Entry not found: {target_id}", style="red")
        except Exception as e:
            self.conversation.add_system_message(f"Jump failed: {e}", style="red")

    def action_cancel(self) -> None:
        """Handle Ctrl+C - cancel current task."""
        if self.current_worker and self.current_worker.state == WorkerState.RUNNING:
            self.cancel_event.set()
            if self.agent:
                self.agent.cancel()
            self.conversation.add_system_message("⚠️ Cancelling task...", style="yellow")
        else:
            self.conversation.add_system_message("⚠️ No active task to cancel", style="dim yellow")

    def action_clear(self) -> None:
        """Handle Ctrl+L - clear display."""
        self.conversation.clear_history()

    def action_quit(self) -> None:
        """Handle Ctrl+Q - quit application."""
        self.exit()

    def action_toggle_tree(self) -> None:
        """Handle Ctrl+T - toggle session tree sidebar."""
        tree_panel = self.session_tree
        # Toggle display
        if tree_panel.styles.display == "none":
            tree_panel.styles.display = "block"
            self.conversation.add_system_message("Session tree shown (Ctrl+T to hide)", style="cyan")
        else:
            tree_panel.styles.display = "none"
            self.conversation.add_system_message("Session tree hidden", style="cyan")

    async def ask_approval(self, tool_name: str, risk: str, arguments: dict) -> dict:
        """Show approval modal and wait for user decision.

        Args:
            tool_name: Name of the tool to execute
            risk: Risk level description
            arguments: Tool arguments

        Returns:
            dict with keys:
                - "decision": "y" | "n" | "c"
                - "advice": str (only when decision is "c")
        """
        from ui.textual_modals import ApprovalModal

        result = await self.push_screen_wait(ApprovalModal(tool_name, risk, arguments))
        return result if result else {"decision": "n", "advice": ""}

    async def ask_branch_navigation(self, plan=None) -> BranchNavigationChoice:
        """Show branch navigation modal and wait for user choice.

        Args:
            plan: Optional Plan object with target information

        Returns:
            BranchNavigationChoice: DIRECT | SUMMARIZE | CANCEL
        """
        from ui.textual_modals import BranchNavigationModal

        result = await self.push_screen_wait(BranchNavigationModal(plan))
        return result if result else BranchNavigationChoice.CANCEL

    def _refresh_tree_panel(self) -> None:
        if not self.session_manager:
            return
        all_entries = self.session_manager.all_entries()
        current_leaf = self.session_manager.get_leaf_id()
        self.session_tree.build_tree(all_entries, current_leaf)


def run_tui(
    session_manager: SessionManager | None = None,
    agent: ReactAgent | None = None,
    runtime=None,
    long_term=None,
) -> None:
    """Entry point to run the TUI."""
    app = PaiCLIApp(
        session_manager=session_manager,
        agent=agent,
        runtime=runtime,
        long_term=long_term,
    )
    app.run()


if __name__ == "__main__":
    run_tui()
