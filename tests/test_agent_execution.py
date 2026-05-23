import unittest

from agent import PlanExecuteAgent
from planning import Plan, Task, TaskType
from tools import ExecuteCommandTool


class CaptureTool:
    def __init__(self, key=None):
        self.key = key
        self.calls = []

    def execute(self, arguments):
        self.calls.append(arguments)
        if self.key is None:
            return arguments
        return arguments[self.key]


class CaptureRegistry:
    def __init__(self):
        self.tools = {
            "execute_command": CaptureTool("command"),
            "write_file": CaptureTool(),
        }

    def get(self, name):
        return self.tools[name]


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


class AgentDescriptionParsingTests(unittest.TestCase):
    def setUp(self):
        self.registry = CaptureRegistry()
        self.agent = PlanExecuteAgent(planner=None, tool_registry=self.registry)

    def test_command_task_extracts_command_after_chinese_command_marker(self):
        task = Task(
            "task_5",
            "列出项目目录内容，执行命令 ls -l demo",
            TaskType.COMMAND,
        )

        result = self.agent._execute_by_type(task)

        self.assertEqual(result, "ls -l demo")

    def test_command_task_extracts_command_after_use_command_marker(self):
        task = Task(
            "task_1",
            "创建 demo 目录，使用命令 mkdir demo",
            TaskType.COMMAND,
        )

        result = self.agent._execute_by_type(task)

        self.assertEqual(result, "mkdir demo")

    def test_file_write_task_extracts_content_and_explicit_path(self):
        task = Task(
            "task_2",
            "创建 main.py 文件，内容为 'print(\"Hello World\")'，写入路径 demo/main.py",
            TaskType.FILE_WRITE,
        )

        self.agent._execute_by_type(task)

        self.assertEqual(
            self.registry.tools["write_file"].calls[-1],
            {"path": "demo/main.py", "content": 'print("Hello World")'},
        )

    def test_file_write_task_preserves_newline_content(self):
        task = Task(
            "task_3",
            "创建 README.md 文件，内容为 '# Demo Project\\nThis is a demo Python project.'，写入路径 demo/README.md",
            TaskType.FILE_WRITE,
        )

        self.agent._execute_by_type(task)

        self.assertEqual(
            self.registry.tools["write_file"].calls[-1],
            {
                "path": "demo/README.md",
                "content": "# Demo Project\nThis is a demo Python project.",
            },
        )


class ExecuteCommandToolTests(unittest.TestCase):
    def test_execute_command_supports_ls_in_project_shell(self):
        result = ExecuteCommandTool().execute({"command": "ls -l ."})

        self.assertIn("agent.py", result)
        self.assertNotIn("not recognized", result)


if __name__ == "__main__":
    unittest.main()
