"""测试纯流式 Agent 和 Ctrl+C 中止功能。"""
import threading
from llm.types import Message
from multi_agent.sub_agent import SubAgent
from multi_agent.roles import AgentRole
from tooling.registry import ToolRegistry
from tooling.command_tools import BashTool
from tooling.file_tools import ReadTool, WriteTool, ListDirTool
from llm.client import chat

def main():
    # 创建工具注册表
    registry = ToolRegistry()
    registry.register(BashTool())
    registry.register(ReadTool())
    registry.register(WriteTool())
    registry.register(ListDirTool())

    # 创建取消事件
    cancel_event = threading.Event()

    # 创建 Agent
    agent = SubAgent(
        name="test-agent",
        role=AgentRole.REACT,
        chat=chat,
        tool_registry=registry,
        cancel=cancel_event,
    )

    # 测试任务：让模型生成一段长文本
    task = Message(
        role="user",
        content="请用 Python 写一个简单的计算器程序，支持加减乘除四则运算。"
    )

    print("=" * 60)
    print("开始流式执行（按 Ctrl+C 可随时中止）")
    print("=" * 60)

    try:
        for event in agent.execute(task):
            if event.type == "content":
                print(event.data, end="", flush=True)
            elif event.type == "tool_call_start":
                print(f"\n\n🛠️  调用工具: {event.data['name']}")
                print(f"   参数: {event.data['args'][:100]}...")
            elif event.type == "tool_result":
                result = event.data['result']
                preview = result[:200] if len(result) > 200 else result
                print(f"✅ 工具结果 ({len(result)} 字): {preview}...")
            elif event.type == "done":
                reason = event.data.get('reason') if event.data else 'unknown'
                print(f"\n\n{'='*60}")
                print(f"执行完成，原因: {reason}")
                print(f"{'='*60}")
                break

    except KeyboardInterrupt:
        print("\n\n⚠️  检测到 Ctrl+C，设置取消标志...")
        cancel_event.set()
        # 继续消费剩余事件，让 Agent 优雅退出
        for event in agent.execute(task):
            if event.type == "done":
                print(f"Agent 已停止，原因: {event.data.get('reason')}")
                break
        print("✅ 已取消")

if __name__ == "__main__":
    main()
