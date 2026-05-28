"""Probe lifecycle with the real filesystem MCP server via npx."""
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

    config = McpServerConfig(
        command="npx",
        args=["-y", "@modelcontextprotocol/server-filesystem", str(ROOT)],
        env={},
        disabled=False,
    )

    manager = McpServerManager()
    print("starting filesystem server")
    tools = manager.start_server_sync("filesystem", config)
    print("tool_count=", len(tools))
    print("first_tools=", [tool["name"] for tool in tools[:8]])
    print("servers_before_call=", list(manager.servers.keys()))
    print("thread_alive_before_call=", bool(manager.loop_thread and manager.loop_thread.is_alive()))

    result = manager.call_tool_sync(
        "filesystem",
        "list_directory",
        {"path": str(ROOT)},
    )
    lines = result.splitlines()
    print("list_directory_first_lines=", lines[:10])
    print("list_directory_line_count=", len(lines))

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
