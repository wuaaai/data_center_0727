"""
PDF 解析模块：使用 minerU 将 PDF 转换为结构化 JSON 内容。
"""

import json
import os
import sys
from pathlib import Path
from typing import Optional

from loguru import logger

# 确保项目根目录在 sys.path 中
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import (
    BACKEND,
    PARSE_METHOD,
    LANG,
    FORMULA_ENABLE,
    TABLE_ENABLE,
    DUMP_MIDDLE_JSON,
    DUMP_CONTENT_LIST,
    START_PAGE_ID,
    END_PAGE_ID,
    OUTPUT_DIR,
    # VLM_SERVER_URL,  # pipeline 模式下不需要
)


def parse_pdf(
    pdf_path: Path,
    output_dir: Optional[Path] = None,
    backend: str = BACKEND,
    parse_method: str = PARSE_METHOD,
    lang: str = LANG,
    formula_enable: bool = FORMULA_ENABLE,
    table_enable: bool = TABLE_ENABLE,
    start_page_id: int = START_PAGE_ID,
    end_page_id: Optional[int] = END_PAGE_ID,
    server_url: Optional[str] = None,
) -> Path:
    """
    使用 minerU 解析 PDF，输出到指定目录。

    返回解析结果目录路径，其中包含:
      - {stem}.md           markdown 文件
      - {stem}_content_list_v2.json  结构化内容列表
      - {stem}_middle.json  中间 JSON（含布局信息）
      - images/             提取的图片

    Parameters
    ----------
    pdf_path : Path
        PDF 文件路径。
    output_dir : Path, optional
        输出根目录，默认使用 config.OUTPUT_DIR。
    backend : str
        minerU 后端引擎。
    parse_method : str
        解析方法。
    lang : str
        文档语言代码。
    formula_enable : bool
        是否启用公式识别。
    table_enable : bool
        是否启用表格识别。
    start_page_id : int
        起始页（0-based）。
    end_page_id : int, optional
        结束页（0-based，None 表示最后一页）。

    Returns
    -------
    Path
        该 PDF 的解析输出子目录。
    """
    if output_dir is None:
        output_dir = OUTPUT_DIR

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF 文件不存在: {pdf_path}")
    if pdf_path.suffix.lower() != ".pdf":
        raise ValueError(f"仅支持 PDF 文件，收到: {pdf_path.suffix}")

    pdf_stem = pdf_path.stem

    logger.info(f"开始解析 PDF: {pdf_path.name}")
    logger.info(f"  后端: {backend}, 方法: {parse_method}, 语言: {lang}")

    # 读取 PDF 字节
    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()

    # 动态导入避免 torch DLL 问题阻塞其他模块
    try:
        from mineru.cli.common import do_parse
    except ImportError as e:
        logger.error(f"无法导入 minerU: {e}")
        raise

    # # 设置远程 VLM 服务器环境变量（pipeline 模式下不需要）
    # if server_url:
    #     os.environ["MINERU_VL_SERVER"] = server_url
    #     logger.info(f"  使用远程 VLM 服务器: {server_url}")

    try:
        do_parse(
            output_dir=str(output_dir),
            pdf_file_names=[pdf_stem],
            pdf_bytes_list=[pdf_bytes],
            p_lang_list=[lang],
            backend=backend,
            parse_method=parse_method,
            formula_enable=formula_enable,
            table_enable=table_enable,
            server_url=server_url,
            f_draw_layout_bbox=False,
            f_draw_span_bbox=False,
            f_dump_md=True,
            f_dump_middle_json=DUMP_MIDDLE_JSON,
            f_dump_model_output=False,
            f_dump_orig_pdf=False,
            f_dump_content_list=DUMP_CONTENT_LIST,
            start_page_id=start_page_id,
            end_page_id=end_page_id,
        )
    except Exception as e:
        logger.error(f"PDF 解析失败: {e}")
        raise

    # 定位输出子目录
    # minerU 不同 backend 输出到不同子目录:
    #   pipeline → {stem}/{parse_method}/
    #   vlm*     → {stem}/vlm/          (mineru 内部硬编码)
    #   hybrid*  → {stem}/hybrid_{parse_method}/
    #   office   → {stem}/office/
    # VLM 路径优先，因为 vlm-http-client 是最常用的远程后端
    if backend.startswith("vlm-"):
        _expected_subdir = "vlm"
    elif backend.startswith("hybrid-"):
        _expected_subdir = f"hybrid_{parse_method}"
    else:
        _expected_subdir = parse_method

    possible_dirs = [
        output_dir / pdf_stem / _expected_subdir,
        output_dir / pdf_stem / parse_method,
        output_dir / pdf_stem / f"hybrid_{parse_method}",
        output_dir / pdf_stem / "vlm",
        output_dir / pdf_stem / "office",
    ]
    # 去重
    seen = set()
    unique_dirs = []
    for d in possible_dirs:
        if str(d) not in seen:
            seen.add(str(d))
            unique_dirs.append(d)

    # 优先选择包含 content_list 的目录，其次选存在的目录
    result_dir = None
    for d in unique_dirs:
        v2 = d / f"{pdf_stem}_content_list_v2.json"
        v1 = d / f"{pdf_stem}_content_list.json"
        if v2.exists() or v1.exists():
            result_dir = d
            break

    if result_dir is None:
        for d in unique_dirs:
            if d.exists():
                result_dir = d
                break

    if result_dir is None:
        logger.warning(f"未找到解析输出目录，尝试过: {possible_dirs}")
        result_dir = output_dir / pdf_stem

    logger.info(f"PDF 解析完成，输出目录: {result_dir}")
    return result_dir


def load_content_list(parse_dir: Path, pdf_stem: str) -> list[dict]:
    """
    加载 minerU 解析生成的内容列表。

    优先加载 content_list_v2.json（更精细的块分类），
    回退到 content_list.json。
    """
    v2_path = parse_dir / f"{pdf_stem}_content_list_v2.json"
    v1_path = parse_dir / f"{pdf_stem}_content_list.json"

    for path in (v2_path, v1_path):
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            logger.info(f"加载内容列表: {path} ({len(data)} 块)")
            return data

    raise FileNotFoundError(
        f"未找到内容列表文件，尝试过: {v2_path}, {v1_path}"
    )


def load_middle_json(parse_dir: Path, pdf_stem: str) -> dict:
    """加载 minerU 中间 JSON（含 pdf_info 布局信息）。"""
    path = parse_dir / f"{pdf_stem}_middle.json"
    if not path.exists():
        raise FileNotFoundError(f"未找到 middle JSON: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ======================================================================
# content_list → 干净段落（无分块标记）
# ======================================================================

def content_list_to_clean_paragraphs(
    content_list: list,
    pdf_stem: str = "",
) -> tuple[list[dict], str, int]:
    """将 minerU 内容列表转换为干净段落（无 *** / <-split-> 标记）。

    干净段落由后续的分块策略统一插入标记，实现解析与分块解耦。

    Returns
    -------
    tuple[list[dict], str, int]
        (clean_paragraphs, doc_title, total_pages)
        每个段落 dict: {"text": str, "style": str, "level": int, "image": optional dict}
    """
    from tqdm import tqdm

    from chunking.text_utils import (
        _extract_text, _extract_table_html, _parse_table_rows,
        _get_title_level, _SKIP_TYPES, _TITLE_TYPES,
    )
    from chunking.toc_filter import _filter_front_back_matter, _flatten_blocks
    from chunking.spatial_merge import _merge_spatial_text_to_images
    from chunking.image_analyzer import (
        IMAGE_TYPES, FIGURE_TYPES, TABLE_TYPES,
        extract_image_path, extract_caption_text,
        merge_caption_to_prev_image, make_image_entry,
        precompute_llm_decisions, process_image_block,
    )
    from chunking.default_strategy import _compute_parent_threshold
    from config import INCLUDE_IMAGES, MAX_SUB_BLOCK_TOKENS

    desc = f"  解析 {pdf_stem}" if pdf_stem else "  解析"
    doc_title = ""
    paragraphs: list[dict] = []

    # 从原始内容中提取文档标题
    for page_blocks in content_list if isinstance(content_list[0], list) else [content_list]:
        if isinstance(page_blocks, list):
            for block in page_blocks:
                if isinstance(block, dict):
                    block_type = (block.get("type", "") or "").strip().lower()
                    if block_type in _TITLE_TYPES:
                        text = _extract_text(block)
                        if text and text not in ("目录", "目 录", "CONTENTS", "附", "录"):
                            doc_title = text
                            break
                if doc_title:
                    break
        if doc_title:
            break

    # 过滤目录/附录
    content_list, extracted_title = _filter_front_back_matter(content_list)
    if extracted_title and not doc_title:
        doc_title = extracted_title

    flat_blocks = _flatten_blocks(content_list)
    _merge_spatial_text_to_images(flat_blocks)
    parent_threshold = _compute_parent_threshold(flat_blocks)
    llm_decisions = precompute_llm_decisions(flat_blocks)

    max_page = 0
    pending_body: list[str] = []  # 缓冲同一样式下的连续正文
    _LIST_TYPES = {"list", "text_list"}

    pbar = tqdm(
        flat_blocks, desc=desc, unit="块", ncols=100,
        bar_format="{desc}: {percentage:3.0f}% |{bar}| {n_fmt}/{total_fmt}",
    )

    gidx = -1

    def _flush_body():
        nonlocal pending_body
        if pending_body:
            merged = "\n".join(pending_body)
            paragraphs.append({
                "text": merged,
                "style": "Normal",
                "level": 0,
            })
            pending_body = []

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

        # --- 标题块 ---
        is_title = block_type in _TITLE_TYPES or (
            block_type == "text" and "text_level" in block
        )
        if is_title:
            if text and len(text) <= 1:
                continue
            title_level = _get_title_level(block)
            if not doc_title:
                doc_title = text
                continue

            bbox = block.get("bbox")
            title_height = (bbox[3] - bbox[1]) if (bbox and len(bbox) == 4) else 0

            if parent_threshold > 0 and title_height < parent_threshold:
                # 小标题 → 作为正文
                if text:
                    pending_body.append(text)
                continue

            # 大标题 → flush 之前的正文，输出标题
            _flush_body()

            style = "Heading 2" if title_level <= 1 else "Heading 3"
            if title_level == 0:
                style = "Title"
            paragraphs.append({
                "text": text,
                "style": style,
                "level": title_level,
            })
            continue

        # --- 无文本非图表 → 跳过 ---
        if not text and block_type not in FIGURE_TYPES:
            continue

        # --- 图表块 ---
        if block_type in FIGURE_TYPES:
            _flush_body()

            img_path = extract_image_path(block)
            has_table_html = bool(_extract_table_html(block)) if block_type in TABLE_TYPES else False
            caption_text = extract_caption_text(block) or _extract_text(block)

            if not img_path and not has_table_html:
                if caption_text:
                    # 纯图注 → 合并到上文或作为正文
                    merged = False
                    for j in range(len(paragraphs) - 1, -1, -1):
                        if paragraphs[j].get("image"):
                            prev_cap = paragraphs[j].get("text", "")
                            paragraphs[j]["text"] = (prev_cap + " | " + caption_text) if prev_cap else caption_text
                            merged = True
                            break
                    if not merged:
                        pending_body.append(caption_text)
                continue

            if block_type in IMAGE_TYPES:
                action, entries = process_image_block(
                    block, global_idx=gidx, mode=INCLUDE_IMAGES,
                    llm_decisions=llm_decisions,
                )
                if action == "discard":
                    continue
                if action in ("text_only", "caption_only"):
                    pending_body.extend(entries)
                    continue

            if block_type in TABLE_TYPES:
                caption = extract_caption_text(block)
                rows = _parse_table_rows(block)
                if rows:
                    if caption:
                        paragraphs.append({
                            "text": f"[表] {caption}",
                            "style": "Normal",
                            "level": 0,
                        })
                    for row_text in rows:
                        paragraphs.append({
                            "text": row_text,
                            "style": "Normal",
                            "level": 0,
                        })
                else:
                    paragraphs.append({
                        "text": caption or "",
                        "style": "Normal",
                        "level": 0,
                        "image": make_image_entry(block),
                    })
                continue

            # chart / image_body / image
            paragraphs.append({
                "text": caption_text or "",
                "style": "Normal",
                "level": 0,
                "image": make_image_entry(block),
            })
            continue

        # --- 正文 ---
        if text:
            if block_type in _LIST_TYPES:
                pending_body.append(text)
            else:
                pending_body.append(text)

    pbar.close()
    _flush_body()

    return paragraphs, doc_title, max_page

