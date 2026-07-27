"""
PDF 快路径解析：使用 PyMuPDF 直接提取纯文字 PDF 的文本，
生成与 minerU 路径兼容的段落数据格式，直接供 build_docx() 使用。

适用于无图片、文本量充足的 PDF 文件。
"""

import re
from pathlib import Path

from loguru import logger
from tqdm import tqdm

import math
import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import (
    FAST_PDF_TITLE_FONT_THRESHOLD,
    PARENT_SPLIT_MARKER,
    SPLIT_MARKER,
    MAX_SUB_BLOCK_TOKENS,
)

# 目录/前言关键词（用于跳过目录页、前言页）
# 注意：匹配时会先去掉所有空格，以应对 PDF 中 "目   录" 等排版变体
_TOC_KEYWORDS = ["目录", "目 录", "目  录", "CONTENTS"]
_PREFACE_KEYWORDS = ["前言", "FOREWORD", "序言", "PREFACE"]
_APPENDIX_KEYWORDS = ["附录", "附 录", "APPENDIX"]


# 末尾出版日期行：如 "2026年2月3日印"、"2026 年2 月3 日印"
_END_DATE_RE = re.compile(r"\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日")


_PAGE_NUM_RE = re.compile(r'^\s*[—\-－]+\s*\d+\s*[—\-－]+\s*$')

def _is_page_number_line(text: str) -> bool:
    """判断是否为页码/分页符行（如 "— 3 —"）。"""
    return bool(_PAGE_NUM_RE.match(text.strip()))


def _is_end_meta_line(text: str) -> bool:
    """判断单行文本是否为末尾出版信息。"""
    t = text.strip()
    if len(t) > 80:
        return False
    if _END_DATE_RE.search(t):
        return True
    if "秘书处" in t:
        return True
    return False


def parse_pdf_fast(
    pdf_path: Path,
    title_threshold: float = FAST_PDF_TITLE_FONT_THRESHOLD,
    clean: bool = False,
) -> tuple[list[dict], str]:
    """使用 PyMuPDF 快速解析纯文字 PDF。

    自动过滤目录页、前言页、附录页。返回正文内容。

    Parameters
    ----------
    clean : bool
        False（默认）→ 输出含 *** / <-split-> 标记的传统段落。
        True → 输出干净段落（无标记，由分块策略后处理）。

    Returns
    -------
    tuple[list[dict], str]
        (paragraphs, doc_title)
    """
    import fitz

    doc = None
    try:
        doc = fitz.open(str(pdf_path))
        total_pages = doc.page_count

        # Step 1: 逐页提取文本行 + 表格 → all_spans + all_tables
        all_spans: list[dict] = []   # [{text, size, page}]
        all_tables: list[dict] = []  # [{rows: [[str]], page: int}]
        pages_text: dict[int, str] = {}  # page → 该页全部文字（用于检测目录/前言）

        pbar = tqdm(
            range(total_pages),
            desc=f"  快解析 {pdf_path.stem}",
            unit="页",
            ncols=100,
            bar_format="{desc}: {percentage:3.0f}% |{bar}| {n_fmt}/{total_fmt}",
        )

        for page_idx in pbar:
            page = doc[page_idx]
            page_num = page_idx + 1

            # ---- 表格识别 ----
            table_bboxes: list = []
            try:
                for table in page.find_tables():
                    rows = table.extract()
                    if rows and any(any(cell for cell in row) for row in rows):
                        all_tables.append({
                            "rows": [[str(cell).strip() if cell is not None else ""
                                      for cell in row] for row in rows],
                            "page": page_num,
                        })
                        table_bboxes.append(table.bbox)
            except Exception:
                pass

            # ---- 文本提取 ----
            text_dict = page.get_text("dict")
            page_text_parts: list[str] = []

            for block in text_dict.get("blocks", []):
                if block.get("type") != 0:  # 跳过图片块
                    continue

                for line in block.get("lines", []):
                    spans = line.get("spans", [])
                    if not spans:
                        continue

                    line_text = "".join(s.get("text", "") for s in spans)
                    if not line_text.strip():
                        continue

                    # 落在表格区域内的文字行跳过（避免重复提取）
                    line_bbox = line.get("bbox")
                    if line_bbox and _is_inside_any_table(line_bbox, table_bboxes):
                        continue

                    font_size = spans[0].get("size", 12)
                    text = _clean_embedded_page_num(line_text.strip())
                    page_text_parts.append(text)

                    all_spans.append({
                        "text": text,
                        "size": font_size,
                        "page": page_num,
                    })

            pages_text[page_num] = " ".join(page_text_parts)

        pbar.close()

        if not all_spans and not all_tables:
            logger.warning("  [快解析] 未提取到任何文本")
            return [], ""

        # Step 2: 找出需要跳过的页面范围
        skip_pages = _find_skip_pages(pages_text, all_spans, total_pages)
        logger.info(f"  [快解析] 跳过 {len(skip_pages)} 页（目录/前言），"
                     f"保留 {max(1, total_pages - len(skip_pages))} 页")

        # Step 3: 过滤掉表格中重复的文本行 + 跳页 + 元信息 + 页码
        remaining_spans = [
            s for s in all_spans
            if s["page"] not in skip_pages
            and not _is_end_meta_line(s["text"])
            and not _is_page_number_line(s["text"])
        ]
        remaining_tables = [t for t in all_tables if t["page"] not in skip_pages]

        if not remaining_spans and not remaining_tables:
            logger.warning("  [快解析] 过滤后无剩余内容")
            return [], ""

        if remaining_tables:
            logger.info(f"  [快解析] 识别到 {len(remaining_tables)} 个表格")

        # Step 4: 字号统计（基于保留的 span）
        sizes = [s["size"] for s in remaining_spans]
        max_size = max(sizes) if sizes else 12
        median_size = sorted(sizes)[len(sizes) // 2] if sizes else 12
        effective_threshold = max(title_threshold, max_size * 0.85)

        # Step 5: 提取文档标题（从全部页面中提取，含被过滤的封面页）
        doc_title = _extract_doc_title(all_spans, effective_threshold)

        # Step 6: 生成段落数据
        if clean:
            paragraphs = _spans_to_clean_paragraphs(
                remaining_spans, remaining_tables,
                title_threshold=effective_threshold,
                median_size=median_size, max_size=max_size,
            )
        else:
            paragraphs = _spans_to_paragraphs(
                remaining_spans, remaining_tables,
                title_threshold=effective_threshold,
                median_size=median_size, max_size=max_size,
            )
            paragraphs = _merge_empty_heading_blocks(paragraphs)

        return paragraphs, doc_title

    finally:
        if doc is not None:
            doc.close()


# 句子结束标点 —— 以此结尾的行视为段落自然结束
# # 旧：； 结尾也分段
# _SENTENCE_ENDERS = frozenset("。！？…》）\"'；;.!" + "」』】》〕〉")
_SENTENCE_ENDERS = frozenset("。！？…》）\"'.!" + "」』】》〕〉")

# 嵌入正文中的页码残留：如 "省级—  5  —"洁净城市""
_EMBEDDED_PAGE_NUM_RE = re.compile(r'[—\-－]+\s*\d+\s*[—\-－]+')


def _clean_embedded_page_num(text: str) -> str:
    """清除嵌入文本中的页码残片，如 '省级—  5  —洁净城市' → '省级洁净城市'。"""
    return _EMBEDDED_PAGE_NUM_RE.sub('', text).strip()


def _is_sentence_end(text: str) -> bool:
    """判断文本是否以句子结束标点结尾。"""
    if not text:
        return True
    return text.rstrip()[-1] in _SENTENCE_ENDERS


def _is_inside_any_table(line_bbox, table_bboxes: list) -> bool:
    """检查文本行 bbox 是否完全落在任一表格区域内。"""
    if not table_bboxes or not line_bbox:
        return False
    x1, y1, x2, y2 = line_bbox[:4]
    for tb in table_bboxes:
        tx1, ty1, tx2, ty2 = tb[:4]
        if x1 >= tx1 - 2 and y1 >= ty1 - 2 and x2 <= tx2 + 2 and y2 <= ty2 + 2:
            return True
    return False


def _is_new_para_start(text: str) -> bool:
    """判断一行文本是否为新段落的起始（编号、序号、关键词引导等）。"""
    t = text.lstrip()
    if not t:
        return False
    # 序号: "1." "1、" 等（限 1-3 位数字 + 标点 + 非数字，避免误判 "4920.1亿"）
    if re.match(r'^\d{1,3}\s*[.、．)）]\s*\D', t):
        return True
    if re.match(r'^[（(]\s*\d+\s*[）)]', t):
        return True
    if re.match(r'^[（(][一二三四五六七八九十百千\d]+[）)]', t):
        return True
    if re.match(r'^第[一二三四五六七八九十百千\d]+[章节条条款项部]', t):
        return True
    if re.match(r'^[一二三四五六七八九十]、', t):
        return True
    # 关键词引导
    if re.match(r'^(一是|二是|三是|四是|五是|六是|七是|八是|九是|十是)', t):
        return True
    # 项目符号
    if t[0] in ('●', '·', '•', '○', '◆', '■', '□', '▪', '▸', '➢'):
        return True
    return False


# 列表项合并最大长度：每条超过此字符数则不参与合并（视为带正文的独立条目）
_MAX_LIST_ITEM_CHARS = 100

# 列表项识别：与 _is_new_para_start 类似，但排除章节级标记（第X章/节/条）
_LIST_ITEM_RE = re.compile(
    r'^\d{1,3}\s*[.、．)）](?=\D)|'                    # 1. 1、10）
    r'^[（(]\s*\d+\s*[）)]|'                            # （1）(1)
    r'^[（(][一二三四五六七八九十百千\d]+[）)]|'          # （一）(一)
    r'^[一二三四五六七八九十]+[、．]|'                    # 一、
    r'^(一是|二是|三是|四是|五是|六是|七是|八是|九是|十是)|'  # 一是二是
    r'^[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳]|'            # 带圈数字
    r'^[★—●·•○◆■□▪▸➢☑✓✔✗✘]'                       # 项目符号
)


def _is_list_item(text: str) -> bool:
    """判断一行文本是否为列表项（编号、序号、符号开头）。

    排除章节标记（第X章/第X节/第X条），这些应独立成段。
    """
    t = text.lstrip()
    if not t:
        return False
    # 排除章节标记
    if re.match(r'^第[一二三四五六七八九十百千\d]+[章节条条款项部编]', t):
        return False
    return bool(_LIST_ITEM_RE.match(t))


def _merge_consecutive_list_items(paras: list[str]) -> list[str]:
    """将连续的短列表项段落合并为一个 \\n 分隔的段落。

    只合并每条 ≤ _MAX_LIST_ITEM_CHARS 字符的短列表项（纯标题/编号），
    包含大段正文的列表项保持独立，不参与合并。

    例如:
      ["（1）收入完成100亿", "（2）支出完成90亿", "正文段落"]
      → ["（1）收入完成100亿\\n（2）支出完成90亿", "正文段落"]

      ["1. 简短标题", "2. 这是一大段政策原文...(500字)", "3. 又一短标题"]
      → ["1. 简短标题", "2. 这是一大段政策原文...(500字)", "3. 又一短标题"]
    """
    if len(paras) <= 1:
        return paras

    result: list[str] = []
    list_buf: list[str] = []

    for para in paras:
        if _is_list_item(para) and len(para) <= _MAX_LIST_ITEM_CHARS:
            list_buf.append(para)
        else:
            if list_buf:
                result.append("\n".join(list_buf))
                list_buf = []
            result.append(para)

    if list_buf:
        result.append("\n".join(list_buf))

    return result


def _merge_body_into_paragraphs(body_lines: list[str]) -> list[str]:
    """将正文行列表合并为逻辑段落。

    规则：
    1. 下一行以序号/编号开头 → 无条件分段
    2. 其余合并（PDF 行内换行，不因句号而分段）
    3. 合并不以结束标点结尾的短段落（第二遍兜底）
    4. 连续短列表项 → 合并为一个 \\n 分隔的段落
    """
    if not body_lines:
        return []

    # ---- 第一遍：合并 PDF 行内换行，仅在列表/编号处分段 ----
    raw_paras: list[str] = []
    current = ""

    for line in body_lines:
        line = line.strip()
        if not line:
            continue

        if not current:
            current = line
        elif _is_new_para_start(line):
            # 下一行是编号/列表/标题开头 → 无条件分段
            raw_paras.append(current)
            current = line
        else:
            # PDF 行内换行 → 合并
            current += line

    if current:
        raw_paras.append(current)

    # ---- 第二遍：合并不以结束标点结尾的短段落（与 minerU 行为一致） ----
    if len(raw_paras) <= 1:
        return _merge_consecutive_list_items(raw_paras)

    merged: list[str] = []
    for para in raw_paras:
        # # 旧：编号项也不合并
        # should_merge = (
        #     merged
        #     and not _is_sentence_end(merged[-1])
        #     and not _is_new_para_start(para)
        # )
        # 新：列表项（（一）1. 等）可与上文合并，章节标题仍独立
        should_merge = (
            merged
            and not _is_sentence_end(merged[-1])
            and (not _is_new_para_start(para) or _is_list_item(para))
        )
        if should_merge:
            merged[-1] += para
        else:
            merged.append(para)

    # ---- 第三遍：合并连续列表项 ----
    return _merge_consecutive_list_items(merged)


def _emit_heading(paragraphs: list[dict], text: str, style: str, level: int) -> None:
    """输出一个标题（*** + 标题文字 + <-split->）。"""
    paragraphs.append({
        "text": PARENT_SPLIT_MARKER,
        "style": "Normal",
        "level": 0,
    })
    paragraphs.append({
        "text": text,
        "style": style,
        "level": level,
    })
    paragraphs.append({
        "text": SPLIT_MARKER,
        "style": "Normal",
        "level": 0,
    })


def _emit_table_block(paragraphs: list[dict], rows: list[list[str]]) -> None:
    """输出一个表格独立块（*** + 首行作标题 + 各行内容）。"""
    if not rows:
        return
    heading = " | ".join(rows[0])

    paragraphs.append({"text": PARENT_SPLIT_MARKER, "style": "Normal", "level": 0})
    paragraphs.append({"text": heading, "style": "Heading 3", "level": 2})
    paragraphs.append({"text": SPLIT_MARKER, "style": "Normal", "level": 0})

    for row in rows:
        row_text = " | ".join(row)
        paragraphs.append({"text": row_text, "style": "Normal", "level": 0})
        paragraphs.append({"text": SPLIT_MARKER, "style": "Normal", "level": 0})


# ---------- Token 估算（与 text_chunker._estimate_tokens 一致）----------

def _estimate_tokens(text: str) -> int:
    """逐字符估算 token 数：CJK/假名/韩文/全角 = 1.0，空白 = 0，其他 = 0.25。"""
    total = 0.0
    for ch in text:
        code = ord(ch)
        if (
            0x4E00 <= code <= 0x9FFF or 0x3400 <= code <= 0x4DBF or
            0x20000 <= code <= 0x2A6DF or 0xF900 <= code <= 0xFAFF or
            0x2F800 <= code <= 0x2FA1F or 0x30000 <= code <= 0x3134F or
            0x2A700 <= code <= 0x2CEAF or 0x2CEB0 <= code <= 0x2EBEF or
            0x3040 <= code <= 0x309F or 0x30A0 <= code <= 0x30FF or
            0xAC00 <= code <= 0xD7AF or 0x1100 <= code <= 0x11FF or
            0x3000 <= code <= 0x303F or 0xFF00 <= code <= 0xFFEF
        ):
            total += 1.0
        elif not ch.isspace():
            total += 0.25
    return math.ceil(total)


def _split_long_para(text: str, max_tokens: int) -> list[str]:
    """规则拆分：按标点优先级在 token 限制内断开。

    断点优先级：。！？； → \\n\\n → ，、, → \\n → 空格 → 硬截断
    """
    if not text or _estimate_tokens(text) <= max_tokens:
        return [text]

    parts: list[str] = []
    remaining = text

    while remaining:
        if _estimate_tokens(remaining) <= max_tokens:
            parts.append(remaining.strip())
            break

        accumulated = 0.0
        best_break = -1       # 句子结束
        best_break2 = -1      # 子句边界
        best_break3 = -1      # 空格
        hard_break = -1

        for i, ch in enumerate(remaining):
            code = ord(ch)
            if (
                0x4E00 <= code <= 0x9FFF or 0x3400 <= code <= 0x4DBF or
                0x20000 <= code <= 0x2A6DF or 0xF900 <= code <= 0xFAFF or
                0x2F800 <= code <= 0x2FA1F or 0x30000 <= code <= 0x3134F or
                0x2A700 <= code <= 0x2CEAF or 0x2CEB0 <= code <= 0x2EBEF or
                0x3040 <= code <= 0x309F or 0x30A0 <= code <= 0x30FF or
                0xAC00 <= code <= 0xD7AF or 0x1100 <= code <= 0x11FF or
                0x3000 <= code <= 0x303F or 0xFF00 <= code <= 0xFFEF
            ):
                accumulated += 1.0
            elif not ch.isspace():
                accumulated += 0.25

            if accumulated > max_tokens:
                hard_break = i
                break

            # # 旧：；也作为断点
            # if ch in ('。', '！', '？', '；', '!', '?', ';') or (
            if ch in ('。', '！', '？', '!', '?') or (
                ch == '\n' and i + 1 < len(remaining) and remaining[i + 1] == '\n'
            ):
                best_break = i + 1
            if ch in ('，', '、', ',', '\n'):
                best_break2 = i + 1
            if ch == ' ':
                best_break3 = i + 1

        split_at = best_break or best_break2 or best_break3 or hard_break
        if split_at <= 0:
            split_at = max(1, hard_break)

        if accumulated <= max_tokens and not hard_break:
            parts.append(remaining.strip())
            break

        part = remaining[:split_at].strip()
        if part:
            parts.append(part)
        remaining = remaining[split_at:]

    return parts or [text.strip()]


def _emit_body_para(paragraphs: list[dict], text: str) -> None:
    """输出一个正文段落（正文 + <-split->），超限时按 token 限制拆分。"""
    text = text.strip()
    if not text:
        return
    # 过滤纯碎片：单字符、纯破折号/分隔线、纯数字小数
    if len(text) <= 2 and (text in ('—', '—', '-', '一', '') or text.replace('.', '').replace(' ', '').isdigit()):
        return

    # Layer 2 兜底拆分：超 token 限制时拆分，各片段间补 <-split->
    parts = _split_long_para(text, MAX_SUB_BLOCK_TOKENS)
    for j, part in enumerate(parts):
        paragraphs.append({
            "text": part,
            "style": "Normal",
            "level": 0,
        })
        if j + 1 < len(parts):
            paragraphs.append({
                "text": SPLIT_MARKER,
                "style": "Normal",
                "level": 0,
            })

    paragraphs.append({
        "text": SPLIT_MARKER,
        "style": "Normal",
        "level": 0,
    })


def _spans_to_paragraphs(
    spans: list[dict],
    tables: list[dict],
    title_threshold: float,
    median_size: float,
    max_size: float,
) -> list[dict]:
    """将 spans + 表格按页面顺序交插，转换为段落数据。

    表格独立成块（***），表格前后的正文共享同一父标题。
    """
    paragraphs: list[dict] = []
    body_buf: list[str] = []

    # spans 和 tables 合并为按页面排序的统一序列
    items: list[dict] = []
    for s in spans:
        items.append({"kind": "span", "page": s["page"], "data": s})
    for t in tables:
        items.append({"kind": "table", "page": t["page"], "data": t})
    items.sort(key=lambda x: (x["page"], 0 if x["kind"] == "span" else 1))

    body_max = median_size * 1.2
    first_heading = True
    last_heading_text = ""

    for item in items:
        if item["kind"] == "table":
            table = item["data"]
            _flush_body_merged(paragraphs, body_buf)

            # 表格独立成块
            _emit_table_block(paragraphs, table["rows"])

            # 表格后恢复前面的父标题
            if last_heading_text:
                _emit_heading(paragraphs, last_heading_text, "Heading 2", level=1)

        else:
            span = item["data"]
            size = span["size"]
            text = span["text"]

            if size >= title_threshold:
                if first_heading:
                    first_heading = False
                    last_heading_text = text
                    continue  # 作为 doc_title

                _flush_body_merged(paragraphs, body_buf)
                _emit_heading(paragraphs, text, "Heading 2", level=1)
                last_heading_text = text

            elif size > body_max:
                body_buf.append(text)

            else:
                body_buf.append(text)

    _flush_body_merged(paragraphs, body_buf)

    if not paragraphs:
        for span in spans:
            _emit_body_para(paragraphs, span["text"])

    paragraphs = _merge_empty_heading_blocks(paragraphs)

    return paragraphs


def _flush_body_merged(paragraphs: list[dict], body_buf: list[str]) -> None:
    """合并 body_buf 中的连续行为逻辑段落，输出到 paragraphs。"""
    if not body_buf:
        return
    merged = _merge_body_into_paragraphs(body_buf)
    for para in merged:
        _emit_body_para(paragraphs, para)
    body_buf.clear()


def _merge_empty_heading_blocks(paragraphs: list[dict]) -> list[dict]:
    """合并空标题块：*** + Heading + <-split-> + *** → 标题文字合并到下一正文开头。

    扫描 *** + Heading + <-split-> + *** 模式，
    将空标题文字插入到后一个 *** 节的第一个正文段落之前。
    """
    n = len(paragraphs)
    if n < 6:
        return paragraphs

    # 找到所有 *** 的位置
    star_positions = [i for i, p in enumerate(paragraphs) if p.get("text") == PARENT_SPLIT_MARKER]

    result: list[dict] = list(paragraphs)  # 复制，原位修改
    removed_count = 0  # 记录已删除的段落数，用于调整索引

    for idx in range(len(star_positions) - 1):
        # 当前 *** 位置（已考虑之前的删除）
        pos = star_positions[idx] - removed_count
        nxt_pos = star_positions[idx + 1] - removed_count

        if pos + 2 >= len(result):
            continue
        if nxt_pos <= pos + 2:
            continue

        # 检查是否为空标题：*** + Heading + <-split-> + ...
        h = result[pos + 1]
        s = result[pos + 2]
        if not h.get("style", "").startswith("Heading"):
            continue
        if s.get("text") != SPLIT_MARKER:
            continue

        # 找到下一节的第一段正文（跳过 *** / <-split-> / Heading）
        body_idx = nxt_pos + 1
        while body_idx < len(result):
            bp = result[body_idx]
            if bp.get("text") in (PARENT_SPLIT_MARKER, SPLIT_MARKER):
                body_idx += 1
                continue
            if bp.get("style", "").startswith("Heading"):
                body_idx += 1
                continue
            break

        if body_idx >= len(result):
            # 下一节无正文 → 跳到结尾
            nxt_split_idx = nxt_pos + 1
            while nxt_split_idx < len(result) and result[nxt_split_idx].get("text") == SPLIT_MARKER:
                nxt_split_idx += 1
            continue

        # 检查 pos 到 nxt_pos 之间是否只有 heading + split（无正文）
        has_body_between = any(
            result[j].get("text") not in (PARENT_SPLIT_MARKER, SPLIT_MARKER)
            and not result[j].get("style", "").startswith("Heading")
            for j in range(pos + 3, nxt_pos)
        )
        if has_body_between:
            continue

        # 空标题：删除 pos..nxt_pos（去除一个 ***），标题文字插入到下一节正文
        heading_text = h.get("text", "")
        # 在正文前插入标题文字
        result[body_idx]["text"] = heading_text + "\n" + result[body_idx]["text"]
        # 删除 pos 到 nxt_pos-1 的段落
        del result[pos:nxt_pos]
        removed_count += nxt_pos - pos

    return result


# ---------------------------------------------------------------------------
# 页面过滤：跳过目录页、前言页、附录页
# ---------------------------------------------------------------------------

def _contains_keyword(text: str, keywords: list[str]) -> bool:
    """检查文本是否包含任一关键词（忽略空格差异）。"""
    text_compact = text.replace(" ", "").replace("\t", "")
    return any(kw.replace(" ", "").replace("\t", "") in text_compact for kw in keywords)


def _find_skip_pages(
    pages_text: dict[int, str],
    all_spans: list[dict],
    total_pages: int,
) -> set[int]:
    """找出需要跳过的页面编号集合。

    策略：
    1. 目录页及之前的页 → 跳过
    2. 目录之后的连续"无实质正文"页 → 跳过（目录续页）
    3. 附录页及之后 → 跳过
    4. 无目录时：前几页只有极少量文字的封面页 → 跳过
    """
    skip: set[int] = set()
    page_nums = sorted(pages_text.keys())

    if not page_nums:
        return skip

    # ---- 查找目录页 ----
    toc_page = _find_keyword_page(pages_text, _TOC_KEYWORDS, max_search=6)

    # ---- 确定正文起始页 ----
    first_body_page = 1

    if toc_page > 0:
        first_body_page = toc_page + 1
        # 跳过目录之后的连续无实质页
        while (first_body_page <= total_pages
               and not _has_substantial_text(pages_text.get(first_body_page, ""))):
            first_body_page += 1
    else:
        # 无目录页：从第一个有实质内容的页开始（跳过封面/前言/解读说明页）
        for pg in range(1, min(6, total_pages + 1)):
            text = pages_text.get(pg, "")
            if _contains_keyword(text, _PREFACE_KEYWORDS):
                # 前言页及之前全跳过
                first_body_page = pg + 1
                while (first_body_page <= total_pages
                       and not _has_substantial_text(pages_text.get(first_body_page, ""))):
                    first_body_page += 1
                continue
            if _has_substantial_text(text):
                first_body_page = pg
                break

    # ---- 查找附录页 ----
    appendix_page = _find_keyword_page(pages_text, _APPENDIX_KEYWORDS,
                                        max_search=8, from_end=True)

    # ---- 收集跳过页 ----
    for pg in range(1, first_body_page):
        skip.add(pg)

    if appendix_page > 0:
        for pg in range(appendix_page, total_pages + 1):
            skip.add(pg)
    elif toc_page <= 0 and first_body_page == 1:
        # 无目录且从第一页开始 → 仍跳过纯封面页（文字极少）
        for pg in range(1, min(4, total_pages + 1)):
            text = pages_text.get(pg, "")
            # 跳过"内部资料"、"解读"等扉页
            if _is_cover_page(text):
                skip.add(pg)
            else:
                break

    return skip


def _extract_doc_title(all_spans: list[dict], title_threshold: float) -> str:
    """从全部 span（含封面页）中提取文档标题。

    优先取符合字号阈值的 span，忽略目录/前言标签。
    """
    for span in all_spans:
        if span["size"] < title_threshold:
            continue
        text = span["text"]
        if _contains_keyword(text, _TOC_KEYWORDS):
            continue
        if _contains_keyword(text, _PREFACE_KEYWORDS):
            continue
        # 跳过页码行（纯数字或 "— N —" 格式）
        stripped = text.replace("—", "").replace(" ", "").strip()
        if stripped.isdigit() or len(text) <= 3:
            continue
        return text
    return ""


def _find_keyword_page(
    pages_text: dict[int, str],
    keywords: list[str],
    max_search: int = 6,
    from_end: bool = False,
) -> int:
    """在页面中搜索关键词，返回匹配的页码（未找到返回 -1）。"""
    page_nums = sorted(pages_text.keys())
    if from_end:
        search_pages = page_nums[-max_search:] if len(page_nums) >= max_search else page_nums[::-1]
    else:
        search_pages = page_nums[:max_search]

    for pg in search_pages:
        text = pages_text.get(pg, "")
        if _contains_keyword(text, keywords):
            return pg
    return -1


# 封面/扉页关键词
_COVER_SIGNALS = [
    "内部资料", "妥善保管", "参阅文件", "解读", "说明",
    "人大", "人大常委会", "预算工作委员会",
]
# 扉页上允许保留的实质关键词（即使含上述词也保留）
_COVER_WHITELIST = [
    "国民经济", "社会发展", "五年规划", "纲要", "预算报告",
    "决算报告", "计划报告",
]


def _is_cover_page(text: str) -> bool:
    """判断是否为扉页/封面页（仅有说明性文字，无实质正文）。

    扉页特征：文字量很少，且包含"内部资料""解读"等标志词，
    但不应包含正文实质性内容（如"国民经济""五年规划"等）。
    """
    if not text:
        return True

    # 如果包含正文白名单内容，不是纯扉页
    for kw in _COVER_WHITELIST:
        if kw in text:
            return False

    # 文字量极少的页视为封面
    if len(text) < 60:
        return True

    return False


def _has_substantial_text(text: str, min_chars: int = 80) -> bool:
    """判断页面文字是否为实质正文内容。

    排除：纯数字页码、仅含"目录""前言"等关键词的页、空白页。
    """
    if not text:
        return False

    # 排除纯目录/前言的标签页
    for kw in _TOC_KEYWORDS + _PREFACE_KEYWORDS:
        text_no_kw = text.replace(kw, "").strip()
        if len(text_no_kw) < 20:
            return False

    return len(text) >= min_chars


