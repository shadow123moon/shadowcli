"""rag_pythonic：原 paicli RAG 模块的 Python 简化移植。

公共 API 速查:
    chunk      : CodeChunk / CodeChunker
    embedding  : EmbedFn / mock_embed / cosine_similarity
    store      : VectorStore / SearchResult / IndexStats
    index      : CodeIndex / IndexResult
    retriever  : CodeRetriever
    tokenizer  : tokenize
    formatter  : format_for_cli / format_for_tool / build_summary

最简用法:
    from rag_pythonic import CodeIndex, CodeRetriever, VectorStore, format_for_cli

    store = VectorStore()
    CodeIndex().index("./my_project", store)
    results = CodeRetriever(store).hybrid_search("如何实现拓扑排序", top_k=5)
    print(format_for_cli("如何实现拓扑排序", results))
"""
from .chunk import MAX_CHUNK_CHARS, CodeChunk, CodeChunker
from .embedding import (
    DEFAULT_DIM,
    EmbedFn,
    cosine_similarity,
    mock_embed,
    to_array,
    truncate,
)
from .formatter import build_summary, format_for_cli, format_for_tool
from .index import CodeIndex, IndexResult
from .retriever import CodeRetriever
from .store import IndexStats, SearchResult, VectorStore
from .tokenizer import tokenize

__all__ = [
    # chunk
    "CodeChunk",
    "CodeChunker",
    "MAX_CHUNK_CHARS",
    # embedding
    "EmbedFn",
    "DEFAULT_DIM",
    "mock_embed",
    "cosine_similarity",
    "to_array",
    "truncate",
    # store
    "VectorStore",
    "SearchResult",
    "IndexStats",
    # index
    "CodeIndex",
    "IndexResult",
    # retriever
    "CodeRetriever",
    # tokenizer
    "tokenize",
    # formatter
    "format_for_cli",
    "format_for_tool",
    "build_summary",
]
