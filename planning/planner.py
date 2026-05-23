from __future__ import annotations
import json
import re
import time
from typing import Callable, Dict, Optional

from .plan import Plan
from .task import Task, TaskType, TaskStatus


PLANNING_PROMPT = """你是一个任务规划助手。请将用户的需求分解为一个有序的执行计划,用 JSON 格式返回。

可用任务类型:
- FILE_READ: 读取文件内容
- FILE_WRITE: 写入文件内容
- COMMAND: 执行 Shell 命令
- ANALYSIS: 分析结果
- VERIFICATION: 验证结果

返回格式:
{
  "summary": "任务一句话摘要",
  "tasks": [
    {"id": "task_1", "description": "具体操作", "type": "FILE_READ", "dependencies": []}
  ]
}

规则:
1. 每个任务必须有唯一 id
2. dependencies 列出依赖的任务 id
3. 任务应按照执行顺序排列
4. 描述要具体可执行
5. 复杂任务分解为 5-10 个子任务
"""


# LLM 调用回调签名: chat(system_prompt, user_prompt) -> 返回的纯文本 (可能含 ```json 代码块)
ChatFn = Callable[[str, str], str]


class Planner:
    """LLM 驱动的任务分解器。

    工程上做了简化:
    - LLM 客户端通过回调注入 (chat_fn),不耦合具体 SDK
    - 不做流式渲染、不打彩色框,专注 Plan/DAG 逻辑
    保留的核心逻辑:
    - 简单目标短路 (避免无意义的 LLM 调用)
    - 两遍解析 + id 重映射 (LLM 给的 id 不可信)
    - 循环依赖检测 (拓扑排序失败即抛错)
    - replan (基于已完成任务的失败重规划)
    """

    def __init__(self, chat_fn: Optional[ChatFn] = None):
        self.chat_fn = chat_fn or self._default_chat

    @staticmethod
    def _default_chat(system_prompt: str, user_prompt: str) -> str:
        from llm_client import chat
        from model import Message

        response = chat([
            Message(role="system", content=system_prompt),
            Message(role="user", content=user_prompt),
        ])
        return response.content or ""

    # ---------- 入口 ----------
    def create_plan(self, goal: str) -> Plan:
        if self._is_simple_goal(goal):
            return self._create_minimal_plan(goal)
        raw = self.chat_fn(PLANNING_PROMPT, f"请为以下任务制定执行计划:\n{goal}")
        return self._parse_plan(goal, raw)

    def replan(self, failed_plan: Plan, failure_reason: str) -> Plan:
        ctx = [
            f"原任务: {failed_plan.goal}",
            f"失败原因: {failure_reason}",
            "已完成的任务:",
        ]
        for t in failed_plan.all_tasks():
            if t.status == TaskStatus.COMPLETED:
                ctx.append(f"- {t.id}: {t.description}")
        ctx.append("\n请制定新的执行计划,避开之前的问题。")
        return self.create_plan("\n".join(ctx))

    # ---------- 简单目标短路 ----------
    _MULTI_STEP_CUES = ("然后", "并且", "并", "再", "最后", "同时", "先", "之后", "接着", "以及")
    _SIMPLE_KEYWORDS = ("列出", "查看", "读取", "显示", "执行", "运行", "搜索", "当前目录", "文件")

    def _is_simple_goal(self, goal: Optional[str]) -> bool:
        if not goal:
            return False
        g = goal.strip()
        if not g or len(g) > 30:
            return False
        if any(cue in g for cue in self._MULTI_STEP_CUES):
            return False
        return any(kw in g for kw in self._SIMPLE_KEYWORDS)

    def _create_minimal_plan(self, goal: str) -> Plan:
        plan = Plan(goal)
        plan.summary = f"直接执行简单任务: {goal.strip()}"
        plan.add_task(Task(
            id="task_1",
            description=goal.strip(),
            type=self._infer_simple_type(goal),
        ))
        if not plan.compute_execution_order():
            raise RuntimeError("简单计划不应出现循环依赖")
        return plan

    @staticmethod
    def _infer_simple_type(goal: str) -> TaskType:
        g = (goal or "").strip()
        if "读取" in g or "打开" in g or ("查看" in g and "文件" in g):
            return TaskType.FILE_READ
        if "写入" in g or "修改" in g or "创建文件" in g:
            return TaskType.FILE_WRITE
        if "分析" in g or "总结" in g or "解释" in g:
            return TaskType.ANALYSIS
        if "验证" in g or "检查" in g:
            return TaskType.VERIFICATION
        return TaskType.COMMAND

    # ---------- LLM JSON 解析 ----------
    @staticmethod
    def _strip_fence(text: str) -> str:
        cleaned = re.sub(r"```json\s*", "", text)
        cleaned = re.sub(r"```\s*", "", cleaned)
        return cleaned.strip()

    @staticmethod
    def _parse_task_type(s: str) -> TaskType:
        try:
            return TaskType[(s or "").upper()]
        except KeyError:
            return TaskType.ANALYSIS  # 容错: 未知类型回退到 ANALYSIS

    def _parse_plan(self, goal: str, plan_json: str) -> Plan:
        data = json.loads(self._strip_fence(plan_json))
        tasks_data = data.get("tasks", []) or []

        plan = Plan(goal)
        plan.summary = data.get("summary", "")

        # 第一遍: 建节点 + 把 LLM 给的原始 id 统一重映射为 task_1, task_2, ...
        id_mapping: Dict[str, str] = {}
        for idx, t in enumerate(tasks_data, start=1):
            original_id = t.get("id", f"_anon_{idx}")
            new_id = f"task_{idx}"
            id_mapping[original_id] = new_id
            plan.add_task(Task(
                id=new_id,
                description=t.get("description", ""),
                type=self._parse_task_type(t.get("type", "")),
            ))

        # 第二遍: 按 id_mapping 翻译依赖,并维护反向边
        for idx, t in enumerate(tasks_data, start=1):
            new_id = f"task_{idx}"
            task = plan.get_task(new_id)
            if task is None:
                continue
            for dep_original in t.get("dependencies", []) or []:
                dep_new_id = id_mapping.get(dep_original)
                if dep_new_id is None:
                    continue  # LLM 引用了不存在的 id, 跳过
                dep = plan.get_task(dep_new_id)
                if dep is None:
                    continue
                task.add_dependency(dep_new_id)
                dep.add_dependent(task.id)

        if not plan.compute_execution_order():
            raise ValueError("计划中存在循环依赖")
        return plan
