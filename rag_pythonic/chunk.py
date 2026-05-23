"""代码分块：CodeChunk 数据模型 + CodeChunker 分块器。

策略简化（对照 Java 版）：
- Python 文件     ：用标准库 ast 提取类/函数级 chunk
- 其他所有文件    ：按 MAX_CHUNK_CHARS 字符大小切段
                   （原 Java 版只对 .java 用 JavaParser，其他按大小切）

Pythonic 要点：
- @dataclass(slots=True) + classmethod 工厂   替代 Java record 多构造
- pathlib.Path 替代 java.nio.file.Path
- ast.walk + isinstance 分支              替代 JavaParser 的 cu.findAll
- generator 分段                          省内存
"""
from __future__ import annotations

import ast
import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

# 单 chunk 最大字符（与 Java 版一致：~4000-6000 token，适配 8192 上下文）
MAX_CHUNK_CHARS = 2000


@dataclass(slots=True)
class CodeChunk:
    """代码块：文件级 / 类级 / 方法级。"""

    file_path: str
    chunk_type: str  # "file" | "class" | "method"
    name: str
    content: str
    start_line: int = 0
    end_line: int = 0

    @classmethod
    def file_chunk(cls, file_path: str, content: str) -> CodeChunk:
        return cls(file_path, "file", file_path, content)

    @classmethod
    def class_chunk(
        cls, file_path: str, class_name: str, content: str, start: int, end: int
    ) -> CodeChunk:
        return cls(file_path, "class", class_name, content, start, end)

    @classmethod
    def method_chunk(
        cls, file_path: str, method_name: str, content: str, start: int, end: int
    ) -> CodeChunk:
        return cls(file_path, "method", method_name, content, start, end)

    def to_embedding_text(self) -> str:
        """生成喂给 embedding 模型的文本表示（带类型/名称前缀，提升语义信号）。"""
        return f"[{self.chunk_type}:{self.name}] {self.content}"

    def key(self) -> str:
        """store / merge 用的唯一 key。"""
        return f"{self.file_path}#{self.name}"


class CodeChunker:
    """文件分块器。"""

    def chunk_file(self, file_path: Path) -> list[CodeChunk]:
        """对单个文件分块。读不出来就返回空列表，不抛异常打断整体索引。"""
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            log.warning("read failed for %s: %s", file_path, exc)
            return []

        path_str = str(file_path)
        if file_path.suffix == ".py":
            return self._chunk_python(path_str, content)
        return self._chunk_text(path_str, content)

    # ---------- Python AST 分块 ----------
    def _chunk_python(self, file_path: str, content: str) -> list[CodeChunk]:
        try:
            tree = ast.parse(content)
        except SyntaxError as exc:
            log.warning("python ast parse failed for %s: %s", file_path, exc)
            return self._chunk_text(file_path, content)

        lines = content.splitlines()
        chunks: list[CodeChunk] = []

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                chunks.extend(self._emit_class(file_path, node, lines))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                chunks.append(self._emit_function(file_path, node, lines, qualifier=""))

        # 空模块（只有 import / 常量）：退化到按大小切
        if not chunks:
            return self._chunk_text(file_path, content)
        return chunks

    def _emit_class(
        self, file_path: str, node: ast.ClassDef, lines: list[str]
    ) -> list[CodeChunk]:
        start, end = node.lineno, _end_lineno(node)
        class_header = _extract_lines(lines, start, min(start + 5, end))
        chunks = [CodeChunk.class_chunk(file_path, node.name, class_header, start, end)]

        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                chunks.append(
                    self._emit_function(file_path, child, lines, qualifier=node.name)
                )
        return chunks

    @staticmethod
    def _emit_function(
        file_path: str,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        lines: list[str],
        *,
        qualifier: str,
    ) -> CodeChunk:
        start, end = node.lineno, _end_lineno(node)
        body = _extract_lines(lines, start, end)
        name = f"{qualifier}.{node.name}" if qualifier else node.name
        return CodeChunk.method_chunk(file_path, name, body, start, end)

    # ---------- 按大小切段 ----------
    @staticmethod
    def _chunk_text(file_path: str, content: str) -> list[CodeChunk]:
        if len(content) <= MAX_CHUNK_CHARS:
            return [CodeChunk.file_chunk(file_path, content)]

        chunks: list[CodeChunk] = []
        lines = content.splitlines()
        segment: list[str] = []
        segment_len = 0
        seg_index = 1
        start_line = 1

        for i, line in enumerate(lines, start=1):
            line_len = len(line) + 1  # +1 for "\n"
            if segment and segment_len + line_len > MAX_CHUNK_CHARS:
                chunks.append(CodeChunk(
                    file_path=file_path,
                    chunk_type="file",
                    name=f"{file_path}#{seg_index}",
                    content="\n".join(segment).strip(),
                    start_line=start_line,
                    end_line=i - 1,
                ))
                segment, segment_len = [], 0
                seg_index += 1
                start_line = i
            segment.append(line)
            segment_len += line_len

        if segment:
            chunks.append(CodeChunk(
                file_path=file_path,
                chunk_type="file",
                name=f"{file_path}#{seg_index}",
                content="\n".join(segment).strip(),
                start_line=start_line,
                end_line=len(lines),
            ))
        return chunks


def _end_lineno(node: ast.AST) -> int:
    """ast 节点的结束行号，py 3.8+ 才有 end_lineno。"""
    return getattr(node, "end_lineno", None) or node.lineno


def _extract_lines(lines: list[str], start: int, end: int) -> str:
    """1-based 行号区间，闭区间 [start, end]。"""
    if start < 1:
        start = 1
    if end > len(lines):
        end = len(lines)
    return "\n".join(lines[start - 1:end]).strip()
