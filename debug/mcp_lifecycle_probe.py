"""Probe MCP start -> list_tools -> call_tool -> shutdown lifecycle."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp_integration.config import McpServerConfig
from mcp_integration.manager import McpServerManager


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")

    server_script = ROOT / "debug" / "mcp_echo_server.py"
    config = McpServerConfig(
        command=sys.executable,
        args=[str(server_script)],
        env={},
        disabled=False,
    )

    manager = McpServerManager()
    print("starting")
    tools = manager.start_server_sync("echo", config)
    print("tools=", [tool["name"] for tool in tools])
    print("servers_before_call=", list(manager.servers.keys()))
    print("thread_alive_before_call=", bool(manager.loop_thread and manager.loop_thread.is_alive()))

    echo_result = manager.call_tool_sync("echo", "echo", {"text": "hello lifecycle"})
    add_result = manager.call_tool_sync("echo", "add", {"left": 2, "right": 3})
    print("echo_result=", echo_result)
    print("add_result=", add_result)

    print("shutdown")
    manager.shutdown()
    print("servers_after_shutdown=", list(manager.servers.keys()))
    print("stacks_after_shutdown=", list(manager.exit_stacks.keys()))
    print("tasks_after_shutdown=", list(manager.server_tasks.keys()))
    print("loop_after_shutdown=", manager.loop)
    print("thread_alive_after_shutdown=", bool(manager.loop_thread and manager.loop_thread.is_alive()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
