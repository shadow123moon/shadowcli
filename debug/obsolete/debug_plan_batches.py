"""Generate a real planner-only plan and inspect scheduler batches.

This does not execute workers or tools. It only:
1. calls the Planner,
2. parses the returned steps,
3. repeatedly calls AgentOrchestrator._get_executable_steps().
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cli_app.factories import build_registry
from llm.client import chat
from multi_agent import AgentOrchestrator, AgentRole, StepStatus, SubAgent
from multi_agent.planning_phase import PlanningPhase


DEFAULT_TASK = (
    "在当前项目中改进 /plan 模式：让 Planner 为每个 step 输出 reads/writes，"
    "并让调度器根据 dependencies 和读写冲突选择可并行批次。"
    "只做最小代码改动，并补充单元测试。"
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task", nargs="?", default=DEFAULT_TASK)
    args = parser.parse_args()

    registry = build_registry()
    planner = SubAgent("planner", AgentRole.PLANNER, chat, registry)
    planning = PlanningPhase(planner)

    result = planning.run(args.task)
    if not result.ok:
        print(f"\nplanning_error={result.error}")
        return 1

    print("\n=== parsed steps ===")
    for step in result.steps:
        print(
            f"{step.id}: {step.description} | "
            f"reads={step.reads} writes={step.writes} deps={step.dependencies}"
        )

    orchestrator = AgentOrchestrator(chat=None, tool_registry=registry)
    print("\n=== scheduler batches ===")
    batch_index = 1
    while True:
        batch = orchestrator._get_executable_steps(result.steps)
        if not batch:
            break
        print(f"batch{batch_index}: {[step.id for step in batch]}")
        for step in batch:
            print(
                f"  {step.id}: reads={step.reads} writes={step.writes} "
                f"deps={step.dependencies}"
            )
            step.status = StepStatus.COMPLETED
        batch_index += 1

    unfinished = [step.id for step in result.steps if not step.is_completed]
    print(f"\nunfinished={unfinished}")
    return 0 if not unfinished else 2


if __name__ == "__main__":
    raise SystemExit(main())
