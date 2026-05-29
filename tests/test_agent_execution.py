import contextlib
import inspect
import io
import logging
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cli_app as cli
from agent.agent_loop import AgentLoop
from agent.react_agent import ReactAgent
from extensions.tool_runtime import ToolExecutionBlocked, ToolRuntime
from llm import FunctionCall, Message, ToolCall
from llm.client import StreamEvent
from sessions import BranchSummaryEntry, RuntimeContextBuilder, SessionStore, TextLongTermMemory
from tooling import (
    BashTool,
    EditTool,
    FindTool,
    GrepTool,
    LsTool,
    ReadTool,
    ToolRegistry,
    WriteTool,
)
from ui import BranchNavigationChoice, ask_branch_navigation_choice


class CaptureRegistry:
    def __init__(self):
        self.tools = {}
        self.executed = []

    def get(self, name):
        return self.tools[name]

    def execute(self, name, arguments):
        self.executed.append((name, arguments))
        return self.tools[name].execute(arguments)

    def get_all_definitions(self):
        return []


class ModuleLayoutTests(unittest.TestCase):
    def test_legacy_root_modules_are_removed(self):
        root = Path(__file__).resolve().parents[1]

        for filename in [
            "cli.py",
            "tools.py",
            "tool_registry.py",
            "config.py",
            "model.py",
            "llm_client.py",
        ]:
            self.assertFalse((root / filename).exists(), filename)

    def test_agent_package_does_not_depend_on_multi_agent(self):
        root = Path(__file__).resolve().parents[1]

        for path in (root / "agent").glob("*.py"):
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("multi_agent", source, path.name)

    def test_memory_pythonic_python_modules_are_removed(self):
        root = Path(__file__).resolve().parents[1]

        self.assertEqual(list((root / "memory_pythonic").glob("*.py")), [])


class ReactAgentTests(unittest.TestCase):
    def test_runs_single_react_turn_with_streaming_chat(self):
        calls = []
        agent = ReactAgent(CaptureRegistry())

        with patch("agent.agent_loop.chat_stream", _stream_content(calls, "你好，我是 ReAct 助手")):
            result = agent.run("你好")

        self.assertEqual(result, "你好，我是 ReAct 助手")
        self.assertEqual(calls[0][0][-1].content, "你好")
        self.assertIsNone(calls[0][1])

    def test_react_greeting_does_not_receive_tools(self):
        calls = []
        agent = ReactAgent(_ToolDefinitionRegistry())

        with patch("agent.agent_loop.chat_stream", _stream_content(calls, "你好")):
            agent.run("你好")

        self.assertEqual([tools for _, tools in calls], [None])

    def test_react_file_task_receives_tools(self):
        calls = []
        agent = ReactAgent(_ToolDefinitionRegistry())

        with patch("agent.agent_loop.chat_stream", _stream_content(calls, "可以读取")):
            agent.run("读取 cli_app/runner.py 文件")

        self.assertIsNotNone(calls[0][1])
        self.assertEqual(calls[0][1][0]["function"]["name"], "read")

    def test_react_keeps_tool_call_and_result_messages_between_turns(self):
        calls = []
        registry = CaptureRegistry()
        registry.tools["read"] = _StubTool("文件内容：hello")
        agent = ReactAgent(registry)

        def fake_stream(messages, tools=None, cancel=None):
            calls.append((list(messages), tools))
            if len(calls) == 1:
                yield StreamEvent(
                    "tool_call",
                    {
                        "id": "call-read",
                        "type": "function",
                        "name": "read",
                        "arguments": '{"path": "demo.txt"}',
                    },
                )
                yield StreamEvent("done", None)
                return
            if len(calls) == 2:
                yield StreamEvent("content", "读完了")
                yield StreamEvent("done", None)
                return
            yield StreamEvent("content", "上一轮读到 hello")
            yield StreamEvent("done", None)

        with patch("agent.agent_loop.chat_stream", fake_stream):
            agent.run("读取 demo.txt")
            agent.run("刚才读到了什么？")

        second_turn_messages = calls[-1][0]
        self.assertTrue(any(
            message.role == "assistant"
            and message.tool_calls
            and message.tool_calls[0].id == "call-read"
            for message in second_turn_messages
        ))
        self.assertTrue(any(
            message.role == "tool"
            and message.tool_call_id == "call-read"
            and "文件内容：hello" in (message.content or "")
            for message in second_turn_messages
        ))
        self.assertEqual(second_turn_messages[-1].role, "user")
        self.assertEqual(second_turn_messages[-1].content, "刚才读到了什么？")

    def test_react_agent_no_longer_accepts_legacy_memory_manager(self):
        self.assertNotIn("memory_manager", inspect.signature(ReactAgent).parameters)

    def test_react_agent_uses_conversation_message_names(self):
        params = inspect.signature(ReactAgent).parameters

        self.assertIn("conversation_messages", params)
        self.assertIn("on_message_appended", params)
        self.assertNotIn("session_messages", params)
        self.assertNotIn("message_sink", params)

    def test_react_turn_uses_external_context_without_persisting_augmented_user_text(self):
        calls = []
        agent = ReactAgent(CaptureRegistry())

        with patch("agent.agent_loop.chat_stream", _stream_content(calls, "按你的偏好来")):
            agent.run("入口和 React 怎么安排？", context="## 相关长期记忆\n- 用户偏好：普通输入走 React")

        prompt = calls[0][0][-1].content
        self.assertIn("## 相关长期记忆", prompt)
        self.assertIn("用户偏好：普通输入走 React", prompt)
        self.assertIn("当前任务：入口和 React 怎么安排？", prompt)
        self.assertTrue(any(
            message.role == "user"
            and message.content == "入口和 React 怎么安排？"
            for message in agent.conversation_messages
        ))
        self.assertFalse(any(
            message.role == "user"
            and message.content
            and "## 相关长期记忆" in message.content
            for message in agent.conversation_messages
        ))

    def test_react_agent_preserves_injected_conversation_messages(self):
        calls = []
        conversation_messages = [Message(role="user", content="上一轮的问题")]
        agent = ReactAgent(CaptureRegistry(), conversation_messages=conversation_messages)

        with patch("agent.agent_loop.chat_stream", _stream_content(calls, "继续回答")):
            agent.run("继续")

        self.assertIs(agent.conversation_messages, conversation_messages)
        self.assertEqual(calls[0][0][1].content, "上一轮的问题")
        self.assertEqual(calls[0][0][-1].content, "继续")

    def test_on_message_appended_receives_runtime_messages_immediately(self):
        persisted = []
        registry = CaptureRegistry()
        registry.tools["read"] = _StubTool("文件内容")
        agent = ReactAgent(registry, on_message_appended=persisted.append)

        def fake_stream(messages, tools=None, cancel=None):
            if not persisted or persisted[-1].role == "user":
                yield StreamEvent(
                    "tool_call",
                    {
                        "id": "call-read",
                        "type": "function",
                        "name": "read",
                        "arguments": '{"path": "demo.txt"}',
                    },
                )
                yield StreamEvent("done", None)
                return
            yield StreamEvent("content", "完成")
            yield StreamEvent("done", None)

        with patch("agent.agent_loop.chat_stream", fake_stream):
            agent.run("读取 demo.txt")

        self.assertEqual([message.role for message in persisted], ["user", "assistant", "tool", "assistant"])
        self.assertEqual(persisted[2].tool_call_id, "call-read")


class RuntimeContextBuilderTests(unittest.TestCase):
    def test_builds_context_from_branch_summary_and_long_term_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp) / "project"
            cwd.mkdir()
            session = SessionStore(root=Path(tmp) / "sessions").create(cwd)
            session.append_message(Message(role="user", content="root"))
            fork_point = session.append_message(Message(role="assistant", content="fork"))
            session.append_message(Message(role="user", content="短期对话不应该重复注入"))
            session.branch_to_with_summary(fork_point.id, summary="用户正在重构 session 和 memory。")
            long_term = TextLongTermMemory(session.path.parent.parent / "long_term.md")
            long_term.remember("用户偏好：普通输入走 React")

            context = RuntimeContextBuilder(session=session, long_term=long_term).build("React 入口")

        self.assertIn("## 分支摘要", context)
        self.assertIn("用户正在重构 session 和 memory。", context)
        self.assertIn("## 相关长期记忆", context)
        self.assertIn("用户偏好：普通输入走 React", context)
        self.assertNotIn("短期对话不应该重复注入", context)


class AgentLoopTests(unittest.TestCase):
    def test_exec_one_uses_registry_execute_as_single_tool_entrypoint(self):
        registry = _ExecuteOnlyRegistry()
        agent = AgentLoop(
            "react",
            "system",
            chat=None,
            tool_registry=registry,
        )
        tool_call = ToolCall(
            id="call-1",
            function=FunctionCall(
                name="write",
                arguments='{"path": "demo.txt", "content": "ok"}',
            ),
        )

        result = agent._exec_one(tool_call)

        self.assertEqual(result, "executed:write")
        self.assertEqual(
            registry.calls,
            [("write", {"path": "demo.txt", "content": "ok"})],
        )

    def test_hard_rejected_tool_call_stops_current_agent(self):
        calls = []

        def fake_stream(messages, tools=None, cancel=None):
            calls.append((list(messages), tools))
            if len(calls) > 1:
                raise AssertionError("硬拒绝后不应继续调用模型")
            yield StreamEvent(
                "tool_call",
                {
                    "id": "call-write",
                    "type": "function",
                    "name": "write",
                    "arguments": '{"path": "demo.txt", "content": "ok"}',
                },
            )
            yield StreamEvent("done", {"reason": "finished"})

        agent = AgentLoop(
            "react",
            "system",
            chat=None,
            tool_registry=_HardRejectRuntime(),
        )

        with patch("agent.agent_loop.chat_stream", fake_stream):
            with self.assertLogs("agent.agent_loop", level="WARNING"):
                events = list(agent.execute(Message(role="user", content="写文件")))

        done = [event for event in events if event.type == "done"][-1]
        tool_result = [event for event in events if event.type == "tool_result"][-1]
        self.assertEqual(done.data["reason"], "blocked")
        self.assertIn("用户拒绝", tool_result.data["result"])
        self.assertEqual(len(calls), 1)

    def test_blocked_tool_call_is_logged_as_warning(self):
        agent = AgentLoop(
            "react",
            "system",
            chat=None,
            tool_registry=_HardRejectRuntime(),
        )
        tool_call = ToolCall(
            id="call-write",
            function=FunctionCall(
                name="write",
                arguments='{"path": "demo.txt", "content": "ok"}',
            ),
        )

        with self.assertLogs("agent.agent_loop", level="WARNING") as logs:
            with self.assertRaises(ToolExecutionBlocked):
                agent._exec_one(tool_call)

        output = "\n".join(logs.output)
        self.assertIn("被拒绝", output)
        self.assertIn("WARNING", output)


class CliAgentTests(unittest.TestCase):
    def test_tree_and_jump_commands_are_parsed(self):
        self.assertTrue(cli.parse_tree_command("/tree"))
        self.assertFalse(cli.parse_tree_command("/tree now"))
        self.assertEqual(cli.parse_jump_command("/jump"), "")
        self.assertEqual(cli.parse_jump_command("/jump abc123"), "abc123")
        self.assertIsNone(cli.parse_jump_command("/jumpabc123"))

    def test_format_session_tree_marks_current_branch_and_leaf(self):
        with tempfile.TemporaryDirectory() as tmp:
            session, target_id, old_leaf_id = _branching_session(Path(tmp))

            tree = cli.format_session_tree(session)

        self.assertIn("会话树", tree)
        self.assertIn(target_id, tree)
        self.assertIn(old_leaf_id, tree)
        self.assertIn("assistant", tree)
        self.assertIn("旧分支问题", tree)
        self.assertIn("<- current", tree)

    def test_repl_builds_agent_with_tool_runtime_and_message_callback(self):
        runtime = ToolRuntime(ToolRegistry())
        seen = []

        def remember_registry(registry, *, conversation_messages=None, on_message_appended=None):
            seen.append((registry, conversation_messages, callable(on_message_appended)))
            return _StubReactAgent()

        import cli_app.runner as runner
        with (
            patch("cli_app.runner.load_dotenv"),
            patch("cli_app.runner.configure_logging"),
            patch("cli_app.runner.build_registry", return_value=runtime),
            patch("cli_app.runner.build_long_term_memory", return_value=_StubLongTermMemory()),
            patch("cli_app.runner.SessionStore", return_value=_StubSessionStore()),
            patch("cli_app.runner.load_mcp_config", return_value={}),
            patch("cli_app.runner.build_agent", side_effect=remember_registry),
            patch("cli_app.runner.print_message"),
            patch("builtins.input", side_effect=EOFError),
        ):
            runner.repl()

        self.assertEqual(seen, [(runtime, [], True)])

    def test_repl_tree_command_prints_session_tree(self):
        runtime = ToolRuntime(ToolRegistry())
        printed = []

        with tempfile.TemporaryDirectory() as tmp:
            session, target_id, old_leaf_id = _branching_session(Path(tmp))
            import cli_app.runner as runner
            with (
                patch("cli_app.runner.load_dotenv"),
                patch("cli_app.runner.configure_logging"),
                patch("cli_app.runner.build_registry", return_value=runtime),
                patch("cli_app.runner.build_long_term_memory", return_value=_StubLongTermMemory()),
                patch("cli_app.runner.SessionStore", return_value=_FixedSessionStore(session, Path(tmp))),
                patch("cli_app.runner.load_mcp_config", return_value={}),
                patch("cli_app.runner.build_agent", return_value=_StubReactAgent()),
                patch("cli_app.runner.print_message", side_effect=printed.append),
                patch("builtins.input", side_effect=["/tree", EOFError]),
            ):
                runner.repl()

        output = "\n".join(printed)
        self.assertIn(target_id, output)
        self.assertIn(old_leaf_id, output)
        self.assertIn("<- current", output)

    def test_repl_jump_command_moves_leaf_and_reloads_agent_history(self):
        runtime = ToolRuntime(ToolRegistry())
        agent = _StubReactAgent()

        with tempfile.TemporaryDirectory() as tmp:
            session, target_id, old_leaf_id = _branching_session(Path(tmp))
            import cli_app.runner as runner
            with (
                patch("cli_app.runner.load_dotenv"),
                patch("cli_app.runner.configure_logging"),
                patch("cli_app.runner.build_registry", return_value=runtime),
                patch("cli_app.runner.build_long_term_memory", return_value=_StubLongTermMemory()),
                patch("cli_app.runner.SessionStore", return_value=_FixedSessionStore(session, Path(tmp))),
                patch("cli_app.runner.load_mcp_config", return_value={}),
                patch("cli_app.runner.build_agent", return_value=agent),
                patch("cli_app.runner.ask_branch_navigation_choice", return_value=BranchNavigationChoice.DIRECT),
                patch("cli_app.runner.print_message"),
                patch("builtins.input", side_effect=[f"/jump {target_id}", EOFError]),
            ):
                runner.repl()

        self.assertEqual(session.get_leaf_id(), target_id)
        self.assertIn(old_leaf_id, {entry.id for entry in session.all_entries()})
        self.assertEqual([message.content for message in agent.reloaded[-1]], ["root", "fork"])

    def test_repl_jump_summary_choice_uses_summary_generator(self):
        runtime = ToolRuntime(ToolRegistry())

        with tempfile.TemporaryDirectory() as tmp:
            session, target_id, _old_leaf_id = _branching_session(Path(tmp))
            import cli_app.runner as runner
            with (
                patch("cli_app.runner.load_dotenv"),
                patch("cli_app.runner.configure_logging"),
                patch("cli_app.runner.build_registry", return_value=runtime),
                patch("cli_app.runner.build_long_term_memory", return_value=_StubLongTermMemory()),
                patch("cli_app.runner.SessionStore", return_value=_FixedSessionStore(session, Path(tmp))),
                patch("cli_app.runner.load_mcp_config", return_value={}),
                patch("cli_app.runner.build_agent", return_value=_StubReactAgent()),
                patch("cli_app.runner.ask_branch_navigation_choice", return_value=BranchNavigationChoice.SUMMARIZE),
                patch("cli_app.runner.generate_branch_summary", return_value="总结旧分支"),
                patch("cli_app.runner.print_message"),
                patch("builtins.input", side_effect=[f"/jump {target_id}", EOFError]),
            ):
                runner.repl()

        leaf = session.all_entries()[-1]
        self.assertIsInstance(leaf, BranchSummaryEntry)
        self.assertEqual(leaf.summary, "总结旧分支")

    def test_cli_default_agent_is_react_agent(self):
        agent = cli.build_agent(CaptureRegistry())

        self.assertIsInstance(agent, ReactAgent)

    def test_cli_does_not_export_plan_agent_factory(self):
        self.assertFalse(hasattr(cli, "build_plan_agent"))

    def test_build_long_term_memory_uses_project_memory_file_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            default_path = Path(tmp) / "agent_memory" / "long_term.md"
            with patch("cli_app.factories.DEFAULT_LONG_TERM_PATH", default_path):
                memory = cli.build_long_term_memory()

            self.assertEqual(memory.storage_path, default_path)
            self.assertEqual(memory.storage_path.name, "long_term.md")

    def test_run_once_routes_plain_input_to_react_agent(self):
        react = _StubReactAgent()

        with contextlib.redirect_stdout(io.StringIO()):
            cli.run_once(react, "你好")

        self.assertEqual(react.inputs, [("你好", "")])

    def test_run_once_routes_plan_command_to_react_agent(self):
        react = _StubReactAgent()

        with tempfile.TemporaryDirectory() as tmp:
            with contextlib.redirect_stdout(io.StringIO()):
                cli.run_once(react, "/plan 统计当前目录", plan_log_dir=Path(tmp))

        self.assertEqual(len(react.inputs), 1)
        self.assertIn("单 Agent 计划执行模式", react.inputs[0][0])
        self.assertIn("统计当前目录", react.inputs[0][0])

    def test_plan_run_does_not_write_legacy_plan_log_file(self):
        react = _StubReactAgent()

        with tempfile.TemporaryDirectory() as tmp:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                cli.run_once(react, "/plan 统计当前目录", plan_log_dir=Path(tmp))

            log_files = list(Path(tmp).glob("*.log"))

        self.assertEqual(log_files, [])
        self.assertNotIn("计划日志:", output.getvalue())

    def test_plain_react_run_does_not_write_plan_log_file(self):
        react = _StubReactAgent()

        with tempfile.TemporaryDirectory() as tmp:
            with contextlib.redirect_stdout(io.StringIO()):
                cli.run_once(react, "你好", plan_log_dir=Path(tmp))

            log_files = list(Path(tmp).glob("*.log"))

        self.assertEqual(log_files, [])

    def test_run_once_passes_context_to_agent_events(self):
        react = _StubReactAgent()

        with contextlib.redirect_stdout(io.StringIO()):
            cli.run_once(
                react,
                "你好",
                runtime_context_builder=_StaticRuntimeContextBuilder("## 相关长期记忆\n- fact"),
            )

        self.assertEqual(react.inputs, [("你好", "## 相关长期记忆\n- fact")])

    def test_run_once_error_prints_clean_message_without_traceback(self):
        react = _FailingReactAgent()
        output = io.StringIO()

        with self.assertLogs("cli_app.runner", level="ERROR"):
            with contextlib.redirect_stdout(output):
                cli.run_once(react, "你好")

        text = output.getvalue()
        self.assertIn("[ERROR] 执行失败: boom", text)
        self.assertNotIn("Traceback", text)

    def test_configure_logging_default_console_hides_info_logs(self):
        errors = io.StringIO()

        with _isolated_root_logger(), patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PAICLI_LOG_LEVEL", None)
            os.environ.pop("PAICLI_DEBUG_LOG", None)
            with contextlib.redirect_stderr(errors):
                cli.configure_logging()
                logging.getLogger("tests.console").info("internal info")
                logging.getLogger("tests.console").warning("visible warning")

        text = errors.getvalue()
        self.assertNotIn("internal info", text)
        self.assertIn("visible warning", text)

    def test_configure_logging_writes_debug_file_without_console_noise(self):
        errors = io.StringIO()

        with tempfile.TemporaryDirectory() as tmp:
            debug_path = Path(tmp) / "debug.log"
            with _isolated_root_logger(), patch.dict(os.environ, {}, clear=False):
                os.environ.pop("PAICLI_LOG_LEVEL", None)
                os.environ.pop("PAICLI_DEBUG_LOG", None)
                with contextlib.redirect_stderr(errors):
                    cli.configure_logging(debug_log_path=debug_path)
                    logging.getLogger("tests.debug.file").debug("deep debug detail")

            content = debug_path.read_text(encoding="utf-8")

        self.assertIn("deep debug detail", content)
        self.assertNotIn("deep debug detail", errors.getvalue())

    def test_remember_command_writes_long_term_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "long_term.md"
            memory = cli.build_long_term_memory(path)

            message = cli.handle_remember(memory, "/remember 用户偏好：默认使用 React")

            self.assertIn("已记住", message)
            self.assertEqual(list(memory), ["用户偏好：默认使用 React"])
            self.assertEqual(path.read_text(encoding="utf-8").strip(), "- 用户偏好：默认使用 React")

    def test_memory_status_shows_long_term_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = cli.build_long_term_memory(Path(tmp) / "memory.json")
            memory.remember("用户偏好：默认使用 React")

            status = cli.format_memory_status(memory)

            self.assertNotIn("short_term", status)
            self.assertNotIn("tokens", status)
            self.assertIn("long_term : 1 facts", status)

    def test_empty_long_term_file_loads_as_empty_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "long_term.md"
            path.write_text("", encoding="utf-8")

            memory = cli.build_long_term_memory(path)

            self.assertEqual(len(memory), 0)

    def test_navigate_session_branch_direct_choice_moves_leaf_without_summary(self):
        import cli_app.runner as runner

        with tempfile.TemporaryDirectory() as tmp:
            session, target_id, old_leaf_id = _branching_session(Path(tmp))

            result = runner.navigate_session_branch(
                session,
                target_id,
                choose_navigation=lambda plan: BranchNavigationChoice.DIRECT,
                build_branch_summary=lambda plan: self.fail("直接跳转不应生成摘要"),
            )

            self.assertEqual(result, BranchNavigationChoice.DIRECT)
            self.assertEqual(session.get_leaf_id(), target_id)
            self.assertFalse(any(isinstance(entry, BranchSummaryEntry) for entry in session.all_entries()))
            self.assertIn(old_leaf_id, {entry.id for entry in session.all_entries()})

    def test_navigate_session_branch_summary_choice_appends_branch_summary(self):
        import cli_app.runner as runner

        with tempfile.TemporaryDirectory() as tmp:
            session, target_id, old_leaf_id = _branching_session(Path(tmp))
            seen = []

            result = runner.navigate_session_branch(
                session,
                target_id,
                choose_navigation=lambda plan: BranchNavigationChoice.SUMMARIZE,
                build_branch_summary=lambda plan: seen.append(plan) or "离开分支摘要",
            )

            leaf = session.all_entries()[-1]
            self.assertEqual(result, BranchNavigationChoice.SUMMARIZE)
            self.assertIsInstance(leaf, BranchSummaryEntry)
            self.assertEqual(leaf.parent_id, target_id)
            self.assertEqual(leaf.from_id, old_leaf_id)
            self.assertEqual(leaf.summary, "离开分支摘要")
            self.assertEqual([entry.content for entry in [e.message for e in seen[0].leaving_entries]], ["旧分支问题"])

    def test_navigate_session_branch_cancel_choice_keeps_current_leaf(self):
        import cli_app.runner as runner

        with tempfile.TemporaryDirectory() as tmp:
            session, target_id, old_leaf_id = _branching_session(Path(tmp))

            result = runner.navigate_session_branch(
                session,
                target_id,
                choose_navigation=lambda plan: BranchNavigationChoice.CANCEL,
                build_branch_summary=lambda plan: self.fail("取消跳转不应生成摘要"),
            )

            self.assertEqual(result, BranchNavigationChoice.CANCEL)
            self.assertEqual(session.get_leaf_id(), old_leaf_id)


class TerminalBranchNavigationTests(unittest.TestCase):
    def test_ask_branch_navigation_choice_returns_summary_choice(self):
        output = io.StringIO()

        with patch("builtins.input", return_value="2"):
            choice = ask_branch_navigation_choice(out=output)

        self.assertEqual(choice, BranchNavigationChoice.SUMMARIZE)
        self.assertIn("跳转到旧消息？", output.getvalue())
        self.assertIn("总结当前分支后跳转", output.getvalue())

    def test_ask_branch_navigation_choice_reprompts_invalid_choice(self):
        output = io.StringIO()

        with patch("builtins.input", side_effect=["x", "3"]):
            choice = ask_branch_navigation_choice(out=output)

        self.assertEqual(choice, BranchNavigationChoice.CANCEL)
        self.assertIn("请输入 1、2 或 3", output.getvalue())


class _StubReactAgent:
    def __init__(self):
        self.inputs = []
        self.reloaded = []

    def events(self, user_input, context=""):
        self.inputs.append((user_input, context))
        yield StreamEvent("content", f"react:{user_input}")
        yield StreamEvent("done", {"reason": "finished"})

    def cancel(self):
        return None

    def replace_conversation_messages(self, messages):
        self.reloaded.append(list(messages))


class _FailingReactAgent:
    def events(self, user_input, context=""):
        raise RuntimeError("boom")

    def cancel(self):
        return None


class _StaticRuntimeContextBuilder:
    def __init__(self, context):
        self.context = context

    def build(self, query):
        return self.context


class _StubLongTermMemory:
    pass


class _StubSession:
    path = Path(".")

    def __init__(self):
        self.appended = []

    def messages(self):
        return []

    def append_message(self, message):
        self.appended.append(message)


class _StubSessionStore:
    def __init__(self):
        self.session = _StubSession()

    def open_recent(self, cwd):
        return self.session

    def create(self, cwd):
        return self.session

    def project_dir(self, cwd):
        return Path("agent_memory")


class _FixedSessionStore:
    def __init__(self, session, project_dir):
        self.session = session
        self._project_dir = Path(project_dir)

    def open_recent(self, cwd):
        return self.session

    def create(self, cwd):
        return self.session

    def project_dir(self, cwd):
        return self._project_dir


def _branching_session(tmp: Path):
    cwd = tmp / "project"
    cwd.mkdir()
    session = SessionStore(root=tmp / "sessions").create(cwd)
    session.append_message(Message(role="user", content="root"))
    target = session.append_message(Message(role="assistant", content="fork"))
    old_leaf = session.append_message(Message(role="user", content="旧分支问题"))
    return session, target.id, old_leaf.id


def _stream_content(calls, content):
    def fake_stream(messages, tools=None, cancel=None):
        calls.append((list(messages), tools))
        yield StreamEvent("content", content)
        yield StreamEvent("done", {"reason": "finished"})

    return fake_stream


@contextlib.contextmanager
def _isolated_root_logger():
    root = logging.getLogger()
    old_handlers = list(root.handlers)
    old_level = root.level
    for handler in old_handlers:
        root.removeHandler(handler)
    try:
        yield root
    finally:
        for handler in list(root.handlers):
            root.removeHandler(handler)
            handler.close()
        for handler in old_handlers:
            root.addHandler(handler)
        root.setLevel(old_level)


class _StubTool:
    def __init__(self, result):
        self.result = result

    def execute(self, arguments):
        return self.result


class _ExecuteOnlyRegistry:
    def __init__(self):
        self.calls = []

    def get(self, name):
        raise AssertionError("工具执行必须通过 registry.execute()")

    def execute(self, name, arguments):
        self.calls.append((name, arguments))
        return f"executed:{name}"

    def get_all_definitions(self):
        return []


class _HardRejectRuntime:
    def get_all_definitions(self):
        return []

    def execute(self, name, arguments):
        raise ToolExecutionBlocked("用户拒绝")


class _ToolDefinitionRegistry:
    def get_all_definitions(self):
        return [
            {
                "type": "function",
                "function": {
                    "name": "read",
                    "description": "读取文件内容",
                    "parameters": {},
                },
            }
        ]

    def execute(self, name, arguments):
        return "executed"


class BashToolTests(unittest.TestCase):
    def test_bash_supports_ls_in_project_shell(self):
        result = BashTool().execute({"command": "ls -l ."})

        self.assertIn("agent", result)
        self.assertNotIn("not recognized", result)

    def test_bash_reports_exit_code_when_stderr_is_empty(self):
        result = BashTool().execute({
            "command": 'python -c "import sys; sys.exit(7)"',
        })

        self.assertIn("命令执行失败（退出码", result)
        self.assertIn("没有 stdout/stderr 输出", result)

    def test_bash_times_out(self):
        result = BashTool().execute({
            "command": 'python -c "import time; time.sleep(2)"',
            "timeout_seconds": 1,
        })

        self.assertIn("命令超时", result)
        self.assertIn("超过 1 秒", result)


class PiStyleToolTests(unittest.TestCase):
    def test_read_write_edit_use_pi_style_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "note.txt"

            write_out = WriteTool().execute({"path": str(path), "content": "hello old"})
            read_out = ReadTool().execute({"path": str(path)})
            edit_out = EditTool().execute({
                "path": str(path),
                "old_text": "old",
                "new_text": "new",
            })

            self.assertEqual(WriteTool().name, "write")
            self.assertEqual(ReadTool().name, "read")
            self.assertEqual(EditTool().name, "edit")
            self.assertIn("写入成功", write_out)
            self.assertEqual(read_out, "hello old")
            self.assertIn("编辑成功", edit_out)
            self.assertEqual(path.read_text(encoding="utf-8"), "hello new")

    def test_edit_rejects_ambiguous_replacement(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "note.txt"
            path.write_text("same\nsame\n", encoding="utf-8")

            out = EditTool().execute({
                "path": str(path),
                "old_text": "same",
                "new_text": "other",
            })

            self.assertIn("匹配到 2 处", out)
            self.assertEqual(path.read_text(encoding="utf-8"), "same\nsame\n")

    def test_bash_ls_grep_find_use_pi_style_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "src" / "app.py").write_text("print('needle')\n", encoding="utf-8")
            (root / "README.md").write_text("needle docs\n", encoding="utf-8")

            ls_out = LsTool().execute({"path": str(root)})
            grep_out = GrepTool().execute({"path": str(root), "pattern": "needle"})
            find_out = FindTool().execute({"path": str(root), "name": "*.py"})
            bash_out = BashTool().execute({"command": "python --version"})

            self.assertEqual(BashTool().name, "bash")
            self.assertEqual(LsTool().name, "ls")
            self.assertEqual(GrepTool().name, "grep")
            self.assertEqual(FindTool().name, "find")
            self.assertIn("src", ls_out)
            self.assertIn("README.md", ls_out)
            self.assertIn("app.py:1:print('needle')", grep_out)
            self.assertIn("README.md:1:needle docs", grep_out)
            self.assertIn("src/app.py", find_out.replace("\\", "/"))
            self.assertIn("Python", bash_out)

    def test_cli_registry_exposes_only_canonical_tool_names(self):
        registry = cli.build_registry()
        names = [d["function"]["name"] for d in registry.get_all_definitions()]

        for name in ["read", "write", "edit", "bash", "ls", "grep", "find", "web_search", "web_fetch"]:
            self.assertIn(name, names)
        for name in ["read_file", "write_file", "list_dir", "execute_command"]:
            self.assertNotIn(name, names)
        for name in ["index_codebase", "search_code"]:
            self.assertNotIn(name, names)

    def test_registry_executes_pi_style_tools_through_same_entrypoint(self):
        registry = ToolRegistry()
        registry.register(WriteTool()).register(ReadTool())
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.txt"

            registry.execute("write", {"path": str(path), "content": "ok"})
            out = registry.execute("read", {"path": str(path)})

        self.assertEqual(out, "ok")

    def test_file_write_tools_do_not_require_approval_by_default(self):
        self.assertFalse(WriteTool().requires_approval({"path": "demo.txt"}))
        self.assertFalse(EditTool().requires_approval({"path": "demo.txt"}))
        self.assertTrue(BashTool().requires_approval({"command": "python --version"}))


if __name__ == "__main__":
    unittest.main()
