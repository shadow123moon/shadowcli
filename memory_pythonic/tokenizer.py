"""检索分词：模块级函数 tokenize / matches，不藏在静态类里。

Pythonic 要点：
- 模块级函数            没有"包装在类里的静态方法"
- set comprehension     紧凑
- jieba 缺失静默降级    捕获 ImportError 而不是裸 Exception
"""
from __future__ import annotations

import logging
import re

log = logging.getLogger(__name__)

try:
    import jieba
    jieba.setLogLevel(logging.WARNING)
    _JIEBA = True
except ImportError:
    _JIEBA = False

_PUNCT = re.compile(
    r"[，。！？；：“”‘’、《》【】（）…—\s\.,;:!\?\"'`/\\\(\)\[\]\{\}<>|~@#\$%\^&\*\+=\-_]+"
)


def tokenize(query: str | None) -> set[str]:
    """对查询文本分词，返回检索 token 集合。"""
    if not query or not query.strip():
        return set()

    text = query.lower().strip()
    if _JIEBA:
        return {
            w for w in (s.strip() for s in jieba.cut(text))
            if len(w) >= 2 and not _PUNCT.fullmatch(w)
        }
    return {w for w in (s.strip() for s in _PUNCT.split(text)) if len(w) >= 2}


def matches(text: str | None, query_tokens: set[str]) -> bool:
    """text 中是否包含任意一个 query token（子串匹配）。"""
    if not text or not query_tokens:
        return False
    lowered = text.lower()
    return any(tok in lowered for tok in query_tokens)
