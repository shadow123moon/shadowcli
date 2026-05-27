import logging

from llm.client import chat
from multi_agent import AgentRole, SubAgent
from multi_agent.sub_agent import _emit_command_result
from tooling import ToolRegistry

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
    def __init__(self, tool_registry: ToolRegistry, chat=chat, memory_manager=None):
        self.memory_manager = memory_manager
        self.reactr = SubAgent(
            name="react",
            role=AgentRole.REACT,
            chat=chat,
            tool_registry=tool_registry,
        )

    def run(self, user_input: str) -> str:
        log.info(
            "[React] 开始处理普通输入，输入 %d 字，记忆模块%s",
            len(user_input or ""),
            "已开启" if self.memory_manager else "未开启",
        )
        memory_context = ""
        if self.memory_manager is not None:
            memory_context = self.memory_manager.context_for(user_input)
            log.info(
                "[React] 直接记忆上下文%s，长度 %d 字",
                "可用" if memory_context else "为空",
                len(memory_context),
            )
            if memory_context:
                log.debug("[React] 记忆上下文预览：%s", _preview(memory_context))
            self.memory_manager.add_user(user_input)

        allow_tools = _should_enable_tools(user_input)
        log.info("[React] 本轮工具%s", "已启用" if allow_tools else "已禁用")

        # 重置取消标志（每次新请求都要清除）
        self.reactr.cancel.clear()

        # 消费流式事件，收集最终结果
        from llm.types import Message
        task = Message(role="user", content=user_input)
        content_parts = []
        try:
            for event in self.reactr.execute(task, context=memory_context, allow_tools=allow_tools):
                if event.type == "content":
                    content_parts.append(event.data)
                    print(event.data, end="", flush=True)  # 实时输出
                elif event.type == "tool_call_start":
                    print(f"\n🛠️ {event.data['name']}", flush=True)
                elif event.type == "tool_result":
                    _emit_command_result(None, "react", event.data["name"], event.data["result"])
                elif event.type == "done":
                    reason = event.data.get("reason") if event.data else None
                    if reason == "cancelled":
                        print("\n\n⚠️ 已取消", flush=True)
                    break
            result = "".join(content_parts)
        except KeyboardInterrupt:
            # 用户按 Ctrl+C，设置取消标志
            print("\n\n⚠️ 检测到 Ctrl+C，正在停止...", flush=True)
            self.reactr.cancel.set()
            result = "".join(content_parts) + "\n[已中止]"
        finally:
            self.reactr.clear_history()
            log.debug("[React] 已清理本轮临时 history")
        if self.memory_manager is not None:
            self.memory_manager.add_assistant(result)

        log.info("[React] 处理完成，回复 %d 字", len(result or ""))
        return result


def _should_enable_tools(user_input: str) -> bool:
    text = (user_input or "").strip().lower()
    if not text:
        return False
    if any(marker in text for marker in ("/", "\\", ".py", ".md", ".txt", ".json", ".yaml", ".yml")):
        return True
    return any(keyword in text for keyword in TOOL_INTENT_KEYWORDS)
