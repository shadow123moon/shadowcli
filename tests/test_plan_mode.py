"""Tests for plan mode state management and runtime guards."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from sessions.plan_mode import (
    DEFAULT_MODE,
    PLAN_MODE,
    PlanModeState,
    format_plan_mode_status,
    plan_mode_context,
)
from sessions import RuntimeContextBuilder, SessionManager, SessionStore
from app_runtime.plan_guard import register_plan_mode_guard
from tooling import ReadTool, WriteTool, EditTool, ToolRegistry, ToolRuntime


class TestPlanModeState(unittest.TestCase):
    """Test PlanModeState lifecycle and serialization."""

    def test_initial_state_is_default_mode(self):
        state = PlanModeState()
        self.assertEqual(state.mode, DEFAULT_MODE)
        self.assertFalse(state.active)
        self.assertEqual(state.task, "")
        self.assertEqual(state.approved_plan, "")
        self.assertIsNone(state.pre_mode)

    def test_enter_plan_mode_sets_task_and_active(self):
        state = PlanModeState()
        state.enter("实现用户认证")
        self.assertEqual(state.mode, PLAN_MODE)
        self.assertTrue(state.active)
        self.assertEqual(state.task, "实现用户认证")
        self.assertEqual(state.approved_plan, "")
        self.assertEqual(state.pre_mode, DEFAULT_MODE)

    def test_enter_normalizes_whitespace(self):
        state = PlanModeState()
        state.enter("  多个   空格  \n  换行  ")
        self.assertEqual(state.task, "多个 空格 换行")

    def test_enter_rejects_empty_task(self):
        state = PlanModeState()
        with self.assertRaises(ValueError):
            state.enter("")
        with self.assertRaises(ValueError):
            state.enter("   ")

    def test_exit_saves_approved_plan_and_restores_mode(self):
        state = PlanModeState()
        state.enter("重构数据库层")
        state.exit("1. 提取接口 2. 实现 Postgres 适配器 3. 迁移现有代码")
        self.assertEqual(state.mode, DEFAULT_MODE)
        self.assertFalse(state.active)
        self.assertEqual(state.approved_plan, "1. 提取接口 2. 实现 Postgres 适配器 3. 迁移现有代码")
        self.assertEqual(state.task, "")
        self.assertIsNone(state.pre_mode)

    def test_exit_normalizes_whitespace(self):
        state = PlanModeState()
        state.enter("task")
        state.exit("  计划  \n  内容  ")
        self.assertEqual(state.approved_plan, "计划 内容")

    def test_exit_rejects_empty_plan(self):
        state = PlanModeState()
        state.enter("task")
        with self.assertRaises(ValueError):
            state.exit("")
        with self.assertRaises(ValueError):
            state.exit("   ")

    def test_reset_clears_all_state(self):
        state = PlanModeState()
        state.enter("task")
        state.exit("plan content")
        state.reset()
        self.assertEqual(state.mode, DEFAULT_MODE)
        self.assertFalse(state.active)
        self.assertEqual(state.task, "")
        self.assertEqual(state.approved_plan, "")
        self.assertIsNone(state.pre_mode)

    def test_to_dict_serializes_all_fields(self):
        state = PlanModeState()
        state.enter("implement auth")
        data = state.to_dict()
        self.assertEqual(data["mode"], PLAN_MODE)
        self.assertEqual(data["task"], "implement auth")
        self.assertEqual(data["pre_mode"], DEFAULT_MODE)
        self.assertEqual(data["approved_plan"], "")

    def test_from_dict_deserializes_correctly(self):
        data = {
            "mode": PLAN_MODE,
            "task": "refactor code",
            "pre_mode": DEFAULT_MODE,
            "approved_plan": "",
        }
        state = PlanModeState.from_dict(data)
        self.assertEqual(state.mode, PLAN_MODE)
        self.assertTrue(state.active)
        self.assertEqual(state.task, "refactor code")
        self.assertEqual(state.pre_mode, DEFAULT_MODE)

    def test_from_dict_handles_none(self):
        state = PlanModeState.from_dict(None)
        self.assertEqual(state.mode, DEFAULT_MODE)
        self.assertFalse(state.active)

    def test_from_dict_handles_invalid_mode(self):
        data = {"mode": "invalid_mode"}
        state = PlanModeState.from_dict(data)
        self.assertEqual(state.mode, DEFAULT_MODE)

    def test_from_dict_normalizes_whitespace_in_task_and_plan(self):
        data = {
            "mode": PLAN_MODE,
            "task": "  task  \n  text  ",
            "approved_plan": "  plan  \n  text  ",
        }
        state = PlanModeState.from_dict(data)
        self.assertEqual(state.task, "task text")
        self.assertEqual(state.approved_plan, "plan text")


class TestPlanModeContext(unittest.TestCase):
    """Test plan mode context injection for LLM."""

    def test_active_plan_mode_returns_instructions(self):
        state = PlanModeState()
        state.enter("设计 API")
        context = plan_mode_context(state)
        self.assertIn("## 当前模式: Plan Mode", context)
        self.assertIn("任务: 设计 API", context)
        self.assertIn("只读计划模式", context)
        self.assertIn("read/ls/grep/find/web", context)
        self.assertIn("write/edit/bash", context)

    def test_approved_plan_returns_plan_content(self):
        state = PlanModeState()
        state.enter("task")
        state.exit("1. 步骤一\n2. 步骤二\n3. 步骤三")
        context = plan_mode_context(state)
        self.assertIn("## 已批准计划", context)
        self.assertIn("1. 步骤一", context)
        self.assertIn("2. 步骤二", context)
        self.assertIn("3. 步骤三", context)

    def test_default_mode_without_plan_returns_empty(self):
        state = PlanModeState()
        context = plan_mode_context(state)
        self.assertEqual(context, "")

    def test_format_status_shows_current_task_when_active(self):
        state = PlanModeState()
        state.enter("重构代码")
        status = format_plan_mode_status(state)
        self.assertIn("当前处于 plan mode", status)
        self.assertIn("任务: 重构代码", status)
        self.assertIn("/exit-plan", status)

    def test_format_status_shows_usage_when_inactive(self):
        state = PlanModeState()
        status = format_plan_mode_status(state)
        self.assertIn("当前未处于 plan mode", status)
        self.assertIn("/plan <任务>", status)


class TestPlanModeGuard(unittest.TestCase):
    """Test runtime guard that blocks write tools in plan mode."""

    def setUp(self):
        self.registry = ToolRegistry()
        self.registry.register(ReadTool())
        self.registry.register(WriteTool())
        self.registry.register(EditTool())
        self.runtime = ToolRuntime(self.registry)
        self.plan_mode_active = False
        register_plan_mode_guard(self.runtime, lambda: self.plan_mode_active)

    def test_register_guard_validates_runtime(self):
        """Test guard registration validates runtime interface."""
        # 没有 on_before_execute 方法
        invalid_runtime = object()
        with self.assertRaises(TypeError) as ctx:
            register_plan_mode_guard(invalid_runtime, lambda: False)
        self.assertIn("on_before_execute", str(ctx.exception))

    def test_normalize_text_rejects_non_string(self):
        """Test _normalize_text raises TypeError for non-string input."""
        from sessions.plan_mode import _normalize_text
        with self.assertRaises(TypeError):
            _normalize_text(123)
        with self.assertRaises(TypeError):
            _normalize_text({"key": "value"})
        with self.assertRaises(TypeError):
            _normalize_text(["list", "item"])

    def test_allows_read_tools_in_plan_mode(self):
        self.plan_mode_active = True
        # 使用一个不存在的绝对路径
        with tempfile.TemporaryDirectory() as tmpdir:
            nonexistent = Path(tmpdir) / "nonexistent.txt"
            result = self.runtime.execute("read", {"path": str(nonexistent)})
            # ReadTool 会因为文件不存在而失败，但不会被 plan guard 拦截
            # 关键是不应该出现 "plan mode 只允许只读工具" 的拦截消息
            self.assertNotIn("plan mode 只允许只读工具", result)

    def test_blocks_write_tool_in_plan_mode(self):
        self.plan_mode_active = True
        result = self.runtime.execute("write", {"path": "/tmp/test.txt", "content": "data"})
        self.assertIn("plan mode 只允许只读工具", result)
        self.assertIn("已拒绝 write", result)

    def test_blocks_edit_tool_in_plan_mode(self):
        self.plan_mode_active = True
        result = self.runtime.execute("edit", {"path": "/tmp/test.txt", "old_text": "a", "new_text": "b"})
        self.assertIn("plan mode 只允许只读工具", result)
        self.assertIn("已拒绝 edit", result)

    def test_allows_write_tools_in_default_mode(self):
        self.plan_mode_active = False
        # 在非 plan mode 下，write 不会被 guard 拦截（但会因为其他原因失败，比如权限）
        result = self.runtime.execute("write", {"path": "/tmp/test.txt", "content": "data"})
        # guard 不应该拦截，所以不应该有 "plan mode 只允许只读工具"
        self.assertNotIn("plan mode 只允许只读工具", result)


class TestPlanModePersistence(unittest.TestCase):
    """Test plan mode state persistence in session metadata."""

    def test_session_persists_and_restores_plan_mode(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SessionStore(root=Path(tmpdir))
            cwd = Path(tmpdir) / "project"
            cwd.mkdir()

            # 创建会话并进入 plan mode
            session = store.create(cwd)
            state = PlanModeState()
            state.enter("实现功能 X")
            session.update_plan_mode(state.to_dict())

            # 重新打开会话
            session_id = session.meta.session_id
            restored = store.open(cwd, session_id)

            # 验证 plan mode 状态恢复
            restored_state = PlanModeState.from_dict(restored.meta.plan_mode)
            self.assertTrue(restored_state.active)
            self.assertEqual(restored_state.task, "实现功能 X")
            self.assertEqual(restored_state.mode, PLAN_MODE)

    def test_session_persists_approved_plan_after_exit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SessionStore(root=Path(tmpdir))
            cwd = Path(tmpdir) / "project"
            cwd.mkdir()

            session = store.create(cwd)
            state = PlanModeState()
            state.enter("任务")
            state.exit("已批准的计划内容")
            session.update_plan_mode(state.to_dict())

            # 重新打开
            session_id = session.meta.session_id
            restored = store.open(cwd, session_id)

            restored_state = PlanModeState.from_dict(restored.meta.plan_mode)
            self.assertFalse(restored_state.active)
            self.assertEqual(restored_state.approved_plan, "已批准的计划内容")


class TestRuntimeContextBuilderPlanIntegration(unittest.TestCase):
    """Test plan mode context injection in RuntimeContextBuilder."""

    def test_context_builder_injects_active_plan_mode(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SessionStore(root=Path(tmpdir))
            cwd = Path(tmpdir) / "project"
            cwd.mkdir()
            session = store.create(cwd)

            plan_state_dict = {"mode": PLAN_MODE, "task": "实现登录", "pre_mode": DEFAULT_MODE, "approved_plan": ""}
            builder = RuntimeContextBuilder(session=session, plan_mode=plan_state_dict)
            context = builder.build("用户查询")

            self.assertIn("## 当前模式: Plan Mode", context)
            self.assertIn("任务: 实现登录", context)
            self.assertIn("只读计划模式", context)

    def test_context_builder_injects_approved_plan(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SessionStore(root=Path(tmpdir))
            cwd = Path(tmpdir) / "project"
            cwd.mkdir()
            session = store.create(cwd)

            plan_state_dict = {
                "mode": DEFAULT_MODE,
                "task": "",
                "pre_mode": None,
                "approved_plan": "步骤 1: 准备\n步骤 2: 执行",
            }
            builder = RuntimeContextBuilder(session=session, plan_mode=plan_state_dict)
            context = builder.build("用户查询")

            self.assertIn("## 已批准计划", context)
            self.assertIn("步骤 1: 准备", context)
            self.assertIn("步骤 2: 执行", context)

    def test_context_builder_no_plan_mode_returns_no_plan_context(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SessionStore(root=Path(tmpdir))
            cwd = Path(tmpdir) / "project"
            cwd.mkdir()
            session = store.create(cwd)

            builder = RuntimeContextBuilder(session=session, plan_mode=None)
            context = builder.build("用户查询")

            self.assertNotIn("## 当前模式: Plan Mode", context)
            self.assertNotIn("## 已批准计划", context)


if __name__ == "__main__":
    unittest.main()
