import os
import subprocess
from typing import Dict

from .base import Tool

DEFAULT_COMMAND_TIMEOUT_SECONDS = 120


class BashTool(Tool):
    approval_required = True
    approval_level = "🔴 高危"
    approval_reason = "将在系统上执行 Shell 命令，可能修改文件、安装软件或影响系统状态"

    @property
    def name(self):
        return "bash"

    @property
    def description(self):
        return "执行 Shell 命令"

    @property
    def parameters(self):
        return {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "要执行的命令"},
                "timeout_seconds": {
                    "type": "integer",
                    "description": "命令最长执行秒数，默认 120 秒",
                },
            },
            "required": ["command"],
        }

    def execute(self, arguments: Dict) -> str:
        command = arguments["command"]
        timeout = _command_timeout(arguments.get("timeout_seconds"))
        try:
            if os.name == "nt":
                result = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", command],
                    capture_output=True,
                    text=True,
                    errors="replace",
                    timeout=timeout,
                )
            else:
                result = subprocess.run(
                    command,
                    shell=True,
                    capture_output=True,
                    text=True,
                    errors="replace",
                    timeout=timeout,
                )
        except subprocess.TimeoutExpired as exc:
            return _format_result(exc, command, timeout)
        return _format_result(result)


def _command_timeout(raw_timeout) -> int:
    """解析超时时间：参数 > 环境变量 > 默认值"""
    try:
        timeout = int(raw_timeout or os.getenv("PAICLI_COMMAND_TIMEOUT_SECONDS") or DEFAULT_COMMAND_TIMEOUT_SECONDS)
    except (TypeError, ValueError):
        return DEFAULT_COMMAND_TIMEOUT_SECONDS
    return max(1, timeout)


def _format_result(result, command: str = "", timeout: int = 0) -> str:
    """格式化命令执行结果（支持正常结果和超时异常）"""
    # 超时异常
    if isinstance(result, subprocess.TimeoutExpired):
        parts = [f"命令超时（超过 {timeout} 秒），已终止。", f"command: {command}"]
        if result.stdout:
            stdout_str = result.stdout.decode(errors="replace") if isinstance(result.stdout, bytes) else str(result.stdout)
            parts.append(f"stdout:\n{stdout_str}")
        if result.stderr:
            stderr_str = result.stderr.decode(errors="replace") if isinstance(result.stderr, bytes) else str(result.stderr)
            parts.append(f"stderr:\n{stderr_str}")
        return "\n\n".join(parts)

    # 正常结果
    stdout = result.stdout or ""
    stderr = result.stderr or ""
    if result.returncode == 0:
        if stdout:
            return stdout
        if stderr:
            return f"命令执行成功，但写入了 stderr：\n{stderr}"
        return "命令执行成功（无输出）"

    parts = [f"命令执行失败（退出码 {result.returncode}）"]
    if stdout:
        parts.append(f"stdout:\n{stdout}")
    if stderr:
        parts.append(f"stderr:\n{stderr}")
    if len(parts) == 1:
        parts.append("没有 stdout/stderr 输出。")
    return "\n\n".join(parts)
