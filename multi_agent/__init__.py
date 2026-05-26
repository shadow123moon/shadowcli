"""multi_agent - Multi-Agent 协作系统的 Pythonic 完成版。

对齐 paicli 设计核心：
- 两类执行角色：PLANNER（规划者）/ WORKER（执行者）
- 主从架构：Orchestrator 编排，SubAgent 执行
- 完整 ReAct 循环（Worker 调工具 + 工具结果回灌 + 多轮迭代）
- AgentBudget 三道防护：token 预算 + 停滞检测 + 硬轮数
- 并行执行：asyncio.Semaphore + Queue 池化，独立缓冲按顺序 flush
- 二级 JSON 解析容错（关键词兜底）
- Memory 集成（写用户输入 / 助手回复 / LLM 调用前压缩历史）
- 取消机制：threading.Event 在 await 点轮询

文件结构：
- roles.py        AgentRole 枚举
- messages.py     AgentMessage + MessageType + 静态工厂
- budget.py       AgentBudget 三道防护
- sub_agent.py    SubAgent 含完整 ReAct 循环
- orchestrator.py AgentOrchestrator 编排 + 并行池化

外部使用示例：

    import asyncio
    from multi_agent import AgentOrchestrator
    from memory_pythonic import MemoryManager
    from llm.client import chat
    from tooling import ExecuteCommandTool, ListDirTool, ReadFileTool, ToolRegistry, WriteFileTool

    registry = ToolRegistry()
    for tool in [ReadFileTool(), WriteFileTool(), ListDirTool(), ExecuteCommandTool()]:
        registry.register(tool)

    mgr = MemoryManager()
    orch = AgentOrchestrator(chat, registry, memory_manager=mgr)

    async def main():
        result = await orch.run("把当前目录的所有 .py 文件统计一下行数")
        print(result)

    asyncio.run(main())

如果要支持 Ctrl+C 取消：

    import signal, threading
    cancel = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: cancel.set())
    orch = AgentOrchestrator(chat, registry, memory_manager=mgr, cancel=cancel)
"""
from .budget import AgentBudget, ExitReason
from .messages import AgentMessage, MessageType
from .orchestrator import AgentOrchestrator, ExecutionStep, StepStatus, PlanReviewDecision, parse_plan_review_input
from .roles import AgentRole
from .sub_agent import ChatFn, SubAgent

__all__ = [
    "AgentBudget",
    "AgentMessage",
    "AgentOrchestrator",
    "AgentRole",
    "ChatFn",
    "ExecutionStep",
    "ExitReason",
    "MessageType",
    "StepStatus",
    "SubAgent",
]
