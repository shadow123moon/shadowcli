"""MCP transport adapters."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from .config import McpServerConfig


@asynccontextmanager
async def open_mcp_transport(config: McpServerConfig) -> AsyncIterator[tuple[object, object]]:
    transport = (config.transport or "stdio").lower()
    if transport == "stdio":
        async with _open_stdio_transport(config) as streams:
            yield streams
        return
    if transport in {"http", "streamable_http", "streamable-http"}:
        async with _open_streamable_http_transport(config) as streams:
            yield streams
        return
    raise ValueError(f"Unsupported MCP transport: {config.transport}")


@asynccontextmanager
async def _open_stdio_transport(config: McpServerConfig) -> AsyncIterator[tuple[object, object]]:
    if not config.command:
        raise ValueError("stdio MCP server requires command")

    from mcp import StdioServerParameters
    from mcp.client.stdio import stdio_client

    server_params = StdioServerParameters(
        command=config.command,
        args=config.args,
        env=config.env,
    )
    async with stdio_client(server_params) as streams:
        read, write = streams
        yield read, write


@asynccontextmanager
async def _open_streamable_http_transport(config: McpServerConfig) -> AsyncIterator[tuple[object, object]]:
    if not config.url:
        raise ValueError("http MCP server requires url")

    try:
        import httpx
        from mcp.client.streamable_http import streamable_http_client
    except ImportError as exc:
        raise RuntimeError("Installed mcp package does not provide streamable HTTP transport") from exc

    async with httpx.AsyncClient(headers=config.headers or None) as client:
        async with streamable_http_client(config.url, http_client=client) as streams:
            read, write, *_ = streams
            yield read, write
