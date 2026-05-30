"""Prompts for the main single-agent path."""
from __future__ import annotations

import os

MCP_INTENT_KEYWORDS = (
    "mcp",
    "devtools",
    "chrome",
    "browser",
    "浏览器",
    "外部工具",
    "外部 server",
    "外部服务器",
)


def react_agent_prompt(tools_desc: str, cwd: str | None = None) -> str:
    cwd = cwd or os.getcwd()
    return f"""你是 PaiCLI 的主助手，负责自然对话，也能在需要时调用工具完成本地项目任务。

原则：
- 如果是简单的问候、自我介绍或常识性问题，直接回答，不要调用工具。
- 如果需要读写文件、执行命令、创建项目等操作，才使用提供的工具。
- 需要工具时先给一句极短说明，然后调用一个最关键的工具；观察结果后再决定下一步，不要一轮里堆多个独立工具调用。
- 优先使用 Pi 风格工具名：read / write / edit / bash / ls / grep / find。
- 当前工作目录（cwd）：{cwd}；用户给出相对路径时都基于该目录解析。
- 当前环境是 Windows；bash 工具实际执行 PowerShell 命令。直接写 PowerShell 命令，不要再嵌套 powershell -Command。
- 普通项目文件任务优先使用本地工具，不要绕到 mcp__filesystem__*。
- 如果用户问项目代码但没给具体文件，可先用 grep / find / ls 定位。
- 如果无法通过工具完成任务（例如查找用户名、偏好设置等），直接告诉用户你无法做到，不要反复尝试工具调用。
- 回答要简洁、友好，避免模板化能力清单。
- 用户问“你是谁/能做什么”时，用一两句话自然回答；不要输出“文件操作/执行命令/搜索代码/解答问题”这类固定功能列表。
- 除非列表明显更清楚，否则不要用大段 Markdown 项目符号包装普通回答。

可用工具：
{tools_desc}
    """


def filter_tool_definitions_for_model(definitions: list[dict], user_input: str | None = None) -> list[dict]:
    """Hide duplicate MCP tools unless the user explicitly asks for MCP-style tools."""
    if _should_expose_mcp_tools(user_input or ""):
        return definitions
    return [definition for definition in definitions if not _tool_name(definition).startswith("mcp__")]


def _should_expose_mcp_tools(user_input: str) -> bool:
    text = (user_input or "").lower()
    return any(keyword in text for keyword in MCP_INTENT_KEYWORDS)


def _tool_name(definition: dict) -> str:
    return str(definition.get("function", {}).get("name", ""))
