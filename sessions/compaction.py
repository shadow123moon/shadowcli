from __future__ import annotations

import os
import sys
from dataclasses import dataclass

from llm import ChatResponse, Message, chat

from .entries import CompactionEntry, MessageEntry
from .manager import SessionManager


DEFAULT_CONTEXT_WINDOW_TOKENS = 256_000
DEFAULT_COMPACT_TRIGGER_RATIO = 0.80
DEFAULT_COMPACT_KEEP_RATIO = 1 / 3
DEFAULT_COMPACT_MAX_TOKENS = int(DEFAULT_CONTEXT_WINDOW_TOKENS * DEFAULT_COMPACT_TRIGGER_RATIO)
DEFAULT_COMPACT_KEEP_TOKENS = int(DEFAULT_COMPACT_MAX_TOKENS * DEFAULT_COMPACT_KEEP_RATIO)


@dataclass
class CompactionPlan:
    summary_entries: list[MessageEntry]
    kept_entries: list[MessageEntry]
    first_kept_entry_id: str
    tokens_before: int
    keep_tokens: int


@dataclass
class CompactionResult:
    compacted: bool
    reason: str
    entry: CompactionEntry | None = None
    plan: CompactionPlan | None = None


def compact_session(
    session: SessionManager,
    *,
    max_tokens: int | None = None,
    keep_tokens: int | None = None,
    force: bool = False,
    chat_fn=chat,
) -> CompactionResult:
    default_max_tokens = _default_compact_max_tokens()
    max_tokens = max_tokens or _read_int_env("SHADOWCLI_COMPACT_MAX_TOKENS", default_max_tokens)
    default_keep_tokens = max(1, int(max_tokens * DEFAULT_COMPACT_KEEP_RATIO))
    keep_tokens = keep_tokens or _read_int_env("SHADOWCLI_COMPACT_KEEP_TOKENS", default_keep_tokens)
    plan = plan_compaction(
        session,
        max_tokens=max_tokens,
        keep_tokens=keep_tokens,
        force=force,
    )
    if plan is None:
        return CompactionResult(False, _skip_reason(session, max_tokens=max_tokens, force=force))

    summary = generate_compaction_summary(plan, chat_fn=chat_fn)
    entry = session.append_compaction(
        summary=summary,
        first_kept_entry_id=plan.first_kept_entry_id,
        tokens_before=plan.tokens_before,
    )
    return CompactionResult(True, "已压缩当前会话分支", entry=entry, plan=plan)


def plan_compaction(
    session: SessionManager,
    *,
    max_tokens: int = DEFAULT_COMPACT_MAX_TOKENS,
    keep_tokens: int = DEFAULT_COMPACT_KEEP_TOKENS,
    force: bool = False,
) -> CompactionPlan | None:
    messages = _messages_after_last_compaction(session)
    blocks = _message_blocks(messages)
    if len(blocks) < 2:
        return None

    block_tokens = [_estimate_entries_tokens(block) for block in blocks]
    total_tokens = sum(block_tokens)
    if not force and total_tokens <= max_tokens:
        return None

    kept_block_index = _choose_kept_block_index(blocks, block_tokens, keep_tokens)
    if kept_block_index is None or kept_block_index <= 0:
        return None

    summary_entries = _flatten(blocks[:kept_block_index])
    kept_entries = _flatten(blocks[kept_block_index:])
    if not summary_entries or not kept_entries:
        return None

    return CompactionPlan(
        summary_entries=summary_entries,
        kept_entries=kept_entries,
        first_kept_entry_id=kept_entries[0].id,
        tokens_before=total_tokens,
        keep_tokens=keep_tokens,
    )


def build_compaction_prompt(plan: CompactionPlan) -> str:
    lines = [
        "请压缩以下较早的会话片段。",
        "只保留任务目标、关键决定、已读/已改文件、重要错误、未完成事项。",
        "不要续写对话，不要调用工具。",
        "",
        "<conversation_to_compact>",
    ]
    for entry in plan.summary_entries:
        lines.append(_format_message_entry(entry))
    lines.extend([
        "</conversation_to_compact>",
        "",
        "输出中文摘要，控制在 300 字以内。",
    ])
    return "\n".join(lines)


def generate_compaction_summary(plan: CompactionPlan, *, chat_fn=chat) -> str:
    response: ChatResponse = chat_fn(
        [Message(role="user", content=build_compaction_prompt(plan))],
        tools=None,
    )
    summary = (response.content or "").strip()
    return summary or "（空压缩摘要）"


def _messages_after_last_compaction(session: SessionManager) -> list[MessageEntry]:
    branch = session.get_branch()
    start_index = 0
    for index, entry in enumerate(branch):
        if isinstance(entry, CompactionEntry):
            start_index = index + 1
    return [
        entry
        for entry in branch[start_index:]
        if isinstance(entry, MessageEntry)
    ]


def _message_blocks(messages: list[MessageEntry]) -> list[list[MessageEntry]]:
    blocks: list[list[MessageEntry]] = []
    current: list[MessageEntry] = []
    for entry in messages:
        if entry.message.role == "user" and current:
            blocks.append(current)
            current = [entry]
        else:
            current.append(entry)
    if current:
        blocks.append(current)
    return blocks


def _choose_kept_block_index(
    blocks: list[list[MessageEntry]],
    block_tokens: list[int],
    keep_tokens: int,
) -> int | None:
    kept_index = len(blocks) - 1
    recent_tokens = block_tokens[kept_index]
    while kept_index > 1 and recent_tokens + block_tokens[kept_index - 1] <= keep_tokens:
        kept_index -= 1
        recent_tokens += block_tokens[kept_index]

    if blocks[kept_index][0].message.role == "user":
        return kept_index

    for index in range(kept_index + 1, len(blocks)):
        if blocks[index][0].message.role == "user":
            return index
    return None


def _estimate_entries_tokens(entries: list[MessageEntry]) -> int:
    return sum(_estimate_text_tokens(_format_message_entry(entry)) for entry in entries)


def _estimate_text_tokens(text: str) -> int:
    encoder = _token_encoder()
    if encoder is not None:
        try:
            return max(1, len(encoder.encode(text or "", disallowed_special=())))
        except TypeError:
            try:
                return max(1, len(encoder.encode(text or "")))
            except Exception:
                pass
        except Exception:
            pass
    # Fallback: ~4 chars per token for English/Chinese mixed text
    return max(1, (len(text) + 3) // 4)


_ENCODER_CACHE = None
_ENCODER_FAILED = False
_ENCODER_MODULE_ID = None


def _token_encoder():
    global _ENCODER_CACHE, _ENCODER_FAILED, _ENCODER_MODULE_ID

    current_module = sys.modules.get("tiktoken")
    current_module_id = id(current_module) if current_module is not None else None
    if _ENCODER_CACHE is not None and _ENCODER_MODULE_ID != current_module_id:
        _ENCODER_CACHE = None
        _ENCODER_FAILED = False
    if _ENCODER_FAILED and current_module is not None:
        _ENCODER_FAILED = False

    if _ENCODER_FAILED:
        return None

    if _ENCODER_CACHE is not None:
        return _ENCODER_CACHE

    try:
        import tiktoken  # type: ignore
    except Exception:
        _ENCODER_FAILED = True
        return None

    _ENCODER_MODULE_ID = id(tiktoken)

    model = os.environ.get("MODEL") or "gpt-4o"

    # Try with a short timeout to avoid hanging on network issues
    import socket
    old_timeout = socket.getdefaulttimeout()
    try:
        socket.setdefaulttimeout(3.0)  # 3 second timeout for downloads

        try:
            enc = tiktoken.encoding_for_model(model)
            _ENCODER_CACHE = enc
            _ENCODER_MODULE_ID = id(tiktoken)
            return enc
        except Exception:
            pass

        for encoding_name in ("o200k_base", "cl100k_base"):
            try:
                enc = tiktoken.get_encoding(encoding_name)
                _ENCODER_CACHE = enc
                _ENCODER_MODULE_ID = id(tiktoken)
                return enc
            except Exception:
                continue
    finally:
        socket.setdefaulttimeout(old_timeout)

    _ENCODER_FAILED = True
    return None


def _format_message_entry(entry: MessageEntry) -> str:
    message = entry.message
    parts = [f"{message.role}: {message.content or ''}".rstrip()]
    if message.tool_calls:
        calls = [
            f"{call.function.name}({call.function.arguments})"
            for call in message.tool_calls
        ]
        parts.append("tool_calls: " + "; ".join(calls))
    if message.tool_call_id:
        parts.append(f"tool_call_id: {message.tool_call_id}")
    return "\n".join(parts)


def _flatten(blocks: list[list[MessageEntry]]) -> list[MessageEntry]:
    return [entry for block in blocks for entry in block]


def _skip_reason(session: SessionManager, *, max_tokens: int, force: bool) -> str:
    messages = _messages_after_last_compaction(session)
    blocks = _message_blocks(messages)
    if len(blocks) < 2:
        return "没有安全切点：至少需要两轮可分割的会话"
    if not force and sum(_estimate_entries_tokens(block) for block in blocks) <= max_tokens:
        return "当前会话未超过压缩阈值"
    return "没有安全切点：无法在 user 消息边界保留最近上下文"


def _read_int_env(key: str, default: int) -> int:
    raw = os.environ.get(key)
    if not raw or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        return default
    return value if value > 0 else default


def _read_float_env(key: str, default: float) -> float:
    raw = os.environ.get(key)
    if not raw or not raw.strip():
        return default
    try:
        value = float(raw.strip())
    except ValueError:
        return default
    return value if value > 0 else default


def _default_compact_max_tokens() -> int:
    context_window = _read_int_env("SHADOWCLI_CONTEXT_WINDOW_TOKENS", DEFAULT_CONTEXT_WINDOW_TOKENS)
    trigger_ratio = _read_float_env("SHADOWCLI_COMPACT_TRIGGER_RATIO", DEFAULT_COMPACT_TRIGGER_RATIO)
    if trigger_ratio > 1:
        trigger_ratio = DEFAULT_COMPACT_TRIGGER_RATIO
    return max(1, int(context_window * trigger_ratio))
