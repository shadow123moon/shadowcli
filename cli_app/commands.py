from memory_pythonic import MemoryManager

from .constants import MEMORY_COMMAND, PLAN_COMMAND, REMEMBER_COMMAND


def parse_plan_command(user_input: str) -> str | None:
    stripped = user_input.strip()
    if stripped == PLAN_COMMAND:
        return ""
    if stripped.startswith(f"{PLAN_COMMAND} "):
        return stripped[len(PLAN_COMMAND):].strip()
    return None


def parse_remember_command(user_input: str) -> str | None:
    stripped = user_input.strip()
    if stripped == REMEMBER_COMMAND:
        return ""
    if stripped.startswith(f"{REMEMBER_COMMAND} "):
        return stripped[len(REMEMBER_COMMAND):].strip()
    return None


def handle_remember(memory: MemoryManager, user_input: str) -> str:
    fact = parse_remember_command(user_input)
    if fact is None:
        return f"用法: {REMEMBER_COMMAND} <事实>"
    if not fact:
        return f"用法: {REMEMBER_COMMAND} <事实>"
    memory.remember(fact)
    return f"已记住: {fact}"


def format_memory_status(memory: MemoryManager) -> str:
    return "\n".join([
        (
            f"short_term: {len(memory.short_term)} entries, "
            f"{memory.short_term.total_tokens}/{memory.short_term.max_tokens} tokens"
        ),
        f"long_term : {len(memory.long_term)} entries, {memory.long_term.total_tokens} tokens",
        f"storage   : {memory.long_term.storage_path}",
    ])
