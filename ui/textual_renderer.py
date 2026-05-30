"""Textual-based renderer implementation."""
from __future__ import annotations

from typing import TYPE_CHECKING

from ui.renderer import BranchNavigationChoice, Renderer

if TYPE_CHECKING:
    from ui.textual_app import PaiCLIApp


class TextualRenderer(Renderer):
    """Renderer that bridges agent events to Textual TUI.

    This renderer is used when the agent runs inside a Textual app,
    allowing interactive modals for approval and branch navigation.
    """

    def __init__(self, app: PaiCLIApp):
        """Initialize with reference to the Textual app.

        Args:
            app: PaiCLIApp instance for pushing modals
        """
        self.app = app

    def message(self, message: str) -> None:
        """Display a system message in the conversation panel.

        Args:
            message: Message text to display
        """
        self.app.conversation.add_system_message(message, style="cyan")

    def agent_event(self, event, *, agent_name: str = "react") -> None:
        """Handle agent events (tool calls, results, etc).

        Args:
            event: StreamEvent from agent execution
            agent_name: Name of the agent (for display)
        """
        # Events are already handled by PaiCLIApp._handle_stream_event
        # This method is here for protocol compliance
        pass

    def cancel_requested(self) -> None:
        """Signal that cancellation was requested."""
        self.app.conversation.add_system_message("⚠️ Cancellation requested", style="yellow")

    def branch_navigation_choice(self, plan=None) -> BranchNavigationChoice:
        """Prompt user for branch navigation strategy.

        Textual modal prompts are asynchronous. The TUI app handles branch
        navigation directly with ``await app.ask_branch_navigation(...)``;
        this synchronous protocol method is only a defensive fallback.

        Args:
            plan: Optional Plan object with target information

        Returns:
            BranchNavigationChoice: User's choice
        """
        self.app.conversation.add_system_message(
            "Branch navigation requires the async TUI flow; cancelled.",
            style="yellow",
        )
        return BranchNavigationChoice.CANCEL

    async def ask_approval_async(self, tool_name: str, risk: str, arguments: dict) -> dict:
        """Async version of approval prompt for use in async contexts.

        Args:
            tool_name: Name of the tool to execute
            risk: Risk level description
            arguments: Tool arguments

        Returns:
            dict with keys:
                - "decision": "y" | "n" | "c"
                - "advice": str (only when decision is "c")
        """
        return await self.app.ask_approval(tool_name, risk, arguments)
