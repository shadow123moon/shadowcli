from collections.abc import Callable

from llm.client import chat
from llm.types import Message
from tooling import ToolRegistry

from .agent_loop import AgentLoop
from .prompts import filter_tool_definitions_for_model, react_agent_prompt


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

    def events(self, user_input: str, context: str = "", *, cancel=None, journal=None, turn_id: str | None = None):
        # 重置取消标志（每次新请求都要清除）
        if cancel is not None:
            self.reactr.cancel = cancel
        else:
            self.reactr.cancel.clear()
        self.reactr.journal = journal
        self.reactr.turn_id = turn_id

        task = Message(role="user", content=user_input)
        yield from self.reactr.execute(task, context=context, allow_tools=True)

    def run(self, user_input: str, context: str = "", *, cancel=None, journal=None, turn_id: str | None = None) -> str:
        """Run the agent and return final streamed text without rendering UI."""
        content_parts = []
        try:
            for event in self.events(user_input, context=context, cancel=cancel, journal=journal, turn_id=turn_id):
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


def _build_react_system_prompt(tool_registry: ToolRegistry) -> str:
    defs = filter_tool_definitions_for_model(tool_registry.get_all_definitions())
    tools_desc = "\n".join(
        f"- {d['function']['name']}: {d['function']['description']}" for d in defs
    )
    tool_guidance = _build_tool_guidance(tool_registry, defs)
    return react_agent_prompt(tools_desc, tool_guidance=tool_guidance)


def _build_tool_guidance(tool_registry: ToolRegistry, definitions: list[dict]) -> str:
    lines: list[str] = []
    for definition in definitions:
        name = str(definition.get("function", {}).get("name", ""))
        if not name:
            continue
        try:
            tool = tool_registry.get(name)
        except (AttributeError, KeyError):
            continue
        guidance = str(getattr(tool, "guidance", "")).strip()
        if guidance:
            lines.append(f"- {name}: {guidance}")
    return "\n".join(lines)
