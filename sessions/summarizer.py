from __future__ import annotations

from dataclasses import dataclass

from llm import Message, chat

from .entries import MessageEntry, SessionEntry
from .manager import NavigationPlan


@dataclass
class BranchSummaryRequest:
    from_id: str | None
    to_id: str | None
    common_ancestor_id: str | None
    entries: list[SessionEntry]


def branch_summary_request(plan: NavigationPlan) -> BranchSummaryRequest:
    return BranchSummaryRequest(
        from_id=plan.from_id,
        to_id=plan.to_id,
        common_ancestor_id=plan.common_ancestor_id,
        entries=list(plan.leaving_entries),
    )


def build_branch_summary_prompt(request: BranchSummaryRequest) -> str:
    lines = [
        "请总结用户即将离开的会话分支。",
        "摘要只保留目标、关键决定、已读/已改文件、未完成事项。",
        "不要续写对话，不要调用工具。",
        "",
        "<branch>",
    ]
    for entry in request.entries:
        if isinstance(entry, MessageEntry):
            role = entry.message.role
            content = entry.message.content or ""
            lines.append(f"{role}: {content}")
    lines.extend(["</branch>", "", "输出中文摘要。"])
    return "\n".join(lines)


def generate_branch_summary(plan: NavigationPlan, chat_fn=chat) -> str:
    request = branch_summary_request(plan)
    prompt = build_branch_summary_prompt(request)
    response = chat_fn([Message(role="user", content=prompt)], tools=None)
    summary = (response.content or "").strip()
    return summary or "（空分支摘要）"
