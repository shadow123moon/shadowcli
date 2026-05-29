from collections.abc import Callable

from llm.client import chat
from llm.types import Message
from tooling import ToolRegistry

from .agent_loop import AgentLoop
from .prompts import react_agent_prompt

TOOL_INTENT_KEYWORDS = (
    "读取", "读", "查看文件", "打开文件", "写入", "创建", "新建", "修改", "编辑",
    "删除", "执行", "运行", "命令", "终端", "shell", "bash", "powershell",
    "列出", "目录", "文件", "代码", "项目", "仓库", "路径", "搜索", "查找",
    "grep", "find", "ls", "测试", "报错", "错误", "日志",
)


class ReactAgent:
    def __init__(
        self,
        tool_registry: ToolRegistry,
        chat=chat,
        conversation_messages: list[Message] | None = None,
        on_message_appended: Callable[[Message], None] | None = None,
    ):
        self.conversation_messages = conversation_messages if conversation_messages is not None else []
        self.reactr = AgentLoop(
            name="react",
            system_prompt=_build_react_system_prompt(tool_registry),
            chat=chat,
            tool_registry=tool_registry,
            conversation_history=self.conversation_messages,
            on_message_appended=on_message_appended,
        )

    def events(self, user_input: str, context: str = ""):
        allow_tools = _should_enable_tools(user_input)

        # 重置取消标志（每次新请求都要清除）
        self.reactr.cancel.clear()

        task = Message(role="user", content=user_input)
        yield from self.reactr.execute(task, context=context, allow_tools=allow_tools)

    def run(self, user_input: str, context: str = "") -> str:
        """Run the agent and return final streamed text without rendering UI."""
        content_parts = []
        try:
            for event in self.events(user_input, context=context):
                if event.type == "content":
                    content_parts.append(event.data)
                elif event.type == "done":
                    break
        except KeyboardInterrupt:
            self.reactr.cancel.set()
            content_parts.append("\n[已中止]")

        result = "".join(content_parts)
        return result

    def cancel(self) -> None:
        self.reactr.cancel.set()

    def replace_conversation_messages(self, messages: list[Message]) -> None:
        self.conversation_messages.clear()
        self.conversation_messages.extend(messages)
        self.reactr._reset_system_prompt()


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
