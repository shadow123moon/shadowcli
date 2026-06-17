from abc import ABC, abstractmethod
from typing import Dict


class Tool(ABC):
    category: str = "general"
    effect: str = "write"
    plan_mode: str | None = None
    plan_mode_only: bool = False
    concurrency_safe: bool = False
    result_kind: str = "text"
    guidance: str = ""

    approval_required: bool = False
    approval_level: str = "🟢 安全"
    approval_reason: str = "安全的只读操作"

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def description(self) -> str: ...

    @property
    @abstractmethod
    def parameters(self) -> Dict: ...

    @abstractmethod
    def execute(self, arguments: Dict) -> str: ...

    def requires_approval(self, arguments: Dict) -> bool:
        return self.approval_required
