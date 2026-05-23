"""hitl_pythonic 烟雾测试。

风格与 tests/test_agent_execution.py 一致 —— 用标准库 unittest,不依赖 pytest。

跑法::

    python -m unittest tests.test_hitl -v
"""
from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

from hitl_pythonic import (
    ApprovalRequest,
    ApprovalResult,
    Decision,
    TerminalHitlHandler,
    danger_level,
    is_mcp_tool,
    mcp_server_name,
    requires_approval,
    with_hitl,
)
from tool_registry import ToolRegistry
from tools import ReadFileTool, WriteFileTool


# ---------- policy ----------
class TestPolicy(unittest.TestCase):
    def test_requires_approval_dangerous_tools(self):
        for name in ("write_file", "execute_command", "create_project", "revert_turn"):
            self.assertTrue(requires_approval(name), name)

    def test_requires_approval_safe_tools(self):
        for name in ("read_file", "list_dir", "search_code"):
            self.assertFalse(requires_approval(name), name)

    def test_requires_approval_all_mcp_tools(self):
        self.assertTrue(requires_approval("mcp__chrome__navigate"))
        self.assertTrue(requires_approval("mcp__github__create_issue"))

    def test_mcp_server_name(self):
        self.assertEqual(mcp_server_name("mcp__chrome__navigate"), "chrome")
        self.assertEqual(mcp_server_name("mcp__github__x"), "github")
        self.assertIsNone(mcp_server_name("write_file"))
        self.assertIsNone(mcp_server_name(None))
        self.assertIsNone(mcp_server_name(""))

    def test_is_mcp_tool(self):
        self.assertTrue(is_mcp_tool("mcp__x__y"))
        self.assertFalse(is_mcp_tool("write_file"))
        self.assertFalse(is_mcp_tool(None))

    def test_danger_level(self):
        self.assertIn("高危", danger_level("execute_command"))
        self.assertIn("高危", danger_level("revert_turn"))
        self.assertIn("中危", danger_level("write_file"))
        self.assertIn("MCP", danger_level("mcp__x__y"))
        self.assertIn("安全", danger_level("read_file"))


# ---------- ApprovalResult ----------
class TestApprovalResult(unittest.TestCase):
    def test_approve(self):
        r = ApprovalResult.approve()
        self.assertTrue(r.is_approved)
        self.assertFalse(r.is_rejected)
        self.assertFalse(r.is_skipped)

    def test_reject_carries_reason(self):
        r = ApprovalResult.reject("不安全")
        self.assertTrue(r.is_rejected)
        self.assertEqual(r.reason, "不安全")
        self.assertFalse(r.is_approved)

    def test_skip(self):
        r = ApprovalResult.skip()
        self.assertTrue(r.is_skipped)
        self.assertFalse(r.is_approved)

    def test_modify_effective_arguments_returns_new(self):
        r = ApprovalResult.modify({"a": 2})
        self.assertTrue(r.is_approved)
        self.assertEqual(r.effective_arguments({"a": 1}), {"a": 2})

    def test_approve_effective_arguments_returns_original(self):
        r = ApprovalResult.approve()
        self.assertEqual(r.effective_arguments({"a": 1}), {"a": 1})

    def test_approve_all_kinds(self):
        self.assertTrue(ApprovalResult.approve_all().is_approved_all_by_tool)
        self.assertTrue(
            ApprovalResult.approve_all_by_server().is_approved_all_by_server
        )


# ---------- ApprovalRequest ----------
class TestApprovalRequest(unittest.TestCase):
    def test_display_text_essentials(self):
        req = ApprovalRequest(
            tool_name="write_file",
            arguments={"path": "/tmp/x.txt", "content": "hello"},
            suggestion="测试覆盖到边角",
        )
        text = req.to_display_text()
        self.assertIn("需要审批", text)
        self.assertIn("write_file", text)
        self.assertIn("中危", text)
        self.assertIn("执行理由", text)
        self.assertIn("/tmp/x.txt", text)

    def test_display_text_truncates_long_content(self):
        req = ApprovalRequest(
            tool_name="write_file",
            arguments={"path": "/tmp/x", "content": "a" * 500},
        )
        self.assertIn("500 字符", req.to_display_text())

    def test_display_text_mcp_shows_server(self):
        req = ApprovalRequest(
            tool_name="mcp__chrome__navigate",
            arguments={"url": "https://example.com"},
        )
        text = req.to_display_text()
        self.assertIn("MCP server", text)
        self.assertIn("chrome", text)

    def test_display_text_empty_args(self):
        req = ApprovalRequest(tool_name="execute_command", arguments={})
        self.assertIn("无参数", req.to_display_text())


# ---------- TerminalHitlHandler ----------
def _terminal(inputs: list[str]) -> tuple[TerminalHitlHandler, io.StringIO]:
    payload = "\n".join(inputs) + "\n" if inputs else ""
    stdin = io.StringIO(payload)
    stdout = io.StringIO()
    return TerminalHitlHandler(enabled=True, stdin=stdin, stdout=stdout), stdout


def _write_request() -> ApprovalRequest:
    return ApprovalRequest(
        tool_name="write_file",
        arguments={"path": "/tmp/x", "content": "hi"},
    )


class TestTerminalHandler(unittest.TestCase):
    def test_approve_with_y(self):
        handler, _ = _terminal(["y"])
        self.assertIs(handler.request_approval(_write_request()).decision, Decision.APPROVED)

    def test_approve_with_enter(self):
        handler, _ = _terminal([""])
        self.assertIs(handler.request_approval(_write_request()).decision, Decision.APPROVED)

    def test_reject_with_reason(self):
        handler, _ = _terminal(["n", "怕被覆盖"])
        result = handler.request_approval(_write_request())
        self.assertIs(result.decision, Decision.REJECTED)
        self.assertEqual(result.reason, "怕被覆盖")

    def test_skip(self):
        handler, _ = _terminal(["s"])
        self.assertIs(handler.request_approval(_write_request()).decision, Decision.SKIPPED)

    def test_modify_with_valid_json(self):
        new_args = json.dumps({"path": "/tmp/y", "content": "hi"})
        handler, _ = _terminal(["m", new_args])
        result = handler.request_approval(_write_request())
        self.assertIs(result.decision, Decision.MODIFIED)
        self.assertEqual(result.modified_arguments, {"path": "/tmp/y", "content": "hi"})

    def test_modify_invalid_then_approve(self):
        handler, stdout = _terminal(["m", "not json at all", "y"])
        result = handler.request_approval(_write_request())
        self.assertIs(result.decision, Decision.APPROVED)
        self.assertIn("不是合法 JSON", stdout.getvalue())

    def test_modify_empty_falls_back_to_approve(self):
        handler, stdout = _terminal(["m", ""])
        result = handler.request_approval(_write_request())
        self.assertIs(result.decision, Decision.APPROVED)
        self.assertIn("改为批准原始参数", stdout.getvalue())

    def test_approve_all_caches_tool(self):
        handler, _ = _terminal(["a"])
        result = handler.request_approval(_write_request())
        self.assertIs(result.decision, Decision.APPROVED_ALL)
        self.assertTrue(handler.is_approved_all_by_tool("write_file"))

    def test_approve_all_mcp_server_scope(self):
        req = ApprovalRequest(tool_name="mcp__chrome__click", arguments={"x": 1})
        handler, _ = _terminal(["a", "server"])
        result = handler.request_approval(req)
        self.assertIs(result.decision, Decision.APPROVED_ALL_BY_SERVER)
        self.assertTrue(handler.is_approved_all_by_server("chrome"))

    def test_approve_all_mcp_default_scope_is_tool(self):
        req = ApprovalRequest(tool_name="mcp__chrome__click", arguments={"x": 1})
        handler, _ = _terminal(["a", ""])
        result = handler.request_approval(req)
        self.assertIs(result.decision, Decision.APPROVED_ALL)
        self.assertTrue(handler.is_approved_all_by_tool("mcp__chrome__click"))
        self.assertFalse(handler.is_approved_all_by_server("chrome"))

    def test_second_call_auto_passes_after_approve_all(self):
        handler, stdout = _terminal(["a"])
        handler.request_approval(_write_request())
        # 第二次不应再读取 stdin
        result2 = handler.request_approval(_write_request())
        self.assertIs(result2.decision, Decision.APPROVED_ALL)
        self.assertIn("自动通过", stdout.getvalue())

    def test_eof_treated_as_reject(self):
        handler, _ = _terminal([])
        self.assertIs(handler.request_approval(_write_request()).decision, Decision.REJECTED)

    def test_invalid_input_5_times_then_reject(self):
        handler, _ = _terminal(["?", "?", "?", "?", "?"])
        self.assertIs(handler.request_approval(_write_request()).decision, Decision.REJECTED)

    def test_sensitive_disables_approve_all(self):
        req = ApprovalRequest(
            tool_name="mcp__chrome__click",
            arguments={"x": 1},
            sensitive_notice="登录页面，操作要小心",
        )
        handler, stdout = _terminal(["a", "y"])
        result = handler.request_approval(req)
        self.assertIs(result.decision, Decision.APPROVED)
        self.assertIn("敏感页面操作不支持全部放行", stdout.getvalue())

    def test_clear_approved_all(self):
        handler, _ = _terminal(["a"])
        handler.request_approval(_write_request())
        self.assertTrue(handler.is_approved_all_by_tool("write_file"))
        handler.clear_approved_all()
        self.assertFalse(handler.is_approved_all_by_tool("write_file"))


# ---------- HitlToolRegistry / with_hitl ----------
class _StubAutoApprove:
    def __init__(self) -> None:
        self.enabled = True
        self.calls = 0

    def request_approval(self, request):
        self.calls += 1
        return ApprovalResult.approve()

    def is_approved_all_by_tool(self, tool_name): return False
    def is_approved_all_by_server(self, server_name): return False
    def clear_approved_all(self): pass


class _StubAutoReject:
    def __init__(self) -> None:
        self.enabled = True
        self.calls = 0

    def request_approval(self, request):
        self.calls += 1
        return ApprovalResult.reject("策略拒绝")

    def is_approved_all_by_tool(self, tool_name): return False
    def is_approved_all_by_server(self, server_name): return False
    def clear_approved_all(self): pass


class TestHitlGate(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _make_gate(self, handler, audit=None):
        base = ToolRegistry()
        base.register(WriteFileTool())
        base.register(ReadFileTool())
        return with_hitl(base, handler, audit), base

    def test_skips_approval_when_disabled(self):
        stub = _StubAutoReject()
        stub.enabled = False
        gate, _ = self._make_gate(stub)
        f = self.tmp_path / "x.txt"
        gate.execute("write_file", {"path": str(f), "content": "ok"})
        self.assertEqual(f.read_text(encoding="utf-8"), "ok")
        self.assertEqual(stub.calls, 0)

    def test_skips_approval_for_safe_tool(self):
        stub = _StubAutoReject()
        f = self.tmp_path / "x.txt"
        f.write_text("hello", encoding="utf-8")
        gate, _ = self._make_gate(stub)
        self.assertEqual(gate.execute("read_file", {"path": str(f)}), "hello")
        self.assertEqual(stub.calls, 0)

    def test_executes_when_approved(self):
        stub = _StubAutoApprove()
        gate, _ = self._make_gate(stub)
        f = self.tmp_path / "x.txt"
        gate.execute("write_file", {"path": str(f), "content": "ok"})
        self.assertEqual(f.read_text(encoding="utf-8"), "ok")
        self.assertEqual(stub.calls, 1)

    def test_blocks_when_rejected(self):
        stub = _StubAutoReject()
        gate, _ = self._make_gate(stub)
        f = self.tmp_path / "x.txt"
        out = gate.execute("write_file", {"path": str(f), "content": "ok"})
        self.assertTrue(out.startswith("[HITL] 操作已被拒绝"))
        self.assertFalse(f.exists())

    def test_calls_audit_hook(self):
        captured = []

        def audit(name, args, result, reason):
            captured.append((name, result.decision, reason))

        gate, _ = self._make_gate(_StubAutoReject(), audit=audit)
        gate.execute(
            "write_file",
            {"path": str(self.tmp_path / "y"), "content": "x"},
        )
        self.assertEqual(len(captured), 1)
        self.assertIs(captured[0][1], Decision.REJECTED)
        self.assertEqual(captured[0][2], "策略拒绝")

    def test_modify_uses_new_args(self):
        target_y = self.tmp_path / "y.txt"
        target_x = self.tmp_path / "x.txt"

        class _ModifyToY:
            enabled = True

            def request_approval(self, request):
                new = dict(request.arguments)
                new["path"] = str(target_y)
                return ApprovalResult.modify(new)

            def is_approved_all_by_tool(self, name): return False
            def is_approved_all_by_server(self, name): return False
            def clear_approved_all(self): pass

        gate, _ = self._make_gate(_ModifyToY())
        gate.execute("write_file", {"path": str(target_x), "content": "ok"})
        self.assertEqual(target_y.read_text(encoding="utf-8"), "ok")
        self.assertFalse(target_x.exists())

    def test_forwards_get_and_definitions(self):
        gate, base = self._make_gate(_StubAutoApprove())
        self.assertIs(gate.get("write_file"), base.get("write_file"))
        defs = gate.get_all_definitions()
        self.assertTrue(any(d["function"]["name"] == "write_file" for d in defs))


if __name__ == "__main__":
    unittest.main()
