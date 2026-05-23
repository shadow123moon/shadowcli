# tools.py
from abc import ABC, abstractmethod
from typing import Dict
import os
import subprocess
from pathlib import Path

class Tool(ABC):
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

# ---------- 具体工具 ----------
class ReadFileTool(Tool):
    @property
    def name(self): return "read_file"
    @property
    def description(self): return "读取文件内容"
    @property
    def parameters(self):
        return {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "文件路径"}},
            "required": ["path"]
        }
    def execute(self, arguments: Dict) -> str:
        return Path(arguments["path"]).read_text(encoding="utf-8")

class WriteFileTool(Tool):
    @property
    def name(self): return "write_file"
    @property
    def description(self): return "写入内容到文件"
    @property
    def parameters(self):
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件路径"},
                "content": {"type": "string", "description": "要写入的内容"}
            },
            "required": ["path", "content"]
        }
    def execute(self, arguments: Dict) -> str:
        path = Path(arguments["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(arguments["content"], encoding="utf-8")
        return f"写入成功: {path}"

class ListDirTool(Tool):
    @property
    def name(self): return "list_dir"
    @property
    def description(self): return "列出目录中的文件和子目录"
    @property
    def parameters(self):
        return {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "目录路径"}},
            "required": ["path"]
        }
    def execute(self, arguments: Dict) -> str:
        path = Path(arguments["path"])
        items = [p.name for p in path.iterdir()]
        return "\n".join(items) if items else "空目录"

class ExecuteCommandTool(Tool):
    @property
    def name(self): return "execute_command"
    @property
    def description(self): return "执行 Shell 命令"
    @property
    def parameters(self):
        return {
            "type": "object",
            "properties": {"command": {"type": "string", "description": "要执行的命令"}},
            "required": ["command"]
        }
    def execute(self, arguments: Dict) -> str:
        command = arguments["command"]
        if os.name == "nt":
            result = subprocess.run(["powershell", "-NoProfile", "-Command", command],
                                    capture_output=True, text=True)
        else:
            result = subprocess.run(command, shell=True,
                                    capture_output=True, text=True)
        return result.stdout if result.returncode == 0 else f"错误: {result.stderr}"
