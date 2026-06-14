"""Minimal stdio MCP server used by lifecycle probes."""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP


server = FastMCP("shadowcli-lifecycle-test")


@server.tool()
def echo(text: str) -> str:
    """Return the provided text."""
    return f"echo:{text}"


@server.tool()
def add(left: int, right: int) -> int:
    """Add two integers."""
    return left + right


if __name__ == "__main__":
    server.run("stdio")
