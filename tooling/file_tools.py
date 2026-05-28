import fnmatch
import re
from pathlib import Path
from typing import Dict

from .base import Tool


class ReadTool(Tool):
    @property
    def name(self):
        return "read"

    @property
    def description(self):
        return "读取文件内容"

    @property
    def parameters(self):
        return {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "文件路径"}},
            "required": ["path"],
        }

    def execute(self, arguments: Dict) -> str:
        return Path(arguments["path"]).read_text(encoding="utf-8")


class WriteTool(Tool):
    approval_required = False
    approval_level = "🟡 中危"
    approval_reason = "将写入或覆盖文件内容，原有内容可能丢失"

    @property
    def name(self):
        return "write"

    @property
    def description(self):
        return "创建或覆盖文件内容"

    @property
    def parameters(self):
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件路径"},
                "content": {"type": "string", "description": "要写入的内容"},
            },
            "required": ["path", "content"],
        }

    def execute(self, arguments: Dict) -> str:
        path = Path(arguments["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(arguments["content"], encoding="utf-8")
        return f"写入成功: {path}"


class EditTool(Tool):
    approval_required = False
    approval_level = "🟡 中危"
    approval_reason = "将精准替换文件中的文本，可能修改项目代码"

    @property
    def name(self):
        return "edit"

    @property
    def description(self):
        return "精准替换文件中的一段文本"

    @property
    def parameters(self):
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件路径"},
                "old_text": {"type": "string", "description": "要被替换的原文"},
                "new_text": {"type": "string", "description": "替换后的新文本"},
                "replace_all": {
                    "type": "boolean",
                    "description": "是否替换全部匹配；默认 false，要求只匹配一处",
                },
            },
            "required": ["path", "old_text", "new_text"],
        }

    def execute(self, arguments: Dict) -> str:
        path = Path(arguments["path"])
        old_text = arguments["old_text"]
        new_text = arguments["new_text"]
        replace_all = bool(arguments.get("replace_all", False))
        if old_text == "":
            return "编辑失败: old_text 不能为空"
        content = path.read_text(encoding="utf-8")
        count = content.count(old_text)
        if count == 0:
            return "编辑失败: 未找到 old_text"
        if count > 1 and not replace_all:
            return f"编辑失败: old_text 匹配到 {count} 处，请提供更精确文本或设置 replace_all=true"
        updated = content.replace(old_text, new_text, -1 if replace_all else 1)
        path.write_text(updated, encoding="utf-8")
        return f"编辑成功: {path} ({count if replace_all else 1} 处替换)"


class LsTool(Tool):
    @property
    def name(self):
        return "ls"

    @property
    def description(self):
        return "列出目录中的文件和子目录"

    @property
    def parameters(self):
        return {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "目录路径，默认当前目录"}},
            "required": [],
        }

    def execute(self, arguments: Dict) -> str:
        path = Path(arguments.get("path") or ".")
        items = sorted(p.name for p in path.iterdir())
        return "\n".join(items) if items else "空目录"


class GrepTool(Tool):
    @property
    def name(self):
        return "grep"

    @property
    def description(self):
        return "递归搜索文本内容，返回 文件:行号:内容"

    @property
    def parameters(self):
        return {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "正则搜索模式"},
                "path": {"type": "string", "description": "文件或目录路径，默认当前目录"},
            },
            "required": ["pattern"],
        }

    def execute(self, arguments: Dict) -> str:
        try:
            regex = re.compile(arguments["pattern"])
        except re.error as exc:
            return f"grep 失败: 正则表达式无效: {exc}"
        root = Path(arguments.get("path") or ".")
        files = [root] if root.is_file() else [p for p in root.rglob("*") if p.is_file()]
        lines: list[str] = []
        for file in sorted(files):
            try:
                text = file.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            label = _display_path(file, root)
            for lineno, line in enumerate(text.splitlines(), start=1):
                if regex.search(line):
                    lines.append(f"{label}:{lineno}:{line}")
        return "\n".join(lines) if lines else "未找到匹配项"


class FindTool(Tool):
    @property
    def name(self):
        return "find"

    @property
    def description(self):
        return "按文件名模式递归查找文件"

    @property
    def parameters(self):
        return {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "文件名模式，例如 *.py"},
                "path": {"type": "string", "description": "搜索目录，默认当前目录"},
            },
            "required": ["name"],
        }

    def execute(self, arguments: Dict) -> str:
        root = Path(arguments.get("path") or ".")
        pattern = arguments["name"]
        matches = [
            _display_path(p, root)
            for p in sorted(root.rglob("*"))
            if p.is_file() and fnmatch.fnmatch(p.name, pattern)
        ]
        return "\n".join(matches) if matches else "未找到文件"


def _display_path(path: Path, root: Path) -> str:
    try:
        base = root if root.is_dir() else root.parent
        return path.relative_to(base).as_posix()
    except ValueError:
        return path.as_posix()
