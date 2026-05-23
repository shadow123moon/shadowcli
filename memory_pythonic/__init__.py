"""memory_pythonic - 纯 Pythonic 风格的记忆模块。

与 memory/ 包对比，这一版去掉了 Java 翻译痕迹，使用：
- typing.Protocol 替代 ABC（结构子类型）
- @property 替代 get_xxx() / set_xxx()
- __len__ / __iter__ / __contains__ / __getitem__ 替代 size() / get_all() 等
- 模块级函数替代静态工具类
- dataclass(slots=True) / keyword-only / walrus 等现代特性
- textwrap.dedent 处理多行 prompt

外部使用：
    from memory_pythonic import MemoryManager, MemoryEntry, MemoryType

    mgr = MemoryManager()
    mgr.add_user("你好")
    for entry in mgr.short_term:            # 直接迭代
        print(entry)
    if "user-abcd1234" in mgr.short_term:   # in 操作符
        ...
    print(len(mgr.short_term))              # len() 内置

与 memory/ 文件对应：
    memory/conversation.py ↔ memory_pythonic/short_term.py
    memory/long_term.py    ↔ memory_pythonic/long_term.py
    memory/tokenizer.py    ↔ memory_pythonic/tokenizer.py
    memory/retriever.py    ↔ memory_pythonic/retrieval.py
    memory/budget.py       ↔ memory_pythonic/budget.py
    memory/compressor.py   ↔ memory_pythonic/compress.py
    memory/manager.py      ↔ memory_pythonic/manager.py
    memory/entry.py        ↔ memory_pythonic/entry.py
    memory/hints.py        × （砍掉，业务硬编码无关 memory 概念）
"""
from .budget import (
    ContextProfile,
    TokenBudget,
    estimate_messages_tokens,
    profile_for_model,
)
from .compress import (
    ChatFn,
    compact_history,
    compress_memory,
    extract_facts,
)
from .entry import (
    Memory,
    MemoryEntry,
    MemoryType,
    estimate_tokens,
)
from .long_term import LongTermMemory
from .manager import MemoryManager
from .retrieval import (
    build_context,
    rank,
    relevance_score,
    search,
    search_long_only,
)
from .short_term import ConversationMemory
from .tokenizer import matches, tokenize

__all__ = [
    # —— 数据 ——
    "Memory",
    "MemoryEntry",
    "MemoryType",
    "estimate_tokens",
    # —— 存储 ——
    "ConversationMemory",
    "LongTermMemory",
    # —— 检索 ——
    "build_context",
    "rank",
    "relevance_score",
    "search",
    "search_long_only",
    # —— 分词 ——
    "matches",
    "tokenize",
    # —— 预算 ——
    "ContextProfile",
    "TokenBudget",
    "estimate_messages_tokens",
    "profile_for_model",
    # —— 压缩 ——
    "ChatFn",
    "compact_history",
    "compress_memory",
    "extract_facts",
    # —— 门面 ——
    "MemoryManager",
]
