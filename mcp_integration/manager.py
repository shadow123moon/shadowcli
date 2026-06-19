"""MCP 服务器管理器 - 后台 event loop + 同步接口"""
from __future__ import annotations
import asyncio
import logging
import threading
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Any, Callable

from .config import McpServerConfig
from .transports import open_mcp_transport

log = logging.getLogger(__name__)


class McpServerManager:
    """MCP 服务器管理器

    设计要点:
    - 内部维护后台 event loop
    - 持有 ClientSession 生命周期
    - 对外提供同步接口
    """

    def __init__(
        self,
        *,
        transport_factory: Callable[[McpServerConfig], Any] = open_mcp_transport,
        session_factory: Callable[[Any, Any], Any] | None = None,
    ):
        self.servers: dict[str, Any] = {}  # name -> ClientSession
        self.exit_stacks: dict[str, Any] = {}  # name -> AsyncExitStack，仅用于状态观察
        self.server_tasks: dict[str, asyncio.Task] = {}
        self.stop_events: dict[str, asyncio.Event] = {}
        self.transport_factory = transport_factory
        self.session_factory = session_factory

        # 后台 event loop
        self.loop: asyncio.AbstractEventLoop | None = None
        self.loop_thread: threading.Thread | None = None
        self._loop_ready = threading.Event()

    def start_background_loop(self):
        """启动后台 event loop"""
        if self.loop is not None and self.loop_thread and self.loop_thread.is_alive():
            return

        self.loop = None
        self._loop_ready.clear()

        def run_loop():
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self._loop_ready.set()
            self.loop.run_forever()

        self.loop_thread = threading.Thread(target=run_loop, daemon=True, name="mcp-event-loop")
        self.loop_thread.start()

        self._loop_ready.wait(timeout=5)
        if self.loop is None:
            raise RuntimeError("MCP event loop failed to start")

    def start_server_sync(self, name: str, config: McpServerConfig) -> list[dict]:
        """同步启动一个 MCP server,返回工具列表"""
        if self.loop is None:
            self.start_background_loop()

        coro = self._start_server(name, config)
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        return future.result(timeout=60)  # initialize 超时 60 秒

    async def _start_server(self, name: str, config: McpServerConfig) -> list[dict]:
        """异步启动 server(内部实现)"""
        if name in self.server_tasks:
            raise RuntimeError(f"MCP server '{name}' already started")

        ready: asyncio.Future[list[dict]] = asyncio.get_running_loop().create_future()
        task = asyncio.create_task(
            self._server_main(name, config, ready),
            name=f"mcp-server-{name}",
        )
        self.server_tasks[name] = task

        try:
            return await ready
        except Exception:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            finally:
                self.server_tasks.pop(name, None)
            raise

    async def _server_main(
        self,
        name: str,
        config: McpServerConfig,
        ready: asyncio.Future[list[dict]],
    ) -> None:
        """在同一个 task 内 enter 和 exit MCP session 生命周期。"""
        from contextlib import AsyncExitStack
        from mcp import ClientSession

        try:
            async with AsyncExitStack() as stack:
                self.exit_stacks[name] = stack

                read, write = await stack.enter_async_context(
                    self.transport_factory(config)
                )

                # 创建 session
                session_factory = self.session_factory or ClientSession
                session = await stack.enter_async_context(
                    session_factory(read, write)
                )

                # 初始化
                await session.initialize()

                self.servers[name] = session
                stop_event = asyncio.Event()
                self.stop_events[name] = stop_event
                log.debug("MCP server '%s' started", name)

                # 获取工具列表
                result = await session.list_tools()
                tools = [
                    {
                        "name": tool.name,
                        "description": tool.description or "",
                        "inputSchema": tool.inputSchema or {},
                    }
                    for tool in result.tools
                ]
                if not ready.done():
                    ready.set_result(tools)

                await stop_event.wait()
        except Exception as e:
            if ready.done():
                log.exception("MCP server '%s' failed", name)
            if not ready.done():
                ready.set_exception(e)
        finally:
            self.servers.pop(name, None)
            self.exit_stacks.pop(name, None)
            self.stop_events.pop(name, None)
            log.debug("MCP server '%s' closed", name)

    def call_tool_sync(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict,
        timeout: int = 60,
    ) -> str:
        """同步调用 MCP 工具"""
        if self.loop is None:
            raise RuntimeError("Manager not started")

        coro = self._call_tool(server_name, tool_name, arguments)
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        return future.result(timeout=timeout)

    async def _call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict,
    ) -> str:
        """异步调用工具(内部实现)"""
        session = self.servers.get(server_name)
        if session is None:
            raise RuntimeError(f"MCP server '{server_name}' not started")

        result = await session.call_tool(tool_name, arguments=arguments)

        # 合并多个 content 块
        parts = []
        for content in result.content:
            text = getattr(content, "text", None)
            if text is not None:
                parts.append(str(text))
                continue

            content_type = getattr(content, "type", None)
            if content_type == "image":
                # Phase 1 暂时忽略图片
                parts.append(f"[图片: {getattr(content, 'mimeType', 'unknown')}]")
                continue

            label = content_type or content.__class__.__name__
            parts.append(f"[未支持的 MCP 内容: {label}]")

        return "\n".join(parts) if parts else ""

    def shutdown(self):
        """关闭所有 server"""
        if self.loop is None:
            return

        async def cleanup():
            for event in list(self.stop_events.values()):
                event.set()

            tasks = list(self.server_tasks.values())
            if tasks:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for name, result in zip(list(self.server_tasks.keys()), results):
                    if isinstance(result, Exception):
                        log.error(f"Error closing '{name}': {result}")
            self.server_tasks.clear()
            self.servers.clear()
            self.exit_stacks.clear()
            self.stop_events.clear()

        try:
            future = asyncio.run_coroutine_threadsafe(cleanup(), self.loop)
            future.result(timeout=10)
        except FutureTimeoutError:
            log.error("Error during shutdown: timeout")
        except Exception:
            log.exception("Error during shutdown")

        try:
            self.loop.call_soon_threadsafe(self.loop.stop)
        except Exception:
            pass

        if self.loop_thread and self.loop_thread.is_alive():
            self.loop_thread.join(timeout=5)

        loop = self.loop
        if loop is not None and not loop.is_closed():
            try:
                loop.close()
            except Exception:
                log.exception("Error closing MCP event loop")

        self.loop = None
        self.loop_thread = None
        self._loop_ready.clear()
