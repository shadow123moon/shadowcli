from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
import json
import requests
from abc import ABC, abstractmethod

# ----- 数据结构 -----
@dataclass
class FunctionCall:
    name: str
    arguments: str  # JSON 字符串

@dataclass
class ToolCall:
    id: str
    function: FunctionCall
    type: str = "function"

@dataclass
class Message:
    role: str
    content: Optional[str] = None
    tool_calls: Optional[List[ToolCall]] = None
    tool_call_id: Optional[str] = None

@dataclass
class ChatResponse:
    content: Optional[str] = None
    tool_calls: Optional[List[ToolCall]] = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

# ----- 工具抽象 -----
class Tool(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...
    @property
    @abstractmethod
    def description(self) -> str: ...
    @property
    @abstractmethod
    def parameters(self) -> Dict[str, Any]: ...
    @abstractmethod
    def execute(self, arguments: Dict[str, Any]) -> str: ...

# ----- 工具注册表 -----
class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool):
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        tool = self._tools.get(name)
        if not tool:
            raise ValueError(f"未知工具: {name}")
        return tool

    def get_all_definitions(self) -> List[Dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters
                }
            }
            for tool in self._tools.values()
        ]

# ----- 模拟的聊天函数（实际使用时请替换为真实API调用） -----
def chat(messages: List[Message], tools: Optional[List[Dict]] = None,
         api_key: str = "", api_url: str = "", model: str = "gpt-4") -> ChatResponse:
    """
    模拟聊天，用于测试。它会根据最近一条用户消息的内容返回不同响应。
    实际使用时，请替换为之前实现的真实 HTTP 调用。
    """
    last_msg = messages[-1] if messages else None
    # 如果是规划请求，返回一个静态计划JSON
    if last_msg and last_msg.role == "user":
        if "制定执行计划" in last_msg.content or "请为以下任务" in last_msg.content:
            goal = last_msg.content.split(":\n")[-1] if ":\n" in last_msg.content else last_msg.content
            # 返回一个模拟的规划响应
            plan_json = {
                "summary": f"执行任务: {goal[:30]}",
                "tasks": [
                    {"id": "task_1", "description": "读取文件 /tmp/hello.py", "type": "FILE_READ", "dependencies": []},
                    {"id": "task_2", "description": "分析代码内容", "type": "ANALYSIS", "dependencies": ["task_1"]},
                    {"id": "task_3", "description": "执行编译命令", "type": "COMMAND", "dependencies": ["task_2"]},
                    {"id": "task_4", "description": "验证编译结果", "type": "VERIFICATION", "dependencies": ["task_3"]}
                ]
            }
            return ChatResponse(content=json.dumps(plan_json, ensure_ascii=False))
        # 其他普通聊天可以返回一个模拟回答
        return ChatResponse(content="这是一个模拟响应。")
    return ChatResponse(content="")

# 为了测试方便，提供一个创建空ToolRegistry的辅助函数
def create_registry():
    return ToolRegistry()