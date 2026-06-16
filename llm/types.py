from dataclasses import dataclass
from typing import List, Optional


@dataclass
class FunctionCall:
    name: str
    arguments: str


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
    metadata: Optional[dict] = None


@dataclass
class ChatResponse:
    content: Optional[str] = None
    tool_calls: Optional[List[ToolCall]] = None
    prompt_tokens: int = 0
    cached_prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
