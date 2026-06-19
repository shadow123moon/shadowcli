import asyncio
import logging
import socket
import threading
import time
import unittest
import warnings
from contextlib import asynccontextmanager
from unittest.mock import patch
from types import SimpleNamespace

from mcp_integration.config import McpServerConfig
from mcp_integration.manager import McpServerManager
from mcp_integration.transports import open_mcp_transport


class McpConfigTests(unittest.TestCase):
    def test_stdio_config_defaults_to_stdio_transport(self):
        config = McpServerConfig.from_dict({
            "command": "npx",
            "args": ["-y", "server"],
            "env": {"A": "B"},
        })

        self.assertEqual(config.transport, "stdio")
        self.assertEqual(config.command, "npx")
        self.assertEqual(config.args, ["-y", "server"])
        self.assertEqual(config.env, {"A": "B"})
        self.assertEqual(config.url, "")
        self.assertEqual(config.headers, {})

    def test_http_config_accepts_url_and_headers(self):
        config = McpServerConfig.from_dict({
            "transport": "http",
            "url": "http://localhost:3333/mcp",
            "headers": {"Authorization": "Bearer token"},
        })

        self.assertEqual(config.transport, "http")
        self.assertEqual(config.url, "http://localhost:3333/mcp")
        self.assertEqual(config.headers, {"Authorization": "Bearer token"})
        self.assertEqual(config.command, "")
        self.assertEqual(config.args, [])
        self.assertEqual(config.env, {})


class McpManagerTransportTests(unittest.TestCase):
    def test_start_server_uses_configured_transport_factory(self):
        async def run():
            opened = []

            @asynccontextmanager
            async def fake_transport(config):
                opened.append(config)
                yield "read-stream", "write-stream"

            class FakeSession:
                def __init__(self, read, write):
                    self.read = read
                    self.write = write
                    self.initialized = False

                async def __aenter__(self):
                    return self

                async def __aexit__(self, *_exc):
                    return None

                async def initialize(self):
                    self.initialized = True

                async def list_tools(self):
                    return SimpleNamespace(tools=[
                        SimpleNamespace(
                            name="search",
                            description="Search docs",
                            inputSchema={"type": "object"},
                        )
                    ])

            config = McpServerConfig.from_dict({
                "transport": "http",
                "url": "http://localhost:3333/mcp",
            })
            manager = McpServerManager(
                transport_factory=fake_transport,
                session_factory=FakeSession,
            )

            tools = await manager._start_server("docs", config)
            try:
                self.assertEqual(opened, [config])
                self.assertEqual(tools, [{
                    "name": "search",
                    "description": "Search docs",
                    "inputSchema": {"type": "object"},
                }])
                self.assertIn("docs", manager.servers)
            finally:
                manager.stop_events["docs"].set()
                await manager.server_tasks["docs"]

        asyncio.run(run())


class McpHttpTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_http_transport_manages_client_for_empty_headers_too(self):
        clients = []

        @asynccontextmanager
        async def fake_streamable_http_client(url, *, http_client):
            self.assertEqual(url, "http://localhost:3333/mcp")
            self.assertIsNotNone(http_client)
            self.assertFalse(http_client.is_closed)
            clients.append(http_client)
            yield "read-stream", "write-stream", lambda: "session-id"
            self.assertFalse(http_client.is_closed)

        config = McpServerConfig.from_dict({
            "transport": "http",
            "url": "http://localhost:3333/mcp",
        })

        with patch("mcp.client.streamable_http.streamable_http_client", fake_streamable_http_client):
            async with open_mcp_transport(config) as streams:
                self.assertEqual(streams, ("read-stream", "write-stream"))

        self.assertEqual(len(clients), 1)
        self.assertTrue(clients[0].is_closed)


class McpToolResultFormattingTests(unittest.IsolatedAsyncioTestCase):
    async def test_call_tool_keeps_unknown_content_as_placeholder(self):
        class FakeSession:
            async def call_tool(self, tool_name, arguments):
                return SimpleNamespace(content=[
                    SimpleNamespace(type="resource", uri="file:///tmp/result.txt")
                ])

        manager = McpServerManager()
        manager.servers["docs"] = FakeSession()

        result = await manager._call_tool("docs", "fetch", {"id": "1"})

        self.assertIn("resource", result)
        self.assertNotEqual(result, "")


class McpRealHttpIntegrationTests(unittest.TestCase):
    def test_manager_loads_and_calls_real_streamable_http_server(self):
        warnings.filterwarnings("ignore", category=DeprecationWarning, module="websockets")
        warnings.filterwarnings("ignore", category=DeprecationWarning, module="uvicorn")
        warnings.filterwarnings("ignore", category=ResourceWarning, module="anyio.streams.memory")

        from mcp.server.fastmcp import FastMCP
        import uvicorn

        port = _free_port()
        app = FastMCP("shadowcli-test-http", host="127.0.0.1", port=port, log_level="ERROR")

        @app.tool()
        def echo(text: str) -> str:
            return f"echo:{text}"

        server = uvicorn.Server(
            uvicorn.Config(
                app.streamable_http_app(),
                host="127.0.0.1",
                port=port,
                log_level="error",
            )
        )
        thread = threading.Thread(target=server.run, name="test-http-mcp", daemon=True)
        thread.start()
        _wait_for_port(port)

        manager = McpServerManager()
        config = McpServerConfig.from_dict({
            "transport": "http",
            "url": f"http://127.0.0.1:{port}/mcp",
        })
        asyncio_logger = logging.getLogger("asyncio")
        previous_asyncio_level = asyncio_logger.level
        asyncio_logger.setLevel(logging.CRITICAL)
        try:
            tools = manager.start_server_sync("local_http", config)
            self.assertIn("echo", [tool["name"] for tool in tools])

            result = manager.call_tool_sync(
                "local_http",
                "echo",
                {"text": "hello"},
                timeout=10,
            )

            self.assertIn("echo:hello", result)
        finally:
            manager.shutdown()
            server.should_exit = True
            thread.join(timeout=5)
            asyncio_logger.setLevel(previous_asyncio_level)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_port(port: int, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.2)
            try:
                sock.connect(("127.0.0.1", port))
                return
            except OSError:
                time.sleep(0.05)
    raise TimeoutError(f"HTTP MCP server did not start on port {port}")
