import os
import queue
import signal
import subprocess
import time
from typing import Dict

from .base import Tool
from .process_io import StreamCaptureState, start_stream_reader
from .results import truncate_tool_text

DEFAULT_COMMAND_TIMEOUT_SECONDS = 120
DEFAULT_COMMAND_OUTPUT_LIMIT_BYTES = 256 * 1024
DEFAULT_OUTPUT_QUEUE_SIZE = 128


class BashTool(Tool):
    category = "shell"
    effect = "execute"
    concurrency_safe = False
    result_kind = "command_output"
    guidance = (
        "bash 工具只用于执行真正的本机 PowerShell 命令；不要通过 bash 调 ShadowCLI 工具"
        "（read/write/edit/ls/grep/find）或 ShadowCLI slash 命令（/skill、/plugin、/tree、/jump、/compact），"
        "这些不是终端命令。"
    )

    approval_required = True
    approval_level = "🔴 高危"
    approval_reason = "将在系统上执行 Shell 命令，可能修改文件、安装软件或影响系统状态"

    @property
    def name(self):
        return "bash"

    @property
    def description(self):
        return "执行本机命令。Windows 环境：强制使用 PowerShell 语法（ls、Select-Object、ForEach-Object、$env:VAR 等），禁止使用 Linux/Bash 命令（find、grep、&&、||、export）"

    @property
    def parameters(self):
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": (
                        "要执行的命令。当前平台：Windows PowerShell。"
                        "必须使用 PowerShell 语法：ls（不是 find）、Select-Object（不是 grep）、"
                        "$env:VAR（不是 export VAR）、分号分隔命令（不是 && 或 ||）。"
                        "禁止使用 Linux 命令：find、xargs、grep、tail、head、&&、||、export。"
                    ),
                },
                "timeout_seconds": {
                    "type": "integer",
                    "description": "命令最长执行秒数，默认 120 秒",
                },
            },
            "required": ["command"],
        }

    def execute(self, arguments: Dict) -> str:
        return self.execute_with_context(arguments, None)

    def execute_with_context(self, arguments: Dict, context) -> str:
        command = arguments["command"]
        timeout = _command_timeout(arguments.get("timeout_seconds"))
        cancel = getattr(context, "cancel", None) if context is not None else None
        return _run_command(command, timeout=timeout, cancel=cancel)


def _run_command(command: str, *, timeout: int, cancel=None) -> str:
    output_limit = _command_output_limit()
    output_queue: queue.Queue = queue.Queue(maxsize=DEFAULT_OUTPUT_QUEUE_SIZE)
    stdout_state = StreamCaptureState("stdout")
    stderr_state = StreamCaptureState("stderr")
    chunks: dict[str, list[bytes]] = {"stdout": [], "stderr": []}

    popen_kwargs = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": False,
    }
    if os.name == "nt":
        args = ["powershell", "-NoProfile", "-Command", command]
        popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        args = command
        popen_kwargs["shell"] = True
        popen_kwargs["start_new_session"] = True

    try:
        process = subprocess.Popen(args, **popen_kwargs)
    except OSError as exc:
        return f"命令执行失败（启动失败）\n错误类型: command_start_failed\nstderr:\n{exc}"

    stdout_thread = start_stream_reader(
        process.stdout,
        "stdout",
        output_queue,
        stdout_state,
        limit_bytes=output_limit,
    )
    stderr_thread = start_stream_reader(
        process.stderr,
        "stderr",
        output_queue,
        stderr_state,
        limit_bytes=output_limit,
    )
    deadline = time.monotonic() + timeout

    while True:
        _drain_output(output_queue, chunks)

        if cancel is not None and cancel.is_set():
            _kill_process_tree(process)
            _finish_process(process)
            _join_readers(stdout_thread, stderr_thread)
            _close_process_streams(process)
            _drain_output(output_queue, chunks)
            return _format_cancelled_result(command, chunks, stdout_state, stderr_state)

        try:
            returncode = process.poll()
        except OSError as exc:
            _kill_process_tree(process)
            return f"命令执行失败（状态检查失败）\n错误类型: command_poll_failed\nstderr:\n{exc}"

        if returncode is not None:
            _join_readers(stdout_thread, stderr_thread)
            _close_process_streams(process)
            _drain_output(output_queue, chunks)
            result = subprocess.CompletedProcess(
                args=args,
                returncode=returncode,
                stdout=_decode_stream(chunks["stdout"], stdout_state),
                stderr=_decode_stream(chunks["stderr"], stderr_state),
            )
            return _format_result(result)

        if time.monotonic() >= deadline:
            _kill_process_tree(process)
            _finish_process(process)
            _join_readers(stdout_thread, stderr_thread)
            _close_process_streams(process)
            _drain_output(output_queue, chunks)
            exc = subprocess.TimeoutExpired(
                cmd=command,
                timeout=timeout,
                output=_decode_stream(chunks["stdout"], stdout_state),
                stderr=_decode_stream(chunks["stderr"], stderr_state),
            )
            return _format_result(exc, command, timeout)

        if cancel is not None:
            cancel.wait(0.05)
        else:
            time.sleep(0.05)


def _command_timeout(raw_timeout) -> int:
    """解析超时时间：参数 > 环境变量 > 默认值"""
    try:
        timeout = int(raw_timeout or os.getenv("SHADOWCLI_COMMAND_TIMEOUT_SECONDS") or DEFAULT_COMMAND_TIMEOUT_SECONDS)
    except (TypeError, ValueError):
        return DEFAULT_COMMAND_TIMEOUT_SECONDS
    return max(1, timeout)


def _command_output_limit() -> int:
    try:
        limit = int(os.getenv("SHADOWCLI_COMMAND_OUTPUT_LIMIT_BYTES") or DEFAULT_COMMAND_OUTPUT_LIMIT_BYTES)
    except (TypeError, ValueError):
        return DEFAULT_COMMAND_OUTPUT_LIMIT_BYTES
    return max(1024, limit)


def _drain_output(output_queue: queue.Queue, chunks: dict[str, list[bytes]]) -> None:
    while True:
        try:
            stream_name, payload = output_queue.get_nowait()
        except queue.Empty:
            return
        chunks.setdefault(stream_name, []).append(payload)


def _join_readers(*threads) -> None:
    for thread in threads:
        thread.join(timeout=1.0)


def _close_process_streams(process: subprocess.Popen) -> None:
    for stream in (process.stdout, process.stderr):
        if stream is None:
            continue
        try:
            stream.close()
        except OSError:
            pass


def _finish_process(process: subprocess.Popen) -> None:
    try:
        process.wait(timeout=5)
    except (subprocess.TimeoutExpired, OSError):
        pass


def _kill_process_tree(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(process.pid)],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            try:
                process.kill()
            except OSError:
                pass
        return

    try:
        os.killpg(process.pid, signal.SIGTERM)
    except OSError:
        try:
            process.terminate()
        except OSError:
            pass
    try:
        process.wait(timeout=2)
    except (OSError, subprocess.TimeoutExpired):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            try:
                process.kill()
            except OSError:
                pass


def _decode_stream(chunks: list[bytes], state: StreamCaptureState) -> str:
    text = b"".join(chunks).decode(errors="replace")
    notices: list[str] = []
    if state.truncated_by_limit:
        notices.append(f"[{state.stream_name} output truncated: exceeded {state.kept_bytes} bytes]")
    if state.truncated_by_queue:
        notices.append(f"[{state.stream_name} output dropped: internal output queue was full]")
    if state.read_error:
        notices.append(f"[{state.stream_name} read error: {state.read_error}]")
    if notices:
        suffix = "\n".join(notices)
        if text and not text.endswith("\n"):
            text += "\n"
        text += suffix + "\n"
    return text


def _format_cancelled_result(
    command: str,
    chunks: dict[str, list[bytes]],
    stdout_state: StreamCaptureState,
    stderr_state: StreamCaptureState,
) -> str:
    parts = [
        "命令已取消，已尝试终止进程树。",
        "错误类型: cancelled",
        f"command: {command}",
    ]
    stdout = _decode_stream(chunks["stdout"], stdout_state)
    stderr = _decode_stream(chunks["stderr"], stderr_state)
    if stdout:
        parts.append(f"stdout:\n{truncate_tool_text(stdout)}")
    if stderr:
        parts.append(f"stderr:\n{truncate_tool_text(stderr)}")
    return "\n\n".join(parts)


def _format_result(result, command: str = "", timeout: int = 0) -> str:
    """格式化命令执行结果（支持正常结果和超时异常）"""
    # 超时异常
    if isinstance(result, subprocess.TimeoutExpired):
        parts = [f"命令超时（超过 {timeout} 秒），已终止。", "错误类型: timeout", f"command: {command}"]
        if result.stdout:
            stdout_str = _stream_text(result.stdout)
            parts.append(f"stdout:\n{stdout_str}")
        if result.stderr:
            stderr_str = _stream_text(result.stderr)
            parts.append(f"stderr:\n{stderr_str}")
        return "\n\n".join(parts)

    # 正常结果
    stdout = result.stdout or ""
    stderr = result.stderr or ""
    if result.returncode == 0:
        if stdout:
            return truncate_tool_text(stdout)
        if stderr:
            return f"命令执行成功，但写入了 stderr：\n{truncate_tool_text(stderr)}"
        return "命令执行成功（无输出）"

    parts = [f"命令执行失败（退出码 {result.returncode}）", "错误类型: command_failed"]
    if stdout:
        parts.append(f"stdout:\n{truncate_tool_text(stdout)}")
    if stderr:
        parts.append(f"stderr:\n{truncate_tool_text(stderr)}")
    if len(parts) == 2:
        parts.append("没有 stdout/stderr 输出。")
    return "\n\n".join(parts)


def _stream_text(value) -> str:
    text = value.decode(errors="replace") if isinstance(value, bytes) else str(value)
    return truncate_tool_text(text)
