"""Agent loop exit budget and stagnation protection."""
from __future__ import annotations

import os
import sys
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable


class ExitReason(Enum):
    WITHIN_BUDGET = "WITHIN_BUDGET"
    TOKEN_BUDGET_EXCEEDED = "TOKEN_BUDGET_EXCEEDED"
    STAGNATION_DETECTED = "STAGNATION_DETECTED"
    HARD_ITERATION_LIMIT = "HARD_ITERATION_LIMIT"


DEFAULT_STAGNATION_WINDOW = 3
DEFAULT_HARD_MAX_ITERATIONS = 50


@dataclass
class AgentBudget:
    """Exit budget for one agent loop."""

    token_budget: int = sys.maxsize
    stagnation_window: int = DEFAULT_STAGNATION_WINDOW
    hard_max_iterations: int = DEFAULT_HARD_MAX_ITERATIONS

    iteration: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cached_input_tokens: int = 0
    _recent_signatures: deque[str] = field(default_factory=deque, repr=False)
    _stagnant: bool = field(default=False, repr=False)

    def __post_init__(self) -> None:
        if self.token_budget <= 0:
            raise ValueError("token_budget must be positive")
        if self.stagnation_window < 2:
            raise ValueError("stagnation_window must be >= 2")
        if self.hard_max_iterations <= 0:
            raise ValueError("hard_max_iterations must be positive")
        self._recent_signatures = deque(maxlen=self.stagnation_window)

    @classmethod
    def from_env(cls) -> AgentBudget:
        return cls(
            token_budget=_read_int_env("SHADOWCLI_REACT_TOKEN_BUDGET", sys.maxsize),
            stagnation_window=_read_int_env("SHADOWCLI_REACT_STAGNATION_WINDOW", DEFAULT_STAGNATION_WINDOW),
            hard_max_iterations=_read_int_env("SHADOWCLI_REACT_HARD_MAX_ITERATIONS", DEFAULT_HARD_MAX_ITERATIONS),
        )

    def begin_iteration(self) -> int:
        self.iteration += 1
        return self.iteration

    def record_tokens(self, input_tokens: int, output_tokens: int, *, cached: int = 0) -> None:
        self.total_input_tokens += max(0, input_tokens)
        self.total_output_tokens += max(0, output_tokens)
        self.total_cached_input_tokens += max(0, cached)

    def record_tool_calls(self, tool_calls: Iterable | None) -> None:
        if not tool_calls:
            self._recent_signatures.clear()
            return
        sig = _signature_of(tool_calls)
        self._recent_signatures.append(sig)
        if len(self._recent_signatures) == self.stagnation_window:
            self._stagnant = all(s == sig for s in self._recent_signatures)

    def check(self) -> ExitReason:
        if self._stagnant:
            return ExitReason.STAGNATION_DETECTED
        if self.is_token_budget_exceeded():
            return ExitReason.TOKEN_BUDGET_EXCEEDED
        if self.iteration >= self.hard_max_iterations:
            return ExitReason.HARD_ITERATION_LIMIT
        return ExitReason.WITHIN_BUDGET

    def is_token_budget_exceeded(self) -> bool:
        return self.total_input_tokens + self.total_output_tokens >= self.token_budget

    def describe_exit(self, reason: ExitReason) -> str:
        return {
            ExitReason.WITHIN_BUDGET: "未触发兜底条件",
            ExitReason.TOKEN_BUDGET_EXCEEDED: (
                f"Token 预算已用尽（{self.total_input_tokens + self.total_output_tokens} / "
                f"{self.token_budget}），任务被强制收尾"
            ),
            ExitReason.STAGNATION_DETECTED: (
                f"检测到连续 {self.stagnation_window} 轮重复的工具调用，疑似死循环，已强制收尾"
            ),
            ExitReason.HARD_ITERATION_LIMIT: (
                f"达到硬轮数上限（{self.hard_max_iterations}），已强制收尾"
            ),
        }[reason]


def _signature_of(tool_calls: Iterable) -> str:
    parts = []
    for tc in tool_calls:
        parts.append(f"{tc.function.name}|{tc.function.arguments};")
    return "".join(parts)


def _read_int_env(key: str, default: int) -> int:
    raw = os.environ.get(key)
    if not raw or not raw.strip():
        return default
    try:
        value = int(raw.strip())
        return value if value > 0 else default
    except ValueError:
        return default
