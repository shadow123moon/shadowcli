import fnmatch
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict

from .base import Tool
from .file_cache import get_read_state_cache, scope_id_from_context
from .file_tracker import get_file_tracker

# 搜索时默认跳过的目录（噪音大 / 体积大）
_IGNORED_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    ".idea", ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build",
}
_BINARY_SNIFF_BYTES = 8192
_GREP_MAX_HITS = 200
_GREP_MAX_LINE = 500
_FIND_MAX_HITS = 500
_MAX_PARALLEL_READS = 8
_MAX_READ_PATHS = 20


class ReadTool(Tool):
    category = "file"
    effect = "read"
    concurrency_safe = True
    result_kind = "text"
    guidance = "ShadowCLI read 工具，用于读取文件内容并显示行号；编辑已有文件前先 read，大文件用 offset/limit 分段读取。"

    @property
    def name(self):
        return "read"

    @property
    def description(self):
        return """读取文件内容，显示带行号的结果，方便定位代码。

场景：
- 用 find 或 grep 找到文件后，用 read 查看具体内容
- 编辑文件前必须先 read，否则 edit/write 会拒绝

用法：
- path: 文件路径（必填）
- paths: 多个文件路径；需要一次查看多个文件时使用
- offset: 从第几行开始读（从 1 开始，默认 1）
- limit: 最多读多少行（默认 2000）

限制：
- 文件最大 250 KB
- 默认最多 2000 行
- 超过 2000 字符的行会被截断
- 不能读二进制/图片文件

提示：
- 大文件用 offset 分段读取
- read 会记录读取时间，后续 edit/write 依赖这个记录"""

    @property
    def parameters(self):
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件路径"},
                "paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "多个文件路径；需要一次查看多个文件时使用。与 path 二选一",
                },
                "offset": {"type": "integer", "description": "起始行号（从 1 开始），默认 1"},
                "limit": {"type": "integer", "description": "最多读取行数，默认 2000"},
            },
            "required": [],
        }

    def execute(self, arguments: Dict) -> str:
        return self._execute(arguments, cache_scope=scope_id_from_context(None))

    def execute_with_context(self, arguments: Dict, context) -> str:
        return self._execute(arguments, cache_scope=scope_id_from_context(context))

    def _execute(self, arguments: Dict, *, cache_scope: str) -> str:
        if "paths" in arguments:
            return self._read_many(arguments, cache_scope=cache_scope)
        if "path" not in arguments:
            return "读取失败: 必须提供 path 或 paths"
        return self._read_one({**arguments, "cache_scope": cache_scope})

    def _read_many(self, arguments: Dict, *, cache_scope: str) -> str:
        paths = arguments.get("paths")
        if isinstance(paths, str):
            paths = [paths]
        if not isinstance(paths, list) or not paths:
            return "读取失败: paths 必须是非空文件路径列表"
        if len(paths) > _MAX_READ_PATHS:
            return f"读取失败: 一次最多读取 {_MAX_READ_PATHS} 个文件"

        offset = arguments.get("offset")
        limit = arguments.get("limit")
        read_args = [
            {"path": str(path), "offset": offset, "limit": limit, "cache_scope": cache_scope}
            for path in paths
        ]

        worker_count = min(len(read_args), _MAX_PARALLEL_READS)
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            results = list(executor.map(self._read_one, read_args))

        sections = []
        for args, result in zip(read_args, results):
            sections.append(f"==> {Path(args['path'])}\n{result}")
        return "\n\n".join(sections)

    def _read_one(self, arguments: Dict) -> str:
        path = Path(arguments["path"])
        scope_id = arguments.get("cache_scope") or scope_id_from_context(None)

        if not path.exists():
            return f"文件不存在: {path}"
        if path.is_dir():
            return f"这是目录不是文件: {path}"

        offset = max(1, int(arguments.get("offset") or 1))
        limit = max(1, int(arguments.get("limit") or 2000))

        cache = get_read_state_cache()
        decision = cache.lookup(path, scope_id=scope_id, offset=offset, limit=limit)
        if not decision.should_read:
            get_file_tracker().record_read(path)
            return decision.message or f"[CACHED] {path.name} already shown (unchanged)"

        size = path.stat().st_size
        if size > 250 * 1024:
            return f"文件太大（{size} 字节），最大支持 250 KB"

        try:
            raw = path.read_bytes()[:_BINARY_SNIFF_BYTES]
            if b"\x00" in raw:
                return f"这是二进制文件，无法显示: {path}"
        except OSError as exc:
            return f"读取失败: {exc}"

        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            return f"读取失败: {exc}"

        # 成功读取文件即记录（含空文件 / 超范围 offset），供 edit/write 校验
        get_file_tracker().record_read(path)

        total = len(lines)
        full_content = "\n".join(lines)
        if total == 0:
            cache.store(path, content=full_content, total_lines=total, shown_range=None, scope_id=scope_id)
            return "（空文件，0 行）"
        if offset > total:
            cache.store(path, content=full_content, total_lines=total, shown_range=None, scope_id=scope_id)
            return f"行号 {offset} 超出范围（文件共 {total} 行）"

        selected = lines[offset - 1: offset - 1 + limit]
        shown_range = (offset, offset + len(selected) - 1)

        numbered = []
        for i, line in enumerate(selected, start=offset):
            if len(line) > 2000:
                line = line[:2000] + "..."
            numbered.append(f"{i:6d}| {line}")

        content = "\n".join(numbered)

        # 增量对比（如果有旧内容）
        if decision.old_content:
            diff = self._compute_diff(decision.old_content, full_content)
            changed_lines = diff.count('\n')
            # 变化小于30%且少于100行，显示diff
            if changed_lines > 5 and changed_lines < min(100, total * 0.3):
                cache.store(path, content=full_content, total_lines=total, shown_range=shown_range, scope_id=scope_id)
                header = f"[UPDATED] {path.name} (total {total} lines, {changed_lines} changes)"
                return f"{header}\n\n{diff}"

        # 首次读取或大改动，显示完整内容
        cache.store(path, content=full_content, total_lines=total, shown_range=shown_range, scope_id=scope_id)

        header = f"共 {total} 行，显示 {offset}-{offset + len(selected) - 1}"
        if offset + len(selected) <= total:
            header += f"（还有更多，用 offset={offset + len(selected)} 继续读取）"

        return header + "\n" + content

    def _compute_diff(self, old: str, new: str) -> str:
        """计算文件差异，返回简化的 unified diff"""
        import difflib
        old_lines = old.splitlines(keepends=False)
        new_lines = new.splitlines(keepends=False)
        diff_lines = list(difflib.unified_diff(
            old_lines, new_lines,
            fromfile='旧版本', tofile='新版本',
            lineterm='', n=3
        ))
        if not diff_lines:
            return "（无变化）"
        return '\n'.join(diff_lines)


class WriteTool(Tool):
    category = "file"
    effect = "write"
    concurrency_safe = False
    result_kind = "text"
    guidance = "ShadowCLI write 工具，用于创建新文件或完整重写；修改已有文件优先用 edit，覆盖已有文件前必须先 read。"

    approval_required = False
    approval_level = "🟡 中危"
    approval_reason = "将写入或覆盖文件内容，原有内容可能丢失"

    @property
    def name(self):
        return "write"

    @property
    def description(self):
        return """创建或覆盖文件，自动创建缺失的父目录。

行为：
- 文件不存在则创建，已存在则整体覆盖
- 覆盖已存在文件前必须先 read（否则会被拒绝）
- 返回创建/覆盖状态与写入的行数、字节数

注意：
- 只做整文件写入；局部修改请用 edit
- 不能写到一个已存在的目录路径上"""

    @property
    def parameters(self):
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件路径"},
                "content": {"type": "string", "description": "要写入的完整内容"},
            },
            "required": ["path", "content"],
        }

    def execute(self, arguments: Dict) -> str:
        path = Path(arguments["path"])
        content = arguments["content"]

        if path.is_dir():
            return f"写入失败: 目标是目录: {path}"

        existed = path.exists()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        except OSError as exc:
            return f"写入失败: {exc}"

        get_file_tracker().record_write(path)

        action = "已覆盖" if existed else "已创建"
        line_count = _count_lines(content)
        byte_count = len(content.encode("utf-8"))
        return f"{action}: {path}（{line_count} 行，{byte_count} 字节）"


class EditTool(Tool):
    category = "file"
    effect = "write"
    concurrency_safe = False
    result_kind = "text"
    guidance = "ShadowCLI edit 工具，用于精确替换已有文件文本；old_text 必须完全匹配且默认唯一。"

    approval_required = False
    approval_level = "🟡 中危"
    approval_reason = "将精准替换文件中的文本，可能修改项目代码"

    @property
    def name(self):
        return "edit"

    @property
    def description(self):
        return """精准替换文件中的一段文本。

用法：
- old_text 必须与文件中的原文完全一致（含缩进/换行）
- 默认要求 old_text 在文件中唯一；匹配到多处会拒绝
- 要替换全部匹配，设 replace_all=true

注意：
- 编辑前必须先 read（否则会被拒绝）
- old_text 不能为空、且不能与 new_text 相同
- 返回首处替换的行号与替换次数"""

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
        if old_text == new_text:
            return "编辑失败: old_text 与 new_text 相同，无需编辑"
        if not path.exists():
            return f"编辑失败: 文件不存在: {path}"
        if path.is_dir():
            return f"编辑失败: 目标是目录: {path}"

        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            return f"编辑失败: {exc}"

        count = content.count(old_text)
        if count == 0:
            return "编辑失败: 未找到 old_text"
        if count > 1 and not replace_all:
            return f"编辑失败: old_text 匹配到 {count} 处，请提供更精确文本或设置 replace_all=true"

        first_line = content[: content.index(old_text)].count("\n") + 1
        updated = content.replace(old_text, new_text, -1 if replace_all else 1)
        try:
            path.write_text(updated, encoding="utf-8")
        except OSError as exc:
            return f"编辑失败: {exc}"

        get_file_tracker().record_write(path)

        replaced = count if replace_all else 1
        return f"编辑成功: {path}（第 {first_line} 行起，{replaced} 处替换）"


class LsTool(Tool):
    category = "file"
    effect = "read"
    concurrency_safe = True
    result_kind = "file_list"
    guidance = "ShadowCLI ls 工具，这是 Python 目录列表工具，不是终端 ls 命令；用于查看目录结构或单个文件大小。"

    @property
    def name(self):
        return "ls"

    @property
    def description(self):
        return """列出目录内容：目录在前（带 / 后缀），文件在后并显示大小。

用法：
- path: 目录路径，默认当前目录
- 传入文件路径时，显示该文件的大小"""

    @property
    def parameters(self):
        return {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "目录路径，默认当前目录"}},
            "required": [],
        }

    def execute(self, arguments: Dict) -> str:
        path = Path(arguments.get("path") or ".")

        if not path.exists():
            return f"路径不存在: {path}"
        if path.is_file():
            return f"{path.name}  ({_human_size(path.stat().st_size)})"

        try:
            entries = list(path.iterdir())
        except OSError as exc:
            return f"列目录失败: {exc}"
        if not entries:
            return "空目录"

        dirs = sorted((p for p in entries if p.is_dir()), key=lambda p: p.name)
        files = sorted((p for p in entries if not p.is_dir()), key=lambda p: p.name)

        lines = [f"{p.name}/" for p in dirs]
        lines += [f"{p.name}  ({_human_size(_safe_size(p))})" for p in files]
        return "\n".join(lines)


class GrepTool(Tool):
    category = "file"
    effect = "read"
    concurrency_safe = True
    result_kind = "search_hits"
    guidance = "ShadowCLI grep 工具，这是 Python 搜索工具，不是终端 grep/rg 命令；用于按正则搜索文件内容，按文件名找用 find。"

    @property
    def name(self):
        return "grep"

    @property
    def description(self):
        return """递归搜索文本内容，返回 文件:行号:内容。

用法：
- pattern: 正则搜索模式（必填）
- path: 文件或目录，默认当前目录
- include: 只搜匹配该 glob 的文件，如 *.py
- ignore_case: 是否忽略大小写

说明：
- 自动跳过二进制文件和 .git/node_modules 等目录
- 最多返回 200 处匹配，超出会截断"""

    @property
    def parameters(self):
        return {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "正则搜索模式"},
                "path": {"type": "string", "description": "文件或目录路径，默认当前目录"},
                "include": {"type": "string", "description": "只搜匹配该 glob 的文件，如 *.py"},
                "ignore_case": {"type": "boolean", "description": "是否忽略大小写，默认 false"},
            },
            "required": ["pattern"],
        }

    def execute(self, arguments: Dict) -> str:
        flags = re.IGNORECASE if arguments.get("ignore_case") else 0
        try:
            regex = re.compile(arguments["pattern"], flags)
        except re.error as exc:
            return f"grep 失败: 正则表达式无效: {exc}"

        root = Path(arguments.get("path") or ".")
        if not root.exists():
            return f"路径不存在: {root}"
        include = arguments.get("include")

        if root.is_file():
            files = [root]
        else:
            files = sorted(
                p for p in root.rglob("*")
                if p.is_file()
                and not _is_ignored(p)
                and (not include or fnmatch.fnmatch(p.name, include))
            )

        hits: list[str] = []
        truncated = False
        for file in files:
            if _looks_binary(file):
                continue
            try:
                text = file.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            label = _display_path(file, root)
            for lineno, line in enumerate(text.splitlines(), start=1):
                if regex.search(line):
                    if len(line) > _GREP_MAX_LINE:
                        line = line[:_GREP_MAX_LINE] + "..."
                    hits.append(f"{label}:{lineno}:{line}")
                    if len(hits) >= _GREP_MAX_HITS:
                        truncated = True
                        break
            if truncated:
                break

        if not hits:
            return "未找到匹配项"
        header = f"找到 {len(hits)} 处匹配"
        if truncated:
            header += f"（已截断，仅显示前 {_GREP_MAX_HITS} 处）"
        return header + "\n" + "\n".join(hits)


class FindTool(Tool):
    category = "file"
    effect = "read"
    concurrency_safe = True
    result_kind = "file_list"
    guidance = "ShadowCLI find 工具，这是 Python 文件名搜索工具，不是终端 find 命令；用于按 glob 文件名模式找文件，按内容搜用 grep。"

    @property
    def name(self):
        return "find"

    @property
    def description(self):
        return """按文件名模式递归查找。

用法：
- name: 文件名模式，如 *.py（必填）
- path: 搜索目录，默认当前目录
- type: 限定 file 或 dir，默认两者都找

说明：
- 自动跳过 .git/node_modules 等目录
- 目录结果带 / 后缀；最多返回 500 项"""

    @property
    def parameters(self):
        return {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "文件名模式，例如 *.py"},
                "path": {"type": "string", "description": "搜索目录，默认当前目录"},
                "type": {"type": "string", "description": "限定 file 或 dir，默认两者"},
            },
            "required": ["name"],
        }

    def execute(self, arguments: Dict) -> str:
        root = Path(arguments.get("path") or ".")
        if not root.exists():
            return f"路径不存在: {root}"

        pattern = arguments["name"]
        want_type = arguments.get("type")

        matches: list[str] = []
        truncated = False
        for p in sorted(root.rglob("*")):
            if _is_ignored(p):
                continue
            if not fnmatch.fnmatch(p.name, pattern):
                continue
            is_dir = p.is_dir()
            if want_type == "file" and is_dir:
                continue
            if want_type == "dir" and not is_dir:
                continue
            matches.append(_display_path(p, root) + ("/" if is_dir else ""))
            if len(matches) >= _FIND_MAX_HITS:
                truncated = True
                break

        if not matches:
            return "未找到文件"
        header = f"找到 {len(matches)} 个"
        if truncated:
            header += f"（已截断，仅显示前 {_FIND_MAX_HITS} 个）"
        return header + "\n" + "\n".join(matches)


def _display_path(path: Path, root: Path) -> str:
    try:
        base = root if root.is_dir() else root.parent
        return path.relative_to(base).as_posix()
    except ValueError:
        return path.as_posix()


def _count_lines(content: str) -> int:
    if not content:
        return 0
    return content.count("\n") + (0 if content.endswith("\n") else 1)


def _human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def _safe_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _is_ignored(path: Path) -> bool:
    return any(part in _IGNORED_DIRS for part in path.parts)


def _looks_binary(path: Path) -> bool:
    try:
        return b"\x00" in path.read_bytes()[:_BINARY_SNIFF_BYTES]
    except OSError:
        return True
