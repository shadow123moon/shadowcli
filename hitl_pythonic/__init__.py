"""hitl_pythonic - 人工审批（HITL）Pythonic 移植。

对照 Java com.paicli.hitl 的取舍：
    ApprovalPolicy 静态类     ↔ policy.py 模块函数 + frozenset
    ApprovalRequest record    ↔ request.py @dataclass(frozen, slots)
    ApprovalResult record     ↔ result.py @dataclass + Decision Enum
    HitlHandler 接口          ↔ handler.py typing.Protocol
    TerminalHitlHandler       ↔ terminal.py (threading.Lock 替 synchronized)
    HitlToolRegistry 继承     ↔ gate.py 组合包装 + with_hitl 工厂
    SwitchableHitlHandler     × 暂略（Python 端只有 Terminal 一种 UI）
    RendererHitlHandler       × 暂略（Python 端尚无 Renderer 体系）
    AuditLog 集成             ↔ AuditHook 注入点（业务层接入）

最简用法::

    from hitl_pythonic import TerminalHitlHandler, with_hitl
    from tool_registry import ToolRegistry
    from tools import WriteFileTool

    base = ToolRegistry()
    base.register(WriteFileTool())
    gate = with_hitl(base, TerminalHitlHandler(enabled=True))
    print(gate.execute("write_file", {"path": "/tmp/x", "content": "hi"}))

与 Java 文件对应::

    hitl/ApprovalPolicy.java         ↔ hitl_pythonic/policy.py
    hitl/ApprovalRequest.java        ↔ hitl_pythonic/request.py
    hitl/ApprovalResult.java         ↔ hitl_pythonic/result.py
    hitl/HitlHandler.java            ↔ hitl_pythonic/handler.py
    hitl/TerminalHitlHandler.java    ↔ hitl_pythonic/terminal.py
    hitl/HitlToolRegistry.java       ↔ hitl_pythonic/gate.py
    hitl/SwitchableHitlHandler.java  × （未移植）
    hitl/RendererHitlHandler.java    × （未移植）
"""
from .gate import AuditHook, HitlToolRegistry, with_hitl
from .handler import HitlHandler
from .policy import (
    DANGEROUS_TOOLS,
    MCP_PREFIX,
    danger_level,
    is_mcp_tool,
    mcp_server_name,
    requires_approval,
    risk_description,
)
from .request import ApprovalRequest
from .result import ApprovalResult, Decision
from .terminal import TerminalHitlHandler

__all__ = [
    # —— 数据 ——
    "ApprovalRequest",
    "ApprovalResult",
    "Decision",
    # —— 策略 ——
    "DANGEROUS_TOOLS",
    "MCP_PREFIX",
    "requires_approval",
    "danger_level",
    "risk_description",
    "is_mcp_tool",
    "mcp_server_name",
    # —— 处理器 ——
    "HitlHandler",
    "TerminalHitlHandler",
    # —— 集成 ——
    "HitlToolRegistry",
    "with_hitl",
    "AuditHook",
]
