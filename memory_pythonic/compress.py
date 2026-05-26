"""上下文压缩：短期记忆 Map-Reduce + 消息历史压缩。

两道压缩各自解决：
- compress_memory   : 压 ConversationMemory（短期记忆条目）
- compact_history   : 压 Agent 主循环的 conversation_history（List[Message]）
                       关键约束：分割点必须在 user message 边界，保护 tool_call 配对

Pythonic 要点：
- 模块级函数替代静态类   ContextCompressor / ConversationHistoryCompactor 都拆成函数
- textwrap.dedent        让长 prompt 的缩进对齐源码而不影响实际内容
- keyword-only 参数      *, retain_recent / chunk_size / trigger_tokens
- walrus / generator     紧凑表达
- history[:] = rebuilt   原地替换列表的 Python 习惯
"""
from __future__ import annotations

import logging
import textwrap
import uuid
from collections.abc import Callable, Iterable, Iterator
from typing import TYPE_CHECKING

from .budget import estimate_messages_tokens
from .entry import MemoryEntry, MemoryType

if TYPE_CHECKING:
    from llm import Message

    from .long_term import LongTermMemory
    from .short_term import ConversationMemory

log = logging.getLogger(__name__)

# LLM chat 函数签名：chat(messages, tools=None, ...) -> ChatResponse-like
ChatFn = Callable[..., object]


# ---------- 提示词（dedent 让缩进对齐源码） ----------
MAP_PROMPT = textwrap.dedent("""\
    请将以下对话片段压缩成一段简洁的摘要，保留关键信息：
    - 用户的需求和意图
    - 已执行的操作和结果
    - 做出的决策和结论
    - 重要的技术细节

    对话片段：
    {chunk}

    请用中文输出摘要，控制在200字以内。
    """)

REDUCE_PROMPT = textwrap.dedent("""\
    请将以下多个摘要合并成一个整体摘要，保留所有关键信息。

    各片段摘要：
    {summaries}

    请用中文输出合并摘要，控制在300字以内。
    """)

EXTRACT_FACTS_PROMPT = textwrap.dedent("""\
    请从以下对话中提取"跨会话仍然成立、未来复用仍有价值"的稳定事实，格式为每行一条：
    - 用户偏好和习惯
    - 项目信息（名称、路径、技术栈）
    - 重要决策和约定

    只保留用户明确说明、或工具/代码库可验证的信息。
    绝对不要提取以下内容：
    - 当前这一轮让你执行的临时任务、步骤、todo
    - 一次性的文件名、目录名、输出要求
    - 模型自己的猜测、纠错、提醒、推断
    - "用户想要/需要/让我/请你..." 这类请求句

    对话内容：
    {conversation}

    请每行一条事实，不要多余解释。
    """)

HISTORY_PROMPT = textwrap.dedent("""\
    请把下面的对话历史压缩成简明摘要，保留：
    1. 用户提出的关键诉求与目标
    2. Agent 已经完成的关键操作（哪些工具调用了什么、返回了什么核心结果）
    3. 已经达成的共识或结论
    4. 仍未解决的问题或待办

    不要复述每条原文，不要列举所有工具调用，不要保留无关闲聊。
    输出 1-3 段中文，不要用列表，不要加任何前缀或元描述。

    === 待压缩的对话 ===
    {conversation}
    === 待压缩的对话（结束）===
    """)


# 事实过滤词表
EPHEMERAL_PREFIXES = (
    "用户想", "用户要", "用户需要", "用户请求", "帮我", "让我",
    "新建", "创建", "删除", "修改", "生成", "补充要求", "当前这一轮", "本次任务",
)
SPECULATION_CUES = ("可能", "应该", "猜测", "推测", "笔误", "提醒")
DURABLE_HINTS = (
    "用户偏好", "用户习惯", "喜欢", "倾向", "项目", "仓库", "路径", "技术栈",
    "版本", "模型", "接口", "配置", "环境变量", "命令", "约定", "规则", "默认",
)

MAX_HISTORY_INPUT_CHARS = 60_000


# ---------- 私有：Message 构造助手（延迟 import 避免循环） ----------
def _system(content: str) -> Message:
    from llm import Message
    return Message(role="system", content=content)


def _user(content: str) -> Message:
    from llm import Message
    return Message(role="user", content=content)


def _assistant(content: str) -> Message:
    from llm import Message
    return Message(role="assistant", content=content)


# ---------- 短期记忆压缩 ----------
def compress_memory(
    memory: ConversationMemory,
    chat: ChatFn,
    *,
    retain_recent: int = 3,
    chunk_size: int = 5,
) -> str | None:
    """Map-Reduce 压缩短期记忆。

    流程：
    1. 把短期记忆按 chunk_size 切片，每片让 LLM 摘要（Map）
    2. 多片合并成最终摘要（Reduce）
    3. 清空短期记忆，注入 [历史对话摘要] + 保留最后 retain_recent 条

    :return: 最终摘要文本；条目数不足 retain_recent 时返回 None。
    """
    entries = list(memory)
    if len(entries) <= retain_recent:
        return None

    split = len(entries) - retain_recent
    old, recent = entries[:split], entries[split:]

    chunk_summaries = _map_phase(old, chat, chunk_size)
    if not chunk_summaries:
        return None

    summary = (
        chunk_summaries[0]
        if len(chunk_summaries) == 1
        else _reduce_phase(chunk_summaries, chat)
    )

    memory.clear()
    memory.store(MemoryEntry(
        id=f"summary-{uuid.uuid4().hex[:8]}",
        content=f"[历史对话摘要] {summary}",
        type=MemoryType.SUMMARY,
    ))
    for entry in recent:
        memory.store(entry)
    return summary


def _map_phase(entries: list[MemoryEntry], chat: ChatFn, chunk_size: int) -> list[str]:
    summaries: list[str] = []
    for chunk in _chunked(entries, chunk_size):
        chunk_text = "\n\n".join(f"{e.type.name}: {e.content}" for e in chunk)
        try:
            response = chat(messages=[
                _system("你是一个对话摘要助手。"),
                _user(MAP_PROMPT.format(chunk=chunk_text)),
            ])
            content = getattr(response, "content", None)
            summaries.append(content or _fallback(chunk_text))
        except Exception as exc:
            log.warning("摘要生成失败: %s", exc)
            summaries.append(_fallback(chunk_text))
    return summaries


def _reduce_phase(summaries: list[str], chat: ChatFn) -> str:
    joined = "\n\n---\n\n".join(summaries)
    try:
        response = chat(messages=[
            _system("你是一个摘要合并助手。"),
            _user(REDUCE_PROMPT.format(summaries=joined)),
        ])
        content = getattr(response, "content", None)
        return content or "；".join(summaries)
    except Exception as exc:
        log.warning("摘要合并失败: %s", exc)
        return "；".join(summaries)


def _chunked(items: list[MemoryEntry], size: int) -> Iterator[list[MemoryEntry]]:
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _fallback(text: str) -> str:
    return f"[压缩] {text[:200]}"


# ---------- 事实提取 ----------
def extract_facts(
    entries: Iterable[MemoryEntry],
    long_term: LongTermMemory,
    chat: ChatFn,
) -> list[str]:
    """从对话中提取持久事实，按规则过滤后写入长期记忆。"""
    entries = list(entries)
    if not entries:
        return []

    conversation = "\n".join(
        f"{_source_of(e).upper()}({e.type.name}): {e.content}\n" for e in entries
    )

    try:
        response = chat(messages=[
            _system("你是一个信息提取助手，只输出关键事实，不输出其他内容。"),
            _user(EXTRACT_FACTS_PROMPT.format(conversation=conversation)),
        ])
        text = getattr(response, "content", None) or ""
    except Exception as exc:
        log.warning("事实提取失败: %s", exc)
        return []

    facts: list[str] = []
    for line in text.split("\n"):
        fact = _strip_bullet(line)
        if _is_durable(fact):
            facts.append(fact)
            long_term.store(MemoryEntry(
                id=f"fact-{uuid.uuid4().hex[:8]}",
                content=fact,
                type=MemoryType.FACT,
                metadata={"source": "fact_extractor"},
            ))
    return facts


def _source_of(entry: MemoryEntry) -> str:
    if (src := entry.metadata.get("source")) and src.strip():
        return src
    for prefix in ("user", "assistant", "tool"):
        if entry.id.startswith(f"{prefix}-"):
            return prefix
    return "unknown"


def _strip_bullet(line: str) -> str:
    fact = (line or "").strip()
    return fact[2:].strip() if fact.startswith(("- ", "• ")) else fact


def _is_durable(fact: str) -> bool:
    if not fact or len(fact) <= 5:
        return False
    lower = fact.lower()
    if any(lower.startswith(p) for p in EPHEMERAL_PREFIXES):
        return False
    if any(cue in lower for cue in SPECULATION_CUES):
        return False
    if "：" in lower or ":" in lower:
        return True
    return any(hint in lower for hint in DURABLE_HINTS)


# ---------- 消息历史压缩 ----------
def compact_history(
    history: list[Message],
    chat: ChatFn,
    *,
    trigger_tokens: int,
    retain_recent: int = 3,
) -> bool:
    """在 user message 边界切分，压缩 history 前段为摘要并原地替换。

    关键约束：split_idx 必然落在 user message 上，避免切断 tool_call/tool_result 配对。

    :return: 是否真的执行了压缩
    """
    if not history:
        return False

    current = estimate_messages_tokens(history)
    if current < trigger_tokens:
        return False

    system_end = 1 if history[0].role == "system" else 0
    user_indices = [
        i for i, m in enumerate(history[system_end:], system_end) if m.role == "user"
    ]
    if len(user_indices) <= retain_recent:
        log.info(
            "history compact skip: only %d user turns, <= %d",
            len(user_indices), retain_recent,
        )
        return False

    split_idx = user_indices[-retain_recent]
    if split_idx <= system_end:
        return False

    old = history[system_end:split_idx]
    if not old:
        return False

    try:
        summary = _summarize_history(old, chat)
    except Exception as exc:
        log.warning("history summary failed: %s", exc)
        return False

    if not summary or not summary.strip():
        log.warning("history summary returned empty; skip compaction")
        return False

    rebuilt = (
        history[:system_end]
        + [
            _user(f"[已压缩的历史对话摘要]\n{summary.strip()}"),
            _assistant("好的，我已了解之前的上下文，请继续。"),
        ]
        + history[split_idx:]
    )

    after = estimate_messages_tokens(rebuilt)
    history[:] = rebuilt  # 原地替换
    log.info(
        "history compacted: %d → %d tokens, %d messages, summary %d chars",
        current, after, len(rebuilt), len(summary),
    )
    return True


def _summarize_history(messages: list[Message], chat: ChatFn) -> str:
    parts: list[str] = []
    chars = 0
    for m in messages:
        parts.append(f"{m.role.upper()}: ")
        if m.content:
            parts.append(m.content)
        for tc in (m.tool_calls or []):
            parts.append(f"\n  TOOL_CALL {tc.function.name}: {tc.function.arguments}")
        parts.append("\n\n")
        chars += sum(len(p) for p in parts[-3:])
        if chars > MAX_HISTORY_INPUT_CHARS:
            parts.append("...(超长内容已截断)\n")
            break

    response = chat(messages=[
        _system("你是一个对话摘要助手，只输出摘要本身，不输出元描述。"),
        _user(HISTORY_PROMPT.format(conversation="".join(parts))),
    ])
    return getattr(response, "content", None) or ""
