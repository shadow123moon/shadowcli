from __future__ import annotations

from typing import Any

from .state import PlanModeState


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
    state.enter(task)
    persist_plan_mode(session, state)
    return state


def exit_plan_mode(runtime: Any, session: Any | None, plan: str) -> PlanModeState:
    state = ensure_plan_mode_state(runtime)
    state.exit(plan)
    persist_plan_mode(session, state)
    return state
