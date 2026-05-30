"""Example: Integrating TextualRenderer with agent runtime for approval hooks.

This demonstrates how to:
1. Create a PaiCLIApp with TextualRenderer
2. Hook approval requests to show modal dialogs
3. Handle branch navigation with interactive prompts
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from agent.agent_loop import AgentLoop
from llm import Message
from sessions.manager import SessionManager
from ui.textual_app import PaiCLIApp
from ui.textual_renderer import TextualRenderer

if TYPE_CHECKING:
    from planning.plan import Plan


class ApprovalHook:
    """Hook for intercepting tool execution and requesting approval."""

    def __init__(self, renderer: TextualRenderer):
        self.renderer = renderer

    async def on_before_execute(self, tool_name: str, arguments: dict) -> dict:
        """Called before tool execution to request approval.

        Args:
            tool_name: Name of the tool to execute
            arguments: Tool arguments

        Returns:
            dict with keys:
                - "approved": bool
                - "advice": str (optional feedback to agent)
        """
        # Determine risk level based on tool name
        risk = self._assess_risk(tool_name, arguments)

        if risk == "LOW":
            # Auto-approve low-risk tools
            return {"approved": True, "advice": ""}

        # Show approval modal for medium/high risk
        result = await self.renderer.ask_approval_async(tool_name, risk, arguments)

        decision = result.get("decision", "n")
        advice = result.get("advice", "")

        if decision == "y":
            return {"approved": True, "advice": ""}
        elif decision == "c":
            return {"approved": False, "advice": advice}
        else:
            return {"approved": False, "advice": "User denied execution"}

    def _assess_risk(self, tool_name: str, arguments: dict) -> str:
        """Assess risk level of a tool call.

        Returns:
            "LOW" | "MEDIUM" | "HIGH"
        """
        # High-risk tools
        high_risk_tools = {
            "execute_command",
            "write_file",
            "delete_file",
            "git_push",
            "deploy",
        }

        # Medium-risk tools
        medium_risk_tools = {
            "edit_file",
            "create_file",
            "git_commit",
        }

        if tool_name in high_risk_tools:
            return "HIGH"
        elif tool_name in medium_risk_tools:
            return "MEDIUM"
        else:
            return "LOW"


class IntegratedPaiCLIApp(PaiCLIApp):
    """Extended PaiCLIApp with approval hooks integrated."""

    def __init__(self, session_manager: SessionManager | None = None, agent: AgentLoop | None = None):
        super().__init__(session_manager, agent)
        self.textual_renderer = TextualRenderer(self)
        self.approval_hook = ApprovalHook(self.textual_renderer)

    async def _agent_worker(self, user_input: str) -> None:
        """Override worker to integrate approval hooks."""
        from llm import Message

        def run_agent():
            """Run agent with approval hooks."""
            task = Message(role="user", content=user_input)
            try:
                # In a real implementation, you'd pass the approval hook to the agent
                # For now, this demonstrates the structure
                for event in self.agent.execute(task):
                    if self.cancel_event.is_set():
                        break

                    # Check if this is a tool call that needs approval
                    if event.type == "tool_call_start":
                        tool_name = event.data.get("name", "unknown")
                        try:
                            import json
                            args = json.loads(event.data.get("args", "{}"))
                        except json.JSONDecodeError:
                            args = {}

                        # Request approval (this would need to be async in real impl)
                        # For now, just bridge the event
                        self.call_from_thread(self._handle_stream_event, event)
                    else:
                        self.call_from_thread(self._handle_stream_event, event)

            except Exception as exc:
                from llm.client import StreamEvent
                error_event = StreamEvent("error", str(exc))
                self.call_from_thread(self._handle_stream_event, error_event)

        import asyncio
        await asyncio.to_thread(run_agent)


def run_integrated_tui():
    """Run the integrated TUI with approval hooks."""
    # Create session manager
    session_manager = SessionManager()

    # Create agent (simplified - would need proper initialization)
    # agent = AgentLoop(...)

    # Create and run app
    app = IntegratedPaiCLIApp(session_manager=session_manager, agent=None)
    app.run()


if __name__ == "__main__":
    run_integrated_tui()
