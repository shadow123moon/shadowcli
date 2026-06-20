from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from llm import Message

PLAN_HANDOFF_METADATA_KEY = "plan_mode_handoff"


@dataclass(frozen=True)
class PlanHandoff:
    plan: str
    plan_file_path: str
    message: Message


def plan_file_path_for_session(session) -> Path:
    session_path = Path(getattr(session, "path", ""))
    session_id = getattr(getattr(session, "meta", None), "session_id", "") or "plan"
    return session_path / "plans" / f"{_slug(session_id)}.md"


def write_plan_file(session, plan: str) -> Path:
    path = plan_file_path_for_session(session)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_format_plan_file(plan), encoding="utf-8")
    return path


def build_plan_handoff(session, plan: str, plan_file_path: str | Path) -> PlanHandoff:
    path_text = str(plan_file_path)
    message = Message(
        role="user",
        content=build_implementation_message(plan, path_text, _transcript_path(session)),
        metadata={
            PLAN_HANDOFF_METADATA_KEY: {
                "plan_file_path": path_text,
            },
        },
    )
    return PlanHandoff(plan=plan, plan_file_path=path_text, message=message)


def build_implementation_message(plan: str, plan_file_path: str, transcript_path: str) -> str:
    return "\n\n".join([
        "请开始实施以下已批准计划。",
        plan.strip(),
        f"完整计划文件: {plan_file_path}",
        f"如果实施时需要回看 plan mode 阶段的探索细节，请读取会话 transcript: {transcript_path}",
    ]).strip()


def compact_planning_history(session, handoff_message_entry, *, plan: str, plan_file_path: str):
    summary = "\n".join([
        "Plan mode 阶段已结束，规划对话已从执行上下文中折叠。",
        f"已批准计划文件: {plan_file_path}",
        "执行阶段应以 handoff 消息中的计划为准；需要细节时读取完整 transcript。",
        "",
        "已批准计划:",
        plan.strip(),
    ]).strip()
    return session.append_compaction(
        summary=summary,
        first_kept_entry_id=handoff_message_entry.id,
        tokens_before=0,
    )


def _format_plan_file(plan: str) -> str:
    return "\n".join([
        "# Approved Plan",
        "",
        plan.strip(),
        "",
    ])


def _transcript_path(session) -> str:
    return str(Path(getattr(session, "path", "")) / "messages.jsonl")


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", value).strip("-")
    return slug or "plan"
