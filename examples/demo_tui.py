"""Textual TUI demo - standalone test without full session manager."""
from pathlib import Path
from ui.textual_app import PaiCLIApp, run_tui


def demo_without_session():
    """Run TUI without session manager for UI testing."""
    print("Starting Textual TUI demo...")
    print("Press Ctrl+Q to quit, Ctrl+L to clear, type /help for commands")
    run_tui(session_manager=None)


def demo_with_mock_session():
    """Run TUI with a mock session for testing."""
    from sessions.manager import SessionManager
    from sessions.types import SessionMeta

    # Create a temporary session
    session_dir = Path("E:/fastproject/pythonProject4/.sessions/demo_tui")
    session_dir.mkdir(parents=True, exist_ok=True)

    meta = SessionMeta(
        version=1,
        session_id="demo_tui",
        title="TUI Demo Session",
        created_at="2026-05-30T00:00:00Z",
        updated_at="2026-05-30T00:00:00Z",
        message_count=0,
    )

    manager = SessionManager(
        path=session_dir,
        cwd=Path.cwd(),
        meta=meta,
    )

    # Add some demo messages
    from llm.types import Message

    manager.append_message(Message(role="user", content="Hello, this is a test message!"))
    manager.append_message(Message(role="assistant", content="Hello! This is a **demo** response with *markdown* support.\n\n- Item 1\n- Item 2\n- Item 3"))
    manager.append_message(Message(role="user", content="Can you show me a code example?"))
    manager.append_message(Message(role="assistant", content="Sure! Here's a Python example:\n\n```python\ndef hello():\n    print('Hello, World!')\n```"))

    print("Starting Textual TUI with mock session...")
    print("Press Ctrl+Q to quit, Ctrl+L to clear, type /help for commands")
    run_tui(session_manager=manager)


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--mock":
        demo_with_mock_session()
    else:
        demo_without_session()
