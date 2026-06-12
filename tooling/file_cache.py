import os
from pathlib import Path
from typing import Dict, Tuple, Optional


class FileCache:
    """会话级文件读取缓存"""

    def __init__(self):
        self._cache: Dict[str, Tuple[str, float]] = {}  # {path: (content, mtime)}

    def should_read(self, path: Path) -> Tuple[bool, Optional[str]]:
        """检查是否需要重新读取文件

        Returns:
            (需要读取?, 缓存提示消息或旧内容?)
        """
        path_str = str(path.resolve())
        if path_str not in self._cache:
            return True, None

        cached_content, cached_mtime = self._cache[path_str]
        try:
            current_mtime = os.path.getmtime(path)
        except OSError:
            # 文件被删除或不可访问
            del self._cache[path_str]
            return True, None

        if current_mtime == cached_mtime:
            # 文件未修改，无需重新读取
            return False, f"[CACHED] {path.name} already in context (unchanged, skip re-read)"

        # 文件已修改，返回旧内容用于增量对比
        return True, cached_content

    def store(self, path: Path, content: str) -> None:
        """缓存文件内容"""
        path_str = str(path.resolve())
        self._cache[path_str] = (content, os.path.getmtime(path))

    def clear(self) -> None:
        """清空缓存"""
        self._cache.clear()


# 全局单例
_file_cache = FileCache()
