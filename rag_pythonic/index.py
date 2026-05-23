"""代码索引编排：遍历项目 → 分块 → 向量化 → 写入 VectorStore。

对照 Java 版：
- Java CodeIndex 接 EmbeddingClient + CodeChunker + CodeAnalyzer，
  这里去掉 CodeAnalyzer（用户选择不做关系图谱），只保留前两个。
- Embedding 来源由调用方注入 embed_fn，跑测试可以用 mock_embed。

Pythonic 要点：
- pathlib.Path.rglob 替代 Files.walkFileTree
- 集合字面量 frozenset(...) 替代 if/equals 长链
- @dataclass(slots=True) for IndexResult     替代 Java record
- 默认参数 progress=None + 内部 _emit 统一调用
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .chunk import CodeChunker
from .embedding import EmbedFn, mock_embed, truncate
from .store import VectorStore

log = logging.getLogger(__name__)

ProgressFn = Callable[[str], None]


# 常见非代码目录：跳过整棵子树
_EXCLUDED_DIRS = frozenset({
    "node_modules", "target", "build", ".git", ".idea", ".vscode",
    "dist", "out", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".venv", "venv", "env",
})

# 支持的代码 / 文档文件扩展名（与 Java 版一致 + Python 习惯）
_INCLUDED_SUFFIXES = frozenset({
    ".py", ".java", ".js", ".ts", ".tsx", ".jsx",
    ".go", ".rs", ".c", ".cpp", ".h", ".hpp", ".kt",
    ".md", ".xml", ".yaml", ".yml", ".json",
    ".properties", ".sh", ".gradle", ".toml",
})


@dataclass(slots=True)
class IndexResult:
    chunk_count: int
    message: str


class CodeIndex:
    """项目级代码索引编排器。"""

    def __init__(
        self,
        embed_fn: EmbedFn | None = None,
        progress: ProgressFn | None = None,
    ):
        """
        :param embed_fn: 应用层注入的 embedding 函数；未指定则用 mock_embed（适合测试）
        :param progress: 进度回调，默认无操作
        """
        self.embed_fn: EmbedFn = embed_fn or mock_embed
        self.chunker = CodeChunker()
        self._progress = progress

    def index(self, project_path: str | Path, store: VectorStore) -> IndexResult:
        """全量索引：清空 store → 遍历 → 分块 → 向量化 → 批量写入。"""
        root = Path(project_path).resolve()
        if not root.exists():
            msg = f"路径不存在: {project_path}"
            self._emit(f"[X] {msg}")
            return IndexResult(0, msg)

        self._emit(f"[索引] 开始: {root}")

        files = list(_collect_files(root))
        self._emit(f"[索引] 发现 {len(files)} 个文件待索引")

        store.clear()
        entries: list[tuple] = []
        total = len(files)

        for processed, file in enumerate(files, start=1):
            if processed % 10 == 0 or processed == total:
                self._emit(f"   进度: {processed}/{total} ({file.name})")
            try:
                chunks = self.chunker.chunk_file(file)
                for chunk in chunks:
                    embedding = self.embed_fn(truncate(chunk.to_embedding_text()))
                    entries.append((chunk, embedding))
            except Exception as exc:
                self._emit(f"   [!] 索引失败: {file} - {exc}")
                log.warning("index failed for %s", file, exc_info=exc)

        store.insert_chunks(entries)
        stats = store.stats()
        msg = f"索引完成: {stats.chunk_count} 个代码块"
        self._emit(f"[v] {msg}")
        return IndexResult(stats.chunk_count, msg)

    def _emit(self, message: str) -> None:
        if self._progress is not None:
            self._progress(message)


def _collect_files(root: Path) -> list[Path]:
    """递归收集需要索引的文件，跳过非代码目录和点号开头的目录。"""
    out: list[Path] = []
    for entry in root.rglob("*"):
        # 跳过有任何父目录命中黑名单的路径
        if any(_is_excluded(part) for part in entry.relative_to(root).parts[:-1]):
            continue
        if not entry.is_file():
            continue
        if entry.suffix.lower() in _INCLUDED_SUFFIXES:
            out.append(entry)
    return out


def _is_excluded(name: str) -> bool:
    return name in _EXCLUDED_DIRS or (name.startswith(".") and name not in {".", ".."})
