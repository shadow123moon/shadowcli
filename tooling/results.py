from __future__ import annotations

DEFAULT_TOOL_RESULT_TEXT_LIMIT = 12_000


def truncate_tool_text(text: str, limit: int = DEFAULT_TOOL_RESULT_TEXT_LIMIT) -> str:
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    omitted = len(text) - limit
    return text[:limit].rstrip() + f"\n...(已截断，省略 {omitted} 字符)"
