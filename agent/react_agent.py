import logging

from ui import (
    print_cancel_requested,
    print_cancelled,
    print_command_result,
    print_content_delta,
    print_tool_start,
)
from llm.client import chat
from llm.types import Message
from tooling import ToolRegistry

from .agent_loop import AgentLoop
from .prompts import react_agent_prompt

log = logging.getLogger(__name__)

TOOL_INTENT_KEYWORDS = (
    "读取", "读", "查看文件", "打开文件", "写入", "创建", "新建", "修改", "编辑",
    "删除", "执行", "运行", "命令", "终端", "shell", "bash", "powershell",
    "列出", "目录", "文件", "代码", "项目", "仓库", "路径", "搜索", "查找",
    "grep", "find", "ls", "测试", "报错", "错误", "日志",
)


def _preview(text: str, limit: int = 160) -> str:
    compact = " ".join((text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[:limit] + "..."


class ReactAgent:
    def __init__(
        self,
        tool_registry: ToolRegistry,
        chat=chat,
        memory_manager=None,
        session_messages: list[Message] | None = None,
    ):
        _ = memory_manager
        self.session_messages = session_messages if session_messages is not None else []
        self.reactr = AgentLoop(
            name="react",
            system_prompt=_build_react_system_prompt(tool_registry),
            chat=chat,
            tool_registry=tool_registry,
            conversation_history=self.session_messages,
        )

    def run(self, user_input: str, context: str = "") -> str:
        log.info(
            "[React] 开始处理普通输入，输入 %d 字，上下文%s",
            len(user_input or ""),
            "已提供" if context else "为空",
        )
        if context:
            log.debug("[React] 外部上下文预览：%s", _preview(context))

        allow_tools = _should_enable_tools(user_input)
        log.info("[React] 本轮工具%s", "已启用" if allow_tools else "已禁用")

        # 重置取消标志（每次新请求都要清除）
        self.reactr.cancel.clear()

        # 消费流式事件，收集最终结果
        task = Message(role="user", content=user_input)
        content_parts = []
        try:
            for event in self.reactr.execute(task, context=context, allow_tools=allow_tools):
                if event.type == "content":
                    content_parts.append(event.data)
                    print_content_delta(event.data)  # 实时输出
                elif event.type == "tool_call_start":
                    print_tool_start(event.data["name"])
                elif event.type == "tool_result":
                    print_command_result("react", event.data["name"], event.data["result"])
                elif event.type == "done":
                    reason = event.data.get("reason") if event.data else None
                    if reason == "cancelled":
                        print_cancelled()
                    break
            result = "".join(content_parts)
        except KeyboardInterrupt:
            # 用户按 Ctrl+C，设置取消标志
            print_cancel_requested()
            self.reactr.cancel.set()
            result = "".join(content_parts) + "\n[已中止]"
        finally:
            log.debug("[React] 本轮结束，保留 session messages %d 条", len(self.session_messages))

        log.info("[React] 处理完成，回复 %d 字", len(result or ""))
        return result


def _should_enable_tools(user_input: str) -> bool:
    text = (user_input or "").strip().lower()
    if not text:
        return False
    if any(marker in text for marker in ("/", "\\", ".py", ".md", ".txt", ".json", ".yaml", ".yml")):
        return True
    return any(keyword in text for keyword in TOOL_INTENT_KEYWORDS)


def _build_react_system_prompt(tool_registry: ToolRegistry) -> str:
    defs = tool_registry.get_all_definitions()
    tools_desc = "\n".join(
        f"- {d['function']['name']}: {d['function']['description']}" for d in defs
    )
    return react_agent_prompt(tools_desc)
