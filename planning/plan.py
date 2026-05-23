from __future__ import annotations
import time
from enum import Enum
from typing import Dict, List, Optional

from .task import Task, TaskStatus


class PlanStatus(Enum):
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class Plan:
    """执行计划 = 一个 DAG。

    节点是 Task,边是 dependencies (入边) / dependents (出边)。
    DAG 操作: 拓扑排序、可执行节点筛选、按层划分并行批次。
    """

    def __init__(self, goal: str, plan_id: Optional[str] = None):
        self.id = plan_id or f"plan_{int(time.time() * 1000)}"
        self.goal = goal
        self.summary = ""
        self.tasks: Dict[str, Task] = {}
        self.execution_order: List[str] = []
        self.status = PlanStatus.CREATED
        self.start_time = 0.0
        self.end_time = 0.0

    # ---------- 节点管理 ----------
    def add_task(self, task: Task) -> None:
        self.tasks[task.id] = task
        # 反向边: 已经在表里的依赖, 顺手回填 dependents
        for dep_id in task.dependencies:
            dep = self.tasks.get(dep_id)
            if dep is not None:
                dep.add_dependent(task.id)

    def get_task(self, task_id: str) -> Optional[Task]:
        return self.tasks.get(task_id)

    def all_tasks(self) -> List[Task]:
        return list(self.tasks.values())

    # ---------- DAG 核心 ----------
    def compute_execution_order(self) -> bool:
        """DFS + 三色标记拓扑排序。返回 False 表示有环。"""
        self.execution_order = []
        visited: set[str] = set()
        visiting: set[str] = set()

        def dfs(task: Task) -> bool:
            tid = task.id
            if tid in visiting:
                return False  # 撞到正在访问的节点 => 有环
            if tid in visited:
                return True
            visiting.add(tid)
            for dep_id in task.dependencies:
                dep = self.tasks.get(dep_id)
                if dep is not None and not dfs(dep):
                    return False
            visiting.remove(tid)
            visited.add(tid)
            self.execution_order.append(tid)
            return True

        for task in self.tasks.values():
            if task.id not in visited and not dfs(task):
                return False
        return True

    def get_execution_order(self) -> List[str]:
        if not self.execution_order:
            self.compute_execution_order()
        return list(self.execution_order)

    def root_tasks(self) -> List[Task]:
        """没有依赖的入口节点。"""
        return [t for t in self.tasks.values() if not t.dependencies]

    def get_executable_tasks(self) -> List[Task]:
        """当前可立即执行的节点 (PENDING 且所有依赖已 COMPLETED)。"""
        return [t for t in self.tasks.values() if t.is_executable(self.tasks)]

    def get_execution_batches(self) -> List[List[Task]]:
        """按"前驱全部完成"逐层划分,每一层内的任务可并行执行。

        注意: 这里是基于依赖关系的静态分层,忽略当前 status,
              用于"看看这个 DAG 能怎么并行调度"。
        """
        if not self.tasks:
            return []
        remaining = dict(self.tasks)
        completed: set[str] = set()
        batches: List[List[Task]] = []
        while remaining:
            batch = [
                t for t in remaining.values()
                if all(d in completed for d in t.dependencies)
            ]
            if not batch:
                break  # 剩下的都依赖未完成节点 => 有环或断链
            batches.append(batch)
            for t in batch:
                remaining.pop(t.id)
                completed.add(t.id)
        return batches

    # ---------- 状态 / 进度 ----------
    def progress(self) -> float:
        if not self.tasks:
            return 1.0
        done = sum(1 for t in self.tasks.values() if t.status == TaskStatus.COMPLETED)
        return done / len(self.tasks)

    def is_all_completed(self) -> bool:
        return all(t.status == TaskStatus.COMPLETED for t in self.tasks.values())

    def has_failed(self) -> bool:
        return any(t.status == TaskStatus.FAILED for t in self.tasks.values())

    def mark_started(self) -> None:
        self.status = PlanStatus.RUNNING
        self.start_time = time.time()

    def mark_completed(self) -> None:
        self.status = PlanStatus.COMPLETED
        self.end_time = time.time()

    def mark_failed(self) -> None:
        self.status = PlanStatus.FAILED
        self.end_time = time.time()

    def duration(self) -> float:
        if self.start_time == 0.0:
            return 0.0
        end = self.end_time if self.end_time else time.time()
        return end - self.start_time

    # ---------- 可视化 (简化版) ----------
    _STATUS_ICON = {
        TaskStatus.PENDING: "·",
        TaskStatus.RUNNING: ">",
        TaskStatus.COMPLETED: "v",
        TaskStatus.FAILED: "x",
        TaskStatus.SKIPPED: "-",
    }

    def visualize(self) -> str:
        lines = [f"Plan[{self.id}] goal={self.goal}  status={self.status.value}"]
        for i, tid in enumerate(self.get_execution_order(), 1):
            t = self.tasks[tid]
            icon = self._STATUS_ICON.get(t.status, "?")
            deps = ",".join(t.dependencies) if t.dependencies else "-"
            lines.append(f"  {i}. [{icon}] {t.id} ({t.type.value}) deps={deps} | {t.description}")
        lines.append(f"progress={self.progress() * 100:.0f}%")
        return "\n".join(lines)

    def summarize(self) -> str:
        batches = self.get_execution_batches()
        ready = self.get_executable_tasks()
        head = ", ".join(t.id for t in batches[0]) if batches else "-"
        tail = ", ".join(t.id for t in batches[-1]) if len(batches) > 1 else "-"
        return (
            f"目标: {self.goal}\n"
            f"任务数: {len(self.tasks)} | 批次: {len(batches)} | "
            f"可执行: {len(ready)} | 状态: {self.status.value}\n"
            f"首批: {head}\n"
            f"末批: {tail}"
        )

    def __repr__(self) -> str:
        return f"Plan[{self.id}: {self.goal}] ({len(self.tasks)} tasks, {self.status.value})"
