"""检索结果格式化：把 SearchResult 列表转成"人/LLM 可读"的文本。

对照 Java 版：
- 两种风格：format_for_cli（带 emoji，给终端看）/ format_for_tool（纯文本，给 LLM 看）
- build_summary 是核心：从 top 结果里抽取"最相关入口 / 涉及文件 / 关键词"三句话
- 实现保持简单：不再调 LLM，纯字符串拼接

Pythonic 要点：
- textwrap.shorten / 自写 _snippet 截断
- pathlib.Path.parts 替代 java Path.subpath
- 模块级 const + 简短函数               替代 final 工具类
"""
from __future__ import annotations

from pathlib import PurePath

from .store import SearchResult
from .tokenizer import tokenize


def format_for_cli(query: str, results: list[SearchResult]) -> str:
    """终端展示用：带计数 + 摘要 + 每条 120 字符片段。"""
    lines = [f"[搜索] 找到 {len(results)} 个相关代码块:", "", build_summary(query, results), ""]
    for i, r in enumerate(results, start=1):
        lines.append(
            f"{i}. [{r.chunk_type}:{r.name}] (相似度: {r.similarity:.3f}) {r.file_path}"
        )
        lines.append("   " + _snippet(r.content, 120).replace("\n", "\n   "))
        lines.append("")
    return "\n".join(lines).rstrip()


def format_for_tool(query: str, results: list[SearchResult]) -> str:
    """给 LLM 工具调用回包用：去掉 emoji，每条 180 字符片段。"""
    lines = ["检索摘要:", build_summary(query, results), "", "检索结果:"]
    for i, r in enumerate(results, start=1):
        lines.append(
            f"{i}. [{r.chunk_type}:{r.name}] (相似度: {r.similarity:.3f}) {r.file_path}"
        )
        lines.append("   " + _snippet(r.content, 180).replace("\n", "\n   "))
        lines.append("")
    return "\n".join(lines).rstrip()


def build_summary(query: str, results: list[SearchResult]) -> str:
    """三句话摘要：最相关入口 / 涉及文件 / 排序依据。"""
    if not results:
        return "搜索摘要:\n- 没有命中可用代码块。"

    top = results[0]
    # 保序去重涉及到的文件名
    file_names: dict[str, None] = {}
    for r in results:
        file_names.setdefault(PurePath(r.file_path).name, None)

    tokens = list(tokenize(query))[:3]
    token_text = "、".join(tokens) if tokens else "自然语言语义"

    related = "、".join(list(file_names)[:3])
    related_suffix = " 等文件" if len(file_names) > 3 else " 这些文件"

    return (
        "搜索摘要:\n"
        f"- 最相关的入口是 [{top.chunk_type}:{top.name}],位于 {_shorten_path(top.file_path)}。\n"
        f"- 当前结果主要集中在 {related}{related_suffix}。\n"
        f"- 这次排序综合参考了 {token_text} 等关键词与语义相似度;先看第 1 条,再按文件继续展开最稳妥。"
    )


def _snippet(content: str | None, max_chars: int) -> str:
    if not content:
        return "(无内容片段)"
    normalized = content.strip().replace("\r\n", "\n").replace("\r", "\n")
    if len(normalized) <= max_chars:
        return normalized
    return normalized[:max_chars] + "..."


def _shorten_path(file_path: str) -> str:
    """太深的路径只留最后 3 段。"""
    parts = PurePath(file_path).parts
    if len(parts) <= 3:
        return file_path
    return str(PurePath(*parts[-3:]))
