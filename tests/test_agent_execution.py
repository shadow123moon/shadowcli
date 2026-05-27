import contextlib
import io
import inspect
import logging
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cli_app as cli
from agent.react_agent import ReactAgent
from extensions.tool_runtime import ToolExecutionBlocked
from llm import ChatResponse, FunctionCall, Message, ToolCall
from llm.client import StreamEvent
from memory_pythonic import MemoryManager
from multi_agent import AgentOrchestrator, AgentRole, ExecutionStep, SubAgent
from multi_agent.sub_agent import PLANNER_PROMPT, _tool_action, _worker_prompt
from planning import Plan, Task, TaskType
from tooling import (
    BashTool,
    EditTool,
    ExecuteCommandTool,
    FindTool,
    GrepTool,
    LsTool,
    ReadTool,
    ToolRegistry,
    WriteFileTool,
    WriteTool,
)


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


class ExecutionPlanTests(unittest.TestCase):
    def test_compute_execution_order_keeps_dependencies_before_dependents(self):
        plan = Plan("create demo")
        plan.add_task(Task("task_1", "create directory", TaskType.COMMAND))
        plan.add_task(Task("task_2", "write main", TaskType.FILE_WRITE, ["task_1"]))
        plan.add_task(Task("task_3", "write readme", TaskType.FILE_WRITE, ["task_1"]))
        plan.add_task(Task("task_4", "run main", TaskType.COMMAND, ["task_2"]))
        plan.add_task(Task("task_5", "list directory", TaskType.COMMAND, ["task_4"]))

        self.assertTrue(plan.compute_execution_order())

        self.assertLess(plan.execution_order.index("task_1"), plan.execution_order.index("task_2"))
        self.assertLess(plan.execution_order.index("task_1"), plan.execution_order.index("task_3"))
        self.assertLess(plan.execution_order.index("task_2"), plan.execution_order.index("task_4"))
        self.assertLess(plan.execution_order.index("task_4"), plan.execution_order.index("task_5"))


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


class ReactAgentTests(unittest.TestCase):
    def test_runs_single_react_turn_with_streaming_chat(self):
        calls = []
        agent = ReactAgent(CaptureRegistry())

        with patch("multi_agent.sub_agent.chat_stream", _stream_content(calls, "你好，我是 ReAct 助手")):
            with contextlib.redirect_stdout(io.StringIO()):
                result = agent.run("你好")

        self.assertEqual(result, "你好，我是 ReAct 助手")
        self.assertEqual(calls[0][0][-1].content, "你好")
        self.assertIsNone(calls[0][1])

    def test_react_greeting_does_not_receive_tools(self):
        calls = []
        agent = ReactAgent(_ToolDefinitionRegistry())

        with patch("multi_agent.sub_agent.chat_stream", _stream_content(calls, "你好")):
            with contextlib.redirect_stdout(io.StringIO()):
                agent.run("你好")

        self.assertEqual([tools for _, tools in calls], [None])

    def test_react_file_task_receives_tools(self):
        calls = []
        agent = ReactAgent(_ToolDefinitionRegistry())

        with patch("multi_agent.sub_agent.chat_stream", _stream_content(calls, "可以读取")):
            with contextlib.redirect_stdout(io.StringIO()):
                agent.run("读取 cli_app/runner.py 文件")

        self.assertIsNotNone(calls[0][1])
        self.assertEqual(calls[0][1][0]["function"]["name"], "read")

    def test_records_react_turn_in_short_term_memory(self):
        memory = MemoryManager()
        agent = ReactAgent(CaptureRegistry(), memory_manager=memory)

        with patch("multi_agent.sub_agent.chat_stream", _stream_content([], "记住了")):
            with contextlib.redirect_stdout(io.StringIO()):
                agent.run("以后默认用 React")

        contents = [entry.content for entry in memory.short_term]
        self.assertEqual(contents, ["以后默认用 React", "记住了"])

    def test_react_turn_injects_recent_short_term_and_relevant_long_term(self):
        calls = []

        with tempfile.TemporaryDirectory() as tmp:
            memory = MemoryManager(long_term_path=Path(tmp) / "memory.json")
            memory.add_user("项目入口是 cli.py")
            memory.remember("用户偏好：普通输入走 React")
            agent = ReactAgent(CaptureRegistry(), memory_manager=memory)

            with patch("multi_agent.sub_agent.chat_stream", _stream_content(calls, "按你的偏好来")):
                with contextlib.redirect_stdout(io.StringIO()):
                    agent.run("入口和 React 怎么安排？")

        prompt = calls[0][0][-1].content
        self.assertIn("## 记忆上下文", prompt)
        self.assertIn("项目入口是 cli.py", prompt)
        self.assertIn("用户偏好：普通输入走 React", prompt)
        self.assertIn("当前任务：入口和 React 怎么安排？", prompt)


class MemoryManagerContextTests(unittest.TestCase):
    def test_context_for_concatenates_short_term_and_searches_long_term(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = MemoryManager(long_term_path=Path(tmp) / "memory.json")
            memory.add_user("项目入口是 cli.py")
            memory.add_assistant("普通输入默认走 React")
            memory.add_assistant("完全无关的短期反馈：今天心情不错")
            memory.remember("用户偏好：/plan 才走多 Agent")
            memory.remember("用户偏好：命令环境是 PowerShell")

            context = memory.context_for("React 和 /plan 入口")

        self.assertIn("## 记忆上下文", context)
        self.assertIn("[短期/user] 项目入口是 cli.py", context)
        self.assertIn("[短期/assistant] 普通输入默认走 React", context)
        self.assertIn("[短期/assistant] 完全无关的短期反馈：今天心情不错", context)
        self.assertIn("[长期/fact] 用户偏好：/plan 才走多 Agent", context)
        self.assertNotIn("用户偏好：命令环境是 PowerShell", context)
        self.assertIn("相关长期记忆", context)


class AgentOrchestratorMemoryTests(unittest.TestCase):
    def test_planner_injects_recent_short_term_and_relevant_long_term(self):
        calls = []

        with tempfile.TemporaryDirectory() as tmp:
            memory = MemoryManager(long_term_path=Path(tmp) / "memory.json")
            memory.add_user("项目入口是 cli.py")
            memory.remember("用户偏好：普通输入走 React")
            orchestrator = AgentOrchestrator(chat=None, tool_registry=CaptureRegistry(), memory_manager=memory)

            import asyncio
            with patch("multi_agent.sub_agent.chat_stream", _stream_content(calls, '{"steps": []}')):
                with contextlib.redirect_stdout(io.StringIO()):
                    asyncio.run(orchestrator.run("根据 React 入口规划一下"))

        prompt = calls[0][0][-1].content
        self.assertIn("## 记忆上下文", prompt)
        self.assertIn("项目入口是 cli.py", prompt)
        self.assertIn("用户偏好：普通输入走 React", prompt)
        self.assertIn("请为以下任务制定执行计划", prompt)
        self.assertIn("当前任务：请为以下任务制定执行计划", prompt)


class AgentOrchestratorPlanTests(unittest.TestCase):
    def test_plan_execution_does_not_call_reviewer(self):
        roles = []

        def fake_stream(messages, tools=None, cancel=None):
            system = messages[0].content
            if "任务规划专家" in system:
                roles.append("planner")
                yield StreamEvent("content", '{"steps": [{"description": "直接分析", "dependencies": []}]}')
                yield StreamEvent("done", {"reason": "finished"})
                return
            if "质量检查专家" in system:
                roles.append("reviewer")
                yield StreamEvent("content", '{"approved": false, "issues": ["不应调用"]}')
                yield StreamEvent("done", {"reason": "finished"})
                return
            roles.append("worker")
            yield StreamEvent("content", "执行完成")
            yield StreamEvent("done", {"reason": "finished"})

        orchestrator = AgentOrchestrator(chat=None, tool_registry=CaptureRegistry())

        import asyncio
        with patch("multi_agent.sub_agent.chat_stream", fake_stream):
            with contextlib.redirect_stdout(io.StringIO()):
                result = asyncio.run(orchestrator.run("做一个轻量计划"))

        self.assertEqual(roles, ["planner", "worker"])
        self.assertIn("执行完成", result)

    def test_orchestrator_contains_only_planner_and_workers(self):
        orchestrator = AgentOrchestrator(lambda messages, tools=None: ChatResponse(content=""), CaptureRegistry())

        roles = [agent.role for agent in orchestrator]

        self.assertEqual(roles, [AgentRole.PLANNER, AgentRole.WORKER, AgentRole.WORKER])
        self.assertEqual(len(orchestrator), 3)
        self.assertFalse(hasattr(orchestrator, "reviewer"))

    def test_worker_prompt_discourages_repeated_commands(self):
        prompt = _worker_prompt("")
        self.assertIn("不要为了同一个目的反复调用等价命令", prompt)
        self.assertIn("可以重试一次", prompt)
        self.assertIn("不要重复执行完全相同或仅形式不同的命令", prompt)

    def test_planner_prompt_requires_small_executable_steps(self):
        self.assertIn("每个步骤必须足够小", PLANNER_PROMPT)
        self.assertIn("不要把多个文件的大规模实现合并成一个步骤", PLANNER_PROMPT)
        self.assertIn("实现和验证应拆成不同步骤", PLANNER_PROMPT)

    def test_planner_prompt_defaults_to_minimal_demo_loop(self):
        self.assertIn("最小可验证闭环", PLANNER_PROMPT)
        self.assertIn("不要主动规划安装依赖", PLANNER_PROMPT)
        self.assertIn("不要规划启动长驻服务", PLANNER_PROMPT)
        self.assertIn("不要把创建目录单独拆成步骤", PLANNER_PROMPT)
        self.assertIn("短命令", PLANNER_PROMPT)
        self.assertIn("MVP", PLANNER_PROMPT)

    def test_worker_prompt_limits_scope_and_stops_after_current_step(self):
        prompt = _worker_prompt("")
        self.assertIn("只完成当前步骤描述的范围", prompt)
        self.assertIn("不要主动扩展到后续计划步骤", prompt)
        self.assertIn("关键验证已经通过后，立即输出最终结果", prompt)

    def test_worker_prompt_limits_environment_probe_and_long_running_commands(self):
        prompt = _worker_prompt("")
        self.assertIn("环境检查最多执行 1-2 条命令", prompt)
        self.assertIn("不要运行 pip list", prompt)
        self.assertIn("不要安装依赖", prompt)
        self.assertIn("不要启动前台长驻服务", prompt)
        self.assertIn("conda run -n <环境名>", prompt)

    def test_worker_prompt_avoids_app_run_entrypoint_when_service_not_requested(self):
        prompt = _worker_prompt("")
        self.assertIn("不要主动写", prompt)
        self.assertIn("app.run", prompt)
        self.assertIn("uvicorn.run", prompt)
        self.assertIn("暴露 app 对象", prompt)

    def test_worker_prompt_avoids_redundant_file_and_verification_tools(self):
        prompt = _worker_prompt("")
        self.assertIn("write 工具会自动创建父目录", prompt)
        self.assertIn("不要为了创建目录单独调用 bash mkdir", prompt)
        self.assertIn("不要创建临时测试文件", prompt)
        self.assertIn("不要在验证成功后再执行 python --version", prompt)

class SubAgentToolLogTests(unittest.TestCase):
    def test_sub_agent_exposes_only_streaming_execute_entrypoint(self):
        self.assertFalse(hasattr(SubAgent, "execute_batch"))

    def test_sub_agent_does_not_store_unused_memory_manager(self):
        agent = SubAgent(
            "react",
            AgentRole.REACT,
            chat=None,
            tool_registry=CaptureRegistry(),
        )

        self.assertNotIn("memory_manager", inspect.signature(SubAgent).parameters)
        self.assertFalse(hasattr(agent, "memory_manager"))

    def test_tool_action_truncates_long_command_preview(self):
        long_command = "python -c " + "print('hello world'); " * 10

        action = _tool_action("bash", {"command": long_command})

        self.assertTrue(action.startswith("执行命令："))
        self.assertIn("...", action)
        self.assertNotIn("print('hello world'); " * 4, action)

    def test_exec_one_uses_registry_execute_as_single_tool_entrypoint(self):
        registry = _ExecuteOnlyRegistry()
        agent = SubAgent(
            "react",
            AgentRole.REACT,
            chat=lambda messages, tools=None: ChatResponse(content=""),
            tool_registry=registry,
        )
        tool_call = ToolCall(
            id="call-1",
            function=FunctionCall(
                name="write_file",
                arguments='{"path": "demo.txt", "content": "ok"}',
            ),
        )

        result = agent._exec_one(tool_call)

        self.assertEqual(result, "executed:write_file")
        self.assertEqual(
            registry.calls,
            [("write_file", {"path": "demo.txt", "content": "ok"})],
        )

    def test_execute_command_log_includes_command(self):
        registry = CaptureRegistry()
        registry.tools["execute_command"] = _StubTool("done")
        agent = SubAgent(
            "react",
            AgentRole.REACT,
            chat=lambda messages, tools=None: ChatResponse(content=""),
            tool_registry=registry,
        )
        tool_call = ToolCall(
            id="call-1",
            function=FunctionCall(
                name="execute_command",
                arguments='{"command": "python --version"}',
            ),
        )

        with self.assertLogs("multi_agent.sub_agent", level="INFO") as logs:
            result = agent._exec_one(tool_call)

        self.assertEqual(result, "done")
        output = "\n".join(logs.output)
        self.assertIn("执行命令：python --version", output)
        self.assertNotIn("完成，结果", output)

    def test_tool_debug_log_includes_full_result_for_plan_log(self):
        full_result = "命令输出：" + ("x" * 300) + "FULL_RESULT_TAIL"
        registry = CaptureRegistry()
        registry.tools["bash"] = _StubTool(full_result)
        agent = SubAgent(
            "worker-1",
            AgentRole.WORKER,
            chat=lambda messages, tools=None: ChatResponse(content=""),
            tool_registry=registry,
        )
        tool_call = ToolCall(
            id="call-bash",
            function=FunctionCall(
                name="bash",
                arguments='{"command": "demo"}',
            ),
        )

        with self.assertLogs("multi_agent.sub_agent", level="DEBUG") as logs:
            agent._exec_one(tool_call)

        self.assertIn("FULL_RESULT_TAIL", "\n".join(logs.output))

    def test_tool_log_includes_current_plan_step(self):
        registry = CaptureRegistry()
        registry.tools["write"] = _StubTool("done")
        calls = []

        def fake_stream(messages, tools=None, cancel=None):
            calls.append((list(messages), tools))
            if len(calls) == 1:
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
                return
            yield StreamEvent("content", "写完了")
            yield StreamEvent("done", {"reason": "finished"})

        orchestrator = AgentOrchestrator(chat=None, tool_registry=registry, worker_count=1)
        step = ExecutionStep(id="step_7", description="写入演示文件")
        output = io.StringIO()

        import asyncio
        with patch("multi_agent.sub_agent.chat_stream", fake_stream):
            with self.assertLogs("multi_agent.sub_agent", level="INFO") as logs:
                asyncio.run(
                    orchestrator.execution.run_step(
                        step,
                        orchestrator.workers[0],
                        context="",
                        out=output,
                    )
                )

        self.assertEqual(step.result, "写完了")
        self.assertIn("[step_7", "\n".join(logs.output))

    def test_file_tool_logs_include_target_path(self):
        registry = CaptureRegistry()
        registry.tools["read_file"] = _StubTool("read done")
        registry.tools["write_file"] = _StubTool("write done")
        agent = SubAgent(
            "worker-1",
            AgentRole.WORKER,
            chat=lambda messages, tools=None: ChatResponse(content=""),
            tool_registry=registry,
        )

        read_call = ToolCall(
            id="call-read",
            function=FunctionCall(name="read_file", arguments='{"path": "cli.py"}'),
        )
        write_call = ToolCall(
            id="call-write",
            function=FunctionCall(
                name="write_file",
                arguments='{"path": "demo/main.py", "content": "print(1)"}',
            ),
        )

        with self.assertLogs("multi_agent.sub_agent", level="INFO") as logs:
            agent._exec_one(read_call)
            agent._exec_one(write_call)

        output = "\n".join(logs.output)
        self.assertIn("读取文件：cli.py", output)
        self.assertIn("写入文件：demo/main.py，内容 8 字", output)

    def test_bash_result_event_can_be_rendered_to_output(self):
        registry = CaptureRegistry()
        registry.tools["bash"] = _StubTool("命令执行失败（退出码 1）\nstderr: boom")
        calls = []

        def fake_stream(messages, tools=None, cancel=None):
            calls.append((list(messages), tools))
            if len(calls) == 1:
                yield StreamEvent(
                    "tool_call",
                    {
                        "id": "call-bash",
                        "type": "function",
                        "name": "bash",
                        "arguments": '{"command": "bad command"}',
                    },
                )
                yield StreamEvent("done", {"reason": "finished"})
                return
            yield StreamEvent("content", "收尾")
            yield StreamEvent("done", {"reason": "finished"})

        agent = SubAgent(
            "worker-1",
            AgentRole.WORKER,
            chat=None,
            tool_registry=registry,
        )

        output = io.StringIO()
        with patch("multi_agent.sub_agent.chat_stream", fake_stream):
            events = list(agent.execute(Message(role="user", content="运行命令")))
        for event in events:
            if event.type == "tool_result":
                from ui import print_command_result

                print_command_result(agent.name, event.data["name"], event.data["result"], output)

        text = output.getvalue()
        self.assertIn("📤 [worker-1] bash 结果", text)
        self.assertIn("命令执行失败（退出码 1）", text)

    def test_hard_rejected_tool_call_stops_current_agent(self):
        registry = _HardRejectRuntime()
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

        agent = SubAgent(
            "react",
            AgentRole.REACT,
            chat=None,
            tool_registry=registry,
        )

        with patch("multi_agent.sub_agent.chat_stream", fake_stream):
            events = list(agent.execute(Message(role="user", content="写文件")))

        done = [event for event in events if event.type == "done"][-1]
        tool_result = [event for event in events if event.type == "tool_result"][-1]
        self.assertEqual(done.data["reason"], "blocked")
        self.assertIn("用户拒绝", tool_result.data["result"])
        self.assertEqual(len(calls), 1)

    def test_blocked_tool_call_is_not_logged_as_warning(self):
        agent = SubAgent(
            "react",
            AgentRole.REACT,
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

        with self.assertLogs("multi_agent.sub_agent", level="INFO") as logs:
            with self.assertRaises(ToolExecutionBlocked):
                agent._exec_one(tool_call)

        output = "\n".join(logs.output)
        self.assertIn("被拒绝", output)
        self.assertNotIn("WARNING", output)


class CliAgentTests(unittest.TestCase):
    def test_cli_default_agent_is_react_agent(self):
        agent = cli.build_agent(CaptureRegistry())

        self.assertIsInstance(agent, ReactAgent)

    def test_cli_plan_agent_has_no_reviewer_even_if_old_env_is_set(self):
        with patch.dict(os.environ, {"PAICLI_PLAN_REVIEW": "1"}, clear=False):
            plan_agent = cli.build_plan_agent(CaptureRegistry())

        roles = [agent.role for agent in plan_agent]
        self.assertEqual(roles, [AgentRole.PLANNER, AgentRole.WORKER, AgentRole.WORKER])

    def test_build_memory_uses_project_memory_file_by_default(self):
        memory = cli.build_memory()

        self.assertEqual(
            memory.long_term.storage_path,
            Path("agent_memory/long_term_memory.json"),
        )

    def test_run_once_routes_plain_input_to_react_agent(self):
        react = _StubReactAgent()
        plan = _StubPlanAgent()

        with contextlib.redirect_stdout(io.StringIO()):
            cli.run_once(react, plan, "你好")

        self.assertEqual(react.inputs, ["你好"])
        self.assertEqual(plan.inputs, [])

    def test_run_once_routes_plan_command_to_orchestrator(self):
        react = _StubReactAgent()
        plan = _StubPlanAgent()

        with tempfile.TemporaryDirectory() as tmp:
            with contextlib.redirect_stdout(io.StringIO()):
                cli.run_once(react, plan, "/plan 统计当前目录", plan_log_dir=Path(tmp))

        self.assertEqual(react.inputs, [])
        self.assertEqual(plan.inputs, ["统计当前目录"])

    def test_plan_run_writes_log_file(self):
        react = _StubReactAgent()
        plan = _StubPlanAgent()

        with tempfile.TemporaryDirectory() as tmp:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                cli.run_once(react, plan, "/plan 统计当前目录", plan_log_dir=Path(tmp))

            log_files = list(Path(tmp).glob("*.log"))
            self.assertEqual(len(log_files), 1)
            content = log_files[0].read_text(encoding="utf-8")

        self.assertIn("[计划日志] 开始记录本次计划", content)
        self.assertIn("统计当前目录", content)
        self.assertIn("[入口] 识别为计划模式", content)
        self.assertIn("[入口] 准备输出计划模式结果:", content)
        self.assertIn("计划日志:", output.getvalue())

    def test_plain_react_run_does_not_write_plan_log_file(self):
        react = _StubReactAgent()
        plan = _StubPlanAgent()

        with tempfile.TemporaryDirectory() as tmp:
            with contextlib.redirect_stdout(io.StringIO()):
                cli.run_once(react, plan, "你好", plan_log_dir=Path(tmp))

            log_files = list(Path(tmp).glob("*.log"))

        self.assertEqual(log_files, [])

    def test_run_once_error_prints_clean_message_without_traceback(self):
        react = _FailingReactAgent()
        plan = _StubPlanAgent()
        output = io.StringIO()
        errors = io.StringIO()

        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            cli.run_once(react, plan, "你好")

        text = output.getvalue()
        self.assertIn("[ERROR] 执行失败: boom", text)
        self.assertNotIn("Traceback", text)
        self.assertNotIn("Traceback", errors.getvalue())

    def test_plan_log_file_captures_debug_details(self):
        with tempfile.TemporaryDirectory() as tmp:
            with cli.PlanLogSession("测试 debug", Path(tmp)) as session:
                logging.getLogger("tests.debug").debug("这是一条 debug 细节")

            content = session.path.read_text(encoding="utf-8")

        self.assertIn("这是一条 debug 细节", content)
        self.assertIn("========== PLAN START ==========", content)
        self.assertIn("========== PLAN END ==========", content)

    def test_plan_log_file_excludes_third_party_debug_noise(self):
        with tempfile.TemporaryDirectory() as tmp:
            with cli.PlanLogSession("测试 noise", Path(tmp)) as session:
                logging.getLogger("multi_agent.demo").debug("保留项目 debug")
                logging.getLogger("openai._base_client").debug("Request options: noisy")
                logging.getLogger("httpx").info("HTTP Request: noisy")
                logging.getLogger("httpcore.http11").debug("receive_response_headers noisy")
                logging.getLogger("urllib3.connectionpool").debug("POST noisy")

            content = session.path.read_text(encoding="utf-8")

        self.assertIn("保留项目 debug", content)
        self.assertNotIn("Request options: noisy", content)
        self.assertNotIn("HTTP Request: noisy", content)
        self.assertNotIn("receive_response_headers noisy", content)
        self.assertNotIn("POST noisy", content)

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
            memory = cli.build_memory(Path(tmp) / "memory.json")

            message = cli.handle_remember(memory, "/remember 用户偏好：默认使用 React")

            self.assertIn("已记住", message)
            self.assertEqual(
                [entry.content for entry in memory.long_term],
                ["用户偏好：默认使用 React"],
            )

    def test_memory_status_shows_short_and_long_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = cli.build_memory(Path(tmp) / "memory.json")
            memory.add_user("你好")
            memory.remember("用户偏好：默认使用 React")

            status = cli.format_memory_status(memory)

            self.assertIn("short_term: 1 entries", status)
            self.assertIn("long_term : 1 entries", status)

    def test_empty_long_term_file_loads_as_empty_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "memory.json"
            path.write_text("", encoding="utf-8")

            with self.assertNoLogs("memory_pythonic.long_term", level="WARNING"):
                memory = cli.build_memory(path)

            self.assertEqual(len(memory.long_term), 0)


class _StubReactAgent:
    def __init__(self):
        self.inputs = []

    def run(self, user_input):
        self.inputs.append(user_input)
        return f"react:{user_input}"


class _FailingReactAgent:
    def run(self, user_input):
        raise RuntimeError("boom")


class _StubPlanAgent:
    def __init__(self):
        self.inputs = []

    async def run(self, user_input):
        self.inputs.append(user_input)
        return f"plan:{user_input}"


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


class ExecuteCommandToolTests(unittest.TestCase):
    def test_execute_command_supports_ls_in_project_shell(self):
        result = ExecuteCommandTool().execute({"command": "ls -l ."})

        self.assertIn("agent", result)
        self.assertNotIn("not recognized", result)

    def test_execute_command_reports_exit_code_when_stderr_is_empty(self):
        result = ExecuteCommandTool().execute({
            "command": 'python -c "import sys; sys.exit(7)"',
        })

        self.assertIn("命令执行失败（退出码", result)
        self.assertIn("没有 stdout/stderr 输出", result)

    def test_execute_command_times_out(self):
        result = ExecuteCommandTool().execute({
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

    def test_cli_registry_includes_pi_style_tools_and_old_aliases(self):
        registry = cli.build_registry()
        names = [d["function"]["name"] for d in registry.get_all_definitions()]

        for name in ["read", "write", "edit", "bash", "ls", "grep", "find"]:
            self.assertIn(name, names)
        for name in ["read_file", "write_file", "list_dir", "execute_command"]:
            self.assertIn(name, names)
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
        self.assertFalse(WriteFileTool().requires_approval({"path": "demo.txt"}))
        self.assertFalse(EditTool().requires_approval({"path": "demo.txt"}))
        self.assertTrue(BashTool().requires_approval({"command": "python --version"}))


if __name__ == "__main__":
    unittest.main()
