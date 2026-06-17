from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sessions import RuntimeContextBuilder, compact_session


log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PreparedAgentRun:
    context_builder: Any
    compaction_result: Any | None = None
    warning: str = ""


@dataclass
class SessionRuntime:
    long_term_memory: Any
    plan_mode_provider: Callable[[], Any] | None = None

    def prepare_agent_run(
        self,
        session: Any,
        agent: Any,
        context_builder: Any,
        *,
        chat_fn: Callable[..., Any] | None = None,
    ) -> PreparedAgentRun:
        try:
            kwargs = {"chat_fn": chat_fn} if chat_fn is not None else {}
            result = compact_session(session, force=False, **kwargs)
        except Exception as exc:
            log.exception("[会话压缩] 自动压缩失败")
            return PreparedAgentRun(
                context_builder=context_builder,
                warning=f"[WARN] 自动压缩失败，继续使用未压缩上下文: {exc}",
            )

        if not result.compacted:
            return PreparedAgentRun(context_builder=context_builder, compaction_result=result)

        reload_agent_conversation(agent, session)
        return PreparedAgentRun(
            context_builder=self.build_context(session),
            compaction_result=result,
        )

    def compact_agent_session(
        self,
        session: Any,
        agent: Any,
        *,
        chat_fn: Callable[..., Any] | None = None,
    ) -> PreparedAgentRun:
        kwargs = {"chat_fn": chat_fn} if chat_fn is not None else {}
        result = compact_session(session, force=True, **kwargs)
        if result.compacted:
            reload_agent_conversation(agent, session)
        return PreparedAgentRun(
            context_builder=self.build_context(session),
            compaction_result=result,
        )

    def build_context(self, session: Any) -> RuntimeContextBuilder:
        return RuntimeContextBuilder(
            session=session,
            long_term=self.long_term_memory,
            plan_mode_provider=self.plan_mode_provider,
        )


def reload_agent_conversation(agent: Any, session: Any) -> None:
    if hasattr(agent, "replace_conversation_messages"):
        agent.replace_conversation_messages(session.messages())
