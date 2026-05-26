import asyncio
from multi_agent.sub_agent import SubAgent, AgentRole
from llm.types import ChatResponse, FunctionCall, Message, ToolCall
from tooling import ToolRegistry
from llm.client import chat
registry = ToolRegistry()
agent = SubAgent(name="test", role=AgentRole.REACT, chat=chat,tool_registry=registry)

task = Message(role="user", content="读取 README.md 的前 100 字")
for event in agent.execute_stream(task):
    if event.type == "content":
        print(event.data, end="", flush=True)
    elif event.type == "tool_call_start":
        print(f"\n[调用: {event.data['name']}]")
    elif event.type == "tool_result":
        print(f"[结果: {event.data['result'][:50]}...]")
    elif event.type == "done":
        print("\n[完成]")