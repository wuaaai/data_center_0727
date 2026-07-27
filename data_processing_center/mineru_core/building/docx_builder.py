"""
DOCX 生成模块：将分块后的文本内容写入 Word 文档。
"""

import re
from pathlib import Path

from docx import Document
from docx.shared import Cm, Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from tqdm import tqdm


# XML 不允许的控制字符（除 \t \n \r 外）
_INVALID_XML_CHARS_RE = re.compile(
    "[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]"
)


def _clean_xml_text(text: str) -> str:
    """移除 XML 不允许的控制字符。"""
    return _INVALID_XML_CHARS_RE.sub("", text).strip()

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

from config import (
    PAGE_WIDTH_CM,
    PAGE_HEIGHT_CM,
    MARGIN_TOP_CM,
    MARGIN_BOTTOM_CM,
    MARGIN_LEFT_CM,
    MARGIN_RIGHT_CM,
    FONT_NAME,
    FONT_SIZE_PT,
    TITLE_FONT_NAME,
    TITLE_FONT_SIZE_PT,
    H1_FONT_NAME,
    H1_FONT_SIZE_PT,
    H2_FONT_NAME,
    H2_FONT_SIZE_PT,
    LINE_SPACING,
    INCLUDE_IMAGES,
)


def _set_page_config(doc: Document) -> None:
    """配置页面尺寸和页边距。"""
    for section in doc.sections:
        section.page_width = Cm(PAGE_WIDTH_CM)
        section.page_height = Cm(PAGE_HEIGHT_CM)
        section.top_margin = Cm(MARGIN_TOP_CM)
        section.bottom_margin = Cm(MARGIN_BOTTOM_CM)
        section.left_margin = Cm(MARGIN_LEFT_CM)
        section.right_margin = Cm(MARGIN_RIGHT_CM)


def _set_run_font(
    run,
    font_name: str = FONT_NAME,
    font_size_pt: float = FONT_SIZE_PT,
    bold: bool = False,
) -> None:
    """设置 run 的字体属性（同时设置西文和中文字体）。"""
    run.font.size = Pt(font_size_pt)
    run.font.name = font_name
    run.bold = bold
    # 设置中文字体（东亚字体）
    r = run._element
    rPr = r.find(qn("w:rPr"))
    if rPr is None:
        rPr = r.makeelement(qn("w:rPr"), {})
        r.insert(0, rPr)
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = rPr.makeelement(qn("w:rFonts"), {})
        rPr.insert(0, rFonts)
    rFonts.set(qn("w:eastAsia"), font_name)
    rFonts.set(qn("w:ascii"), font_name)
    rFonts.set(qn("w:hAnsi"), font_name)


def _set_paragraph_spacing(paragraph, line_spacing: float = LINE_SPACING) -> None:
    """设置段落行间距。"""
    pf = paragraph.paragraph_format
    pf.line_spacing = line_spacing
    pf.space_before = Pt(0)
    pf.space_after = Pt(0)


def _add_styled_paragraph(
    doc: Document,
    text: str,
    font_name: str = FONT_NAME,
    font_size_pt: float = FONT_SIZE_PT,
    bold: bool = False,
    alignment: int = WD_ALIGN_PARAGRAPH.LEFT,
    line_spacing: float = LINE_SPACING,
) -> None:
    """添加带样式的段落。"""
    text = _clean_xml_text(text)
    if not text:
        return
    para = doc.add_paragraph()
    para.alignment = alignment
    _set_paragraph_spacing(para, line_spacing)
    run = para.add_run(text)
    _set_run_font(run, font_name, font_size_pt, bold)
    return para


def _add_title(doc: Document, text: str) -> None:
    """添加文档标题。"""
    _add_styled_paragraph(
        doc,
        text,
        font_name=TITLE_FONT_NAME,
        font_size_pt=TITLE_FONT_SIZE_PT,
        bold=True,
        alignment=WD_ALIGN_PARAGRAPH.CENTER,
        line_spacing=1.5,
    )


def _add_heading1(doc: Document, text: str) -> None:
    """添加一级标题（黑体三号加粗）。"""
    _add_styled_paragraph(
        doc,
        text,
        font_name=H1_FONT_NAME,
        font_size_pt=H1_FONT_SIZE_PT,
        bold=True,
    )


def _add_heading2(doc: Document, text: str) -> None:
    """添加二级标题（楷体三号加粗）。"""
    _add_styled_paragraph(
        doc,
        text,
        font_name=H2_FONT_NAME,
        font_size_pt=H2_FONT_SIZE_PT,
        bold=True,
    )


def _add_body(doc: Document, text: str) -> None:
    """添加正文段落（仿宋三号）。"""
    _add_styled_paragraph(
        doc,
        text,
        font_name=FONT_NAME,
        font_size_pt=FONT_SIZE_PT,
        bold=False,
    )


def _add_split_marker(doc: Document, text: str = "<-split->") -> None:
    """添加分块标记段落。"""
    _add_body(doc, text)


def build_docx(
    paragraphs: list[dict],
    doc_title: str,
    output_path: Path,
    pdf_stem: str = "",
    image_dir: Path | None = None,
) -> Path:
    """
    根据段落数据生成 DOCX 文件。

    Parameters
    ----------
    paragraphs : list[dict]
        段落数据列表，每项包含:
          - text: 文本内容
          - style: 样式名 (Title / Heading 1 / Heading 2 / Normal)
          - image: (可选) 图片信息 dict {'path': str, 'caption': str}
    doc_title : str
        文档标题。
    output_path : Path
        输出 DOCX 文件路径。
    pdf_stem : str
        PDF 文件名（用于进度条描述）。
    image_dir : Path, optional
        图片文件所在目录（用于解析相对路径）。

    Returns
    -------
    Path
        生成的 DOCX 文件路径。
    """
    doc = Document()
    _set_page_config(doc)

    # 可用页面宽度（用于缩放图片）
    page_width = doc.sections[0].page_width - doc.sections[0].left_margin - doc.sections[0].right_margin

    # 写入文档标题
    if doc_title:
        _add_title(doc, doc_title)

    # 写入段落（带进度条）
    desc = f"  生成DOCX {pdf_stem}" if pdf_stem else "  生成DOCX"
    pbar = tqdm(
        paragraphs,
        desc=desc,
        unit="段",
        ncols=100,
        bar_format="{desc}: {percentage:3.0f}% |{bar}| {n_fmt}/{total_fmt}",
    )

    for pdata in pbar:
        text = pdata.get("text", "")
        style = pdata.get("style", "Normal")
        image_info = pdata.get("image")

        if style == "Title":
            _add_title(doc, text)
        elif style == "Heading 1":
            _add_heading1(doc, text)
        elif style == "Heading 2":
            _add_heading2(doc, text)
        elif text.strip() in ("<-split->", "***"):
            _add_split_marker(doc, text.strip())
        else:
            _add_body(doc, text)

        # 如果有图片且未设为 none 模式，嵌入图片
        if image_info and INCLUDE_IMAGES != "none":
            _add_image(doc, image_info, image_dir, page_width)

    pbar.close()

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(output_path))

    return output_path


def _add_image(
    doc: Document,
    image_info: dict,
    image_dir: Path | None,
    max_width,
) -> None:
    """在文档中嵌入图片（居中对齐，自适应宽度）。"""
    rel_path = image_info.get("path", "")
    if not rel_path:
        return

    # 尝试多种路径组合定位图片文件
    candidates = []
    if image_dir:
        candidates.append(image_dir / Path(rel_path).name)
        candidates.append(image_dir / rel_path)
    candidates.append(Path(rel_path))

    img_file = None
    for c in candidates:
        if c.exists():
            img_file = c
            break

    if img_file is None:
        # 图片文件找不到，仅输出文本引用
        caption = image_info.get("caption", "")
        para = doc.add_paragraph()
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = para.add_run(f"[图片] {caption}" if caption else "[图片：文件未找到]")
        run.font.size = Pt(10)
        run.italic = True
        return

    try:
        para = doc.add_paragraph()
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = para.add_run()
        run.add_picture(
            str(img_file),
            width=max_width,
        )
    except Exception:
        # 图片格式不兼容时回退为文本
        caption = image_info.get("caption", "")
        para = doc.add_paragraph()
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = para.add_run(f"[图片] {caption}" if caption else "[图片]")
        run.font.size = Pt(10)
        run.italic = True
