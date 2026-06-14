from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from llm import Message
from tooling.process_io import StreamCaptureState, capture_stream_to_queue, start_stream_reader


def new_turn_id() -> str:
    return f"turn_{uuid4().hex[:12]}"


class RuntimeJournal:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def append(self, event_type: str, **fields) -> dict:
        event = {
            "type": event_type,
            "timestamp": _now_iso(),
            **fields,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n"
        with self._lock:
            with self.path.open("a", encoding="utf-8") as fp:
                fp.write(line)
                fp.flush()
                os.fsync(fp.fileno())
        return event

    def load(self) -> list[dict]:
        if not self.path.exists():
            return []
        events: list[dict] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return events

    def format_last_cancelled_turn_notice(self) -> str:
        events = self.load()
        terminal = next(
            (
                event
                for event in reversed(events)
                if event.get("type") in {"turn_cancelled", "turn_finished", "turn_failed"}
            ),
            None,
        )
        if not terminal or terminal.get("type") != "turn_cancelled":
            return ""

        turn_id = terminal.get("turn_id")
        effectful_tools = [
            event
            for event in events
            if event.get("type") == "tool_started"
            and event.get("turn_id") == turn_id
            and event.get("effect") != "read"
        ]
        if not effectful_tools:
            return "上一轮被用户中断，会话消息未提交。"

        lines = [
            "上一轮被用户中断，会话消息未提交。",
            "以下有副作用工具已经开始执行，物理状态可能已经改变；不要假设命令没有执行：",
            "如果当前用户只是询问上一轮发生了什么，先直接说明中断事实，不要主动调用工具。",
            "只有在继续上一轮任务、依赖工具结果或用户要求核实时，才先检查现实状态：",
        ]
        for event in effectful_tools:
            name = event.get("name", "tool")
            preview = event.get("args_preview") or ""
            status = _tool_status(events, turn_id, event.get("tool_call_id"))
            lines.append(f"- {name}: {preview} (status={status})")
        return "\n".join(lines)


@dataclass
class RuntimeTask:
    id: str
    kind: str
    cancel: threading.Event = field(default_factory=threading.Event)
    status: str = "pending"
    error: str = ""
    cancel_reason: str = ""
    cancel_journal_recorded: bool = False
    thread: threading.Thread | None = None


class TaskRuntime:
    def __init__(self, journal: RuntimeJournal | None = None):
        self.journal = journal
        self._lock = threading.Lock()
        self.current_interactive: RuntimeTask | None = None

    def start_interactive(self, fn) -> RuntimeTask:
        task = RuntimeTask(id=new_turn_id(), kind="interactive_turn")
        journal = self.journal
        with self._lock:
            if self.current_interactive and not self.current_interactive.cancel.is_set():
                self.current_interactive.cancel.set()
                self.current_interactive.cancel_reason = "stale"
            self.current_interactive = task

        if journal is not None:
            journal.append("turn_started", turn_id=task.id, task_kind=task.kind)

        def run() -> None:
            task.status = "running"
            try:
                fn(task)
                if task.cancel.is_set():
                    task.status = "cancelled"
                else:
                    task.status = "finished"
            except Exception as exc:  # pragma: no cover - defensive status capture
                task.status = "error"
                task.error = str(exc)
            finally:
                if task.status == "cancelled" and journal is not None and not task.cancel_journal_recorded:
                    journal.append(
                        "turn_cancelled",
                        turn_id=task.id,
                        reason=task.cancel_reason or "cancelled",
                    )
                elif task.status == "finished" and journal is not None:
                    journal.append("turn_finished", turn_id=task.id)
                elif task.status == "error" and journal is not None:
                    journal.append("turn_failed", turn_id=task.id, error=task.error)

        task.thread = threading.Thread(target=run, name=f"shadowcli-{task.id}", daemon=True)
        task.thread.start()
        return task

    def cancel_current(self, reason: str = "user_cancelled") -> bool:
        with self._lock:
            task = self.current_interactive
            if task is None or task.status in {"finished", "cancelled", "error"}:
                return False
            task.cancel_reason = reason
            task.cancel.set()
            if self.journal is not None and not task.cancel_journal_recorded:
                self.journal.append(
                    "turn_cancelled",
                    turn_id=task.id,
                    reason=task.cancel_reason or "cancelled",
                )
                task.cancel_journal_recorded = True
            return True

    def wait_current(self, timeout: float | None = None) -> bool:
        with self._lock:
            task = self.current_interactive
        if task is None or task.thread is None:
            return True
        task.thread.join(timeout=timeout)
        return not task.thread.is_alive()

    def is_current(self, task_id: str) -> bool:
        with self._lock:
            return self.current_interactive is not None and self.current_interactive.id == task_id


class TurnBuffer:
    def __init__(self):
        self.messages: list[Message] = []

    def append(self, message: Message) -> None:
        if message.role != "system":
            self.messages.append(message)

    def commit(self, session) -> None:
        if self.messages:
            session.append_messages(self.messages)


def _tool_status(events: list[dict], turn_id: str | None, tool_call_id: str | None) -> str:
    finished = [
        event
        for event in events
        if event.get("type") == "tool_finished"
        and event.get("turn_id") == turn_id
        and event.get("tool_call_id") == tool_call_id
    ]
    if finished:
        return str(finished[-1].get("status") or "finished")
    return "unknown_after_cancel"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
