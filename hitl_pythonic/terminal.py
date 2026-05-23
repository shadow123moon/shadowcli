"""终端 HITL 实现。

对照 Java com.paicli.hitl.TerminalHitlHandler 的取舍：
- Java 用 synchronized 整体方法 ↔ Python threading.Lock
- Java BufferedReader / PrintStream ↔ Python TextIO（可注入测试用 StringIO）
- 修改参数：Java 解析 JsonNode；Python 用 json.loads 并要求 dict
- 失败保守拒绝（fail-safe）：EOF / 5 次无效输入 → 拒绝
"""
from __future__ import annotations

import json
import sys
import threading
from typing import TextIO

from .request import ApprovalRequest
from .result import ApprovalResult

_MAX_RETRIES = 5


class TerminalHitlHandler:
    """通过 stdin/stdout 与用户交互的 HITL 处理器。"""

    def __init__(
        self,
        enabled: bool = False,
        stdin: TextIO | None = None,
        stdout: TextIO | None = None,
    ) -> None:
        self.enabled = enabled
        self._stdin = stdin if stdin is not None else sys.stdin
        self._stdout = stdout if stdout is not None else sys.stdout
        self._approved_tools: set[str] = set()
        self._approved_servers: set[str] = set()
        self._lock = threading.Lock()

    # ---------- HitlHandler 接口 ----------
    def request_approval(self, request: ApprovalRequest) -> ApprovalResult:
        with self._lock:
            return self._do_request(request)

    def is_approved_all_by_tool(self, tool_name: str) -> bool:
        return tool_name in self._approved_tools

    def is_approved_all_by_server(self, server_name: str | None) -> bool:
        return server_name is not None and server_name in self._approved_servers

    def clear_approved_all(self) -> None:
        self._approved_tools.clear()
        self._approved_servers.clear()

    def clear_approved_all_for_server(self, server_name: str) -> None:
        self._approved_servers.discard(server_name)

    # ---------- 内部 ----------
    def _do_request(self, request: ApprovalRequest) -> ApprovalResult:
        sensitive = bool(request.sensitive_notice)
        server = request.mcp_server

        if not sensitive and self.is_approved_all_by_tool(request.tool_name):
            self._println(
                f"  [HITL] {request.tool_name} 已在本次会话中全部放行，自动通过"
            )
            return ApprovalResult.approve_all()
        if not sensitive and self.is_approved_all_by_server(server):
            self._println(
                f"  [HITL] MCP server {server} 已在本次会话中全部放行，自动通过"
            )
            return ApprovalResult.approve_all_by_server()

        self._println("")
        self._println("────────── ⚠️  HITL 审批请求 ──────────")
        if sensitive:
            self._println(f"⚠️  {request.sensitive_notice}")
        self._println(request.to_display_text())

        return self._prompt_until_decision(request, sensitive)

    def _prompt_until_decision(
        self, request: ApprovalRequest, sensitive: bool
    ) -> ApprovalResult:
        for _ in range(_MAX_RETRIES):
            self._println("")
            if sensitive:
                self._println(
                    "请选择操作：[y/Enter] 批准本次  [n] 拒绝  [s] 跳过  [m] 修改参数"
                )
            else:
                self._println(
                    "请选择操作：[y/Enter] 批准  [a] 全部放行  [n] 拒绝  [s] 跳过  [m] 修改参数"
                )

            line = self._read_line("> ")
            if line is None:
                self._println("  [HITL] 输入流已关闭，保守处理为拒绝")
                return ApprovalResult.reject("输入流已关闭")

            choice = line.strip().lower()
            if choice in {"", "y"}:
                self._println("  已批准")
                return ApprovalResult.approve()
            if choice == "a":
                if sensitive:
                    self._println("  敏感页面操作不支持全部放行，请选择 y/n/s/m")
                    continue
                return self._prompt_approve_all_scope(request)
            if choice == "n":
                reason = self._read_line("  拒绝原因（可直接回车跳过）：") or ""
                return ApprovalResult.reject(reason.strip())
            if choice == "s":
                self._println("  已跳过本次操作")
                return ApprovalResult.skip()
            if choice == "m":
                modified = self._prompt_modified_arguments(request)
                if modified is not None:
                    return modified
                continue
            self._println(
                f"  ❓ 无法识别的选项：'{line}'，请输入 y/a/n/s/m 之一（Enter 等价于 y）"
            )

        self._println("  [HITL] 连续多次无效输入，保守处理为拒绝")
        return ApprovalResult.reject("连续多次无效输入")

    def _prompt_approve_all_scope(self, request: ApprovalRequest) -> ApprovalResult:
        server = request.mcp_server
        if not server:
            self._approved_tools.add(request.tool_name)
            self._println(f"  已批准，后续 {request.tool_name} 操作将自动通过")
            return ApprovalResult.approve_all()

        self._println("  全部放行范围：")
        self._println(f"  [tool / Enter] 仅本工具 {request.tool_name}")
        self._println(
            f"  [server]       整个 MCP server {server}（连续浏览器操作推荐）"
        )
        scope = (self._read_line("> ") or "").strip().lower()
        if scope in {"server", "s"}:
            self._approved_servers.add(server)
            self._println(
                f"  已批准，后续 MCP server {server} 的工具调用将自动通过"
            )
            return ApprovalResult.approve_all_by_server()
        self._approved_tools.add(request.tool_name)
        self._println(f"  已批准，后续 {request.tool_name} 操作将自动通过")
        return ApprovalResult.approve_all()

    def _prompt_modified_arguments(
        self, request: ApprovalRequest
    ) -> ApprovalResult | None:
        """JSON 合法 → 返回 modify；空输入 → 直接 approve；非法 → 返回 None 让主循环重试。"""
        self._println(
            f"  当前参数：{json.dumps(request.arguments, ensure_ascii=False)}"
        )
        line = self._read_line(
            "  请输入修改后的参数（JSON 格式，空行则使用原始参数）："
        )
        if line is None or not line.strip():
            self._println("  输入为空，改为批准原始参数")
            return ApprovalResult.approve()
        try:
            parsed = json.loads(line.strip())
        except json.JSONDecodeError as e:
            self._println(f"  ❌ 修改后的参数不是合法 JSON：{e}")
            return None
        if not isinstance(parsed, dict):
            self._println("  ❌ 修改后的参数必须是 JSON 对象")
            return None
        return ApprovalResult.modify(parsed)

    # ---------- I/O ----------
    def _println(self, text: str) -> None:
        print(text, file=self._stdout, flush=True)

    def _read_line(self, prompt: str) -> str | None:
        print(prompt, end="", file=self._stdout, flush=True)
        line = self._stdin.readline()
        if not line:
            return None  # EOF
        return line.rstrip("\r\n")
