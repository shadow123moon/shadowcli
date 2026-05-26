"""Approval policy based on tool metadata."""
from __future__ import annotations

from typing import Any, Dict

MCP_PREFIX = "mcp__"
DEFAULT_SAFE_LEVEL = "🟢 安全"
DEFAULT_SAFE_REASON = "安全的只读操作"
MCP_LEVEL = "🟡 MCP"
MCP_REASON = "将调用外部 MCP server 提供的工具，可能访问网络、文件或第三方服务"


def is_mcp_tool(tool_name: str | None) -> bool:
    return bool(tool_name) and tool_name.startswith(MCP_PREFIX)


def mcp_server_name(tool_name: str | None) -> str | None:
    """Extract server name from ``mcp__<server>__<tool>``."""
    if not tool_name or not tool_name.startswith(MCP_PREFIX):
        return None
    parts = tool_name.split("__", 2)
    return parts[1] if len(parts) >= 2 and parts[1] else None


def requires_approval_for_tool(
    tool: Any,
    arguments: Dict[str, Any] | None = None,
) -> bool:
    checker = getattr(tool, "requires_approval", None)
    if callable(checker):
        return bool(checker(arguments or {}))
    return is_mcp_tool(getattr(tool, "name", ""))


def danger_level_for_tool(tool: Any) -> str:
    level = getattr(tool, "approval_level", None)
    if level:
        return str(level)
    return MCP_LEVEL if is_mcp_tool(getattr(tool, "name", "")) else DEFAULT_SAFE_LEVEL


def risk_description_for_tool(tool: Any) -> str:
    reason = getattr(tool, "approval_reason", None)
    if reason:
        return str(reason)
    return MCP_REASON if is_mcp_tool(getattr(tool, "name", "")) else DEFAULT_SAFE_REASON
