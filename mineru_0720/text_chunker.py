"""
【兼容性重导出】此模块已拆分为 chunking 包下的多个模块。

主要导出:
  chunking.default_strategy: TextChunk, ChunkResult, chunk_content_list, chunks_to_paragraphs
  chunking.text_utils:       clean_text, _estimate_tokens, _split_text_by_token_limit, _is_sentence_end, ...
  chunking.toc_filter:       _filter_front_back_matter, _flatten_blocks, ...
  chunking.spatial_merge:    _merge_spatial_text_to_images

请改用: from chunking import ...
"""
# 核心数据结构 & 分块函数
from chunking.default_strategy import (
    TextChunk,
    ChunkResult,
    chunk_content_list,
    chunks_to_paragraphs,
)

# 文本处理工具
from chunking.text_utils import (
    clean_text,
    fix_wordart_percent_ordering,
    _estimate_tokens,
    _split_text_by_token_limit,
    _split_by_rules,
    _is_sentence_end,
    _is_sub_heading_merged,
    _is_list_item,
    _extract_text,
    _extract_table_html,
    _parse_table_rows,
    _get_title_level,
    _SKIP_TYPES,
    _TITLE_TYPES,
)

# 目录/附录过滤
from chunking.toc_filter import (
    _filter_front_back_matter,
    _filter_toc_blocks,
    _flatten_blocks,
    _has_substantial_block,
    _find_toc_page,
    _find_appendix_page,
    _blocks_to_pages,
)

# 空间合并
from chunking.spatial_merge import (
    _merge_spatial_text_to_images,
)
