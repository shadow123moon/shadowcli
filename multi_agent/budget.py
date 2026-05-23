"""AgentBudget - Agent 循环的退出预算（防死循环 + token 控制）。

三道保险阀（任一命中即结束循环）：
1. token 预算超限    —— 累计 input + output token 超阈值（默认 sys.maxsize，实质不限）
2. 停滞检测          —— 连续 N 轮工具签名完全相同，判定为死循环
3. 硬轮数兜底         —— 累计迭代轮数超过 hard_max_iterations

设计取舍：默认 token 预算无限，让 LLM 自然停在它该停的地方。需要严格成本
控制的场景通过 PAICLI_REACT_TOKEN_BUDGET 环境变量启用。死循环防护由停滞
检测和硬轮数兜底两道。

Pythonic 要点：
- @dataclass + __post_init__ 做参数校验
- collections.deque(maxlen=N) 替代手写循环队列
- @classmethod from_env 替代 Java 静态工厂
- describe_exit 用字典查表，替代 switch
"""
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
    """Agent 循环退出预算管理。"""

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
        # field(default_factory=deque) 不接受 maxlen，需要 __post_init__ 里重建
        self._recent_signatures = deque(maxlen=self.stagnation_window)

    @classmethod
    def from_env(cls) -> AgentBudget:
        """从环境变量读取配置。

        变量：
        - PAICLI_REACT_TOKEN_BUDGET
        - PAICLI_REACT_STAGNATION_WINDOW
        - PAICLI_REACT_HARD_MAX_ITERATIONS
        """
        return cls(
            token_budget=_read_int_env("PAICLI_REACT_TOKEN_BUDGET", sys.maxsize),
            stagnation_window=_read_int_env("PAICLI_REACT_STAGNATION_WINDOW", DEFAULT_STAGNATION_WINDOW),
            hard_max_iterations=_read_int_env("PAICLI_REACT_HARD_MAX_ITERATIONS", DEFAULT_HARD_MAX_ITERATIONS),
        )

    def begin_iteration(self) -> int:
        """进入新一轮，返回当前轮次（从 1 开始）。"""
        self.iteration += 1
        return self.iteration

    def record_tokens(self, input_tokens: int, output_tokens: int, *, cached: int = 0) -> None:
        self.total_input_tokens += max(0, input_tokens)
        self.total_output_tokens += max(0, output_tokens)
        self.total_cached_input_tokens += max(0, cached)

    def record_tool_calls(self, tool_calls: Iterable | None) -> None:
        """记录本轮工具调用签名，判断是否停滞。

        停滞条件：连续 stagnation_window 轮的工具签名完全相同。
        一旦判定停滞，状态会保持，后续 check() 持续返回 STAGNATION_DETECTED。
        """
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
        if self.total_input_tokens + self.total_output_tokens >= self.token_budget:
            return ExitReason.TOKEN_BUDGET_EXCEEDED
        if self.iteration >= self.hard_max_iterations:
            return ExitReason.HARD_ITERATION_LIMIT
        return ExitReason.WITHIN_BUDGET

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
    """把一组 tool_call 的 name + arguments 拼成一个签名串。"""
    parts = []
    for tc in tool_calls:
        parts.append(f"{tc.function.name}|{tc.function.arguments};")
    return "".join(parts)


def _read_int_env(key: str, default: int) -> int:
    raw = os.environ.get(key)
    if not raw or not raw.strip():
        return default
    try:
        v = int(raw.strip())
        return v if v > 0 else default
    except ValueError:
        return default
