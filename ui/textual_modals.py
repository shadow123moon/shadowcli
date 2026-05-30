"""Modal dialogs for Textual TUI - approval and branch navigation."""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static, TextArea

if TYPE_CHECKING:
    from sessions.manager import NavigationPlan

from ui.renderer import BranchNavigationChoice


class ApprovalModal(ModalScreen[dict]):
    """Modal for tool execution approval.

    Returns:
        dict with keys:
            - "decision": "y" | "n" | "c"
            - "advice": str (only when decision is "c")
    """

    CSS = """
    ApprovalModal {
        align: center middle;
    }

    #approval_dialog {
        width: 80;
        height: auto;
        max-height: 30;
        background: $panel;
        border: thick $primary;
        padding: 1 2;
    }

    #approval_title {
        width: 100%;
        text-align: center;
        color: $warning;
        text-style: bold;
        margin-bottom: 1;
    }

    #approval_content {
        width: 100%;
        height: auto;
        margin-bottom: 1;
    }

    #approval_buttons {
        width: 100%;
        height: auto;
        align: center middle;
    }

    #advice_container {
        width: 100%;
        height: auto;
        margin-top: 1;
        display: none;
    }

    #advice_container.visible {
        display: block;
    }

    #advice_input {
        width: 100%;
        height: 5;
        margin-top: 1;
    }

    .approval_button {
        margin: 0 1;
    }
    """

    BINDINGS = [
        ("y", "allow", "Allow"),
        ("n", "deny", "Deny"),
        ("c", "deny_with_advice", "Deny with advice"),
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, tool_name: str, risk: str, arguments: dict):
        super().__init__()
        self.tool_name = tool_name
        self.risk = risk
        self.arguments = arguments
        self.advice_mode = False

    def compose(self) -> ComposeResult:
        with Container(id="approval_dialog"):
            yield Label("🔒 Tool Execution Approval", id="approval_title")

            content_text = Text()
            content_text.append("Tool: ", style="bold cyan")
            content_text.append(f"{self.tool_name}\n", style="cyan")
            content_text.append("Risk: ", style="bold yellow")
            content_text.append(f"{self.risk}\n\n", style="yellow")
            content_text.append("Arguments:\n", style="bold")

            args_json = json.dumps(self.arguments, ensure_ascii=False, indent=2)
            if len(args_json) > 300:
                args_json = args_json[:300] + "\n..."
            content_text.append(args_json, style="dim")

            yield Static(content_text, id="approval_content")

            with Horizontal(id="approval_buttons"):
                yield Button("Allow (y)", id="btn_allow", variant="success", classes="approval_button")
                yield Button("Deny (n)", id="btn_deny", variant="error", classes="approval_button")
                yield Button("Deny with advice (c)", id="btn_advice", variant="warning", classes="approval_button")

            with Vertical(id="advice_container"):
                yield Label("Provide advice for the agent:", id="advice_label")
                yield TextArea(id="advice_input", language="markdown")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button clicks."""
        if event.button.id == "btn_allow":
            self.action_allow()
        elif event.button.id == "btn_deny":
            self.action_deny()
        elif event.button.id == "btn_advice":
            self.action_deny_with_advice()

    def action_allow(self) -> None:
        """Allow tool execution."""
        self.dismiss({"decision": "y", "advice": ""})

    def action_deny(self) -> None:
        """Deny tool execution."""
        self.dismiss({"decision": "n", "advice": ""})

    def action_deny_with_advice(self) -> None:
        """Toggle advice input or submit if already visible."""
        if not self.advice_mode:
            # Show advice input
            self.advice_mode = True
            advice_container = self.query_one("#advice_container")
            advice_container.add_class("visible")
            advice_input = self.query_one("#advice_input", TextArea)
            advice_input.focus()

            # Change button text
            btn_advice = self.query_one("#btn_advice", Button)
            btn_advice.label = "Submit advice (c)"
        else:
            # Submit advice
            advice_input = self.query_one("#advice_input", TextArea)
            advice_text = advice_input.text.strip()
            self.dismiss({"decision": "c", "advice": advice_text})

    def action_cancel(self) -> None:
        """Cancel approval (treat as deny)."""
        self.dismiss({"decision": "n", "advice": ""})


class BranchNavigationModal(ModalScreen[BranchNavigationChoice]):
    """Modal for branch navigation choice.

    Returns:
        BranchNavigationChoice: DIRECT | SUMMARIZE | CANCEL
    """

    CSS = """
    BranchNavigationModal {
        align: center middle;
    }

    #branch_dialog {
        width: 70;
        height: auto;
        background: $panel;
        border: thick $secondary;
        padding: 1 2;
    }

    #branch_title {
        width: 100%;
        text-align: center;
        color: $accent;
        text-style: bold;
        margin-bottom: 1;
    }

    #branch_content {
        width: 100%;
        height: auto;
        margin-bottom: 1;
    }

    #branch_buttons {
        width: 100%;
        height: auto;
        align: center middle;
    }

    .branch_button {
        margin: 0 1;
    }
    """

    BINDINGS = [
        ("1", "direct", "Direct"),
        ("2", "summarize", "Summarize"),
        ("3", "cancel", "Cancel"),
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, plan: NavigationPlan | None = None):
        super().__init__()
        self.plan = plan

    def compose(self) -> ComposeResult:
        with Container(id="branch_dialog"):
            yield Label("🌿 Branch Navigation", id="branch_title")

            content_text = Text()
            content_text.append("A branch point has been detected.\n\n", style="bold")

            if self.plan:
                content_text.append("From: ", style="bold cyan")
                content_text.append(f"{self.plan.from_id or '(root)'}\n", style="cyan")
                content_text.append("To: ", style="bold cyan")
                content_text.append(f"{self.plan.to_id or '(root)'}\n", style="cyan")
                content_text.append("Leaving entries: ", style="bold")
                content_text.append(f"{len(self.plan.leaving_entries)}\n\n", style="dim")

            content_text.append("Choose navigation strategy:\n", style="bold")
            content_text.append("1. ", style="bold green")
            content_text.append("Direct - Jump directly to target node\n", style="green")
            content_text.append("2. ", style="bold yellow")
            content_text.append("Summarize - Generate summary of abandoned branch\n", style="yellow")
            content_text.append("3. ", style="bold red")
            content_text.append("Cancel - Stay at current position", style="red")

            yield Static(content_text, id="branch_content")

            with Horizontal(id="branch_buttons"):
                yield Button("Direct (1)", id="btn_direct", variant="success", classes="branch_button")
                yield Button("Summarize (2)", id="btn_summarize", variant="warning", classes="branch_button")
                yield Button("Cancel (3)", id="btn_cancel", variant="error", classes="branch_button")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button clicks."""
        if event.button.id == "btn_direct":
            self.action_direct()
        elif event.button.id == "btn_summarize":
            self.action_summarize()
        elif event.button.id == "btn_cancel":
            self.action_cancel()

    def action_direct(self) -> None:
        """Choose direct navigation."""
        self.dismiss(BranchNavigationChoice.DIRECT)

    def action_summarize(self) -> None:
        """Choose summarize navigation."""
        self.dismiss(BranchNavigationChoice.SUMMARIZE)

    def action_cancel(self) -> None:
        """Cancel navigation."""
        self.dismiss(BranchNavigationChoice.CANCEL)
