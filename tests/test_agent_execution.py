import contextlib
import io
import logging
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cli_app as cli
from agent.react_agent import ReactAgent
from extensions.tool_runtime import ToolExecutionBlocked
from llm import ChatResponse, FunctionCall, ToolCall
from memory_pythonic import MemoryManager
from multi_agent import AgentOrchestrator, AgentRole, ExecutionStep, SubAgent
from multi_agent.messages import AgentMessage
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
    def test_runs_single_react_turn_with_injected_chat(self):
        calls = []

        def fake_chat(messages, tools=None):
            calls.append((list(messages), tools))
            return ChatResponse(content="你好，我是 ReAct 助手")

        agent = ReactAgent(CaptureRegistry(), chat=fake_chat)

        result = agent.run("你好")

        self.assertEqual(result, "你好，我是 ReAct 助手")
        self.assertEqual(calls[0][0][-1].content, "你好")
        self.assertIsNone(calls[0][1])

    def test_react_greeting_does_not_receive_tools(self):
        calls = []

        def fake_chat(messages, tools=None):
            calls.append(tools)
            return ChatResponse(content="你好")

        agent = ReactAgent(_ToolDefinitionRegistry(), chat=fake_chat)

        agent.run("你好")

        self.assertEqual(calls, [None])

    def test_react_file_task_receives_tools(self):
        calls = []

        def fake_chat(messages, tools=None):
            calls.append(tools)
            return ChatResponse(content="可以读取")

        agent = ReactAgent(_ToolDefinitionRegistry(), chat=fake_chat)

        agent.run("读取 cli_app/runner.py 文件")

        self.assertIsNotNone(calls[0])
        self.assertEqual(calls[0][0]["function"]["name"], "read")

    def test_records_react_turn_in_short_term_memory(self):
        def fake_chat(messages, tools=None):
            return ChatResponse(content="记住了")

        memory = MemoryManager()
        agent = ReactAgent(CaptureRegistry(), chat=fake_chat, memory_manager=memory)

        agent.run("以后默认用 React")

        contents = [entry.content for entry in memory.short_term]
        self.assertEqual(contents, ["以后默认用 React", "记住了"])

    def test_react_turn_injects_recent_short_term_and_relevant_long_term(self):
        calls = []

        def fake_chat(messages, tools=None):
            calls.append(list(messages))
            return ChatResponse(content="按你的偏好来")

        with tempfile.TemporaryDirectory() as tmp:
            memory = MemoryManager(long_term_path=Path(tmp) / "memory.json")
            memory.add_user("项目入口是 cli.py")
            memory.remember("用户偏好：普通输入走 React")
            agent = ReactAgent(CaptureRegistry(), chat=fake_chat, memory_manager=memory)

            agent.run("入口和 React 怎么安排？")

        prompt = calls[0][-1].content
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

        def fake_chat(messages, tools=None):
            calls.append(list(messages))
            return ChatResponse(content='{"steps": []}')

        with tempfile.TemporaryDirectory() as tmp:
            memory = MemoryManager(long_term_path=Path(tmp) / "memory.json")
            memory.add_user("项目入口是 cli.py")
            memory.remember("用户偏好：普通输入走 React")
            orchestrator = AgentOrchestrator(fake_chat, CaptureRegistry(), memory_manager=memory)

            import asyncio
            with contextlib.redirect_stdout(io.StringIO()):
                asyncio.run(orchestrator.run("根据 React 入口规划一下"))

        prompt = calls[0][-1].content
        self.assertIn("## 记忆上下文", prompt)
        self.assertIn("项目入口是 cli.py", prompt)
        self.assertIn("用户偏好：普通输入走 React", prompt)
        self.assertIn("请为以下任务制定执行计划", prompt)
        self.assertIn("当前任务：请为以下任务制定执行计划", prompt)


class AgentOrchestratorPlanTests(unittest.TestCase):
    def test_plan_execution_does_not_call_reviewer(self):
        roles = []

        def fake_chat(messages, tools=None):
            system = messages[0].content
            if "任务规划专家" in system:
                roles.append("planner")
                return ChatResponse(content='{"steps": [{"description": "直接分析", "dependencies": []}]}')
            if "质量检查专家" in system:
                roles.append("reviewer")
                return ChatResponse(content='{"approved": false, "issues": ["不应调用"]}')
            roles.append("worker")
            return ChatResponse(content="执行完成")

        orchestrator = AgentOrchestrator(fake_chat, CaptureRegistry())

        import asyncio
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

    def test_worker_prompt_limits_scope_and_stops_after_current_step(self):
        prompt = _worker_prompt("")
        self.assertIn("只完成当前步骤描述的范围", prompt)
        self.assertIn("不要主动扩展到后续计划步骤", prompt)
        self.assertIn("关键验证已经通过后，立即输出最终结果", prompt)

class SubAgentToolLogTests(unittest.TestCase):
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

    def test_tool_log_includes_current_plan_step(self):
        registry = CaptureRegistry()
        registry.tools["write"] = _StubTool("done")
        calls = []

        def fake_chat(messages, tools=None):
            calls.append(list(messages))
            if len(calls) == 1:
                return ChatResponse(
                    tool_calls=[
                        ToolCall(
                            id="call-write",
                            function=FunctionCall(
                                name="write",
                                arguments='{"path": "demo.txt", "content": "ok"}',
                            ),
                        )
                    ]
                )
            return ChatResponse(content="写完了")

        orchestrator = AgentOrchestrator(fake_chat, registry, worker_count=1)
        step = ExecutionStep(id="step_7", description="写入演示文件")
        output = io.StringIO()

        import asyncio
        with self.assertLogs("multi_agent.sub_agent", level="INFO") as logs:
            asyncio.run(
                orchestrator._run_step(
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

    def test_bash_result_is_emitted_to_agent_output(self):
        registry = CaptureRegistry()
        registry.tools["bash"] = _StubTool("命令执行失败（退出码 1）\nstderr: boom")
        calls = []

        def fake_chat(messages, tools=None):
            calls.append(list(messages))
            if len(calls) == 1:
                return ChatResponse(
                    tool_calls=[
                        ToolCall(
                            id="call-bash",
                            function=FunctionCall(
                                name="bash",
                                arguments='{"command": "bad command"}',
                            ),
                        )
                    ]
                )
            return ChatResponse(content="收尾")

        agent = SubAgent(
            "worker-1",
            AgentRole.WORKER,
            chat=fake_chat,
            tool_registry=registry,
        )

        import asyncio
        output = io.StringIO()
        asyncio.run(
            agent.execute(
                AgentMessage.task("orchestrator", "运行命令"),
                out=output,
            )
        )

        text = output.getvalue()
        self.assertIn("🛠️ [worker-1] 调用 1 个工具", text)
        self.assertIn("📤 [worker-1] bash 结果", text)
        self.assertIn("命令执行失败（退出码 1）", text)

    def test_hard_rejected_tool_call_stops_current_agent(self):
        registry = _HardRejectRuntime()
        calls = []

        def fake_chat(messages, tools=None):
            calls.append(list(messages))
            if len(calls) > 1:
                raise AssertionError("硬拒绝后不应继续调用模型")
            return ChatResponse(
                tool_calls=[
                    ToolCall(
                        id="call-write",
                        function=FunctionCall(
                            name="write",
                            arguments='{"path": "demo.txt", "content": "ok"}',
                        ),
                    )
                ]
            )

        agent = SubAgent(
            "react",
            AgentRole.REACT,
            chat=fake_chat,
            tool_registry=registry,
        )

        import asyncio
        output = io.StringIO()
        result = asyncio.run(
            agent.execute(
                AgentMessage.task("user", "写文件"),
                out=output,
            )
        )

        self.assertTrue(result.is_error())
        self.assertIn("用户拒绝", result.content)
        self.assertEqual(len(calls), 1)
        self.assertIn("工具调用被拒绝", output.getvalue())


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

    def test_plan_log_file_captures_debug_details(self):
        with tempfile.TemporaryDirectory() as tmp:
            with cli.PlanLogSession("测试 debug", Path(tmp)) as session:
                logging.getLogger("tests.debug").debug("这是一条 debug 细节")

            content = session.path.read_text(encoding="utf-8")

        self.assertIn("这是一条 debug 细节", content)

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


class _StubPlanAgent:
    def __init__(self):
        self.inputs = []

    async def run(self, user_input):
        self.inputs.append(user_input)
        return f"plan:{user_input}"


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


if __name__ == "__main__":
    unittest.main()
