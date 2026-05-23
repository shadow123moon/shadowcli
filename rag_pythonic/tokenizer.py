"""RAG 查询分词：把"自然语言问题"切成可用于关键词检索的 token。

跟 memory_pythonic.tokenizer 的区别：
- memory 那边只需要"中文词 + 英文短词"
- RAG 这边额外要保留 **代码标识符**（驼峰、下划线、点号），
  因为用户问"怎么实现 CodeRetriever.hybridSearch" 这种词必须命中

Pythonic 要点：
- jieba 缺失静默降级（与 memory tokenizer 同套路）
- frozenset 替代 switch 长链
- 正则配合 .findall 提取所有 ASCII 标识符
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

# 代码标识符：以字母开头，允许 [字母/数字/_./$-]，长度 ≥ 2
_ASCII_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9_.$-]{1,}")

# 中文/英文停用词（与 Java 版同集）
_STOPWORDS = frozenset({
    "怎么", "如何", "什么", "哪些", "一下", "实现", "的是", "一个", "可以", "这里", "那里",
})

# 非分词时的 fallback 切分（标点 / 空白）
_SPLIT_RE = re.compile(r"[，。！？；：\"'（）【】《》、\s\.,;:!\?\(\)\[\]\{\}<>|~@#\$%\^&\*\+=\-_/]+")


def tokenize(query: str | None) -> set[str]:
    """对查询文本分词，返回可用于代码检索的 token 集合。

    保序：用 dict.fromkeys 维护出现顺序，最后转 set 返回。
    （Java 版返回 LinkedHashSet 也是为了顺序。）
    """
    if not query or not query.strip():
        return set()

    normalized = query.strip()
    ordered: dict[str, None] = {}

    # 1. 主分词：jieba 或正则切分
    words = (
        jieba.cut(normalized) if _JIEBA else _SPLIT_RE.split(normalized)
    )
    for word in words:
        token = word.strip()
        if _is_useful(token):
            ordered.setdefault(token, None)

    # 2. ASCII 标识符兜底：把驼峰命名、点号方法名、文件后缀都抓出来
    for m in _ASCII_TOKEN.finditer(normalized):
        token = m.group()
        if _is_useful(token):
            ordered.setdefault(token, None)

    return set(ordered)


def _is_useful(token: str) -> bool:
    if not token or len(token) < 2:
        return False
    lower = token.lower()
    if lower in _STOPWORDS:
        return False
    return _is_meaningful(token)


def _is_meaningful(token: str) -> bool:
    """要求至少包含一个汉字或字母数字，纯标点不算。"""
    has_han = any("一" <= c <= "鿿" for c in token)
    has_alnum = any(c.isalnum() for c in token)
    return has_han or has_alnum
