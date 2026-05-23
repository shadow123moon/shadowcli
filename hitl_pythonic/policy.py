"""审批策略：判断哪些工具需要人工审批。

对照 Java com.paicli.hitl.ApprovalPolicy 的取舍：
- Java 用 final class + private 构造器模拟 namespace
- Python 直接用模块级常量 + 函数，不造类
- 危险等级 / 风险描述用 dict 查找而非 switch 表达式
"""
from __future__ import annotations

from typing import Dict, Any

DANGEROUS_TOOLS: frozenset[str] = frozenset({
    "write_file",
    "execute_command",
    "create_project",
    "revert_turn",
})

MCP_PREFIX = "mcp__"

_DANGER_LEVELS: dict[str, str] = {
    "execute_command": "🔴 高危",
    "revert_turn": "🔴 高危",
    "write_file": "🟡 中危",
    "create_project": "🟡 中危",
}

_RISK_DESCRIPTIONS: dict[str, str] = {
    "execute_command": "将在系统上执行 Shell 命令，可能修改文件、安装软件或影响系统状态",
    "revert_turn": "将按 Side-Git 快照批量恢复工作区文件，可能覆盖当前未保存修改",
    "write_file": "将写入或覆盖文件内容，原有内容将丢失",
    "create_project": "将在磁盘上创建新目录和文件",
}


def is_mcp_tool(tool_name: str | None) -> bool:
    return bool(tool_name) and tool_name.startswith(MCP_PREFIX)


def mcp_server_name(tool_name: str | None) -> str | None:
    """从 ``mcp__<server>__<tool>`` 提取 server 名；非 MCP 工具返回 None。"""
    if not tool_name or not tool_name.startswith(MCP_PREFIX):
        return None
    parts = tool_name.split("__", 2)
    return parts[1] if len(parts) >= 2 and parts[1] else None


def requires_approval(tool_name: str,arguments: Dict[str, Any] |None=None) -> bool:
    # 白名单:写到 /tmp/ 下的临时文件,免审批
    if tool_name == "write_file" and arguments is not None:
        path = arguments.get("path", "")
        if path.startswith("/tmp/"):
            return False
    return tool_name in DANGEROUS_TOOLS or is_mcp_tool(tool_name)


def danger_level(tool_name: str) -> str:
    if tool_name in _DANGER_LEVELS:
        return _DANGER_LEVELS[tool_name]
    return "🟡 MCP" if is_mcp_tool(tool_name) else "🟢 安全"


def risk_description(tool_name: str) -> str:
    if tool_name in _RISK_DESCRIPTIONS:
        return _RISK_DESCRIPTIONS[tool_name]
    if is_mcp_tool(tool_name):
        return "将调用外部 MCP server 提供的工具，可能访问网络、文件或第三方服务"
    return "安全的只读操作"
