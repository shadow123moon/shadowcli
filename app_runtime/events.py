from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RuntimeEvent:
    type: str
    payload: dict[str, Any]


EventHandler = Callable[[RuntimeEvent], None]


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        self._handlers[event_type].append(handler)

    def publish(self, event_type: str, **payload: Any) -> RuntimeEvent:
        event = RuntimeEvent(type=event_type, payload=payload)
        for handler in list(self._handlers.get(event_type, [])):
            handler(event)
        return event
