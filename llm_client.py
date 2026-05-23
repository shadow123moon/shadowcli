# llm_client.py
import os
import json
import requests
from model import Message, ChatResponse, ToolCall, FunctionCall

def chat(messages: list[Message], tools: list[dict] = None,
         model: str = None, api_key: str = None, api_url: str = None) -> ChatResponse:
    """
    与 Java 版本等价的 chat 方法，调用 OpenAI 兼容 API
    """
    api_key = api_key or os.environ.get("OPENAI_API_KEY")
    api_url = api_url or os.environ.get("API_URL", "https://api.openai.com/v1/chat/completions")
    model = model or os.environ.get("MODEL", "gpt-4")

    # 构建请求体
    body = {"model": model, "messages": []}
    for m in messages:
        msg_node = {"role": m.role, "content": m.content}
        if m.tool_calls:
            msg_node["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": tc.type,
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments
                    }
                }
                for tc in m.tool_calls
            ]
        if m.tool_call_id:
            msg_node["tool_call_id"] = m.tool_call_id
        body["messages"].append(msg_node)

    if tools:
        body["tools"] = tools

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    resp = requests.post(api_url, headers=headers, json=body)
    resp.raise_for_status()
    data = resp.json()

    choice = data["choices"][0]
    msg = choice.get("message", {})

    tool_calls = None
    if "tool_calls" in msg and msg["tool_calls"] is not None:
        tool_calls = [
            ToolCall(
                id=tc["id"],
                function=FunctionCall(
                    name=tc["function"]["name"],
                    arguments=tc["function"]["arguments"]
                )
            )
            for tc in msg["tool_calls"]
        ]
    usage = data.get("usage", {})
    return ChatResponse(
        content=msg.get("content"),
        tool_calls=tool_calls,
        prompt_tokens=usage.get("prompt_tokens", 0),
        completion_tokens=usage.get("completion_tokens", 0),
        total_tokens=usage.get("total_tokens", 0)
    )