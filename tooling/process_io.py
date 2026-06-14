from __future__ import annotations

import queue
import threading
from dataclasses import dataclass


@dataclass
class StreamCaptureState:
    stream_name: str
    kept_bytes: int = 0
    dropped_bytes: int = 0
    truncated_by_limit: bool = False
    truncated_by_queue: bool = False
    read_error: str = ""


def capture_stream_to_queue(
    stream,
    stream_name: str,
    output_queue: queue.Queue,
    state: StreamCaptureState,
    *,
    limit_bytes: int,
    chunk_size: int = 16 * 1024,
) -> None:
    """Drain a subprocess stream without allowing retained output to grow unbounded."""
    while True:
        try:
            read = stream.read1 if hasattr(stream, "read1") else stream.read
            chunk = read(chunk_size)
        except OSError as exc:
            state.read_error = str(exc)
            break

        if not chunk:
            break
        if isinstance(chunk, str):
            chunk = chunk.encode(errors="replace")

        remaining = max(0, limit_bytes - state.kept_bytes)
        if remaining <= 0:
            state.truncated_by_limit = True
            state.dropped_bytes += len(chunk)
            continue

        payload = chunk[:remaining]
        overflow = chunk[remaining:]
        state.kept_bytes += len(payload)

        if payload:
            try:
                output_queue.put_nowait((stream_name, payload))
            except queue.Full:
                state.truncated_by_queue = True
                state.dropped_bytes += len(payload)

        if overflow:
            state.truncated_by_limit = True
            state.dropped_bytes += len(overflow)


def start_stream_reader(
    stream,
    stream_name: str,
    output_queue: queue.Queue,
    state: StreamCaptureState,
    *,
    limit_bytes: int,
    chunk_size: int = 16 * 1024,
) -> threading.Thread:
    thread = threading.Thread(
        target=capture_stream_to_queue,
        args=(stream, stream_name, output_queue, state),
        kwargs={"limit_bytes": limit_bytes, "chunk_size": chunk_size},
        daemon=True,
    )
    thread.start()
    return thread
