"""审批请求 + 终端可读展示。

对照 Java com.paicli.hitl.ApprovalRequest 的取舍：
- Java 自己用 60+ 行手算 CJK 显示宽度
  Python 直接用 unicodedata.east_asian_width 标准库判定
- Java 参数存 String(JSON)；Python 直接存 dict，展示时按字段格式化
- 排版工具函数（_pad / _truncate / _wrap）抽到模块级，request 类只组装
"""
from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from typing import Any, Iterator

from . import policy

_BOX_INNER_WIDTH = 58
_FIELD_PREFIX_COLS = 2     # "│  " 内边距占的显示列
_INDENT_PREFIX_COLS = 4    # "│    " 缩进行
_ARG_LINE_WIDTH = _BOX_INNER_WIDTH - _INDENT_PREFIX_COLS - 2  # 末尾 "│" 也占 2 视觉
_MAX_LONG_VALUE_PREVIEW = 120


def _display_width(s: str) -> int:
    """终端显示宽度：CJK / 全角 / 主流 emoji 占 2 列。"""
    if not s:
        return 0
    width = 0
    for ch in s:
        cp = ord(ch)
        if cp < 0x20 or cp == 0x7F:
            continue  # 控制字符不占列
        # F = 全角, W = 宽, A = 模糊（CJK 上下文按宽算）
        if unicodedata.east_asian_width(ch) in {"F", "W", "A"}:
            width += 2
        else:
            width += 1
    return width


def _pad_right(s: str, target_cols: int) -> str:
    extra = target_cols - _display_width(s)
    return s + " " * extra if extra > 0 else s


def _truncate(s: str, target_cols: int, ellipsis: str = "...") -> str:
    if _display_width(s) <= target_cols:
        return s
    reserve = _display_width(ellipsis)
    chars: list[str] = []
    used = 0
    for ch in s:
        cw = 2 if unicodedata.east_asian_width(ch) in {"F", "W", "A"} else 1
        if used + cw > target_cols - reserve:
            break
        chars.append(ch)
        used += cw
    return "".join(chars) + ellipsis


def _wrap(text: str, line_width: int) -> list[str]:
    if not text:
        return [""]
    lines: list[str] = []
    current: list[str] = []
    used = 0
    for ch in text:
        cw = 2 if unicodedata.east_asian_width(ch) in {"F", "W", "A"} else 1
        if used + cw > line_width:
            lines.append("".join(current))
            current = []
            used = 0
        current.append(ch)
        used += cw
    if current:
        lines.append("".join(current))
    return lines or [""]


@dataclass(frozen=True, slots=True)
class ApprovalRequest:
    tool_name: str
    arguments: dict[str, Any]
    suggestion: str | None = None
    caller_context: str | None = None
    sensitive_notice: str | None = None

    @property
    def danger_level(self) -> str:
        return policy.danger_level(self.tool_name)

    @property
    def risk_description(self) -> str:
        return policy.risk_description(self.tool_name)

    @property
    def mcp_server(self) -> str | None:
        return policy.mcp_server_name(self.tool_name)

    def to_display_text(self) -> str:
        """渲染成终端可读的边框文本。"""
        border = "─" * _BOX_INNER_WIDTH
        lines = [
            f"┌{border}┐",
            self._box_line("⚠️  需要审批"),
            f"├{border}┤",
            self._box_field("工具", self.tool_name),
        ]
        if self.mcp_server:
            lines.append(self._box_field("MCP server", self.mcp_server))
        lines.append(self._box_field("等级", self.danger_level))
        lines.append(self._box_field("风险", self.risk_description))
        if self.caller_context:
            lines.append(self._box_field("来源", self.caller_context))
        if self.sensitive_notice:
            lines.append(self._box_field("敏感页面", self.sensitive_notice))
        lines.append(f"├{border}┤")
        lines.append(self._box_line("参数:"))
        for line in self._format_args():
            lines.append(self._box_indented(line))
        if self.suggestion:
            lines.append(f"├{border}┤")
            lines.append(self._box_line("执行理由:"))
            for line in _wrap(self.suggestion, _ARG_LINE_WIDTH):
                lines.append(self._box_indented(line))
        lines.append(f"└{border}┘")
        return "\n".join(lines)

    # ---------- 排版 ----------
    def _box_field(self, label: str, value: str) -> str:
        prefix = f"{label}: "
        target = _BOX_INNER_WIDTH - _display_width(prefix) - _FIELD_PREFIX_COLS
        return f"│  {prefix}{_pad_right(_truncate(value or '', target), target)}│"

    def _box_line(self, text: str) -> str:
        target = _BOX_INNER_WIDTH - _FIELD_PREFIX_COLS
        return f"│  {_pad_right(_truncate(text or '', target), target)}│"

    def _box_indented(self, text: str) -> str:
        target = _BOX_INNER_WIDTH - _INDENT_PREFIX_COLS
        return f"│    {_pad_right(_truncate(text or '', target), target)}│"

    def _format_args(self) -> Iterator[str]:
        """逐字段格式化参数；长字符串只展示前 N 个字符 + 总长度。"""
        if not self.arguments:
            yield "(无参数)"
            return
        for key, val in self.arguments.items():
            if isinstance(val, str):
                if len(val) > _MAX_LONG_VALUE_PREVIEW:
                    head = val[:_MAX_LONG_VALUE_PREVIEW].replace("\n", "⏎")
                    snippet = f'{key}: "{head}..." ({len(val)} 字符)'
                else:
                    snippet = f'{key}: "{val.replace(chr(10), "⏎")}"'
            else:
                snippet = f"{key}: {json.dumps(val, ensure_ascii=False)}"
            yield from _wrap(snippet, _ARG_LINE_WIDTH)
