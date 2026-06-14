from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass, field
from pathlib import Path


DEFAULT_READ_CACHE_SCOPE = "process"


@dataclass(frozen=True)
class ReadCacheDecision:
    should_read: bool
    message: str | None = None
    old_content: str | None = None


@dataclass
class ReadState:
    path: Path
    mtime_ns: int
    content_hash: str
    total_lines: int
    shown_ranges: list[tuple[int, int]] = field(default_factory=list)
    full_content: str | None = None


class ReadStateCache:
    """Track file read state by scope, path, file version, and shown line ranges."""

    def __init__(self) -> None:
        self._states: dict[tuple[str, str], ReadState] = {}
        self._lock = threading.Lock()

    def lookup(self, path: Path, *, scope_id: str, offset: int, limit: int) -> ReadCacheDecision:
        key = self._key(path, scope_id)
        with self._lock:
            state = self._states.get(key)
        if state is None:
            return ReadCacheDecision(should_read=True)

        mtime_ns = _mtime_ns(path)
        if mtime_ns is None:
            with self._lock:
                self._states.pop(key, None)
            return ReadCacheDecision(should_read=True)

        if mtime_ns != state.mtime_ns:
            return ReadCacheDecision(should_read=True, old_content=state.full_content)

        if state.total_lines == 0:
            return ReadCacheDecision(
                should_read=False,
                message=f"[CACHED] {path.name} already shown as empty file (unchanged)",
            )

        requested = _effective_range(offset, limit, state.total_lines)
        if requested is None:
            return ReadCacheDecision(
                should_read=False,
                message=f"[CACHED] {path.name} line {offset} is still outside file range (total {state.total_lines} lines)",
            )

        if _range_covered(requested, state.shown_ranges):
            start, end = requested
            return ReadCacheDecision(
                should_read=False,
                message=f"[CACHED] {path.name} lines {start}-{end} already shown (unchanged)",
            )

        return ReadCacheDecision(should_read=True, old_content=state.full_content)

    def store(
        self,
        path: Path,
        *,
        content: str,
        total_lines: int,
        shown_range: tuple[int, int] | None,
        scope_id: str,
    ) -> None:
        mtime_ns = _mtime_ns(path)
        if mtime_ns is None:
            return
        key = self._key(path, scope_id)
        content_hash = hashlib.sha256(content.encode("utf-8", errors="surrogatepass")).hexdigest()
        with self._lock:
            current = self._states.get(key)
            if current is None or current.mtime_ns != mtime_ns or current.content_hash != content_hash:
                current = ReadState(
                    path=path.resolve(),
                    mtime_ns=mtime_ns,
                    content_hash=content_hash,
                    total_lines=total_lines,
                    full_content=content,
                )
            else:
                current.total_lines = total_lines
                current.full_content = content
            if shown_range is not None:
                current.shown_ranges = _merge_ranges([*current.shown_ranges, shown_range])
            self._states[key] = current

    def clear(self) -> None:
        with self._lock:
            self._states.clear()

    def _key(self, path: Path, scope_id: str) -> tuple[str, str]:
        return scope_id, str(path.resolve())


def scope_id_from_context(context) -> str:
    if context is None:
        return DEFAULT_READ_CACHE_SCOPE

    journal = getattr(context, "journal", None)
    journal_path = getattr(journal, "path", None)
    if journal_path is not None:
        return f"session:{Path(journal_path).parent.resolve()}"

    turn_id = getattr(context, "turn_id", None)
    if turn_id:
        return f"turn:{turn_id}"

    return DEFAULT_READ_CACHE_SCOPE


def get_read_state_cache() -> ReadStateCache:
    return _read_state_cache


def _effective_range(offset: int, limit: int, total_lines: int) -> tuple[int, int] | None:
    if offset > total_lines:
        return None
    start = max(1, offset)
    end = min(total_lines, start + max(1, limit) - 1)
    return start, end


def _range_covered(requested: tuple[int, int], ranges: list[tuple[int, int]]) -> bool:
    start, end = requested
    cursor = start
    for range_start, range_end in sorted(ranges):
        if range_end < cursor:
            continue
        if range_start > cursor:
            return False
        cursor = max(cursor, range_end + 1)
        if cursor > end:
            return True
    return False


def _merge_ranges(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    normalized = sorted((start, end) for start, end in ranges if start <= end)
    if not normalized:
        return []
    merged = [normalized[0]]
    for start, end in normalized[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end + 1:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def _mtime_ns(path: Path) -> int | None:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return None


_read_state_cache = ReadStateCache()
