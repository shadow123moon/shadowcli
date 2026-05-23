"""Embedding 接入：回调注入 + 内置 mock 实现。

设计简化（对照 Java 版）：
- Java EmbeddingClient 内置 Ollama / OpenAI / 智谱 三种 HTTP 客户端。
- Python 版改用回调注入：EmbedFn = Callable[[str], list[float]]，
  应用层自己决定接 Ollama / OpenAI / SDK 还是 mock。

Pythonic 要点：
- typing.Protocol / Callable 类型签名     替代 Java interface
- 模块级函数                              替代 OkHttp 客户端类
- numpy 向量化                            替代 Java 双重 for 循环
- 默认 mock_embed 让烟雾测试零依赖
"""
from __future__ import annotations

import hashlib
from collections.abc import Callable

import numpy as np

# embedding 维度：与 Ollama nomic-embed-text 维度对齐
DEFAULT_DIM = 768

# 文本截断长度（与 Java 版一致）
MAX_INPUT_CHARS = 2000


# 应用层注入的 embedding 函数：输入文本，输出定长向量
EmbedFn = Callable[[str], list[float]]


def truncate(text: str | None, max_chars: int = MAX_INPUT_CHARS) -> str:
    """安全截断输入文本，避免触发 API 上下文上限。"""
    if not text:
        return ""
    return text[:max_chars] if len(text) > max_chars else text


def mock_embed(text: str, dim: int = DEFAULT_DIM) -> list[float]:
    """确定性 hash 假向量：让烟雾测试不依赖任何 embedding 服务。

    用 sha256 取多段字节当种子生成 0-1 浮点，再 L2 归一化。
    同文本同向量；不同文本几乎正交（保证相似度计算有意义）。
    """
    if not text:
        return [0.0] * dim

    digest = hashlib.sha256(text.encode("utf-8")).digest()
    # 反复 hash 拼出足够长的 byte 流
    buf = bytearray(digest)
    while len(buf) < dim * 4:
        digest = hashlib.sha256(digest).digest()
        buf.extend(digest)

    raw = np.frombuffer(bytes(buf[: dim * 4]), dtype=np.uint32).astype(np.float32)
    vec = (raw / np.iinfo(np.uint32).max) - 0.5  # 中心化到 [-0.5, 0.5]
    norm = np.linalg.norm(vec)
    if norm == 0:
        return [0.0] * dim
    return (vec / norm).tolist()


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """余弦相似度。维度不一致或零向量返回 0.0。"""
    if a.shape != b.shape:
        return 0.0
    na = np.linalg.norm(a)
    nb = np.linalg.norm(b)
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def to_array(vec: list[float] | np.ndarray) -> np.ndarray:
    """统一成 float32 ndarray。"""
    if isinstance(vec, np.ndarray):
        return vec.astype(np.float32, copy=False)
    return np.asarray(vec, dtype=np.float32)
