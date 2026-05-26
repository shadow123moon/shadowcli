"""HITL / Reviewer 扩展的测试。

测试范围：
- extensions.approval_policy 的工具危险判断
- extensions.hitl 的人工审查 handler（mock input）
- extensions.reviewer 的 AI 审查 handler（mock chat）
- extensions.tool_runtime 的 hook 拦截行为
"""
import io
import unittest
from pathlib import Path
from unittest.mock import patch

from extensions import hitl as hitl_ext
from extensions import reviewer as reviewer_ext
from extensions.tool_runtime import ToolExecutionBlocked, ToolRuntime
from extensions import approval_policy as policy
from llm.types import ChatResponse
from tooling.base import Tool


# ---------- 测试辅助：构造假工具 ----------
class _FakeSafeTool(Tool):
    approval_required = False
    approval_level = "🟢 安全"
    approval_reason = "只读操作"

    @property
    def name(self):
        return "read"

    @property
    def description(self):
        return "fake"

    @property
    def parameters(self):
        return {}

    def execute(self, arguments):
        return "safe-ok"


class _FakeDangerTool(Tool):
    approval_required = True
    approval_level = "🔴 高危"
    approval_reason = "会修改文件"

    @property
    def name(self):
        return "write"

    @property
    def description(self):
        return "fake"

    @property
    def parameters(self):
        return {}

    def execute(self, arguments):
        return "danger-ok"


class _FakeMcpTool(Tool):
    """没有显式声明 approval_required，靠名字前缀判断。"""

    @property
    def name(self):
        return "mcp__chrome__click"

    @property
    def description(self):
        return "fake"

    @property
    def parameters(self):
        return {}

    def execute(self, arguments):
        return "mcp-ok"


class TestModuleLayout(unittest.TestCase):
    def test_hitl_pythonic_package_removed(self):
        root = Path(__file__).resolve().parents[1]

        self.assertFalse((root / "hitl_pythonic").exists())


# ---------- policy 模块 ----------
class TestPolicy(unittest.TestCase):
    def test_safe_tool_not_required(self):
        self.assertFalse(policy.requires_approval_for_tool(_FakeSafeTool(), {}))

    def test_danger_tool_required(self):
        self.assertTrue(policy.requires_approval_for_tool(_FakeDangerTool(), {}))

    def test_mcp_tool_required_by_prefix(self):
        # 没有 requires_approval 方法的对象，靠名字前缀判断
        class _Bare:
            name = "mcp__chrome__click"

        self.assertTrue(policy.requires_approval_for_tool(_Bare(), {}))

    def test_mcp_tool_with_method_uses_method(self):
        # 有 requires_approval 方法的对象，优先使用方法返回值
        # 这说明：MCP 工具如果继承 Tool 基类，必须显式设 approval_required=True
        self.assertFalse(policy.requires_approval_for_tool(_FakeMcpTool(), {}))

    def test_danger_level_uses_tool_attr(self):
        self.assertEqual(policy.danger_level_for_tool(_FakeDangerTool()), "🔴 高危")

    def test_danger_level_fallback_safe(self):
        # 普通工具没声明 approval_level 时（这里 _FakeSafeTool 声明了）
        # 用空 tool 测 fallback
        class _Empty:
            name = "read"

        self.assertEqual(policy.danger_level_for_tool(_Empty()), policy.DEFAULT_SAFE_LEVEL)

    def test_danger_level_fallback_mcp(self):
        class _Empty:
            name = "mcp__chrome__click"

        self.assertEqual(policy.danger_level_for_tool(_Empty()), policy.MCP_LEVEL)

    def test_risk_description_uses_tool_attr(self):
        self.assertEqual(
            policy.risk_description_for_tool(_FakeDangerTool()),
            "会修改文件",
        )

    def test_is_mcp_tool(self):
        self.assertTrue(policy.is_mcp_tool("mcp__chrome__click"))
        self.assertFalse(policy.is_mcp_tool("write"))
        self.assertFalse(policy.is_mcp_tool(""))
        self.assertFalse(policy.is_mcp_tool(None))

    def test_mcp_server_name(self):
        self.assertEqual(policy.mcp_server_name("mcp__chrome__click"), "chrome")
        self.assertIsNone(policy.mcp_server_name("write"))
        self.assertIsNone(policy.mcp_server_name("mcp__"))


# ---------- HITL 扩展 ----------
class TestHitlExtension(unittest.TestCase):
    def test_safe_tool_skipped(self):
        # 安全工具不应弹审查
        result = hitl_ext.hitl_handler("read", {}, _FakeSafeTool())
        self.assertIsNone(result)

    def test_approve_with_y(self):
        with patch("builtins.input", return_value="y"):
            result = hitl_ext.hitl_handler("write", {"p": "a"}, _FakeDangerTool())
        self.assertIsNone(result)

    def test_reject_with_n_returns_hard_stop(self):
        with patch("builtins.input", return_value="n"):
            result = hitl_ext.hitl_handler("write", {"p": "a"}, _FakeDangerTool())
        self.assertIsNotNone(result)
        self.assertTrue(result["block"])
        self.assertTrue(result["hard_stop"])
        self.assertIn("拒绝", result["reason"])

    def test_correction_with_c_returns_soft_block(self):
        # "c" 是建议修改：block=True 但 hard_stop=False
        inputs = iter(["c", "请用 edit 而不是 write"])
        with patch("builtins.input", side_effect=lambda *_: next(inputs)):
            result = hitl_ext.hitl_handler("write", {"p": "a"}, _FakeDangerTool())
        self.assertTrue(result["block"])
        self.assertFalse(result["hard_stop"])
        self.assertIn("请用 edit", result["reason"])

    def test_correction_with_empty_advice(self):
        inputs = iter(["c", ""])
        with patch("builtins.input", side_effect=lambda *_: next(inputs)):
            result = hitl_ext.hitl_handler("write", {"p": "a"}, _FakeDangerTool())
        self.assertTrue(result["block"])
        self.assertFalse(result["hard_stop"])
        self.assertIn("未提供补充说明", result["reason"])


# ---------- Reviewer 扩展 ----------
def _fake_chat(content: str):
    return lambda messages, **kwargs: ChatResponse(content=content)


class TestReviewerExtension(unittest.TestCase):
    def test_safe_tool_skipped(self):
        # 安全工具不调 LLM，直接放行
        with patch("extensions.reviewer.chat") as mocked:
            result = reviewer_ext.reviewer_handler("read", {}, _FakeSafeTool())
        self.assertIsNone(result)
        mocked.assert_not_called()

    def test_llm_approves(self):
        with patch(
            "extensions.reviewer.chat",
            side_effect=_fake_chat('{"approved": true, "reason": "安全"}'),
        ):
            result = reviewer_ext.reviewer_handler(
                "write", {"p": "a"}, _FakeDangerTool()
            )
        self.assertIsNone(result)

    def test_llm_rejects(self):
        with patch(
            "extensions.reviewer.chat",
            side_effect=_fake_chat('{"approved": false, "reason": "路径可疑"}'),
        ):
            result = reviewer_ext.reviewer_handler(
                "write", {"p": "/etc/passwd"}, _FakeDangerTool()
            )
        self.assertTrue(result["block"])
        self.assertEqual(result["reason"], "路径可疑")

    def test_llm_returns_json_wrapped_in_text(self):
        # LLM 有时会在 JSON 前后加自然语言
        with patch(
            "extensions.reviewer.chat",
            side_effect=_fake_chat(
                '好的，我判断如下：{"approved": false, "reason": "高风险"} 仅供参考'
            ),
        ):
            result = reviewer_ext.reviewer_handler(
                "bash", {"command": "rm -rf /"}, _FakeDangerTool()
            )
        self.assertTrue(result["block"])
        self.assertEqual(result["reason"], "高风险")

    def test_llm_error_blocks(self):
        # 网络异常 / 超时：安全起见拦截
        with patch(
            "extensions.reviewer.chat", side_effect=RuntimeError("网络超时")
        ):
            result = reviewer_ext.reviewer_handler(
                "write", {"p": "a"}, _FakeDangerTool()
            )
        self.assertTrue(result["block"])
        self.assertIn("网络超时", result["reason"])

    def test_llm_non_json_blocks(self):
        # LLM 返回完全不是 JSON：当作异常拦截
        with patch(
            "extensions.reviewer.chat", side_effect=_fake_chat("我不知道")
        ):
            result = reviewer_ext.reviewer_handler(
                "write", {"p": "a"}, _FakeDangerTool()
            )
        self.assertTrue(result["block"])


# ---------- ToolRuntime hook 行为 ----------
class _FakeRegistry:
    """最小化的 registry stub，只支持 get / execute。"""

    def __init__(self, tools: dict):
        self._tools = tools

    def get(self, name):
        return self._tools[name]

    def execute(self, name, arguments):
        return self._tools[name].execute(arguments)

    def get_all_definitions(self):
        return []


class TestToolRuntimeHooks(unittest.TestCase):
    def setUp(self):
        self.registry = _FakeRegistry(
            {
                "read": _FakeSafeTool(),
                "write": _FakeDangerTool(),
            }
        )
        self.runtime = ToolRuntime(self.registry)

    def test_no_hooks_executes_normally(self):
        self.assertEqual(self.runtime.execute("read", {}), "safe-ok")
        self.assertEqual(self.runtime.execute("write", {}), "danger-ok")

    def test_hook_returns_none_lets_through(self):
        self.runtime.on_before_execute(lambda name, args, tool: None)
        self.assertEqual(self.runtime.execute("write", {}), "danger-ok")

    def test_hook_soft_block_returns_message(self):
        self.runtime.on_before_execute(
            lambda *_: {"block": True, "hard_stop": False, "reason": "建议改用 edit"}
        )
        out = self.runtime.execute("write", {})
        self.assertIn("建议改用 edit", out)
        self.assertIn("操作被拒绝", out)

    def test_hook_hard_block_raises(self):
        self.runtime.on_before_execute(
            lambda *_: {"block": True, "hard_stop": True, "reason": "禁止"}
        )
        with self.assertRaises(ToolExecutionBlocked) as ctx:
            self.runtime.execute("write", {})
        self.assertIn("禁止", str(ctx.exception))

    def test_hard_stop_defaults_to_true(self):
        # 不显式设置 hard_stop，默认应该是硬停（保守）
        self.runtime.on_before_execute(
            lambda *_: {"block": True, "reason": "禁止"}
        )
        with self.assertRaises(ToolExecutionBlocked):
            self.runtime.execute("write", {})

    def test_multiple_hooks_first_block_wins(self):
        calls = []

        def hook1(*_):
            calls.append("h1")
            return {"block": True, "hard_stop": True, "reason": "h1 拒绝"}

        def hook2(*_):
            calls.append("h2")
            return None

        self.runtime.on_before_execute(hook1)
        self.runtime.on_before_execute(hook2)

        with self.assertRaises(ToolExecutionBlocked):
            self.runtime.execute("write", {})

        # hook2 不应被调用，因为 hook1 已经拦截
        self.assertEqual(calls, ["h1"])

    def test_hook_receives_tool_object(self):
        captured = {}

        def hook(name, args, tool):
            captured["name"] = name
            captured["args"] = args
            captured["tool_name"] = tool.name
            return None

        self.runtime.on_before_execute(hook)
        self.runtime.execute("write", {"path": "x"})
        self.assertEqual(captured["name"], "write")
        self.assertEqual(captured["args"], {"path": "x"})
        self.assertEqual(captured["tool_name"], "write")


# ---------- 集成：扩展 register 到 runtime ----------
class TestExtensionRegistration(unittest.TestCase):
    def setUp(self):
        self.registry = _FakeRegistry(
            {
                "read": _FakeSafeTool(),
                "write": _FakeDangerTool(),
            }
        )
        self.runtime = ToolRuntime(self.registry)

    def test_hitl_register_blocks_on_reject(self):
        hitl_ext.register(self.runtime)
        with patch("builtins.input", return_value="n"):
            with self.assertRaises(ToolExecutionBlocked):
                self.runtime.execute("write", {})

    def test_hitl_register_passes_safe_tool(self):
        hitl_ext.register(self.runtime)
        # 不会触发 input，因为是安全工具
        self.assertEqual(self.runtime.execute("read", {}), "safe-ok")

    def test_reviewer_register_blocks_raises(self):
        reviewer_ext.register(self.runtime)
        with patch(
            "extensions.reviewer.chat",
            side_effect=_fake_chat('{"approved": false, "reason": "危险"}'),
        ):
            with self.assertRaises(ToolExecutionBlocked):
                self.runtime.execute("write", {})


if __name__ == "__main__":
    unittest.main()
