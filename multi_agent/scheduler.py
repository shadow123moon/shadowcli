"""PlanScheduler - 从计划中选择下一批可并行执行的步骤。"""
from __future__ import annotations

from .plan_types import ExecutionStep, StepStatus


class PlanScheduler:
    """根据显式依赖和声明式读写边界选择执行批次。"""

    def next_batch(self, steps: list[ExecutionStep]) -> list[ExecutionStep]:
        """返回下一批依赖已满足且互不读写冲突的 pending steps。"""
        ready = self.ready_steps(steps)
        batch: list[ExecutionStep] = []
        for step in ready:
            if all(not self.has_io_conflict(step, selected) for selected in batch):
                batch.append(step)
        return batch

    def ready_steps(self, steps: list[ExecutionStep]) -> list[ExecutionStep]:
        """返回显式 dependencies 已完成的 pending steps。"""
        status_map = {step.id: step.status for step in steps}
        return [
            step for step in steps
            if step.is_pending
            and all(status_map.get(dep) == StepStatus.COMPLETED for dep in step.dependencies)
        ]

    def has_io_conflict(self, left: ExecutionStep, right: ExecutionStep) -> bool:
        """读-读不冲突；读-写、写-读、写-写同一路径冲突。"""
        left_reads = _normalized_paths(left.reads)
        left_writes = _normalized_paths(left.writes)
        right_reads = _normalized_paths(right.reads)
        right_writes = _normalized_paths(right.writes)

        return (
            _any_path_overlap(left_writes, right_writes)
            or _any_path_overlap(left_writes, right_reads)
            or _any_path_overlap(left_reads, right_writes)
        )


def _any_path_overlap(left_paths: set[str], right_paths: set[str]) -> bool:
    return any(
        _paths_overlap(left, right)
        for left in left_paths
        for right in right_paths
    )


def _paths_overlap(left: str, right: str) -> bool:
    return (
        left == right
        or right.startswith(left + "/")
        or left.startswith(right + "/")
    )


def _normalized_paths(paths: list[str]) -> set[str]:
    normalized = set()
    for path in paths:
        text = str(path).strip().replace("\\", "/").rstrip("/")
        while text.startswith("./"):
            text = text[2:]
        if text:
            normalized.add(text.lower())
    return normalized
