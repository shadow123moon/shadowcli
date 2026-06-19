"""Tests for plan mode state management and runtime guards."""
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from agent import AgentLoop
from llm import FunctionCall, Message, ToolCall
from plan_mode import (
    DEFAULT_MODE,
    PLAN_MODE,
    PlanModeState,
    filter_tool_definitions_for_mode,
    format_plan_mode_status,
    is_read_only_shell_command,
    plan_mode_context,
    register_plan_mode_guard,
)
from plan_mode.agents import ExploreAgentTool, ForkExploreAgentsTool, PlanAgentTool
from plan_mode.state import _normalize_text
from plan_mode.tools import ExitPlanModeTool, PlanProposal
from llm.client import StreamEvent
from sessions import RuntimeContextBuilder, SessionManager, SessionStore
from tooling import BashTool, ReadTool, WriteTool, EditTool, ToolRegistry, ToolRuntime


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
        self.assertIn("git status/git diff", context)
        self.assertIn("write/edit/propose_memory", context)

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

    def test_allows_exit_plan_mode_tool_in_plan_mode(self):
        self.plan_mode_active = True
        approved: list[str] = []
        self.registry.register(
            ExitPlanModeTool(
                confirm_plan=lambda proposal: True,
                on_plan_approved=approved.append,
            )
        )

        result = self.runtime.execute("exit_plan_mode", {"plan": "1. inspect\n2. implement"})

        self.assertIn("已退出 plan mode", result)
        self.assertEqual(approved, ["1. inspect\n2. implement"])
        self.assertNotIn("plan mode 只允许只读工具", result)

    def test_allows_read_only_git_shell_in_plan_mode(self):
        self.plan_mode_active = True
        self.registry.register(BashTool())

        result = self.runtime.execute("bash", {"command": "git status --short"})

        self.assertNotIn("plan mode 只允许", result)

    def test_blocks_effectful_shell_in_plan_mode(self):
        self.plan_mode_active = True
        self.registry.register(BashTool())

        result = self.runtime.execute("bash", {"command": "New-Item touched.txt"})

        self.assertIn("plan mode 只允许只读 shell 命令", result)
        self.assertIn("已拒绝 bash", result)

    def test_read_only_shell_policy(self):
        self.assertEqual(is_read_only_shell_command("git status --short")[0], True)
        self.assertEqual(is_read_only_shell_command("git diff -- src/app.py")[0], True)
        self.assertEqual(is_read_only_shell_command("git diff --output=x.patch")[0], False)
        self.assertEqual(is_read_only_shell_command("git status; New-Item x")[0], False)

    def test_filters_visible_tools_for_plan_mode(self):
        self.registry.register(BashTool())
        self.registry.register(
            ExitPlanModeTool(
                confirm_plan=lambda proposal: True,
                on_plan_approved=lambda plan: None,
            )
        )

        definitions = filter_tool_definitions_for_mode(
            self.runtime.get_all_definitions(),
            self.runtime,
            plan_mode_active=True,
        )
        names = [definition["function"]["name"] for definition in definitions]

        self.assertIn("read", names)
        self.assertIn("bash", names)
        self.assertIn("exit_plan_mode", names)
        self.assertNotIn("write", names)
        self.assertNotIn("edit", names)

    def test_filters_plan_subagents_visible_in_plan_mode(self):
        self.registry.register(ExploreAgentTool(
            parent_runtime=self.runtime,
            chat_stream_fn=lambda *a, **k: None,
            agent_loop_factory=AgentLoop,
        ))
        self.registry.register(PlanAgentTool(
            parent_runtime=self.runtime,
            chat_stream_fn=lambda *a, **k: None,
            agent_loop_factory=AgentLoop,
        ))
        self.registry.register(ForkExploreAgentsTool(
            parent_runtime=self.runtime,
            chat_stream_fn=lambda *a, **k: None,
            agent_loop_factory=AgentLoop,
            parent_messages_provider=lambda: [],
        ))

        definitions = filter_tool_definitions_for_mode(
            self.runtime.get_all_definitions(),
            self.runtime,
            plan_mode_active=True,
        )
        names = [definition["function"]["name"] for definition in definitions]

        self.assertIn("explore_agent", names)
        self.assertIn("plan_agent", names)
        self.assertIn("fork_explore_agents", names)

    def test_filters_plan_only_tools_outside_plan_mode(self):
        self.registry.register(ExploreAgentTool(
            parent_runtime=self.runtime,
            chat_stream_fn=lambda *a, **k: None,
            agent_loop_factory=AgentLoop,
        ))

        definitions = filter_tool_definitions_for_mode(
            self.runtime.get_all_definitions(),
            self.runtime,
            plan_mode_active=False,
        )
        names = [definition["function"]["name"] for definition in definitions]

        self.assertIn("read", names)
        self.assertIn("write", names)
        self.assertNotIn("explore_agent", names)

    def test_plan_subagents_are_blocked_outside_plan_mode(self):
        self.plan_mode_active = False
        self.registry.register(ExploreAgentTool(
            parent_runtime=self.runtime,
            chat_stream_fn=lambda *a, **k: None,
            agent_loop_factory=AgentLoop,
        ))

        result = self.runtime.execute("explore_agent", {"task": "查结构"})

        self.assertIn("只能在 plan mode 下执行", result)

    def test_explore_agent_runs_with_read_only_tools(self):
        calls: list[list[str]] = []

        def fake_stream(_messages, tools=None, cancel=None):
            calls.append([tool["function"]["name"] for tool in tools or []])
            yield StreamEvent("content", "探索摘要")
            yield StreamEvent("done", {"reason": "finished"})

        tool = ExploreAgentTool(
            parent_runtime=self.runtime,
            chat_stream_fn=fake_stream,
            agent_loop_factory=AgentLoop,
        )

        result = tool.execute({"task": "查 runtime"})

        self.assertEqual(result, "探索摘要")
        self.assertIn("read", calls[0])
        self.assertNotIn("write", calls[0])
        self.assertNotIn("edit", calls[0])

    def test_fork_explore_agents_runs_tasks_in_parallel_and_preserves_parent_history(self):
        parent_messages = [
            Message(role="user", content="父任务"),
            Message(role="assistant", content="父回答"),
        ]
        histories: list[list[Message]] = []
        started_at: list[float] = []

        class FakeLoop:
            def __init__(self, **kwargs):
                self.conversation_history = kwargs["conversation_history"]
                histories.append(self.conversation_history)

            def execute(self, task, allow_tools=True):
                started_at.append(time.monotonic())
                time.sleep(0.12)
                self.conversation_history.append(Message(role="user", content=task.content))
                yield StreamEvent("content", f"完成:{task.content}")
                yield StreamEvent("done", {"reason": "finished"})

        tool = ForkExploreAgentsTool(
            parent_runtime=self.runtime,
            chat_stream_fn=lambda *a, **k: None,
            agent_loop_factory=FakeLoop,
            parent_messages_provider=lambda: parent_messages,
        )

        started = time.monotonic()
        result = tool.execute({"tasks": ["查 session", "查 tooling", "查 plan"]})
        elapsed = time.monotonic() - started

        self.assertLess(elapsed, 0.30)
        self.assertEqual(len(histories), 3)
        self.assertTrue(all(history[:2] == parent_messages for history in histories))
        self.assertEqual([message.content for message in parent_messages], ["父任务", "父回答"])
        self.assertIn("## 1. 查 session", result)
        self.assertIn("完成:查 session", result)
        self.assertIn("## 2. 查 tooling", result)
        self.assertIn("## 3. 查 plan", result)
        self.assertLess(max(started_at) - min(started_at), 0.08)

    def test_fork_explore_agents_drops_in_flight_parent_tool_call_from_prefix(self):
        captured_messages: list[list[Message]] = []
        parent_messages = [
            Message(role="user", content="父任务"),
            Message(
                role="assistant",
                content=None,
                tool_calls=[
                    ToolCall(
                        id="call_fork",
                        function=FunctionCall(name="fork_explore_agents", arguments="{}"),
                    )
                ],
            ),
        ]

        def fake_stream(messages, tools=None, cancel=None):
            captured_messages.append(list(messages))
            yield StreamEvent("content", "探索摘要")
            yield StreamEvent("done", {"reason": "finished"})

        tool = ForkExploreAgentsTool(
            parent_runtime=self.runtime,
            chat_stream_fn=fake_stream,
            agent_loop_factory=AgentLoop,
            parent_messages_provider=lambda: parent_messages,
        )

        result = tool.execute({"tasks": ["查 runtime"]})

        self.assertIn("探索摘要", result)
        self.assertEqual(len(captured_messages), 1)
        sent = captured_messages[0]
        self.assertEqual([message.content for message in parent_messages], ["父任务", None])
        self.assertFalse(any(message.tool_calls for message in sent))
        self.assertEqual(sent[-1].role, "user")
        self.assertEqual(sent[-1].content, "查 runtime")

    def test_single_explore_agent_drops_in_flight_parent_tool_call_from_prefix(self):
        captured_messages: list[list[Message]] = []
        parent_messages = [
            Message(role="user", content="父任务"),
            Message(
                role="assistant",
                content=None,
                tool_calls=[
                    ToolCall(
                        id="call_explore",
                        function=FunctionCall(name="explore_agent", arguments="{}"),
                    )
                ],
            ),
        ]

        def fake_stream(messages, tools=None, cancel=None):
            captured_messages.append(list(messages))
            yield StreamEvent("content", "探索摘要")
            yield StreamEvent("done", {"reason": "finished"})

        tool = ExploreAgentTool(
            parent_runtime=self.runtime,
            chat_stream_fn=fake_stream,
            agent_loop_factory=AgentLoop,
            parent_messages_provider=lambda: parent_messages,
        )

        result = tool.execute({"task": "查 runtime"})

        self.assertEqual(result, "探索摘要")
        self.assertFalse(any(message.tool_calls for message in captured_messages[0]))

    def test_fork_explore_agents_propagates_parent_cancel_to_children(self):
        parent_cancel = threading.Event()
        seen_cancel_events = []

        class SlowLoop:
            def __init__(self, **kwargs):
                self.cancel = kwargs["cancel"]
                seen_cancel_events.append(self.cancel)

            def execute(self, task, allow_tools=True):
                started = time.monotonic()
                while not self.cancel.is_set() and time.monotonic() - started < 0.45:
                    time.sleep(0.01)
                yield StreamEvent("content", "cancelled" if self.cancel.is_set() else "late")
                yield StreamEvent("done", {"reason": "finished"})

        def trigger_cancel():
            time.sleep(0.05)
            parent_cancel.set()

        tool = ForkExploreAgentsTool(
            parent_runtime=self.runtime,
            chat_stream_fn=lambda *a, **k: None,
            agent_loop_factory=SlowLoop,
            parent_messages_provider=lambda: [],
        )
        threading.Thread(target=trigger_cancel).start()
        context = type("Context", (), {"cancel": parent_cancel})()

        started = time.monotonic()
        result = tool.execute_with_context({"tasks": ["a", "b"]}, context)
        elapsed = time.monotonic() - started

        self.assertLess(elapsed, 0.25)
        self.assertTrue(seen_cancel_events)
        self.assertTrue(all(event is parent_cancel for event in seen_cancel_events))
        self.assertTrue("cancelled" in result or "已取消或超时" in result)

    def test_fork_explore_agents_times_out_non_cooperative_children(self):
        class SlowLoop:
            def __init__(self, **kwargs):
                self.cancel = kwargs["cancel"]

            def execute(self, task, allow_tools=True):
                time.sleep(0.35)
                yield StreamEvent("content", "late")
                yield StreamEvent("done", {"reason": "finished"})

        tool = ForkExploreAgentsTool(
            parent_runtime=self.runtime,
            chat_stream_fn=lambda *a, **k: None,
            agent_loop_factory=SlowLoop,
            parent_messages_provider=lambda: [],
        )

        with patch.dict("os.environ", {"SHADOWCLI_FORK_AGENT_TIMEOUT_SECONDS": "0.1"}):
            started = time.monotonic()
            result = tool.execute({"tasks": ["a"]})
            elapsed = time.monotonic() - started

        self.assertLess(elapsed, 0.25)
        self.assertIn("已取消或超时", result)

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

            plan_state = PlanModeState()
            plan_state.enter("实现登录")
            builder = RuntimeContextBuilder(
                session=session,
                extra_context_provider=lambda: plan_mode_context(plan_state),
            )
            context = builder.build("用户查询")

            self.assertIn("## 当前模式: Plan Mode", context)
            self.assertIn("任务: 实现登录", context)
            self.assertIn("只读计划模式", context)

    def test_context_builder_reads_live_plan_mode_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SessionStore(root=Path(tmpdir))
            cwd = Path(tmpdir) / "project"
            cwd.mkdir()
            session = store.create(cwd)

            plan_state = PlanModeState()
            builder = RuntimeContextBuilder(
                session=session,
                extra_context_provider=lambda: plan_mode_context(plan_state),
            )
            self.assertNotIn("## 当前模式: Plan Mode", builder.build("用户查询"))

            plan_state.enter("实现登录")
            context = builder.build("用户查询")

            self.assertIn("## 当前模式: Plan Mode", context)
            self.assertIn("任务: 实现登录", context)

    def test_context_builder_injects_approved_plan(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SessionStore(root=Path(tmpdir))
            cwd = Path(tmpdir) / "project"
            cwd.mkdir()
            session = store.create(cwd)

            plan_state = PlanModeState()
            plan_state.enter("任务")
            plan_state.exit("步骤 1: 准备\n步骤 2: 执行")
            builder = RuntimeContextBuilder(
                session=session,
                extra_context_provider=lambda: plan_mode_context(plan_state),
            )
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

            builder = RuntimeContextBuilder(session=session)
            context = builder.build("用户查询")

            self.assertNotIn("## 当前模式: Plan Mode", context)
            self.assertNotIn("## 已批准计划", context)


class TestExitPlanModeTool(unittest.TestCase):
    """Test ExitPlanModeTool for agent-driven plan mode exit."""

    def test_tool_requires_plan_parameter(self):
        """Test tool rejects empty plan."""
        confirmed = False
        approved_plan = None

        def mock_confirm(proposal):
            nonlocal confirmed
            confirmed = True
            return True

        def mock_on_approved(plan):
            nonlocal approved_plan
            approved_plan = plan

        tool = ExitPlanModeTool(confirm_plan=mock_confirm, on_plan_approved=mock_on_approved)
        result = tool.execute({"plan": ""})

        self.assertIn("错误", result)
        self.assertFalse(confirmed)
        self.assertIsNone(approved_plan)

    def test_tool_executes_on_user_confirmation(self):
        """Test tool exits plan mode when user confirms."""
        confirmed_proposal = None
        approved_plan = None

        def mock_confirm(proposal):
            nonlocal confirmed_proposal
            confirmed_proposal = proposal
            return True

        def mock_on_approved(plan):
            nonlocal approved_plan
            approved_plan = plan

        tool = ExitPlanModeTool(confirm_plan=mock_confirm, on_plan_approved=mock_on_approved)
        test_plan = "1. 步骤一\n2. 步骤二\n3. 步骤三"
        result = tool.execute({"plan": test_plan, "reason": "计划完成"})

        self.assertIsNotNone(confirmed_proposal)
        self.assertEqual(confirmed_proposal.plan, test_plan)
        self.assertEqual(confirmed_proposal.reason, "计划完成")
        self.assertEqual(approved_plan, test_plan)
        self.assertIn("✓", result)
        self.assertIn("已退出 plan mode", result)

    def test_tool_cancels_on_user_rejection(self):
        """Test tool stays in plan mode when user rejects."""
        approved_plan = None

        def mock_confirm(proposal):
            return False  # User rejects

        def mock_on_approved(plan):
            nonlocal approved_plan
            approved_plan = plan

        tool = ExitPlanModeTool(confirm_plan=mock_confirm, on_plan_approved=mock_on_approved)
        test_plan = "incomplete plan"
        result = tool.execute({"plan": test_plan})

        self.assertIsNone(approved_plan)
        self.assertIn("未确认", result)
        self.assertIn("仍处于 plan mode", result)

    def test_tool_metadata(self):
        """Test tool has correct metadata."""
        tool = ExitPlanModeTool(
            confirm_plan=lambda p: True,
            on_plan_approved=lambda p: None,
        )

        self.assertEqual(tool.name, "exit_plan_mode")
        self.assertEqual(tool.effect, "control")
        self.assertEqual(tool.category, "plan")
        self.assertTrue(tool.approval_required)
        self.assertIn("plan", tool.description)


if __name__ == "__main__":
    unittest.main()
