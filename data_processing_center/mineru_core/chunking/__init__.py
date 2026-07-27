"""
分块策略包：将干净段落转换为带标记（*** / <-split->）的分块段落。

提供可插拔的分块策略接口，支持通过配置或 CLI 一键替换策略。

导出：
  - strategy:       ChunkingStrategy ABC, ChunkContext, 注册表
  - default_strategy: DefaultChunkingStrategy, TextChunk, ChunkResult,
                      chunk_content_list(), chunks_to_paragraphs()
  - text_utils:     文本清洗, token 估算, 规则/LLM 拆分
  - toc_filter:     目录/附录/前言过滤
  - spatial_merge:  空间文本-图片合并
  - image_analyzer: 图片分类与过滤
"""

from chunking.strategy import (
    ChunkingStrategy,
    ChunkContext,
    register_strategy,
    get_strategy,
    list_strategies,
)

# 注册内置策略（在导入时自动完成）
from chunking.default_strategy import DefaultChunkingStrategy, NoChunkingStrategy
from chunking.unstructured_strategy import UnstructuredChunkingStrategy
register_strategy("default", DefaultChunkingStrategy)
register_strategy("none", NoChunkingStrategy)
register_strategy("unstructured", UnstructuredChunkingStrategy)
