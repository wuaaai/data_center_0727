"""
目录/附录/前言过滤模块：从 minerU 解析结果中识别并移除非正文页面。
"""

import re

from chunking.text_utils import (
    _extract_text,
    _extract_table_html,
    _SKIP_TYPES,
    _TITLE_TYPES,
)
from chunking.image_analyzer import (
    IMAGE_TYPES,
    TABLE_TYPES,
)

# 目录条目标志：第X章/第X节 开头的短文本
_TOC_CHAPTER_RE = re.compile(r'^\s*第[一二三四五六七八九十百千\d]+[章编节]')
# 正文条目标志：第X条/第X款 开头（非目录）
_BODY_ARTICLE_RE = re.compile(r'^\s*第[一二三四五六七八九十百千\d]+[条款项目]')


def _is_toc_entry_text(text: str, btype: str) -> bool:
    """判断一个 block 是否为目录条目（而非正文）。"""
    text = text.strip()
    if not text:
        return False
    if btype in _TITLE_TYPES:
        return True
    if len(text) < 30 and ('…' in text or '……' in text):
        return True
    if _TOC_CHAPTER_RE.match(text) and len(text) < 25:
        return True
    return False


def _filter_toc_blocks(pages: list[list[dict]], toc_page: int) -> list[list[dict]]:
    """目录与正文同页时，只删目录区域 block，保留后面的正文。"""
    blocks = pages[toc_page]
    result: list[dict] = []
    in_toc = False
    backtrack_title: dict | None = None

    for block in blocks:
        text = _extract_text(block).strip()
        btype = (block.get("type", "") or "").strip().lower()

        if not in_toc:
            if len(text) <= 15 and any(
                kw in text for kw in ["目录", "目 录", "CONTENTS"]
            ):
                in_toc = True
                continue
            result.append(block)
            continue

        if btype in _SKIP_TYPES:
            continue

        if btype in ("list", "text_list", "index", "image", "image_body",
                      "image_caption", "chart", "table"):
            continue

        if btype not in _TITLE_TYPES:
            text_len = len(text)

            if text_len > 80:
                in_toc = False
                if backtrack_title is not None:
                    result.append(backtrack_title)
                result.append(block)
                continue

            if _BODY_ARTICLE_RE.match(text):
                in_toc = False
                if backtrack_title is not None:
                    result.append(backtrack_title)
                result.append(block)
                continue

            if not _is_toc_entry_text(text, btype) and text_len > 15:
                in_toc = False
                if backtrack_title is not None:
                    result.append(backtrack_title)
                result.append(block)
                continue

        if btype in _TITLE_TYPES:
            backtrack_title = block
        elif _TOC_CHAPTER_RE.match(text) and len(text) < 25:
            pass

    if in_toc:
        pages[toc_page] = []
        return pages

    pages[toc_page] = result
    return pages


def _flatten_blocks(content_list: list) -> list[tuple[int, dict]]:
    """将 page-based 或 block-based content_list 展平为 (page_num, block) 列表。"""
    flat: list[tuple[int, dict]] = []
    if not content_list:
        return flat
    first = content_list[0]
    if isinstance(first, list):
        for page_idx, page_blocks in enumerate(content_list, start=1):
            for block in page_blocks:
                if isinstance(block, dict):
                    flat.append((page_idx, block))
    elif isinstance(first, dict):
        for block in content_list:
            if isinstance(block, dict):
                page_num = block.get("page_num", 0) or block.get("page_idx", 0) or 0
                flat.append((page_num, block))
    return flat


def _has_substantial_block(blocks: list[dict]) -> bool:
    """判断页面块列表中是否包含实质正文内容。"""
    for block in blocks:
        btype = (block.get("type", "") or "").strip().lower()
        if btype in _SKIP_TYPES:
            continue
        if btype in IMAGE_TYPES:
            continue
        if btype in TABLE_TYPES:
            html = _extract_table_html(block)
            if len(html) > 30:
                return True
            continue
        text = _extract_text(block)
        if btype in _TITLE_TYPES:
            if any(kw in text for kw in ["目录", "目 录", "CONTENTS", "前言", "FOREWORD"]):
                continue
            if len(text) >= 2:
                return True
            continue
        if len(text) > 30:
            return True
    return False


def _find_toc_page(pages: list[list[dict]], max_search: int = 6) -> int:
    """在页面列表中查找目录页，返回页码索引，未找到返回 -1。"""
    for page_idx in range(min(max_search, len(pages))):
        for block in pages[page_idx]:
            text = _extract_text(block)
            if any(kw in text for kw in ["目录", "目 录", "CONTENTS"]):
                return page_idx
    return -1


def _find_appendix_page(pages: list[list[dict]], max_search: int = 8) -> int:
    """在页面列表中查找附录页，返回页码索引，未找到返回 -1。"""
    total = len(pages)
    for page_idx in range(total - 1, max(0, total - max_search) - 1, -1):
        for block in pages[page_idx]:
            text = _extract_text(block)
            if "附录" in text:
                return page_idx
    return -1


def _blocks_to_pages(blocks: list[dict]) -> list[list[dict]]:
    """将 block-based 格式转换为 page-based 格式。"""
    pages_map: dict[int, list[dict]] = {}
    for block in blocks:
        page_num = block.get("page_num", 0) or block.get("page_idx", 0) or 0
        pages_map.setdefault(page_num, []).append(block)
    return [pages_map[k] for k in sorted(pages_map.keys())]


def _filter_front_back_matter(
    content_list: list,
) -> tuple[list, str]:
    """过滤前言/目录页和附录页，返回 (过滤后的 content_list, 文档标题)。"""
    if not isinstance(content_list, list) or not content_list:
        return content_list, ""

    first = content_list[0]
    input_is_page_based = isinstance(first, list)

    if input_is_page_based:
        pages = content_list
    elif isinstance(first, dict):
        pages = _blocks_to_pages(content_list)
    else:
        return content_list, ""

    total_pages = len(pages)
    if total_pages == 0:
        return content_list, ""

    toc_page = _find_toc_page(pages)

    first_keep = 0
    if toc_page >= 0:
        pages = _filter_toc_blocks(pages, toc_page)
        if not pages[toc_page]:
            first_keep = toc_page + 1
        else:
            first_keep = toc_page
        while first_keep < total_pages and not _has_substantial_block(pages[first_keep]):
            first_keep += 1
    else:
        for page_idx in range(min(5, total_pages)):
            if _has_substantial_block(pages[page_idx]):
                first_keep = page_idx
                break

    appendix_page = _find_appendix_page(pages)
    last_keep = appendix_page if appendix_page >= 0 else total_pages
    if first_keep >= last_keep:
        first_keep = min(1, total_pages)

    filtered_pages = pages[first_keep:last_keep]

    doc_title = ""
    for page_blocks in filtered_pages:
        for block in page_blocks:
            block_type = (block.get("type", "") or "").strip().lower()
            if block_type in _TITLE_TYPES:
                doc_title = _extract_text(block)
                break
        if doc_title:
            break

    if input_is_page_based:
        return filtered_pages, doc_title
    else:
        filtered_blocks: list[dict] = []
        for page_blocks in filtered_pages:
            filtered_blocks.extend(page_blocks)
        return filtered_blocks, doc_title
