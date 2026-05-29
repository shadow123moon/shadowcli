from __future__ import annotations

from enum import Enum
from typing import Protocol


class BranchNavigationChoice(str, Enum):
    DIRECT = "direct"
    SUMMARIZE = "summarize"
    CANCEL = "cancel"


class Renderer(Protocol):
    def message(self, message: str) -> None:
        ...

    def agent_event(self, event, *, agent_name: str = "react") -> None:
        ...

    def cancel_requested(self) -> None:
        ...

    def branch_navigation_choice(self, plan=None) -> BranchNavigationChoice:
        ...
