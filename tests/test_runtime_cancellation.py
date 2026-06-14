import queue
import tempfile
import threading
import time
import unittest
from pathlib import Path

from agent.agent_loop import AgentLoop
from app_runtime import AppRuntime
from app_runtime.tasks import RuntimeJournal, StreamCaptureState, capture_stream_to_queue
from cli_app.router import ReplRouter
from llm import FunctionCall, Message, ToolCall
from sessions import SessionStore
from tooling import BashTool, Tool, ToolRegistry
from tooling.runtime import ToolRuntime


class ChunkStream:
    def __init__(self, chunks):
        self._chunks = list(chunks)
        self.read_calls = 0

    def read1(self, _size):
        self.read_calls += 1
        if not self._chunks:
            return b""
        return self._chunks.pop(0)


class StreamCaptureTests(unittest.TestCase):
    def test_reader_keeps_draining_after_queue_full_and_limit_exceeded(self):
        stream = ChunkStream([b"a" * 4, b"b" * 4, b"c" * 4, b"d" * 4])
        output = queue.Queue(maxsize=1)
        state = StreamCaptureState("stdout")

        capture_stream_to_queue(
            stream,
            "stdout",
            output,
            state,
            limit_bytes=8,
            chunk_size=4,
        )

        self.assertEqual(stream.read_calls, 5)
        self.assertEqual(output.qsize(), 1)
        self.assertTrue(state.truncated_by_queue)
        self.assertTrue(state.truncated_by_limit)
        self.assertGreater(state.dropped_bytes, 0)


class RuntimeJournalTests(unittest.TestCase):
    def test_journal_persists_cancelled_effectful_tool_notice(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = RuntimeJournal(Path(tmp) / "runtime_journal.jsonl")
            journal.append("turn_started", turn_id="turn-1", task_kind="interactive_turn")
            journal.append(
                "tool_started",
                turn_id="turn-1",
                tool_call_id="tool-1",
                name="bash",
                effect="execute",
                args_preview="mkdir new_folder",
            )
            journal.append("turn_cancelled", turn_id="turn-1", reason="ctrl_c")

            events = journal.load()
            notice = journal.format_last_cancelled_turn_notice()

        self.assertEqual([event["type"] for event in events], ["turn_started", "tool_started", "turn_cancelled"])
        self.assertIn("上一轮被用户中断", notice)
        self.assertIn("mkdir new_folder", notice)
        self.assertIn("物理状态可能已经改变", notice)
        self.assertNotIn("下一步必须先检查现实状态", notice)
        self.assertIn("如果当前用户只是询问上一轮发生了什么，先直接说明中断事实，不要主动调用工具", notice)


class ContextRecordingTool(Tool):
    effect = "execute"

    def __init__(self):
        self.context = None

    @property
    def name(self):
        return "record_context"

    @property
    def description(self):
        return "record context"

    @property
    def parameters(self):
        return {"type": "object", "properties": {}}

    def execute(self, _arguments):
        return "missing context"

    def execute_with_context(self, _arguments, context):
        self.context = context
        return "ok"


class ToolExecutionContextTests(unittest.TestCase):
    def test_tool_runtime_records_effectful_tool_journal_and_passes_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            tool = ContextRecordingTool()
            registry = ToolRegistry()
            registry.register(tool)
            runtime = ToolRuntime(registry)
            journal = RuntimeJournal(Path(tmp) / "runtime_journal.jsonl")
            cancel = threading.Event()

            result = runtime.execute(
                "record_context",
                {},
                cancel=cancel,
                journal=journal,
                turn_id="turn-1",
                tool_call_id="tool-1",
            )
            events = journal.load()

        self.assertEqual(result, "ok")
        self.assertIs(tool.context.cancel, cancel)
        self.assertEqual(tool.context.turn_id, "turn-1")
        self.assertEqual(tool.context.tool_call_id, "tool-1")
        self.assertEqual([event["type"] for event in events], ["tool_started", "tool_finished"])

    def test_agent_loop_passes_turn_context_to_tool_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            tool = ContextRecordingTool()
            registry = ToolRegistry()
            registry.register(tool)
            runtime = ToolRuntime(registry)
            journal = RuntimeJournal(Path(tmp) / "runtime_journal.jsonl")
            cancel = threading.Event()
            loop = AgentLoop(
                "react",
                "system",
                chat=lambda *args, **kwargs: None,
                tool_registry=runtime,
                cancel=cancel,
                journal=journal,
                turn_id="turn-1",
            )

            result = loop._exec_one(ToolCall(
                id="tool-1",
                type="function",
                function=FunctionCall(name="record_context", arguments="{}"),
            ))
            events = journal.load()

        self.assertEqual(result, "ok")
        self.assertIs(tool.context.cancel, cancel)
        self.assertEqual(tool.context.turn_id, "turn-1")
        self.assertEqual(tool.context.tool_call_id, "tool-1")
        self.assertEqual([event["type"] for event in events], ["tool_started", "tool_finished"])


class SessionBatchCommitTests(unittest.TestCase):
    def test_append_messages_persists_one_turn_batch_and_reopens_messages(self):
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp) / "project"
            cwd.mkdir()
            store = SessionStore(Path(tmp) / "sessions")
            session = store.create(cwd)

            session.append_messages([
                Message(role="user", content="hi"),
                Message(role="assistant", content="hello"),
            ])

            raw_lines = (session.path / "messages.jsonl").read_text(encoding="utf-8").splitlines()
            reopened = store.open(cwd, session.meta.session_id)

        self.assertTrue(any('"type": "turn"' in line for line in raw_lines))
        self.assertEqual([(message.role, message.content) for message in reopened.messages()], [
            ("user", "hi"),
            ("assistant", "hello"),
        ])


class BashCancellationTests(unittest.TestCase):
    def test_bash_command_can_be_cancelled_without_waiting_for_timeout(self):
        registry = ToolRegistry()
        registry.register(BashTool())
        runtime = ToolRuntime(registry)
        cancel = threading.Event()

        def cancel_soon():
            time.sleep(0.2)
            cancel.set()

        thread = threading.Thread(target=cancel_soon, daemon=True)
        thread.start()

        started = time.monotonic()
        result = runtime.execute(
            "bash",
            {"command": "Start-Sleep -Seconds 5; Write-Output done", "timeout_seconds": 10},
            cancel=cancel,
        )
        elapsed = time.monotonic() - started

        self.assertLess(elapsed, 3)
        self.assertIn("命令已取消", result)
        self.assertNotIn("stdout:\ndone", result)


class CaptureRenderer:
    def __init__(self):
        self.messages = []
        self.events = []
        self.cancel_requested_count = 0

    def message(self, message):
        self.messages.append(message)

    def agent_event(self, event, *, agent_name="react"):
        self.events.append(event)

    def cancel_requested(self):
        self.cancel_requested_count += 1


class BufferedAgent:
    def __init__(self, on_message_appended=None):
        self.on_message_appended = on_message_appended

    def append(self, role, content):
        if self.on_message_appended is not None:
            self.on_message_appended(Message(role=role, content=content))


class RouterWorkerTests(unittest.TestCase):
    def test_worker_turn_commits_buffer_only_after_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp) / "project"
            cwd.mkdir()
            runtime = AppRuntime.create(
                cwd,
                tool_runtime=ToolRuntime(ToolRegistry()),
                session_store=SessionStore(Path(tmp) / "sessions"),
                long_term_memory=[],
            )
            renderer = CaptureRenderer()

            def build_agent(_runtime, *, conversation_messages=None, on_message_appended=None):
                return BufferedAgent(on_message_appended=on_message_appended)

            def run_agent_once(agent, user_input, **_kwargs):
                agent.append("user", user_input)
                agent.append("assistant", "reply")
                return "reply"

            repl_router = ReplRouter(
                app_runtime=runtime,
                renderer=renderer,
                build_agent=build_agent,
                run_agent_once=run_agent_once,
                run_interactive_in_worker=True,
            )

            self.assertTrue(repl_router.route("hello"))
            task = runtime.task_runtime.current_interactive
            self.assertIsNotNone(task)
            task.thread.join(timeout=3)

            messages = repl_router.session.messages()
            raw_lines = (repl_router.session.path / "messages.jsonl").read_text(encoding="utf-8").splitlines()

        self.assertEqual([(message.role, message.content) for message in messages], [
            ("user", "hello"),
            ("assistant", "reply"),
        ])
        self.assertTrue(any('"type": "turn"' in line for line in raw_lines))

    def test_cancelled_worker_turn_does_not_commit_buffer_and_writes_journal(self):
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp) / "project"
            cwd.mkdir()
            runtime = AppRuntime.create(
                cwd,
                tool_runtime=ToolRuntime(ToolRegistry()),
                session_store=SessionStore(Path(tmp) / "sessions"),
                long_term_memory=[],
            )
            renderer = CaptureRenderer()
            started = threading.Event()

            def build_agent(_runtime, *, conversation_messages=None, on_message_appended=None):
                return BufferedAgent(on_message_appended=on_message_appended)

            def run_agent_once(agent, user_input, *, cancel=None, **_kwargs):
                agent.append("user", user_input)
                started.set()
                cancel.wait(timeout=3)
                agent.append("assistant", "late reply")
                return "late reply"

            repl_router = ReplRouter(
                app_runtime=runtime,
                renderer=renderer,
                build_agent=build_agent,
                run_agent_once=run_agent_once,
                run_interactive_in_worker=True,
            )

            self.assertTrue(repl_router.route("slow"))
            self.assertTrue(started.wait(timeout=3))
            self.assertTrue(repl_router.cancel_current(reason="test_cancel"))
            task = runtime.task_runtime.current_interactive
            task.thread.join(timeout=3)

            messages = repl_router.session.messages()
            events = RuntimeJournal(repl_router.session.path / "runtime_journal.jsonl").load()

        self.assertEqual(messages, [])
        self.assertIn("turn_cancelled", [event["type"] for event in events])

    def test_cancel_request_is_visible_to_next_turn_before_cancelled_worker_exits(self):
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp) / "project"
            cwd.mkdir()
            runtime = AppRuntime.create(
                cwd,
                tool_runtime=ToolRuntime(ToolRegistry()),
                session_store=SessionStore(Path(tmp) / "sessions"),
                long_term_memory=[],
            )
            renderer = CaptureRenderer()
            first_started = threading.Event()
            release_first = threading.Event()
            second_context_ready = threading.Event()
            contexts: dict[str, str] = {}

            def build_agent(_runtime, *, conversation_messages=None, on_message_appended=None):
                return BufferedAgent(on_message_appended=on_message_appended)

            def run_agent_once(agent, user_input, *, runtime_context_builder=None, **_kwargs):
                contexts[user_input] = runtime_context_builder.build(user_input)
                if user_input == "slow":
                    first_started.set()
                    release_first.wait(timeout=3)
                    return ""
                second_context_ready.set()
                return "ok"

            repl_router = ReplRouter(
                app_runtime=runtime,
                renderer=renderer,
                build_agent=build_agent,
                run_agent_once=run_agent_once,
                run_interactive_in_worker=True,
            )

            self.assertTrue(repl_router.route("slow"))
            self.assertTrue(first_started.wait(timeout=3))
            first_task = runtime.task_runtime.current_interactive
            self.assertTrue(repl_router.cancel_current(reason="test_cancel"))

            self.assertTrue(repl_router.route("上一轮发生了什么？"))
            second_task = runtime.task_runtime.current_interactive
            self.assertTrue(second_context_ready.wait(timeout=3))

            release_first.set()
            first_task.thread.join(timeout=3)
            second_task.thread.join(timeout=3)

        self.assertIn("上一轮被用户中断", contexts["上一轮发生了什么？"])


if __name__ == "__main__":
    unittest.main()
