from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .state import PlanModeState
from .tools import ExitPlanModeTool, PlanProposal
from .files import plan_file_path_for_session, write_plan_file


def ensure_plan_mode_state(runtime: Any) -> PlanModeState:
    state = getattr(runtime, "plan_mode_state", None)
    if state is None:
        state = PlanModeState()
        runtime.plan_mode_state = state
    return state


def attach_session_plan_mode(runtime: Any, session: Any) -> PlanModeState:
    state = PlanModeState.from_dict(getattr(session.meta, "plan_mode", None))
    runtime.plan_mode_state = state
    return state


def persist_plan_mode(session: Any | None, state: PlanModeState) -> None:
    if session is None:
        return
    data = state.to_dict()
    update_plan_mode = getattr(session, "update_plan_mode", None)
    if callable(update_plan_mode):
        update_plan_mode(data)
        return
    setattr(session.meta, "plan_mode", data)


def enter_plan_mode(runtime: Any, session: Any | None, task: str) -> PlanModeState:
    state = ensure_plan_mode_state(runtime)
    state.enter(task, plan_file_path=_session_plan_file_path(session))
    persist_plan_mode(session, state)
    return state


def exit_plan_mode(runtime: Any, session: Any | None, plan: str) -> PlanModeState:
    state = ensure_plan_mode_state(runtime)
    plan_file_path = _write_approved_plan(session, plan)
    state.exit(plan, plan_file_path=plan_file_path)
    persist_plan_mode(session, state)
    return state


def register_exit_plan_mode_tool(
    runtime: Any,
    *,
    confirm_plan: Callable[[PlanProposal], bool],
    on_plan_approved: Callable[[str], None],
) -> None:
    registry = getattr(runtime, "registry", None)
    register = getattr(registry, "register", None)
    if register is None:
        return
    register(ExitPlanModeTool(confirm_plan=confirm_plan, on_plan_approved=on_plan_approved))


def _session_plan_file_path(session: Any | None) -> str:
    if session is None:
        return ""
    return str(plan_file_path_for_session(session))


def _write_approved_plan(session: Any | None, plan: str) -> str:
    if session is None:
        return ""
    return str(write_plan_file(session, plan))
