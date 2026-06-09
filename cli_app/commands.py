from collections.abc import Sequence

from sessions import BranchSummaryEntry, CompactionEntry, CompactionResult, MessageEntry, SessionManager, TextLongTermMemory
from skills import SkillDefinition

from .constants import (
    COMPACT_COMMAND,
    JUMP_COMMAND,
    MEMORY_COMMAND,
    NEW_COMMAND,
    PLAN_COMMAND,
    REMEMBER_COMMAND,
    RESUME_COMMAND,
    SKILL_COMMAND,
    SKILLS_COMMAND,
    TREE_COMMAND,
)


TREE_PREVIEW_CHARS = 80


def parse_plan_command(user_input: str) -> str | None:
    stripped = user_input.strip()
    if stripped == PLAN_COMMAND:
        return ""
    if stripped.startswith(f"{PLAN_COMMAND} "):
        return stripped[len(PLAN_COMMAND):].strip()
    return None


def parse_skills_command(user_input: str) -> bool:
    return user_input.strip() == SKILLS_COMMAND


def parse_skill_command(user_input: str) -> tuple[str, str] | None:
    stripped = user_input.strip()
    if stripped == SKILL_COMMAND:
        return "", ""
    if not stripped.startswith(f"{SKILL_COMMAND} "):
        return None

    remainder = stripped[len(SKILL_COMMAND):].strip()
    if not remainder:
        return "", ""
    name, _, task = remainder.partition(" ")
    return name.strip(), task.strip()


def parse_remember_command(user_input: str) -> str | None:
    stripped = user_input.strip()
    if stripped == REMEMBER_COMMAND:
        return ""
    if stripped.startswith(f"{REMEMBER_COMMAND} "):
        return stripped[len(REMEMBER_COMMAND):].strip()
    return None


def parse_resume_command(user_input: str) -> str | None:
    stripped = user_input.strip()
    if stripped == RESUME_COMMAND:
        return ""
    if stripped.startswith(f"{RESUME_COMMAND} "):
        return stripped[len(RESUME_COMMAND):].strip()
    return None


def parse_new_command(user_input: str) -> bool:
    return user_input.strip() == NEW_COMMAND


def parse_tree_command(user_input: str) -> bool:
    return user_input.strip() == TREE_COMMAND


def parse_jump_command(user_input: str) -> str | None:
    stripped = user_input.strip()
    if stripped == JUMP_COMMAND:
        return ""
    if stripped.startswith(f"{JUMP_COMMAND} "):
        return stripped[len(JUMP_COMMAND):].strip()
    return None


def parse_compact_command(user_input: str) -> str | None:
    stripped = user_input.strip()
    if stripped == COMPACT_COMMAND:
        return ""
    return None


def handle_remember(memory: TextLongTermMemory, user_input: str) -> str:
    fact = parse_remember_command(user_input)
    if fact is None:
        return f"用法: {REMEMBER_COMMAND} <事实>"
    if not fact:
        return f"用法: {REMEMBER_COMMAND} <事实>"
    memory.remember(fact)
    return f"已记住: {fact}"


def format_memory_status(memory: TextLongTermMemory) -> str:
    return "\n".join([
        f"long_term : {len(memory)} facts",
        f"storage   : {memory.storage_path}",
    ])


def format_skill_list(skills: Sequence[SkillDefinition]) -> str:
    if not skills:
        return "没有可用 skill。"

    lines = [f"可用 skills（{len(skills)} 个）:"]
    for skill in skills:
        source = f" [{skill.source}]" if skill.source else ""
        description = f": {skill.description}" if skill.description else ""
        hint = f"  {skill.argument_hint}" if skill.argument_hint else ""
        lines.append(f"  - {skill.name}{source}{description}{hint}")
    return "\n".join(lines)


def format_session_tree(session: SessionManager, *, limit: int = 20) -> str:
    entries = session.all_entries()
    if not entries:
        return "会话树为空。"

    branch_ids = {entry.id for entry in session.get_branch()}
    leaf_id = session.get_leaf_id()
    shown = entries[-limit:]
    lines = [f"会话树（最近 {len(shown)} / {len(entries)} 条）:"]
    for entry in shown:
        in_branch = "*" if entry.id in branch_ids else " "
        current = " <- current" if entry.id == leaf_id else ""
        lines.append(
            f"{in_branch} {entry.id} {entry_label(entry):<14} {entry_preview(entry)}{current}"
        )
    return "\n".join(lines)


def format_compaction_result(result: CompactionResult) -> str:
    if not result.compacted or result.entry is None or result.plan is None:
        return f"未压缩: {result.reason}"
    return "\n".join([
        "已压缩当前会话分支。",
        f"摘要节点: {result.entry.id}",
        f"保留起点: {result.entry.first_kept_entry_id}",
        f"压缩前估算 tokens: {result.entry.tokens_before}",
    ])


def entry_label(entry) -> str:
    if isinstance(entry, MessageEntry):
        return entry.message.role
    if isinstance(entry, BranchSummaryEntry):
        return "branch_summary"
    if isinstance(entry, CompactionEntry):
        return "compaction"
    return getattr(entry, "type", "entry")


def entry_preview(entry) -> str:
    if isinstance(entry, MessageEntry):
        text = entry.message.content or ""
        if entry.message.tool_calls:
            names = ", ".join(call.function.name for call in entry.message.tool_calls)
            text = text or f"tool_calls: {names}"
    elif isinstance(entry, BranchSummaryEntry):
        text = entry.summary
    elif isinstance(entry, CompactionEntry):
        text = entry.summary
    else:
        text = ""

    compact = " ".join(text.split())
    if len(compact) <= TREE_PREVIEW_CHARS:
        return compact
    return compact[:TREE_PREVIEW_CHARS] + "..."
