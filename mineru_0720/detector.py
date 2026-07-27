"""
路由决策模块：分析输入文件的内容复杂度，选择最优处理路径。

策略:
- DOCX: 始终使用快路径（minerU 无法处理 DOCX，python-docx 原生支持最好）
- PDF: 含图片/文本极少的扫描件 → minerU；纯文字 → fast
"""

from pathlib import Path

from loguru import logger

from config import DETECT_SAMPLE_PAGES, DETECT_MIN_TEXT_PER_PAGE


def detect_strategy(file_path: Path) -> str:
    """分析文件内容复杂度，返回处理策略。

    Returns
    -------
    str
        "fast" — 使用 PyMuPDF / python-docx 直接提取
        "mineru" — 使用 minerU 进行结构化解析（仅 PDF）
    """
    suffix = file_path.suffix.lower()

    if suffix == ".pdf":
        return _detect_pdf(file_path)
    elif suffix in (".docx", ".doc"):
        # DOCX 始终走快路径 — minerU 只能处理 PDF
        return "fast"
    else:
        # 未知格式，回退到 minerU（尝试解析）
        logger.warning(f"未知文件格式 {suffix}，默认使用 minerU")
        return "mineru"


# ---- PDF 检测 ----

def _detect_pdf(file_path: Path) -> str:
    """使用 PyMuPDF 扫描 PDF，判断内容复杂度。"""
    try:
        import fitz
    except ImportError:
        logger.warning("PyMuPDF 未安装，回退到 minerU")
        return "mineru"

    doc = None
    try:
        doc = fitz.open(str(file_path))
        total_pages = doc.page_count

        if total_pages == 0:
            return "mineru"

        # 采样：扫描前 DETECT_SAMPLE_PAGES 页
        sample_pages = min(DETECT_SAMPLE_PAGES, total_pages)
        has_images = False
        total_text_chars = 0
        pages_with_text = 0

        for page_idx in range(sample_pages):
            page = doc[page_idx]

            # 检查图片
            images = page.get_images()
            if images:
                has_images = True
                break

            # 提取文本
            text = page.get_text()
            text_len = len(text.strip())
            total_text_chars += text_len
            if text_len > 0:
                pages_with_text += 1

        if has_images:
            logger.info(
                f"  [检测] PDF 含图片 → 使用 minerU（采样 {sample_pages}/{total_pages} 页）"
            )
            return "mineru"

        # 检查平均文本量（扫描件通常每页文字极少）
        avg_text = total_text_chars / max(sample_pages, 1)
        if avg_text < DETECT_MIN_TEXT_PER_PAGE:
            logger.info(
                f"  [检测] PDF 文本量过低（{avg_text:.0f} 字/页）→ 疑似扫描件，使用 minerU"
            )
            return "mineru"

        if pages_with_text == 0:
            logger.info("  [检测] PDF 无可提取文本 → 疑似扫描件，使用 minerU")
            return "mineru"

        logger.info(
            f"  [检测] PDF 无图片，文本量正常（{avg_text:.0f} 字/页）→ 使用快路径"
        )
        return "fast"

    except Exception as e:
        logger.warning(f"PDF 检测失败: {e}，回退到 minerU")
        return "mineru"
    finally:
        if doc is not None:
            doc.close()


