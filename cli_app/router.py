from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from agent import ReactAgent
from llm import chat as default_chat
from sessions import NavigationPlan, RuntimeContextBuilder, SessionManager, SessionStore, compact_session
from sessions.types import DEFAULT_SESSION_TITLE
from plugin_runtime import PluginManager, PluginStateStore
from skills import (
    SkillContextBuilder,
    SkillRegistry,
    SkillSelection,
    SkillSelector,
    auto_skills_enabled,
    skill_reference,
)
from .commands import (
    entry_label,
    entry_preview,
    format_compaction_result,
    format_memory_status,
    format_plugin_list,
    format_skill_list,
    handle_remember,
    parse_compact_command,
    parse_jump_command,
    parse_new_command,
    parse_plan_command,
    parse_plugin_command,
    parse_plugins_command,
    parse_remember_command,
    parse_resume_command,
    parse_skill_command,
    parse_skills_command,
    parse_tree_command,
)
from .constants import HELP, MEMORY_COMMAND
from .factories import list_tools as default_list_tools
from .terminal_input import SelectOption, select_from_menu
from ui import (
    BranchNavigationChoice,
    Renderer,
    ask_branch_navigation_choice,
)

log = logging.getLogger("cli_app.runner")
DEFAULT_SKILL_TASK = "按 skill 指令执行"


def navigate_session_branch(
    session: SessionManager,
    target_id: str | None,
    *,
    choose_navigation: Callable[[NavigationPlan], BranchNavigationChoice | str] = ask_branch_navigation_choice,
    build_branch_summary: Callable[[NavigationPlan], str] | None = None,
) -> BranchNavigationChoice:
    plan = session.plan_navigation(target_id)
    choice = BranchNavigationChoice(choose_navigation(plan))

    if choice == BranchNavigationChoice.CANCEL:
        return choice
    if choice == BranchNavigationChoice.DIRECT:
        session.branch_to(target_id)
        return choice

    if build_branch_summary is None:
        raise ValueError("build_branch_summary is required when branch navigation chooses summary")
    summary = build_branch_summary(plan)
    session.branch_to_with_summary(target_id, summary=summary)
    return choice


def reload_agent_conversation(agent: ReactAgent, session: SessionManager) -> None:
    if hasattr(agent, "replace_conversation_messages"):
        agent.replace_conversation_messages(session.messages())


def maybe_compact_before_run(
    session: SessionManager,
    agent: ReactAgent,
    long_term: Any,
    runtime_context_builder: RuntimeContextBuilder,
    renderer: Renderer,
    *,
    chat_fn: Callable[..., Any] = default_chat,
) -> RuntimeContextBuilder:
    try:
        result = compact_session(session, force=False, chat_fn=chat_fn)
    except Exception as e:
        log.exception("[会话压缩] 自动压缩失败")
        renderer.message(f"[WARN] 自动压缩失败，继续使用未压缩上下文: {e}")
        return runtime_context_builder

    if not result.compacted:
        return runtime_context_builder

    reload_agent_conversation(agent, session)
    renderer.message(format_compaction_result(result))
    return RuntimeContextBuilder(session=session, long_term=long_term)


class ReplRouter:
    def __init__(
        self,
        *,
        runtime: Any,
        cwd: Path,
        session_store: SessionStore,
        long_term: Any,
        renderer: Renderer,
        build_agent: Callable[..., ReactAgent],
        run_agent_once: Callable[..., None],
        list_tools: Callable[[Any], str] = default_list_tools,
        skill_registry: SkillRegistry | None = None,
        skill_registry_builder: Callable[[Path], SkillRegistry] | None = None,
        skill_selector: SkillSelector | None = None,
        chat_fn: Callable[..., Any] = default_chat,
        build_branch_summary: Callable[[NavigationPlan], str] | None = None,
    ) -> None:
        self.runtime = runtime
        self.cwd = cwd
        self.session_store = session_store
        self.long_term = long_term
        self.renderer = renderer
        self.build_agent = build_agent
        self.run_agent_once = run_agent_once
        self.list_tools = list_tools
        self.skill_registry_builder = skill_registry_builder or (lambda path: SkillRegistry(path))
        self.skill_registry = skill_registry or self.skill_registry_builder(cwd)
        self.skill_selector = skill_selector
        self.chat_fn = chat_fn
        self.build_branch_summary = build_branch_summary

        self.session: SessionManager | None = None
        self.agent: ReactAgent | None = None
        self.runtime_context_builder: RuntimeContextBuilder | None = None

    def route(self, line: str) -> bool:
        if not line:
            return True
        if line in ("/quit", "/exit", "/q"):
            self.renderer.message("再见。")
            return False
        if line == "/help":
            self.renderer.message(HELP)
            return True
        if line == "/tools":
            self.renderer.message(self.list_tools(self.runtime))
            return True
        if parse_plugins_command(line):
            self._handle_plugins()
            return True
        plugin_input = parse_plugin_command(line)
        if plugin_input is not None:
            self._handle_plugin(*plugin_input)
            return True
        if parse_skills_command(line):
            self.renderer.message(format_skill_list(self.skill_registry.list()))
            return True
        skill_input = parse_skill_command(line)
        if skill_input is not None:
            self._handle_skill(*skill_input)
            return True
        if line == MEMORY_COMMAND:
            self.renderer.message(format_memory_status(self.long_term))
            return True
        if parse_new_command(line):
            self.start_new_session()
            return True

        resume_target = parse_resume_command(line)
        if resume_target is not None:
            self._handle_resume(resume_target)
            return True
        if parse_tree_command(line):
            self._handle_tree()
            return True
        if parse_compact_command(line) is not None:
            self._handle_compact()
            return True

        jump_target = parse_jump_command(line)
        if jump_target is not None:
            self._handle_jump(jump_target)
            return True
        if parse_remember_command(line) is not None:
            self.renderer.message(handle_remember(self.long_term, line))
            return True

        plan_input = parse_plan_command(line)
        if plan_input is not None:
            self._handle_plan(line, plan_input)
            return True
        if line.startswith("/"):
            self.renderer.message(f"未知命令: {line}  (输入 /help 查看)")
            return True

        self._run_agent_line(line)
        return True

    def attach_session(self, next_session: SessionManager) -> None:
        self.session = next_session
        self.agent = self.build_agent(
            self.runtime,
            conversation_messages=self.session.messages(),
            on_message_appended=self.session.append_message,
        )
        self.runtime_context_builder = RuntimeContextBuilder(session=self.session, long_term=self.long_term)

    def ensure_session(self) -> tuple[SessionManager, ReactAgent, RuntimeContextBuilder]:
        if self.session is None:
            self.attach_session(self.session_store.create(self.cwd))
            self.renderer.message(f"已开始新对话: {self.session.meta.session_id}")
        assert self.session is not None
        assert self.agent is not None
        assert self.runtime_context_builder is not None
        return self.session, self.agent, self.runtime_context_builder

    def ensure_existing_session(self) -> bool:
        if self.session is not None:
            return True
        recent = self.session_store.open_recent(self.cwd)
        if recent is None:
            return False
        self.attach_session(recent)
        return True

    def start_new_session(self) -> None:
        self.attach_session(self.session_store.create(self.cwd))
        assert self.session is not None
        self.renderer.message(f"已开启新对话: {self.session.meta.session_id}")

    def _handle_resume(self, resume_target: str) -> None:
        resumed = _choose_resume_session(self.session_store, self.cwd, self.renderer, resume_target)
        if resumed is not None:
            self.attach_session(resumed)
            self.renderer.message(_format_loaded_session_summary(resumed))

    def _handle_tree(self) -> None:
        if not self.ensure_existing_session() or self.session is None or self.agent is None:
            self.renderer.message(_no_active_session_message())
            return
        tree_target = _choose_tree_entry(self.session, self.renderer)
        if tree_target is None:
            self.renderer.message("已取消。")
            return
        if tree_target == self.session.get_leaf_id():
            self.renderer.message(f"已在当前节点: {tree_target}")
            return
        self._navigate_to(tree_target)

    def _handle_compact(self) -> None:
        if (
            not self.ensure_existing_session()
            or self.session is None
            or self.agent is None
            or self.runtime_context_builder is None
        ):
            self.renderer.message(_no_active_session_message())
            return
        result = compact_session(self.session, force=True, chat_fn=self.chat_fn)
        if result.compacted:
            reload_agent_conversation(self.agent, self.session)
            self.runtime_context_builder = RuntimeContextBuilder(session=self.session, long_term=self.long_term)
        self.renderer.message(format_compaction_result(result))

    def _handle_jump(self, jump_target: str) -> None:
        if not self.ensure_existing_session() or self.session is None or self.agent is None:
            self.renderer.message(_no_active_session_message())
            return
        if not jump_target:
            self.renderer.message("用法: /jump <entry_id>")
            return
        self._navigate_to(jump_target)

    def _handle_plan(self, line: str, plan_input: str) -> None:
        if not plan_input:
            self.renderer.message("用法: /plan <任务>")
            return
        self._run_agent_line(line)

    def _handle_plugins(self) -> None:
        manager = PluginManager(self.cwd)
        self.renderer.message(format_plugin_list(manager.list_plugins(), manager.diagnostics()))

    def _handle_plugin(self, action: str, name: str) -> None:
        if action not in {"enable", "disable"} or not name:
            self.renderer.message("用法: /plugin enable|disable <name>")
            return

        manager = PluginManager(self.cwd)
        known = {plugin.manifest.id for plugin in manager.list_plugins()}
        if name not in known:
            self.renderer.message(f"未找到插件: {name}")
            return

        state = PluginStateStore(self.cwd)
        if action == "enable":
            state.enable(name)
            self.renderer.message(f"已启用插件: {name}")
        else:
            state.disable(name)
            self.renderer.message(f"已禁用插件: {name}")
        self.skill_registry = self.skill_registry_builder(self.cwd)

    def _handle_skill(self, name: str, task: str) -> None:
        if not name:
            self.renderer.message("用法: /skill <name> [任务]")
            return
        try:
            loaded_skill = self.skill_registry.load(name)
        except KeyError:
            self.renderer.message(f"未找到 skill: {name}")
            return

        active_session, active_agent, context_builder = self.ensure_session()
        self.runtime_context_builder = maybe_compact_before_run(
            active_session,
            active_agent,
            self.long_term,
            context_builder,
            self.renderer,
            chat_fn=self.chat_fn,
        )
        agent_task = task or DEFAULT_SKILL_TASK
        self.run_agent_once(
            active_agent,
            agent_task,
            runtime_context_builder=SkillContextBuilder(
                base=self.runtime_context_builder,
                skill=loaded_skill,
                arguments=task,
            ),
            renderer=self.renderer,
        )

    def _run_agent_line(self, line: str) -> None:
        selection = self._select_auto_skill(line)
        active_session, active_agent, context_builder = self.ensure_session()
        self.runtime_context_builder = maybe_compact_before_run(
            active_session,
            active_agent,
            self.long_term,
            context_builder,
            self.renderer,
            chat_fn=self.chat_fn,
        )
        run_context_builder: RuntimeContextBuilder | SkillContextBuilder = self.runtime_context_builder
        if selection is not None and selection.skill is not None:
            loaded_skill = self.skill_registry.load_definition(selection.skill)
            self.renderer.message(_format_auto_skill_selection(selection))
            run_context_builder = SkillContextBuilder(
                base=self.runtime_context_builder,
                skill=loaded_skill,
                arguments=line,
            )
        self.run_agent_once(
            active_agent,
            line,
            runtime_context_builder=run_context_builder,
            renderer=self.renderer,
        )

    def _select_auto_skill(self, line: str) -> SkillSelection | None:
        if not auto_skills_enabled():
            return None

        selector = self.skill_selector or SkillSelector(self.skill_registry, chat_fn=self.chat_fn)
        selection = selector.select(line)
        if selection is None or selection.skill is None:
            return None
        return selection

    def _navigate_to(self, target_id: str) -> None:
        assert self.session is not None
        assert self.agent is not None
        try:
            choice = navigate_session_branch(
                self.session,
                target_id,
                choose_navigation=self.renderer.branch_navigation_choice,
                build_branch_summary=self.build_branch_summary,
            )
        except KeyError:
            self.renderer.message(f"未找到会话节点: {target_id}")
            return

        if choice != BranchNavigationChoice.CANCEL:
            reload_agent_conversation(self.agent, self.session)
            self.runtime_context_builder = RuntimeContextBuilder(session=self.session, long_term=self.long_term)
            self.renderer.message(f"已跳转到: {self.session.get_leaf_id()}")
        else:
            self.renderer.message("已取消跳转。")


def _format_session_resume_list(sessions, *, limit: int = 20) -> str:
    if not sessions:
        return "没有可恢复的历史对话。"

    shown = sessions[:limit]
    lines = [f"历史对话（最近 {len(shown)} / {len(sessions)} 个）:"]
    for index, meta in enumerate(shown, start=1):
        title = _session_title(meta)
        updated = meta.updated_at.replace("T", " ")[:19]
        lines.append(
            f"  {index:>2}. {title}  {meta.message_count} 条  {updated}"
        )
    lines.append("输入编号或 session_id，回车取消。")
    return "\n".join(lines)


def _resolve_resume_selection(sessions, selection: str):
    selection = selection.strip()
    if not selection:
        return None

    if selection.isdigit():
        index = int(selection)
        if 1 <= index <= len(sessions):
            return sessions[index - 1]

    exact = [meta for meta in sessions if meta.session_id == selection]
    if exact:
        return exact[0]

    prefix = [meta for meta in sessions if meta.session_id.startswith(selection)]
    if len(prefix) == 1:
        return prefix[0]
    return None


def _choose_resume_session(session_store: SessionStore, cwd: Path, renderer: Renderer, selection: str = ""):
    sessions = session_store.list(cwd)
    if not sessions:
        renderer.message("没有可恢复的历史对话。")
        return None

    if selection:
        meta = _resolve_resume_selection(sessions, selection)
        if meta is None:
            renderer.message(f"未找到历史对话: {selection}")
            return None
        return session_store.open(cwd, meta.session_id)

    meta = select_from_menu(
        "历史对话",
        _resume_select_options(sessions),
        prompt="resume",
        output=renderer.message,
    )
    if meta is None:
        renderer.message("已取消恢复。")
        return None

    return session_store.open(cwd, meta.session_id)


def _resume_select_options(sessions) -> list[SelectOption]:
    options = []
    for meta in sessions:
        title = _session_title(meta)
        updated = meta.updated_at.replace("T", " ")[:19]
        description = f"{meta.message_count} 条  {updated}"
        options.append(SelectOption(value=meta, label=title, description=description))
    return options


def _session_title(meta) -> str:
    title = (meta.title or "").strip()
    if not title or title == meta.session_id or title.isdigit():
        return DEFAULT_SESSION_TITLE
    return title


def _tree_select_options(session: SessionManager, *, limit: int = 80) -> list[SelectOption[str]]:
    entries = session.all_entries()
    if not entries:
        return []

    branch_ids = {entry.id for entry in session.get_branch()}
    leaf_id = session.get_leaf_id()
    shown = entries[-limit:]
    options = []
    for entry in shown:
        branch_marker = "*" if entry.id in branch_ids else " "
        current_marker = " current" if entry.id == leaf_id else ""
        label = f"{branch_marker} {entry.id} {entry_label(entry)}{current_marker}"
        description = entry_preview(entry)
        options.append(SelectOption(value=entry.id, label=label, description=description))
    return options


def _choose_tree_entry(session: SessionManager, renderer: Renderer) -> str | None:
    options = _tree_select_options(session)
    if not options:
        renderer.message("会话树为空。")
        return None
    return select_from_menu(
        "会话树",
        options,
        prompt="tree",
        output=renderer.message,
    )


def _format_loaded_session_summary(session: SessionManager) -> str:
    messages = session.messages()
    lines = [
        f"已恢复对话: {_session_title(session.meta)}",
        f"共 {len(messages)} 条消息，最后更新: {session.meta.updated_at[:19]}",
    ]
    if messages:
        lines.append("最近对话:")
        recent = messages[-3:] if len(messages) > 3 else messages
        for msg in recent:
            role_label = {"user": "你", "assistant": "助手", "tool": "工具"}.get(msg.role, msg.role)
            content_preview = (msg.content or "")[:80].replace("\n", " ")
            if len(msg.content or "") > 80:
                content_preview += "..."
            lines.append(f"  {role_label}: {content_preview}")
    return "\n".join(lines)


def _no_active_session_message() -> str:
    return "当前还没有对话。输入第一句话开始新对话，或输入 /resume 恢复历史对话。"


def _format_auto_skill_selection(selection: SkillSelection) -> str:
    assert selection.skill is not None
    reason = selection.reason.strip() or "selector matched the user input"
    return "\n".join([
        f"自动加载 skill: {skill_reference(selection.skill)}",
        f"原因: {reason}",
    ])
