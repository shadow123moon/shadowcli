import os
import threading
from typing import Literal, Any

from openai import OpenAI
from pydantic.dataclasses import dataclass
import requests

from llm.types import ChatResponse, FunctionCall, Message, ToolCall


@dataclass
class StreamEvent:
    """流式事件。

    type 说明：
    - content: 模型输出的文本片段，data 是 str
    - tool_call: 模型请求调用工具（流结束时发出完整的），data 是 dict
    - tool_call_start: Agent 开始执行工具，data 是 {"name": str, "args": str}
    - tool_result: 工具执行完成，data 是 {"name": str, "result": str}
    - done: 本轮结束，data 是 dict | None（可选 reason 字段）
    - error: 错误，data 是 str
    """
    type: Literal["content", "tool_call", "tool_call_start", "tool_result", "done", "error"]
    data: Any

def chat(
        messages: list[Message],
        tools: list[dict] | None = None,
        model: str | None = None,
        api_key: str | None = None,
        api_url: str | None = None,

) -> ChatResponse:
    """Call an OpenAI-compatible chat completion API."""
    api_key = api_key or os.environ.get("OPENAI_API_KEY")
    api_url = api_url or os.environ.get("API_URL")
    model = model or os.environ.get("MODEL")

    if not api_url:
        raise ValueError("API_URL 未配置，请设置环境变量或传入参数")
    if not api_key:
        raise ValueError("OPENAI_API_KEY 未配置，请设置环境变量或传入参数")
    if not model:
        raise ValueError("MODEL 未配置，请设置环境变量或传入参数")

    # 确保 URL 以 /chat/completions 结尾
    if not api_url.endswith("/chat/completions"):
        api_url = api_url.rstrip("/") + "/chat/completions"

    body = {"model": model, "messages": [_message_to_dict(m) for m in messages]}
    if tools:
        body["tools"] = tools
        body["parallel_tool_calls"] = False

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    resp = requests.post(api_url, headers=headers, json=body)
    resp.raise_for_status()
    return _parse_response(resp.json())


def chat_stream(
    messages: list[Message],
    tools: list[dict] | None = None,
    model: str | None = None,
    api_key: str | None = None,
    api_url: str | None = None,
    cancel: threading.Event | None = None,
):
    """纯流式，yield StreamEvent。支持 cancel 实时中断。"""
    api_key = api_key or os.environ.get("OPENAI_API_KEY")
    api_url = api_url or os.environ.get("API_URL")
    model = model or os.environ.get("MODEL")

    if not api_url:
        raise ValueError("API_URL 未配置，请设置环境变量或传入参数")
    if not api_key:
        raise ValueError("OPENAI_API_KEY 未配置，请设置环境变量或传入参数")
    if not model:
        raise ValueError("MODEL 未配置，请设置环境变量或传入参数")

    client = OpenAI(api_key=api_key, base_url=api_url)
    create_kwargs = {
        "model": model,
        "messages": [_message_to_dict(m) for m in messages],
        "tools": tools,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if tools:
        create_kwargs["parallel_tool_calls"] = False

    stream = client.chat.completions.create(**create_kwargs)

    tool_calls_buffer = {}
    usage_data = None
    try:
        for chunk in stream:
            # 检查取消
            if cancel and cancel.is_set():
                yield StreamEvent("content", "\n⏹️ 已取消")
                yield StreamEvent("done", {"reason": "cancelled"})
                return

            if getattr(chunk, "usage", None):
                usage_data = _usage_to_dict(chunk.usage)

            if not chunk.choices:
                continue

            delta = chunk.choices[0].delta

            # content 片段
            if delta.content:
                yield StreamEvent("content", delta.content)

            # tool_calls 片段（累积标准 OpenAI 格式）
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_calls_buffer:
                        tool_calls_buffer[idx] = {
                            "id": tc.id or "",
                            "type": "function",
                            "function": {"name": "", "arguments": ""},
                        }
                    if tc.id:
                        tool_calls_buffer[idx]["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            tool_calls_buffer[idx]["function"]["name"] = tc.function.name
                        if tc.function.arguments:
                            tool_calls_buffer[idx]["function"]["arguments"] += tc.function.arguments

    except KeyboardInterrupt:
        # 用户按 Ctrl+C，设置取消标志并优雅退出
        if cancel:
            cancel.set()
        yield StreamEvent("content", "\n⏹️ 已取消")
        yield StreamEvent("done", {"reason": "cancelled"})
        return

    # 流结束，发出完整的 tool_calls
    if tool_calls_buffer:
        for idx in sorted(tool_calls_buffer.keys()):
            tc = tool_calls_buffer[idx]
            yield StreamEvent("tool_call", {
                "id": tc["id"],
                "type": "function",
                "name": tc["function"]["name"],
                "arguments": tc["function"]["arguments"],
            })

    yield StreamEvent("done", {"usage": usage_data} if usage_data else None)


def _usage_to_dict(usage) -> dict:
    if isinstance(usage, dict):
        return usage
    if hasattr(usage, "model_dump"):
        return usage.model_dump()
    return {
        "prompt_tokens": getattr(usage, "prompt_tokens", 0),
        "completion_tokens": getattr(usage, "completion_tokens", 0),
        "total_tokens": getattr(usage, "total_tokens", 0),
        "prompt_tokens_details": _usage_details_to_dict(
            getattr(usage, "prompt_tokens_details", None)
        ),
    }


def _usage_details_to_dict(details) -> dict:
    if details is None:
        return {}
    if isinstance(details, dict):
        return details
    if hasattr(details, "model_dump"):
        return details.model_dump()
    return {"cached_tokens": getattr(details, "cached_tokens", 0)}

def _message_to_dict(message: Message) -> dict:
    node = {"role": message.role, "content": message.content}
    if message.tool_calls:
        node["tool_calls"] = [
            {
                "id": tc.id,
                "type": tc.type,
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                },
            }
            for tc in message.tool_calls
        ]
    if message.tool_call_id:
        node["tool_call_id"] = message.tool_call_id
    return node


def _parse_response(data: dict) -> ChatResponse:
    choice = data["choices"][0]
    msg = choice.get("message", {})
    usage = data.get("usage", {})

    tool_calls = None
    if msg.get("tool_calls") is not None:
        tool_calls = [
            ToolCall(
                id=tc["id"],
                function=FunctionCall(
                    name=tc["function"]["name"],
                    arguments=tc["function"]["arguments"],
                ),
            )
            for tc in msg["tool_calls"]
        ]

    return ChatResponse(
        content=msg.get("content"),
        tool_calls=tool_calls,
        prompt_tokens=usage.get("prompt_tokens", 0),
        completion_tokens=usage.get("completion_tokens", 0),
        total_tokens=usage.get("total_tokens", 0),
    )
if __name__ == "__main__":
    from llm.types import Message

    for text in chat_stream([Message(role="user", content="讲个笑话")]):
        print(text, end="", flush=True)
