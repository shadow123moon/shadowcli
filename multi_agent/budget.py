"""Compatibility exports for the shared agent loop budget."""
from agent.budget import (
    DEFAULT_HARD_MAX_ITERATIONS,
    DEFAULT_STAGNATION_WINDOW,
    AgentBudget,
    ExitReason,
)

__all__ = [
    "AgentBudget",
    "ExitReason",
    "DEFAULT_STAGNATION_WINDOW",
    "DEFAULT_HARD_MAX_ITERATIONS",
]
