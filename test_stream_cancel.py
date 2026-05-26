"""测试 Ctrl+C 中止功能 - 让模型执行一个耗时任务。"""
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

    # 测试任务：让模型写一个很长的文档（会触发多轮对话）
    task = Message(
        role="user",
        content="""请写一份详细的 Python 编程教程，包含以下章节：
1. Python 基础语法（变量、数据类型、运算符）
2. 控制流（if/else、循环）
3. 函数和模块
4. 面向对象编程
5. 异常处理
6. 文件操作
7. 常用标准库
8. 实战项目示例

每个章节都要详细讲解，包含代码示例和练习题。请把内容写入 python_tutorial.md 文件。"""
    )

    print("=" * 60)
    print("开始流式执行（这是一个耗时任务）")
    print("⚠️  请在模型输出过程中按 Ctrl+C 测试中止功能")
    print("=" * 60)
    print()

    try:
        for event in agent.execute(task):
            if event.type == "content":
                print(event.data, end="", flush=True)
            elif event.type == "tool_call_start":
                print(f"\n\n🛠️  调用工具: {event.data['name']}")
                args_preview = event.data['args'][:100]
                print(f"   参数: {args_preview}{'...' if len(event.data['args']) > 100 else ''}")
            elif event.type == "tool_result":
                result = event.data['result']
                preview = result[:200] if len(result) > 200 else result
                print(f"✅ 工具结果 ({len(result)} 字): {preview}{'...' if len(result) > 200 else ''}")
            elif event.type == "done":
                reason = event.data.get('reason') if event.data else 'unknown'
                print(f"\n\n{'='*60}")
                print(f"执行完成，原因: {reason}")
                print(f"{'='*60}")
                break

    except KeyboardInterrupt:
        print("\n\n⚠️  检测到 Ctrl+C，设置取消标志...")
        cancel_event.set()
        print("✅ 已设置取消标志，Agent 会在下一个检查点停止")
        print("   （如果正在等待 LLM 响应，可能需要等待当前请求完成）")

if __name__ == "__main__":
    main()
