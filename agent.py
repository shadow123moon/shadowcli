# agent.py
import concurrent.futures
import re
from planning import Plan, PlanStatus, Planner, Task, TaskStatus, TaskType
from tool_registry import ToolRegistry

class PlanExecuteAgent:
    def __init__(self, planner: Planner, tool_registry: ToolRegistry, max_parallel: int = 4):
        self.planner = planner
        self.tool_registry = tool_registry
        self.max_parallel = max_parallel

    def run(self, user_input: str, parallel: bool = False) -> str:
        plan = self.planner.create_plan(user_input)
        plan.mark_started()
        print(self._visualize_plan(plan))

        if parallel:
            self._execute_parallel(plan)
        else:
            self._execute_sequential(plan)

        if plan.has_failed():
            plan.status = PlanStatus.FAILED
            return f"计划执行失败:\n{self._collect_errors(plan)}"
        else:
            plan.mark_completed()
            return self._build_final_result(plan)

    def _execute_sequential(self, plan: Plan):
        for task_id in plan.execution_order:
            task = plan.get_task(task_id)
            if task.status == TaskStatus.SKIPPED:
                continue
            self._execute_single_task(task, plan)

    def _execute_parallel(self, plan: Plan):
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_parallel) as executor:
            while True:
                ready = plan.get_executable_tasks()
                if not ready:
                    break
                futures = {executor.submit(self._execute_single_task, t, plan): t.id for t in ready}
                for f in concurrent.futures.as_completed(futures):
                    try:
                        f.result()
                    except Exception as e:
                        print(f"并行任务异常: {futures[f]} - {e}")

    def _execute_single_task(self, task: Task, plan: Plan):
        task.mark_started()
        print(f"▶️ 开始: {task.id} - {task.description}")
        try:
            result = self._execute_by_type(task)
            task.mark_completed(result)
            print(f"✅ 完成: {task.id}")
        except Exception as e:
            task.mark_failed(str(e))
            print(f"❌ 失败: {task.id} - {e}")
            for t in plan.tasks.values():
                if task.id in t.dependencies and t.status == TaskStatus.PENDING:
                    t.status = TaskStatus.SKIPPED

    def _execute_by_type(self, task: Task) -> str:
        # 简化版：直接通过任务类型 + 描述解析工具调用
        # 实际可调用 LLM 生成工具调用（类似内部 ReAct）
        desc = task.description
        if task.type == TaskType.FILE_READ:
            path = desc.split("读取")[-1].strip()
            return self.tool_registry.get("read_file").execute({"path": path})
        elif task.type == TaskType.FILE_WRITE:
            arguments = self._parse_file_write_args(desc)
            return self.tool_registry.get("write_file").execute(arguments)
        elif task.type == TaskType.COMMAND:
            cmd = self._parse_command(desc)
            return self.tool_registry.get("execute_command").execute({"command": cmd})
        elif task.type == TaskType.ANALYSIS:
            return f"分析结果: {desc}"
        elif task.type == TaskType.VERIFICATION:
            return f"验证通过: {desc}"
        else:
            raise ValueError(f"未知任务类型: {task.type}")

    @staticmethod
    def _parse_command(description: str) -> str:
        patterns = [
            r"(?:执行命令|运行命令|使用命令|命令为)\s*[:：]?\s*(?P<command>.+)",
            r"(?:执行|运行)\s*[:：]?\s*(?P<command>.+)",
        ]
        command = description.strip()
        for pattern in patterns:
            match = re.search(pattern, description, re.DOTALL)
            if match:
                command = match.group("command").strip()
                break

        command = re.split(r"\s+并(?:检查|验证|确认|查看|输出).*$", command, maxsplit=1)[0]
        command = re.split(r"[，。；;]\s*(?:并)?(?:检查|验证|确认|查看|输出).*$", command, maxsplit=1)[0]
        return command.strip()

    @classmethod
    def _parse_file_write_args(cls, description: str) -> dict:
        legacy = re.search(
            r"写入文件\s+(?P<path>[^\s，。；;]+)\s+内容\s+(?P<content>.+)",
            description,
            re.DOTALL,
        )
        if legacy:
            return {
                "path": cls._clean_path(legacy.group("path")),
                "content": cls._normalize_content(legacy.group("content").strip()),
            }

        path = cls._extract_write_path(description)
        content = cls._extract_write_content(description)
        return {"path": path or "output.txt", "content": content}

    @staticmethod
    def _extract_write_path(description: str) -> str:
        path_patterns = [
            r"(?:写入路径|保存到|路径为|文件路径)\s*[:：]?\s*(?P<path>[^\s，。；;]+)",
            r"(?:写入文件|创建文件)\s+(?P<path>[^\s，。；;]+)",
            r"创建\s+(?P<path>[^\s，。；;]+)\s+文件",
        ]
        for pattern in path_patterns:
            match = re.search(pattern, description)
            if match:
                return PlanExecuteAgent._clean_path(match.group("path"))
        return ""

    @classmethod
    def _extract_write_content(cls, description: str) -> str:
        marker = re.search(r"内容(?:为|是)?\s*[:：]?\s*", description)
        if not marker:
            return ""

        rest = description[marker.end():].strip()
        if rest and rest[0] in {"'", '"'}:
            quote = rest[0]
            escaped = False
            for index, char in enumerate(rest[1:], 1):
                if char == quote and not escaped:
                    return cls._normalize_content(rest[1:index])
                escaped = char == "\\" and not escaped
                if char != "\\":
                    escaped = False

        stop = re.search(r"[，。；;]\s*(?:写入路径|保存到|路径为|文件路径)", rest)
        content = rest[:stop.start()] if stop else rest
        return cls._normalize_content(content.strip())

    @staticmethod
    def _clean_path(path: str) -> str:
        return path.strip().strip("'\"")

    @staticmethod
    def _normalize_content(content: str) -> str:
        content = content.strip().strip("'\"")
        return content.replace("\\n", "\n").replace("\\t", "\t")

    def _visualize_plan(self, plan: Plan) -> str:
        icons = {
            TaskStatus.PENDING: "⏳", TaskStatus.RUNNING: "▶️",
            TaskStatus.COMPLETED: "✅", TaskStatus.FAILED: "❌",
            TaskStatus.SKIPPED: "⏭️"
        }
        lines = [f"📋 计划: {plan.goal}", f"摘要: {plan.summary}"]
        for tid in plan.execution_order:
            t = plan.tasks[tid]
            icon = icons.get(t.status, "❓")
            dep = f" (依赖: {', '.join(t.dependencies)})" if t.dependencies else ""
            lines.append(f"  {icon} {t.id}: {t.description} [{t.type.value}]{dep}")
        return "\n".join(lines)

    def _collect_errors(self, plan: Plan) -> str:
        return "\n".join(f"  {t.id}: {t.error}" for t in plan.tasks.values()
                         if t.status == TaskStatus.FAILED)

    def _build_final_result(self, plan: Plan) -> str:
        return "\n".join(f"[{t.id}] {t.result}" for t in plan.tasks.values()
                         if t.status == TaskStatus.COMPLETED)
