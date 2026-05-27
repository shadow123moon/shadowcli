# extensions/reviewer.py
import json
import re
import logging

from extensions import approval_policy as policy
from llm import Message
from llm.client import chat
logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是工具调用安全闸门，只判断工具调用是否存在危险副作用。

你的职责：
- 只拦截明显危险、不可逆或高副作用的操作。
- 例如：删除/覆盖大量文件，清空目录，格式化磁盘，修改系统配置，泄露密钥，安装/卸载软件，下载并执行不可信脚本，启动难以管理的长驻/后台进程，访问高风险外部服务。

不要拦截这些情况：
- 不要因为命令可能失败而拒绝。
- 不要因为命令语法、PowerShell/Bash 风格、跨平台兼容性、效率、是否优雅而拒绝。
- 不要给替代命令建议；执行失败会由 worker 根据工具返回的错误信息自行修正。

只回复 JSON，格式：{"approved": true/false, "reason": "理由"}。"""


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
        logger.info("拒绝调用 %s：%s", tool_name, reason)
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
