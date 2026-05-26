# extensions/reviewer.py
import json
import re
import logging

from extensions import approval_policy as policy
from llm import Message
from llm.client import chat
logger = logging.getLogger(__name__)

SYSTEM_PROMPT = '''你是工具调用审查专家。判断这个工具调用是否安全合理。
只回复 JSON，格式：{"approved": true/false, "reason": "理由"}'''


def register(runtime):
    """注册 AI Reviewer 扩展。"""
    runtime.on_before_execute(reviewer_handler)


def reviewer_handler(tool_name, arguments, tool):
    # 只审查危险工具
    if not policy.requires_approval_for_tool(tool, arguments):
        return None

    try:
        data = _ask_llm(tool_name, arguments)
    except Exception as e:
        logger.warning("AI 审查失败，安全起见拦截：%s", e)
        return {"block": True, "reason": f"审查服务异常：{e}"}

    if not data.get("approved", False):
        reason = data.get("reason", "AI 审查未通过")
        logger.warning("拒绝调用 %s：%s", tool_name, reason)
        return {"block": True, "reason": reason}

    return None


def _ask_llm(tool_name, arguments) -> dict:
    messages = [
        Message(role="system", content=SYSTEM_PROMPT),
        Message(role="user", content=(
            f"工具: {tool_name}\n"
            f"参数: {json.dumps(arguments, ensure_ascii=False, indent=2)}"
        )),
    ]
    response = chat(messages)
    content = response.content or ""

    match = re.search(r"\{.*\}", content, re.DOTALL)
    if not match:
        raise ValueError(f"LLM 未返回 JSON: {content!r}")
    return json.loads(match.group(0))
