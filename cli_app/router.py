from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app_runtime import AppRuntime, RuntimeJournal, TurnBuffer
from memory import MemoryProposal, ProposeMemoryTool
from plan_mode import (
    PlanModeState,
    PlanProposal,
    attach_session_plan_mode,
    enter_plan_mode,
    ensure_plan_mode_state,
    exit_plan_mode,
    format_plan_mode_status,
    persist_plan_mode,
    register_exit_plan_mode_tool,
)
from sessions import NavigationPlan, RuntimeContextBuilder, SessionManager, SessionStore
from sessions.types import DEFAULT_SESSION_TITLE
from skills import (
    SkillContextBuilder,
    SkillSelection,
    SkillSelector,
    skill_reference,
)
from .commands import (
    entry_label,
    entry_preview,
    format_compaction_result,
    format_memory_status,
    format_plugin_list,
    format_skill_list,
    format_token_usage,
    handle_remember,
    parse_compact_command,
    parse_exit_plan_command,
    parse_jump_command,
    parse_new_command,
    parse_plan_command,
    parse_plugin_command,
    parse_plugins_command,
    parse_remember_command,
    parse_resume_command,
    parse_skill_command,
    parse_skills_command,
    parse_tokens_command,
    parse_tree_command,
)
from .constants import HELP, MEMORY_COMMAND
from .terminal_input import SelectOption, select_from_menu
from ui import (
    BranchNavigationChoice,
    Renderer,
    ask_branch_navigation_choice,
    ask_memory_confirmation,
)

if TYPE_CHECKING:
    from agent import ReactAgent

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


class ReplRouter:
    def __init__(
        self,
        *,
        app_runtime: AppRuntime,
        renderer: Renderer,
        skill_selector: SkillSelector | None = None,
        confirm_memory: Callable[[MemoryProposal], bool] = ask_memory_confirmation,
        confirm_plan: Callable[[PlanProposal], bool] | None = None,
        run_interactive_in_worker: bool = False,
    ) -> None:
        self.app_runtime = app_runtime
        self.runtime = app_runtime.tool_runtime
        self.cwd = app_runtime.cwd
        self.session_store = app_runtime.session_store
        self.long_term = app_runtime.long_term_memory
        self.renderer = renderer
        self.skill_selector = skill_selector
        self.confirm_memory = confirm_memory
        self.confirm_plan = confirm_plan or self._default_confirm_plan
        self.run_interactive_in_worker = run_interactive_in_worker
        _register_propose_memory_tool(self.runtime, self.long_term, confirm_memory=self.confirm_memory)
        register_exit_plan_mode_tool(
            self.runtime,
            confirm_plan=self.confirm_plan,
            on_plan_approved=self._on_plan_approved,
        )

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
            self.renderer.message(self.app_runtime.list_tools())
            return True
        if line == "/cancel":
            if self.cancel_current(reason="slash_cancel"):
                self.renderer.cancel_requested()
            else:
                self.renderer.message("当前没有正在运行的任务。")
            return True
        if parse_plugins_command(line):
            self._handle_plugins()
            return True
        plugin_input = parse_plugin_command(line)
        if plugin_input is not None:
            self._handle_plugin(*plugin_input)
            return True
        if parse_skills_command(line):
            self.renderer.message(format_skill_list(self.app_runtime.skill_manager.registry.list()))
            return True
        skill_input = parse_skill_command(line)
        if skill_input is not None:
            self._handle_skill(*skill_input)
            return True
        if line == MEMORY_COMMAND:
            self.renderer.message(format_memory_status(self.long_term))
            return True
        if parse_tokens_command(line):
            if not self.ensure_existing_session() or self.session is None:
                self.renderer.message(_no_active_session_message())
                return True
            self.renderer.message(format_token_usage(self.session))
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

        exit_plan_input = parse_exit_plan_command(line)
        if exit_plan_input is not None:
            self._handle_exit_plan(exit_plan_input)
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
        attach_session_plan_mode(self.app_runtime, next_session)
        self.agent = self.app_runtime.build_agent(
            conversation_messages=self.session.messages(),
            on_message_appended=self.session.append_message,
        )
        self.runtime_context_builder = self.app_runtime.session_runtime.build_context(self.session)

    def ensure_session(self) -> tuple[SessionManager, ReactAgent, RuntimeContextBuilder]:
        if self.session is None:
            self.attach_session(self.session_store.create(self.cwd))
            self.renderer.message(f"已开始新对话: {self.session.meta.session_id}")
        assert self.session is not None
        assert self.agent is not None
        assert self.runtime_context_builder is not None
        return self.session, self.agent, self.runtime_context_builder

    def ensure_worker_session(self) -> tuple[SessionManager, RuntimeContextBuilder]:
        if self.session is None:
            self.session = self.session_store.create(self.cwd)
            self.runtime_context_builder = self.app_runtime.session_runtime.build_context(self.session)
            self.renderer.message(f"已开始新对话: {self.session.meta.session_id}")
        assert self.session is not None
        if self.runtime_context_builder is None:
            self.runtime_context_builder = self.app_runtime.session_runtime.build_context(self.session)
        return self.session, self.runtime_context_builder

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
        self._persist_plan_mode()
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
        prepared = self.app_runtime.session_runtime.compact_agent_session(
            self.session,
            self.agent,
            chat_fn=self.app_runtime.chat,
        )
        self.runtime_context_builder = prepared.context_builder
        if prepared.warning:
            self.renderer.message(prepared.warning)
        if prepared.compaction_result is not None:
            self.renderer.message(format_compaction_result(prepared.compaction_result))

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
            self.renderer.message(format_plan_mode_status(self._plan_mode()))
            return
        active_session, active_agent, context_builder = self.ensure_session()
        enter_plan_mode(self.app_runtime, active_session, plan_input)
        self.runtime_context_builder = self._prepare_agent_run(
            active_session,
            active_agent,
            context_builder,
        )
        self.renderer.message(f"已进入 plan mode: {plan_input}")
        self._run_agent_line(
            "单 Agent 计划执行模式：已进入 plan mode，先探索代码并提出计划，不要修改文件。",
            allow_auto_skill=False,
        )

    def _handle_exit_plan(self, plan_input: str) -> None:
        state = self._plan_mode()
        if not state.active:
            self.renderer.message("当前未处于 plan mode。")
            return
        if not plan_input:
            self.renderer.message("用法: /exit-plan <已批准的计划内容>")
            return
        exit_plan_mode(self.app_runtime, self.session, plan_input)
        self.renderer.message("已退出 plan mode，计划已记录。")

    def _handle_plugins(self) -> None:
        plugins, diagnostics = self.app_runtime.plugin_status()
        self.renderer.message(format_plugin_list(plugins, diagnostics))

    def _handle_plugin(self, action: str, name: str) -> None:
        if action not in {"enable", "disable"} or not name:
            self.renderer.message("用法: /plugin enable|disable <name>")
            return

        if not self.app_runtime.set_plugin_enabled(name, action == "enable"):
            self.renderer.message(f"未找到插件: {name}")
            return

        if action == "enable":
            self.renderer.message(f"已启用插件: {name}")
        else:
            self.renderer.message(f"已禁用插件: {name}")

    def _handle_skill(self, name: str, task: str) -> None:
        if not name:
            self.renderer.message("用法: /skill <name> [任务]")
            return

        if self.run_interactive_in_worker:
            active_session, context_builder = self.ensure_worker_session()
            active_agent = self.agent or _ConversationReloadSink()
        else:
            active_session, active_agent, context_builder = self.ensure_session()
        self.runtime_context_builder = self._prepare_agent_run(
            active_session,
            active_agent,
            context_builder,
        )
        agent_task = task or DEFAULT_SKILL_TASK
        try:
            run_context_builder = self._build_skill_context(name, self.runtime_context_builder, arguments=task)
        except KeyError:
            self.renderer.message(f"未找到 skill: {name}")
            return
        self.renderer.message(f"✓ 加载 skill: {name}")
        if self.run_interactive_in_worker:
            buffer = TurnBuffer()
            worker_agent = self.app_runtime.build_agent(
                conversation_messages=active_session.messages(),
                on_message_appended=buffer.append,
            )
            self._start_worker_turn(active_session, agent_task, run_context_builder, worker_agent, buffer)
        else:
            self.app_runtime.run_agent_once(
                active_agent,
                agent_task,
                runtime_context_builder=run_context_builder,
                renderer=self.renderer,
            )

    def _run_agent_line(
        self,
        line: str,
        *,
        allow_auto_skill: bool = True,
    ) -> None:
        if self._plan_mode().active:
            allow_auto_skill = False
        selection = self._select_auto_skill(line) if allow_auto_skill else None
        if self.run_interactive_in_worker:
            active_session, context_builder = self.ensure_worker_session()
            buffer = TurnBuffer()
            active_agent = self.app_runtime.build_agent(
                conversation_messages=active_session.messages(),
                on_message_appended=buffer.append,
            )
        else:
            active_session, active_agent, context_builder = self.ensure_session()
            buffer = None
        self.runtime_context_builder = self._prepare_agent_run(
            active_session,
            active_agent,
            context_builder,
        )
        run_context_builder: RuntimeContextBuilder | SkillContextBuilder = self.runtime_context_builder
        if selection is not None and selection.skill is not None:
            self.renderer.message(_format_auto_skill_selection(selection))
            run_context_builder = self._build_skill_context_for_definition(
                selection.skill,
                self.runtime_context_builder,
                arguments=line,
            )
        if self.run_interactive_in_worker:
            assert buffer is not None
            self._start_worker_turn(active_session, line, run_context_builder, active_agent, buffer)
        else:
            self.app_runtime.run_agent_once(
                active_agent,
                line,
                runtime_context_builder=run_context_builder,
                renderer=self.renderer,
            )

    def _plan_mode(self) -> PlanModeState:
        return ensure_plan_mode_state(self.app_runtime)

    def _persist_plan_mode(self) -> None:
        persist_plan_mode(self.session, self._plan_mode())

    def _default_confirm_plan(self, proposal: PlanProposal) -> bool:
        """Default plan confirmation handler."""
        from ui import ask_plan_confirmation
        return ask_plan_confirmation(proposal)

    def _on_plan_approved(self, plan: str) -> None:
        """Callback when plan is approved via exit_plan_mode tool."""
        state = self._plan_mode()
        if not state.active:
            # Already exited or not in plan mode
            return
        exit_plan_mode(self.app_runtime, self.session, plan)

    def cancel_current(self, reason: str = "user_cancelled") -> bool:
        return self.app_runtime.task_runtime.cancel_current(reason=reason)

    def wait_current(self, timeout: float | None = None) -> bool:
        return self.app_runtime.task_runtime.wait_current(timeout=timeout)

    def _start_worker_turn(
        self,
        active_session: SessionManager,
        user_input: str,
        run_context_builder: RuntimeContextBuilder | SkillContextBuilder,
        worker_agent: ReactAgent,
        buffer: TurnBuffer,
    ) -> None:
        journal = _journal_for_session(active_session)
        self.app_runtime.task_runtime.journal = journal
        context_builder = _RuntimeNoticeContextBuilder(run_context_builder, journal)
        task_runtime = self.app_runtime.task_runtime

        def run(task) -> None:
            scoped_renderer = _TaskScopedRenderer(self.renderer, task_runtime, task)
            self.app_runtime.run_agent_once(
                worker_agent,
                user_input,
                runtime_context_builder=context_builder,
                renderer=scoped_renderer,
                cancel=task.cancel,
                journal=journal,
                turn_id=task.id,
            )
            if task.cancel.is_set() or not task_runtime.is_current(task.id):
                task.cancel.set()
                return
            buffer.commit(active_session)
            self.agent = worker_agent
            self.runtime_context_builder = self.app_runtime.session_runtime.build_context(active_session)

        task_runtime.start_interactive(run)

    def _select_auto_skill(self, line: str) -> SkillSelection | None:
        return self.app_runtime.skill_manager.select_auto_skill(
            line,
            selector=self.skill_selector,
            chat_fn=self.app_runtime.chat,
        )

    def _build_skill_context(
        self,
        name: str,
        base: RuntimeContextBuilder,
        *,
        arguments: str,
    ) -> SkillContextBuilder:
        return self.app_runtime.skill_manager.build_context(name, base, arguments=arguments)

    def _build_skill_context_for_definition(
        self,
        skill: Any,
        base: RuntimeContextBuilder,
        *,
        arguments: str,
    ) -> SkillContextBuilder:
        return self.app_runtime.skill_manager.build_context_for_definition(skill, base, arguments=arguments)

    def _prepare_agent_run(
        self,
        session: SessionManager,
        agent: ReactAgent,
        context_builder: RuntimeContextBuilder,
    ) -> RuntimeContextBuilder:
        prepared = self.app_runtime.session_runtime.prepare_agent_run(
            session,
            agent,
            context_builder,
            chat_fn=self.app_runtime.chat,
        )
        if prepared.warning:
            self.renderer.message(prepared.warning)
        if prepared.compaction_result is not None and prepared.compaction_result.compacted:
            self.renderer.message(format_compaction_result(prepared.compaction_result))
        return prepared.context_builder

    def _navigate_to(self, target_id: str) -> None:
        assert self.session is not None
        assert self.agent is not None
        try:
            choice = navigate_session_branch(
                self.session,
                target_id,
                choose_navigation=self.renderer.branch_navigation_choice,
                build_branch_summary=self.app_runtime.build_branch_summary,
            )
        except KeyError:
            self.renderer.message(f"未找到会话节点: {target_id}")
            return

        if choice != BranchNavigationChoice.CANCEL:
            if hasattr(self.agent, "replace_conversation_messages"):
                self.agent.replace_conversation_messages(self.session.messages())
            self.runtime_context_builder = self.app_runtime.session_runtime.build_context(self.session)
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


class _RuntimeNoticeContextBuilder:
    def __init__(self, base, journal: RuntimeJournal | None):
        self.base = base
        self.journal = journal

    def build(self, query: str = "") -> str:
        context = self.base.build(query)
        notice = self.journal.format_last_cancelled_turn_notice() if self.journal is not None else ""
        if not notice:
            return context
        sections = ["## 上一轮中断状态", notice]
        if context:
            sections.extend(["", context])
        return "\n".join(sections).rstrip()


class _TaskScopedRenderer:
    def __init__(self, base: Renderer, task_runtime, task):
        self.base = base
        self.task_runtime = task_runtime
        self.task = task

    def message(self, message: str) -> None:
        if self._active():
            self.base.message(message)

    def agent_event(self, event, *, agent_name: str = "react") -> None:
        if self._active():
            self.base.agent_event(event, agent_name=agent_name)

    def cancel_requested(self) -> None:
        self.base.cancel_requested()

    def branch_navigation_choice(self, plan=None):
        return self.base.branch_navigation_choice(plan)

    def _active(self) -> bool:
        return self.task_runtime.is_current(self.task.id) and not self.task.cancel.is_set()


class _ConversationReloadSink:
    def replace_conversation_messages(self, messages) -> None:
        return None


def _journal_for_session(session: SessionManager) -> RuntimeJournal | None:
    path = Path(getattr(session, "path", ""))
    if path == Path("."):
        return None
    return RuntimeJournal(path / "runtime_journal.jsonl")


def _register_propose_memory_tool(runtime: Any, long_term: Any, *, confirm_memory: Callable[[MemoryProposal], bool]) -> None:
    registry = getattr(runtime, "registry", None)
    register = getattr(registry, "register", None)
    if register is None:
        return
    register(ProposeMemoryTool(long_term, confirm_memory=confirm_memory))

