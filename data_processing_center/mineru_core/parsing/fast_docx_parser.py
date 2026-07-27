"""
DOCX 快路径解析：使用 python-docx 直接读取 DOCX 的段落、表格、图片，
生成与 minerU 路径兼容的段落数据格式，直接供 build_docx() 使用。

minerU 无法处理 DOCX，所以所有 DOCX 文件都走此路径。
"""

import re
import zipfile
from pathlib import Path
from typing import Optional

from loguru import logger
from tqdm import tqdm

import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import (
    PARENT_SPLIT_MARKER,
    SPLIT_MARKER,
    MAX_SUB_BLOCK_TOKENS,
)
from parsing.fast_pdf_parser import (
    _merge_body_into_paragraphs,
    _emit_body_para,
    _merge_empty_heading_blocks,
    _split_long_para,
)


def parse_docx_fast(
    docx_path: Path,
    image_dir: Optional[Path] = None,
) -> tuple[list[dict], str]:
    """使用 python-docx 解析 DOCX（支持文字、表格、图片）。

    Parameters
    ----------
    docx_path : Path
        DOCX 文件路径。
    image_dir : Path, optional
        图片输出目录。如果为 None，默认在 docx 同目录下创建 images/。

    Returns
    -------
    tuple[list[dict], str]
        (paragraphs, doc_title)
        paragraphs 格式与 chunks_to_paragraphs() 输出兼容。
    """
    from docx import Document

    doc = Document(str(docx_path))
    paragraphs: list[dict] = []

    # 准备图片目录
    if image_dir is None:
        image_dir = docx_path.parent / "images"
    image_dir = Path(image_dir)
    image_dir.mkdir(parents=True, exist_ok=True)

    # 打开 zip 以提取图片
    image_counter = 0

    try:
        zf = zipfile.ZipFile(str(docx_path), "r")
    except Exception:
        zf = None

    body = doc.element.body
    children = list(body)

    # 建立 rels 映射：rId → target path
    rels_map: dict[str, str] = {}
    try:
        for rel in doc.part.rels.values():
            rels_map[rel.rId] = rel.target_ref
    except Exception:
        pass

    # ---- 预扫描：找文档标题 ----
    doc_title = _find_doc_title(children)

    # ---- 主循环：按文档元素顺序处理 ----
    # 正文缓冲：连续 Normal 段落先收集，遇到标题/表格/图片时合并写入
    body_buf: list[str] = []
    pending_heading = ""  # 当前待拼接的章节标题

    def _flush_body():
        """将缓冲的正文段落（含待拼接的章节标题）经过合并+token拆分后写入 paragraphs。"""
        nonlocal body_buf, pending_heading
        if pending_heading:
            if body_buf:
                # 标题拼到第一个正文段落前
                body_buf[0] = pending_heading + "\n" + body_buf[0]
            else:
                # 标题后面没有正文（如连续两个标题）→ 标题自身作为正文
                body_buf.append(pending_heading)
            pending_heading = ""
        if body_buf:
            merged = _merge_body_into_paragraphs(body_buf)
            for para in merged:
                _emit_body_para(paragraphs, para)
            body_buf.clear()

    # ---- 目录检测：预扫描找到目录区域，主循环中跳过 ----
    toc_start, toc_end = _find_toc_range(children)
    if toc_start >= 0:
        logger.info(f"  [快解析] 检测到目录 (第 {toc_start}~{toc_end - 1} 段)，已跳过")

    total = len(children)
    last_heading = ""          # 表格前的最后一个标题
    last_heading_style = ""    # 标题的样式
    last_heading_level = 0     # 标题的层级

    for i, child in enumerate(children):
        # 跳过目录区域
        if toc_start >= 0 and toc_start <= i < toc_end:
            continue
        tag = _local_tag(child)

        if tag == "p":
            para_text = _extract_text_from_para(child)
            para_style = _extract_style(child)
            image_rids = _extract_image_rids(child)
            is_bold = _is_para_bold(child)
            font_size = _extract_max_font_size(child)

            # 标题判定（多策略）：
            #   1. Word 样式为 Heading / Title → 标题
            #   2. Normal + 粗体 → 标题
            #   3. 内容匹配章节模式（第X章/条、一、等）→ 标题
            is_para_heading = (
                para_style.startswith("Heading")
                or para_style == "Title"
                or (para_style == "Normal" and is_bold)
                or _is_heading_by_content(para_text)
            )

            # ---- 图片处理：先 flush 正文缓冲，再独立输出 ----
            has_image = False
            for rid in image_rids:
                rel_target = rels_map.get(rid, "")
                img_path = _save_image_from_zip(zf, rel_target, image_dir, docx_path.stem, image_counter)
                if img_path:
                    image_counter += 1
                    _flush_body()
                    caption = para_text if para_text else ""
                    paragraphs.append({
                        "text": caption,
                        "style": "Normal",
                        "level": 0,
                        "image": {
                            "type": "image",
                            "path": str(img_path),
                            "caption": caption,
                        },
                    })
                    has_image = True

            if has_image:
                continue

            if not para_text:
                continue

            # ---- 标题处理：flush 正文，发 *** 标记新父块，标题拼到下一段正文前 ----
            if is_para_heading:
                _flush_body()
                paragraphs.append({
                    "text": PARENT_SPLIT_MARKER,
                    "style": "Normal",
                    "level": 0,
                })
                # # 旧逻辑：标题单独成块（*** + 标题 + <-split->），不与下文合并
                # heading_level = _style_to_level(para_style) if para_style.startswith("Heading") else 1
                # heading_style = para_style if para_style.startswith("Heading") else ("Heading 2" if heading_level == 1 else "Heading 3")
                # paragraphs.append({"text": para_text, "style": heading_style, "level": heading_level})
                # paragraphs.append({"text": SPLIT_MARKER, "style": "Normal", "level": 0})
                # 新逻辑：标题存入 pending，下次 flush 时拼到第一个正文段落前
                pending_heading = para_text
                heading_level = _style_to_level(para_style) if para_style.startswith("Heading") else 1
                last_heading = para_text
                last_heading_style = para_style
                last_heading_level = heading_level

            else:
                # ---- 正文段落 → 缓冲，等待合并 ----
                body_buf.append(para_text)

        elif tag == "tbl":
            _flush_body()
            # 前看：下一个元素是正文时才恢复标题
            next_is_body = False
            if i + 1 < len(children):
                next_tag = _local_tag(children[i + 1])
                if next_tag == "p":
                    next_style = _extract_style(children[i + 1])
                    next_is_heading = next_style.startswith("Heading") or next_style == "Title" or (
                        next_style == "Normal" and _is_para_bold(children[i + 1])
                    )
                    next_is_body = not next_is_heading

            _handle_table(child, paragraphs,
                          prev_heading=last_heading,
                          prev_heading_style=last_heading_style,
                          prev_heading_level=last_heading_level,
                          restore_heading=next_is_body)

    # 最后 flush 剩余正文 + 合并空标题块
    _flush_body()
    paragraphs = _merge_empty_heading_blocks(paragraphs)

    # DEBUG: 打印最终段落列表，检查 *** 是否存在
    logger.info(f"  [DEBUG] 最终段落数: {len(paragraphs)}")
    star_count = sum(1 for p in paragraphs if p.get("text") == "***")
    logger.info(f"  [DEBUG] *** 出现次数: {star_count}")
    if star_count == 0:
        for j, p in enumerate(paragraphs[:8]):
            logger.info(f"  [DEBUG]   [{j}] style={p.get('style')} text={p.get('text', '')[:60]!r}")

    if zf:
        zf.close()

    if not doc_title:
        doc_title = docx_path.stem

    return paragraphs, doc_title


# ---------------------------------------------------------------------------
# 内部辅助
# ---------------------------------------------------------------------------

_NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pic": "http://schemas.openxmlformats.org/drawingml/2006/picture",
}

# ---------------------------------------------------------------------------
# 目录检测与删除
# ---------------------------------------------------------------------------

# 目录标题关键词
_TOC_HEADING_RE = re.compile(r'^\s*(目\s*录|目\s*次|CONTENTS|Table\s*of\s*Contents)\s*$', re.IGNORECASE)

# 目录条目特征：省略号(2+点) + 末尾页码，或 tab + 末尾页码
_TOC_DOTS_RE = re.compile(r'\.{2,}\s*\d{1,4}$')
_TOC_TAB_RE = re.compile(r'\t\d{1,4}$')
# 前导序号 + 省略号模式：如 "一、......3"  "1........5"
_TOC_LEADING_NUM_RE = re.compile(r'^\s*[IVX\d一二三四五六七八九十]+[、.]?\s*\.{2,}')


def _is_toc_entry(text: str) -> bool:
    """是否为目录条目（省略号/tab + 末尾页码）。"""
    t = text.strip()
    if not t:
        return False
    if _TOC_DOTS_RE.search(t):
        return True
    if _TOC_TAB_RE.search(t):
        return True
    if _TOC_LEADING_NUM_RE.search(t):
        return True
    return False


def _find_toc_range(children: list) -> tuple[int, int]:
    """预扫描 children，找到目录区域 [start, end) 索引范围。

    检测策略：
    1. 找到第一个匹配"目录"关键词的标题段落 → toc_start
    2. 从 toc_start 往后扫描：目录条目继续，遇到真正标题 → toc_end
    3. 连续 3 个非目录正文段落 → 目录结束
    """
    toc_start = -1
    toc_end = -1
    non_toc_count = 0

    for i, child in enumerate(children):
        tag = _local_tag(child)
        if tag != "p":
            if toc_start >= 0:
                non_toc_count += 1
            continue

        text = _extract_text_from_para(child)
        if not text:
            continue

        t = text.strip()

        # 找目录标题
        if toc_start < 0:
            if _TOC_HEADING_RE.match(t):
                toc_start = i
                continue
            continue

        # 已在目录区域内
        if _is_toc_entry(t):
            non_toc_count = 0
            continue

        style = _extract_style(child)
        is_header = style.startswith("Heading") or style == "Title" or _is_para_bold(child)

        # 遇到下一个标题 → 目录结束
        if is_header:
            toc_end = i
            break

        # 连续非目录正文
        non_toc_count += 1
        if non_toc_count > 2:
            toc_end = i - non_toc_count + 1
            break

    if toc_start >= 0 and toc_end < 0:
        toc_end = len(children)

    return (toc_start, toc_end)


def _local_tag(elem) -> str:
    """返回元素的本地标签名（去掉命名空间）。"""
    tag = elem.tag
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _extract_text_from_para(para_elem) -> str:
    """从 w:p 元素中提取纯文本。"""
    texts = []
    for t in para_elem.iter(_qname("w:t")):
        if t.text:
            texts.append(t.text)
    return "".join(texts).strip()


def _extract_style(para_elem) -> str:
    """从 w:p 元素提取样式名。"""
    style_id = None
    pPr = para_elem.find(_qname("w:pPr"))
    if pPr is not None:
        pStyle = pPr.find(_qname("w:pStyle"))
        if pStyle is not None:
            style_id = pStyle.get(_qname("w:val"))
    return _map_style(style_id) if style_id else "Normal"


def _is_para_bold(para_elem) -> bool:
    """检测段落是否包含粗体格式。

    检查所有 w:r 元素：如果任一 run 的 w:b 属性存在且不为 0/false，
    则视为粗体段落（通常用于标题）。
    """
    for r_elem in para_elem.iter(_qname("w:r")):
        rPr = r_elem.find(_qname("w:rPr"))
        if rPr is not None:
            b = rPr.find(_qname("w:b"))
            if b is not None:
                val = b.get(_qname("w:val"))
                if val is None or val in ("1", "true", "on"):
                    # 确认这个 run 有实际文字内容
                    for t in r_elem.iter(_qname("w:t")):
                        if t.text and t.text.strip():
                            return True
    return False


def _extract_max_font_size(para_elem) -> float:
    """从段落 runs 中提取最大字号（pt）。

    DOCX 中字号存在 w:sz (half-points) 或 w:szCs 属性中。
    未显式设字号时返回 0。
    """
    max_sz = 0.0
    for r_elem in para_elem.iter(_qname("w:r")):
        rPr = r_elem.find(_qname("w:rPr"))
        if rPr is None:
            continue
        for attr in ("w:sz", "w:szCs"):
            sz = rPr.find(_qname(attr))
            if sz is not None:
                val = sz.get(_qname("w:val"))
                if val and val.isdigit():
                    max_sz = max(max_sz, int(val) / 2.0)
    return max_sz


# 基于内容的标题检测：只匹配章节级标题
_HEADING_CONTENT_RE = re.compile(
    r'^\s*('
    r'第[一二三四五六七八九十百千\d]+[章节部编]'       # 第X章、第X节
    r'|'
    r'[一二三四五六七八九十]+[、．.\s]+'               # 一、xxx
    r')'
)


def _is_heading_by_content(text: str) -> bool:
    """通过内容模式判断是否为标题（如 第一章、一、等，不含第X条）。"""
    return bool(_HEADING_CONTENT_RE.match(text.strip()))


def _extract_image_rids(para_elem) -> list[str]:
    """从 w:p 元素中提取所有图片的 rId。"""
    rids: list[str] = []
    for blip in para_elem.iter(_qname("a:blip")):
        rid = blip.get(_qname("r:embed"))
        if rid:
            rids.append(rid)
    return rids


def _find_doc_title(children: list) -> str:
    """从 body 子元素中预扫描文档标题。

    优先级：Title 样式 > 第一个 Heading > 第一个粗体短文本 > 第一个正文短文本。
    """
    first_heading_text = ""
    first_bold_short = ""
    first_para_short = ""

    for child in children:
        if _local_tag(child) != "p":
            continue

        text = _extract_text_from_para(child)
        if not text:
            continue

        style = _extract_style(child)

        if style == "Title":
            return text
        if style.startswith("Heading") and not first_heading_text:
            first_heading_text = text
        if not first_para_short and style == "Normal" and len(text) <= 30:
            first_para_short = text
            if _is_para_bold(child) and not first_bold_short:
                first_bold_short = text

        if first_heading_text:
            break

    if first_heading_text:
        return first_heading_text
    if first_bold_short:
        return first_bold_short
    if first_para_short:
        return first_para_short
    return ""


def _handle_paragraph(
    para_elem,
    paragraphs: list[dict],
    rels_map: dict[str, str],
    zf,
    image_dir: Path,
    image_counter: int,
    stem: str,
) -> None:
    """处理单个 w:p 元素（可能含文字、图片或两者都有）。

    粗体/标题样式段落 → 作为父块标题（*** 分隔），
    普通段落 → 作为正文子块。
    """
    text = _extract_text_from_para(para_elem)
    style = _extract_style(para_elem)
    image_rids = _extract_image_rids(para_elem)
    is_bold = _is_para_bold(para_elem)

    # 提取图片
    for rid in image_rids:
        rel_target = rels_map.get(rid, "")
        img_path = _save_image_from_zip(zf, rel_target, image_dir, stem, image_counter)
        if img_path:
            image_counter += 1
            caption = text if text else ""
            paragraphs.append({
                "text": caption,
                "style": "Normal",
                "level": 0,
                "image": {
                    "type": "image",
                    "path": str(img_path),
                    "caption": caption,
                },
            })
            return

    if not text:
        return

    # 标题样式 或 粗体普通段落 → 作为父块标题
    is_parent = style.startswith("Heading") or style == "Title" or (
        style == "Normal" and is_bold
    )

    if is_parent:
        heading_level = _style_to_level(style) if style.startswith("Heading") else 1
        heading_style = style if style.startswith("Heading") else ("Heading 2" if heading_level == 1 else "Heading 3")
        paragraphs.append({
            "text": PARENT_SPLIT_MARKER,
            "style": "Normal",
            "level": 0,
        })
        paragraphs.append({
            "text": text,
            "style": heading_style,
            "level": heading_level,
        })
        paragraphs.append({
            "text": SPLIT_MARKER,
            "style": "Normal",
            "level": 0,
        })
    else:
        paragraphs.append({
            "text": text,
            "style": "Normal",
            "level": 0,
        })
        paragraphs.append({
            "text": SPLIT_MARKER,
            "style": "Normal",
            "level": 0,
        })


def _handle_table(tbl_elem, paragraphs: list[dict],
                  prev_heading: str = "",
                  prev_heading_style: str = "",
                  prev_heading_level: int = 0,
                  restore_heading: bool = False) -> None:
    """处理 w:tbl 元素，独立成块。

    表格作为独立的 *** 块输出。仅当后面紧跟正文（非标题）时，
    才恢复前一个标题使正文归属正确。
    """
    rows: list[list[str]] = []

    for tr in tbl_elem.iter(_qname("w:tr")):
        row_texts: list[str] = []
        for tc in tr.iter(_qname("w:tc")):
            cell_texts = []
            for t in tc.iter(_qname("w:t")):
                if t.text:
                    cell_texts.append(t.text)
            row_texts.append("".join(cell_texts).strip())
        if row_texts:
            rows.append(row_texts)

    if not rows:
        return

    # 表格独立块：*** + [表格] + 行内容
    paragraphs.append({
        "text": PARENT_SPLIT_MARKER,
        "style": "Normal",
        "level": 0,
    })
    paragraphs.append({
        "text": "[表格]",
        "style": "Heading 3",
        "level": 2,
    })
    paragraphs.append({
        "text": SPLIT_MARKER,
        "style": "Normal",
        "level": 0,
    })

    for row in rows:
        row_text = " | ".join(row)
        paragraphs.append({
            "text": row_text,
            "style": "Normal",
            "level": 0,
        })
        paragraphs.append({
            "text": SPLIT_MARKER,
            "style": "Normal",
            "level": 0,
        })

    # 表格后：仅当后面紧跟正文时恢复前面的标题
    if prev_heading and restore_heading:
        heading_style_name = _heading_text_to_style(prev_heading_style, prev_heading_level)
        paragraphs.append({
            "text": PARENT_SPLIT_MARKER,
            "style": "Normal",
            "level": 0,
        })
        paragraphs.append({
            "text": prev_heading,
            "style": heading_style_name,
            "level": prev_heading_level,
        })
        paragraphs.append({
            "text": SPLIT_MARKER,
            "style": "Normal",
            "level": 0,
        })


def _save_image_from_zip(
    zf,
    rel_target: str,
    image_dir: Path,
    stem: str,
    counter: int,
) -> Optional[Path]:
    """从 DOCX zip 中提取图片到 image_dir，返回保存路径。"""
    if zf is None:
        return None

    # rel_target 形如 "media/image1.png"
    # 在 zip 中实际路径为 "word/media/image1.png"
    candidates = [
        rel_target,
        f"word/{rel_target}",
    ]

    for cand in candidates:
        try:
            data = zf.read(cand)
            if data:
                # 用原文件名 + stem 前缀
                name = Path(rel_target).name
                suffix = Path(rel_target).suffix or ".png"
                save_name = f"{counter + 1}_{name}"
                save_path = image_dir / save_name
                save_path.write_bytes(data)
                return save_path
        except (KeyError, OSError):
            continue

    return None


# ---------------------------------------------------------------------------
# 样式映射
# ---------------------------------------------------------------------------

def _qname(tag: str) -> str:
    """将 `ns:local` 格式转为完整的 Clark 记号。"""
    if ":" in tag:
        prefix, local = tag.split(":", 1)
        ns = _NS.get(prefix, "")
        return f"{{{ns}}}{local}"
    return tag


def _map_style(style_id: str | None) -> str:
    """将 DOCX 样式 ID 映射到我们的样式名。"""
    if not style_id:
        return "Normal"

    name = style_id.lower()

    if "title" in name:
        return "Title"
    if "heading" in name or "标题" in name:
        # 尝试提取数字
        m = re.search(r"(\d+)", name)
        if m:
            n = int(m.group(1))
            if n == 1:
                return "Heading 1"
            elif n == 2:
                return "Heading 2"
            else:
                return "Heading 3"
        return "Heading 2"

    return "Normal"


def _style_to_level(style: str) -> int:
    """样式名 → 层级编号。"""
    if style in ("Title", "Heading 1"):
        return 1
    if style == "Heading 2":
        return 1
    return 2


def _heading_text_to_style(style: str, level: int) -> str:
    """从样式名和层级推导 Heading 样式名（用于表格后恢复标题）。"""
    if style.startswith("Heading"):
        return style
    if level <= 1:
        return "Heading 2"
    return "Heading 3"


# ======================================================================
# 干净段落版本（无分块标记，供 pipeline.py 使用）
# ======================================================================

def parse_docx_fast_clean(
    docx_path: Path,
    image_dir: Optional[Path] = None,
) -> tuple[list[dict], str]:
    """使用 python-docx 解析 DOCX，输出干净段落（无 *** / <-split-> 标记）。

    与 parse_docx_fast() 的区别：
    - 输出段落有 style/level 但无分块标记文本
    - 分块标记由后续的 ChunkingStrategy 统一插入
    """
    from docx import Document

    doc = Document(str(docx_path))
    paragraphs: list[dict] = []

    if image_dir is None:
        image_dir = docx_path.parent / "images"
    image_dir = Path(image_dir)
    image_dir.mkdir(parents=True, exist_ok=True)

    image_counter = 0

    try:
        zf = zipfile.ZipFile(str(docx_path), "r")
    except Exception:
        zf = None

    body = doc.element.body
    children = list(body)

    rels_map: dict[str, str] = {}
    try:
        for rel in doc.part.rels.values():
            rels_map[rel.rId] = rel.target_ref
    except Exception:
        pass

    doc_title = _find_doc_title(children)

    body_buf: list[str] = []
    pending_heading = ""

    def _flush_body_clean():
        nonlocal body_buf, pending_heading
        if pending_heading:
            if body_buf:
                body_buf[0] = pending_heading + "\n" + body_buf[0]
            else:
                body_buf.append(pending_heading)
            pending_heading = ""

        if body_buf:
            from parsing.fast_pdf_parser import _merge_body_into_paragraphs
            merged = _merge_body_into_paragraphs(body_buf)
            for para in merged:
                if para.strip():
                    paragraphs.append({"text": para, "style": "Normal", "level": 0})
            body_buf.clear()

    toc_start, toc_end = _find_toc_range(children)
    if toc_start >= 0:
        logger.info(f"  [快解析] 检测到目录 (第 {toc_start}~{toc_end - 1} 段)，已跳过")

    total = len(children)

    for i, child in enumerate(children):
        if toc_start >= 0 and toc_start <= i < toc_end:
            continue
        tag = _local_tag(child)

        if tag == "p":
            para_text = _extract_text_from_para(child)
            para_style = _extract_style(child)
            image_rids = _extract_image_rids(child)
            is_bold = _is_para_bold(child)

            is_para_heading = (
                para_style.startswith("Heading")
                or para_style == "Title"
                or (para_style == "Normal" and is_bold)
                or _is_heading_by_content(para_text)
            )

            has_image = False
            for rid in image_rids:
                rel_target = rels_map.get(rid, "")
                img_path = _save_image_from_zip(zf, rel_target, image_dir, docx_path.stem, image_counter)
                if img_path:
                    image_counter += 1
                    _flush_body_clean()
                    caption = para_text if para_text else ""
                    paragraphs.append({
                        "text": caption,
                        "style": "Normal",
                        "level": 0,
                        "image": {
                            "type": "image",
                            "path": str(img_path),
                            "caption": caption,
                        },
                    })
                    has_image = True

            if has_image:
                continue

            if not para_text:
                continue

            if is_para_heading:
                _flush_body_clean()
                heading_level = _style_to_level(para_style) if para_style.startswith("Heading") else 1
                heading_style_name = para_style if para_style.startswith("Heading") else ("Heading 2" if heading_level == 1 else "Heading 3")
                if para_style == "Title":
                    heading_style_name = "Title"
                paragraphs.append({
                    "text": para_text,
                    "style": heading_style_name,
                    "level": heading_level,
                })
            else:
                body_buf.append(para_text)

        elif tag == "tbl":
            _flush_body_clean()
            rows: list[list[str]] = []
            for tr in child.iter(_qname("w:tr")):
                row_texts: list[str] = []
                for tc in tr.iter(_qname("w:tc")):
                    cell_texts = []
                    for t in tc.iter(_qname("w:t")):
                        if t.text:
                            cell_texts.append(t.text)
                    row_texts.append("".join(cell_texts).strip())
                if row_texts:
                    rows.append(row_texts)

            if rows:
                for row in rows:
                    row_text = " | ".join(row)
                    paragraphs.append({"text": row_text, "style": "Normal", "level": 0})

    _flush_body_clean()

    if zf:
        zf.close()

    if not doc_title:
        doc_title = docx_path.stem

    return paragraphs, doc_title

