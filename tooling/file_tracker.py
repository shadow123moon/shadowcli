"""文件读写追踪 —— 支撑 read-before-edit 与「外部修改」检测。

记录每个文件「我最后已知的修改时间」(mtime 快照)：read / edit / write
成功后刷新；edit / write 之前用 check_readable 确认这个文件我读过、且自那
以后没被进程外改动过。

这里比对的是文件 mtime 快照，而不是墙上时钟时间戳——直接比文件版本，不受
进程时钟与文件系统时钟漂移影响，也不需要 EPS 容差。
"""
from __future__ import annotations

import threading
from pathlib import Path


class FileTracker:
    """线程安全地记录每个文件最后已知的 mtime。"""

    def __init__(self) -> None:
        self._known_mtime_ns: dict[str, int] = {}
        self._lock = threading.Lock()

    def record_read(self, path) -> None:
        """read 成功后调用。"""
        self._remember(path)

    def record_write(self, path) -> None:
        """edit / write 成功后调用。"""
        self._remember(path)

    def check_readable(self, path) -> str | None:
        """edit / write 之前调用。None=放行，str=拒绝原因。"""
        p = Path(path)
        if not p.exists():
            return None  # 新建文件，无需先读

        known = self._get(p)#
        if known is None:
            return f"必须先用 read 读取文件才能修改：{p}"

        if _mtime_ns(p) != known:
            return (
                f"文件在上次读取后被外部修改：{p}\n"
                "请重新用 read 读取最新内容后再修改。"
            )
        return None

    def reset(self) -> None:
        """清空所有记录（主要供测试隔离使用）。"""
        with self._lock:
            self._known_mtime_ns.clear()

    def _remember(self, path) -> None:#生成文件操作时间的快照
        p = Path(path)
        mtime = _mtime_ns(p)
        if mtime is None:
            return
        with self._lock:
            self._known_mtime_ns[_key(p)] = mtime

    def _get(self, path: Path) -> int | None:#获取快照文件最新的操作时间
        with self._lock:
            return self._known_mtime_ns.get(_key(path))


def _key(path: Path) -> str:#获取绝对路径
    return str(path.resolve())


def _mtime_ns(path: Path) -> int | None:
    try:
        return path.stat().st_mtime_ns # 获取文件实际的修改时间
    except OSError:
        return None # 文件不存在或无权限时返回 None


_global_tracker = FileTracker()


def get_file_tracker() -> FileTracker:
    return _global_tracker


_GUARDED_TOOLS = ("edit", "write")


def register_freshness_guard(runtime, tracker: FileTracker | None = None) -> None:
    """把「编辑前必须先读、且未被外部改动」检查挂到 ToolRuntime。

    与 extensions.hitl.register 同一机制：注册一个 before-execute hook，
    命中即返回软拒绝（hard_stop=False），让模型按提示先 read 再重试，
    而不是终止整个任务。
    """
    guard_tracker = tracker or get_file_tracker()

    def hook(name, arguments, _tool):
        if name not in _GUARDED_TOOLS:
            return None
        path = arguments.get("path")
        if not path:
            return None
        reason = guard_tracker.check_readable(path)
        if reason is None:
            return None
        return {"block": True, "hard_stop": False, "reason": reason}

    runtime.on_before_execute(hook)
