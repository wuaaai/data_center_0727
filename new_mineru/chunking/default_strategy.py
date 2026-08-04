"""
默认分块策略：将 minerU 解析的结构化内容按父子关系分块，
使用 *** 分隔父块（部分/章节），<-split-> 分隔子块（段落）。

提供：
  - TextChunk / ChunkResult 数据结构
  - chunk_content_list(): 旧 API（兼容包装）
  - chunks_to_paragraphs(): 旧 API（兼容包装）
  - DefaultChunkingStrategy: 可插拔分块策略
"""

from dataclasses import dataclass, field
from typing import Optional

from tqdm import tqdm

from config import (
    PARENT_SPLIT_MARKER,
    SPLIT_MARKER,
    INCLUDE_IMAGES,
    TITLE_PARENT_HEIGHT_RATIO,
    TITLE_PARENT_MIN_HEIGHT,
    MERGE_ALL_PARAGRAPHS,
    TEXT_MERGE_MIN_LENGTH,
    MAX_SUB_BLOCK_TOKENS,
)

from chunking.text_utils import (
    _extract_text,
    _extract_table_html,
    _parse_table_rows,
    _get_title_level,
    _estimate_tokens,
    _split_text_by_token_limit,
    _is_sentence_end,
    _is_sub_heading_merged,
    _is_list_item,
    _SKIP_TYPES,
    _TITLE_TYPES,
    fix_wordart_percent_ordering,
)

from chunking.toc_filter import (
    _filter_front_back_matter,
    _flatten_blocks,
)

from chunking.spatial_merge import (
    _merge_spatial_text_to_images,
)

from chunking.image_analyzer import (
    IMAGE_TYPES,
    FIGURE_TYPES,
    TABLE_TYPES,
    extract_image_path,
    extract_caption_text,
    merge_caption_to_prev_image,
    make_image_entry,
    precompute_llm_decisions,
    process_image_block,
)

from chunking.strategy import ChunkingStrategy, ChunkContext


# ======================================================================
# 数据结构
# ======================================================================

@dataclass
class TextChunk:
    """一个文本块，包含父级（标题/摘要）和子级（详细内容）。"""
    parent: str = ""
    child: str = ""  # 纯文本 str 或含图片 dict 的 list
    parent_type: str = ""
    level: int = 0
    page_num: int = 0

    @property
    def is_empty(self) -> bool:
        parent_ok = bool(self.parent.strip())
        if isinstance(self.child, str):
            child_ok = bool(self.child.strip())
        else:
            child_ok = bool(self.child)
        return not parent_ok and not child_ok

    @property
    def has_child(self) -> bool:
        if isinstance(self.child, str):
            return bool(self.child.strip())
        for item in self.child:
            if isinstance(item, str):
                if item.strip():
                    return True
            elif isinstance(item, dict) and item.get("type") == "image":
                if item.get("path") or item.get("caption"):
                    return True
            elif item:
                return True
        return False


@dataclass
class ChunkResult:
    chunks: list[TextChunk] = field(default_factory=list)
    doc_title: str = ""
    total_pages: int = 0


# ======================================================================
# 父级标题阈值计算
# ======================================================================

def _compute_parent_threshold(flat_blocks: list[tuple[int, dict]]) -> float:
    """根据所有标题 bbox 高度计算父级标题阈值。"""
    heights: list[float] = []
    for _, block in flat_blocks:
        block_type = (block.get("type", "") or "").strip().lower()
        if block_type not in _TITLE_TYPES:
            if not (block_type == "text" and "text_level" in block):
                continue
        bbox = block.get("bbox")
        if not bbox or len(bbox) != 4:
            continue
        h = bbox[3] - bbox[1]
        if h > 0:
            heights.append(float(h))

    if len(heights) < 3:
        return -1.0

    heights.sort()
    median = heights[len(heights) // 2]
    threshold = max(median * TITLE_PARENT_HEIGHT_RATIO, TITLE_PARENT_MIN_HEIGHT)

    unique_heights = len(set(heights))
    if unique_heights <= 1:
        return -1.0

    parent_count = sum(1 for h in heights if h >= threshold)
    if parent_count == 0:
        return -1.0

    return threshold


# ======================================================================
# 分块核心逻辑
# ======================================================================

def _flush_chunk(
    result: ChunkResult,
    pending_parent: Optional[TextChunk],
    child_parts: list,
) -> None:
    if pending_parent is None:
        return

    cleaned_parts: list = []
    for p in child_parts:
        if isinstance(p, dict) and p.get("type") == "image":
            if p.get("path") or p.get("caption"):
                cleaned_parts.append(p)
        else:
            cleaned_parts.append(p)

    has_images = any(isinstance(p, dict) and p.get("type") == "image" for p in cleaned_parts)
    if has_images:
        pending_parent.child = cleaned_parts
    else:
        raw_text = "\n".join(
            p for p in cleaned_parts if isinstance(p, str)
        ).strip()

        pending_parent.child = fix_wordart_percent_ordering(raw_text)

    if not pending_parent.is_empty:
        result.chunks.append(pending_parent)


def _fallback_chunking(content_list: list) -> ChunkResult:
    result = ChunkResult()
    page_texts: dict[int, list[str]] = {}

    for page_num, block in _flatten_blocks(content_list):
        block_type = (block.get("type", "") or "").strip().lower()
        if block_type in _SKIP_TYPES:
            continue
        text = _extract_text(block)
        if not text:
            continue
        if block_type in _TITLE_TYPES and not result.doc_title:
            result.doc_title = text
            continue
        if page_num not in page_texts:
            page_texts[page_num] = []
        page_texts[page_num].append(text)

    for page_num in sorted(page_texts.keys()):
        paragraphs = page_texts[page_num]
        if not paragraphs:
            continue
        parent = paragraphs[0]
        child = "\n".join(paragraphs[1:]) if len(paragraphs) > 1 else ""
        chunk = TextChunk(
            parent=parent, child=child,
            parent_type="paragraph", level=2, page_num=page_num,
        )
        if not chunk.is_empty:
            result.chunks.append(chunk)

    result.total_pages = max(page_texts.keys()) if page_texts else 0
    return result


def _merge_small_chunks(
    chunks: list[TextChunk],
    min_child_length: int = 10,
) -> list[TextChunk]:
    """合并子级内容过短的 chunks。"""
    if len(chunks) <= 1:
        return chunks

    merged: list[TextChunk] = []
    i = 0
    while i < len(chunks):
        current = chunks[i]
        nxt = chunks[i + 1] if i + 1 < len(chunks) else None
        child_is_empty = not current.has_child

        if child_is_empty and nxt is not None:
            if nxt.child:
                if isinstance(nxt.child, str):
                    new_child = current.parent + "\n" + nxt.child
                else:
                    new_child = [current.parent] + (
                        nxt.child if isinstance(nxt.child, list) else [nxt.child]
                    )
            else:
                new_child = current.parent
                nxt.parent = current.parent

            merged.append(TextChunk(
                parent=nxt.parent,
                child=new_child,
                parent_type=nxt.parent_type,
                level=nxt.level,
                page_num=nxt.page_num,
            ))
            i += 2
        else:
            merged.append(current)
            i += 1
    return merged


def chunk_content_list(
    content_list: list,
    pdf_stem: str = "",
) -> ChunkResult:
    """将 minerU 内容列表分块为父子文本对。"""
    desc = f"  分块 {pdf_stem}" if pdf_stem else "  文本分块"
    result = ChunkResult()
    pending_parent: Optional[TextChunk] = None
    child_parts: list = []
    max_page = 0

    # 从原始内容中提取文档标题（过滤前）
    for page_blocks in content_list if isinstance(content_list[0], list) else [content_list]:
        if isinstance(page_blocks, list):
            for block in page_blocks:
                if isinstance(block, dict):
                    block_type = (block.get("type", "") or "").strip().lower()
                    if block_type in _TITLE_TYPES:
                        text = _extract_text(block)
                        if text and text not in ("目录", "目 录", "CONTENTS", "附", "录"):
                            result.doc_title = text
                            break
                if result.doc_title:
                    break
        if result.doc_title:
            break

    content_list, extracted_title = _filter_front_back_matter(content_list)
    if extracted_title and not result.doc_title:
        result.doc_title = extracted_title

    flat_blocks = _flatten_blocks(content_list)
    _merge_spatial_text_to_images(flat_blocks)
    parent_threshold = _compute_parent_threshold(flat_blocks)
    llm_decisions = precompute_llm_decisions(flat_blocks)

    pbar = tqdm(
        flat_blocks,
        desc=desc,
        unit="块",
        ncols=100,
        bar_format="{desc}: {percentage:3.0f}% |{bar}| {n_fmt}/{total_fmt}",
    )

    gidx = -1
    last_added_is_sub_heading = False
    list_buf: list[str] = []

    def _flush_list_buf():
        nonlocal list_buf
        if list_buf:
            child_parts.append("\n".join(list_buf))
            list_buf = []

    _LIST_TYPES = {"list", "text_list"}

    for page_num, block in pbar:
        gidx += 1
        if page_num > max_page:
            max_page = page_num

        block_type = (block.get("type", "") or "").strip().lower()

        if block_type in _SKIP_TYPES:
            continue

        if block.get("_spatial_merged"):
            continue

        text = _extract_text(block)

        # --- 处理 title 块 ---
        is_title = block_type in _TITLE_TYPES or (
            block_type == "text" and "text_level" in block
        )
        if is_title:
            if text and len(text) <= 1:
                continue

            title_level = _get_title_level(block)

            if not result.doc_title:
                result.doc_title = text
                continue

            bbox = block.get("bbox")
            title_height = (bbox[3] - bbox[1]) if (bbox and len(bbox) == 4) else 0

            if parent_threshold > 0 and title_height < parent_threshold:
                if text:
                    _flush_list_buf()
                    child_parts.append(text)
                    last_added_is_sub_heading = True
                    if pending_parent is None:
                        pending_parent = TextChunk(
                            parent=text,
                            parent_type="sub_title",
                            level=title_level,
                            page_num=page_num,
                        )
                        child_parts = []
                        last_added_is_sub_heading = False
                continue

            _flush_list_buf()
            _flush_chunk(result, pending_parent, child_parts)

            pending_parent = TextChunk(
                parent=text,
                parent_type="title",
                level=title_level,
                page_num=page_num,
            )
            child_parts = []
            last_added_is_sub_heading = False
            continue

        # --- 跳过无文本的非结构化块 ---
        if not text and block_type not in FIGURE_TYPES:
            _flush_list_buf()
            continue

        # --- 处理图表块 ---
        _flush_list_buf()
        if block_type in FIGURE_TYPES:

            img_path = extract_image_path(block)
            has_table_html = bool(_extract_table_html(block)) if block_type in TABLE_TYPES else False
            caption_text = extract_caption_text(block) or _extract_text(block)

            if not img_path and not has_table_html:
                if caption_text:
                    merge_caption_to_prev_image(caption_text, child_parts)
                continue

            if block_type in IMAGE_TYPES:
                action, entries = process_image_block(
                    block, global_idx=gidx, mode=INCLUDE_IMAGES,
                    llm_decisions=llm_decisions,
                )
                if action == "discard":
                    continue
                if action in ("text_only", "caption_only"):
                    child_parts.extend(entries)
                    continue

            if block_type in TABLE_TYPES:
                caption = extract_caption_text(block)

                rows = _parse_table_rows(block)
                if rows:
                    if caption:
                        child_parts.append(f"[表] {caption}")
                    for row_text in rows:
                        child_parts.append(row_text)

                    if pending_parent is None:
                        parent_text = caption or rows[0]
                        pending_parent = TextChunk(
                            parent=parent_text,
                            parent_type="table",
                            level=2,
                            page_num=page_num,
                        )
                else:
                    child_parts.append(make_image_entry(block))
                continue

            child_parts.append(make_image_entry(block))
            continue

        # --- 处理正文 ---
        if text:
            if block_type in _LIST_TYPES:
                last_added_is_sub_heading = False
                list_buf.append(text)
                if pending_parent is None:
                    pending_parent = TextChunk(
                        parent=text, parent_type="list", level=2, page_num=page_num,
                    )
                    child_parts = []
                continue

            _flush_list_buf()

            if last_added_is_sub_heading and child_parts and isinstance(child_parts[-1], str):
                combined = child_parts[-1] + "\n" + text
                if _estimate_tokens(combined) <= MAX_SUB_BLOCK_TOKENS:
                    child_parts[-1] = combined
                else:
                    child_parts.append(text)
            else:
                if MERGE_ALL_PARAGRAPHS:
                    should_merge = (
                        child_parts
                        and isinstance(child_parts[-1], str)
                    )
                else:
                    should_merge = (
                        child_parts
                        and isinstance(child_parts[-1], str)
                        and len(child_parts[-1]) >= TEXT_MERGE_MIN_LENGTH
                        and not _is_sentence_end(child_parts[-1])
                    )
                if should_merge:
                    combined = child_parts[-1] + text
                    if _estimate_tokens(combined) <= MAX_SUB_BLOCK_TOKENS:
                        child_parts[-1] = combined
                    else:
                        child_parts.append(text)
                else:
                    child_parts.append(text)
            last_added_is_sub_heading = False

            if pending_parent is None:
                pending_parent = TextChunk(
                    parent=text,
                    parent_type="paragraph",
                    level=2,
                    page_num=page_num,
                )
                child_parts = []

    pbar.close()

    _flush_list_buf()
    _flush_chunk(result, pending_parent, child_parts)

    result.total_pages = max_page

    if not result.chunks:
        result = _fallback_chunking(content_list)

    result.chunks = _merge_small_chunks(result.chunks)

    return result


# ======================================================================
# Chunk → Paragraph 转换
# ======================================================================

def _map_parent_style(chunk: TextChunk) -> str:
    if chunk.level == 0:
        return "Title"
    if chunk.level == 1:
        return "Heading 2"
    return "Heading 3"


def chunks_to_paragraphs(
    chunks: list[TextChunk],
    pdf_stem: str = "",
) -> list[dict]:
    """将分块结果转换为 DOCX 段落数据（含 *** / <-split-> 标记）。"""
    desc = f"  生成段落 {pdf_stem}" if pdf_stem else "  生成段落"
    paragraphs: list[dict] = []

    pbar = tqdm(
        chunks,
        desc=desc,
        unit="块",
        ncols=100,
        bar_format="{desc}: {percentage:3.0f}% |{bar}| {n_fmt}/{total_fmt}",
    )

    for chunk in pbar:
        if chunk.parent:
            paragraphs.append({
                "text": PARENT_SPLIT_MARKER,
                "style": "Normal",
                "level": 0,
            })

            style = _map_parent_style(chunk)
            paragraphs.append({
                "text": chunk.parent,
                "style": style,
                "level": chunk.level,
            })

        paragraphs.append({
            "text": SPLIT_MARKER,
            "style": "Normal",
            "level": 0,
        })

        if chunk.child:
            if isinstance(chunk.child, list):
                child_items = chunk.child
            else:
                child_items = chunk.child.split("\n")

            for i, line in enumerate(child_items):
                if isinstance(line, dict) and line.get("type") == "image":
                    paragraphs.append({
                        "text": line.get("caption", ""),
                        "style": "Normal",
                        "level": 0,
                        "image": line,
                    })
                else:
                    line_str = line if isinstance(line, str) else ""
                    line_str = line_str.strip()
                    if not line_str:
                        continue
                    sub_parts = _split_text_by_token_limit(line_str, MAX_SUB_BLOCK_TOKENS)
                    for j, part in enumerate(sub_parts):
                        paragraphs.append({
                            "text": part,
                            "style": "Normal",
                            "level": 0,
                        })
                        if j + 1 < len(sub_parts):
                            paragraphs.append({
                                "text": SPLIT_MARKER,
                                "style": "Normal",
                                "level": 0,
                            })

                if i + 1 < len(child_items):
                    nxt = child_items[i + 1]
                    if isinstance(nxt, dict) and nxt.get("type") == "image":
                        continue
                    if isinstance(line, str) and isinstance(nxt, str):
                        if _is_sub_heading_merged(line):
                            continue
                        if _is_list_item(line) and _is_list_item(nxt):
                            continue

                paragraphs.append({
                    "text": SPLIT_MARKER,
                    "style": "Normal",
                    "level": 0,
                })

    pbar.close()
    return paragraphs


# ======================================================================
# DefaultChunkingStrategy（可插拔实现）
# ======================================================================

class DefaultChunkingStrategy(ChunkingStrategy):
    """默认分块策略。

    pipeline.py 在 default 策略时直接使用旧函数
    (chunk_content_list + chunks_to_paragraphs / parse_*_fast)，
    此 chunk() 方法不会被调用。
    """

    @property
    def name(self) -> str:
        return "default"

    def chunk(
        self,
        paragraphs: list[dict],
        context: Optional[ChunkContext] = None,
    ) -> list[dict]:
        raise NotImplementedError(
            "default 策略不走 chunk() 接口，"
            "pipeline.py 直接调用旧函数 chunk_content_list+chunks_to_paragraphs"
        )


# 空标题块合并（复用 fast_pdf_parser 的实现，避免重复）
from chunking._merge import _merge_empty_heading_blocks


# ======================================================================
# NoChunkingStrategy（无分块，直接输出干净段落）
# ======================================================================

class NoChunkingStrategy(ChunkingStrategy):
    """无分块策略：直接返回干净段落，不插入任何标记。

    用于需要纯格式化 DOCX 的场景（无 *** / <-split-> 标记）。
    """

    @property
    def name(self) -> str:
        return "none"

    def chunk(
        self,
        paragraphs: list[dict],
        context: Optional[ChunkContext] = None,
    ) -> list[dict]:
        """直接返回输入段落，不做任何分块处理。"""
        return list(paragraphs)
