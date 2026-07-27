"""
流水线编排模块：Parse → Chunk → Build DOCX。

分块作为可插拔的后处理步骤，支持通过 config.CHUNKING_STRATEGY
或 CLI --chunking-strategy 选择策略。

"default" 策略直接使用原始、已验证的旧逻辑（chunk_content_list +
chunks_to_paragraphs），保证输出 100% 一致。
其他策略使用新架构：干净段落 → 分块 → 生成 DOCX。
"""

import sys
import time
from pathlib import Path

from loguru import logger

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import (
    BACKEND,
    PARSE_METHOD,
    LANG,
    FORMULA_ENABLE,
    TABLE_ENABLE,
    START_PAGE_ID,
    END_PAGE_ID,
    OUTPUT_DIR,
    ROUTE_STRATEGY,
    SUPPORTED_INPUT_EXTENSIONS,
    CHUNKING_STRATEGY,
)
from detector import detect_strategy


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"


def _format_time(seconds: float) -> str:
    if seconds < 1:
        return f"{seconds * 1000:.0f} ms"
    elif seconds < 60:
        return f"{seconds:.1f}s"
    else:
        minutes = int(seconds // 60)
        secs = seconds % 60
        return f"{minutes}m {secs:.0f}s"


def process_single_file(
    file_path: Path,
    output_dir: Path,
    backend: str = BACKEND,
    parse_method: str = PARSE_METHOD,
    lang: str = LANG,
    formula_enable: bool = FORMULA_ENABLE,
    table_enable: bool = TABLE_ENABLE,
    start_page_id: int = START_PAGE_ID,
    end_page_id: int | None = END_PAGE_ID,
    server_url: str | None = None,
    file_index: int = 1,
    total_files: int = 1,
    force_strategy: str | None = None,
    chunking_strategy: str | None = None,
    verbose: bool = False,
) -> Path:
    """处理单个文件：路由 → 解析 → 分块 → 生成 DOCX。

    分块策略决定是否以及如何在 DOCX 中插入 *** / <-split-> 标记。
    "default" 策略直接使用原始旧逻辑，保证输出完全一致。
    """
    from chunking import get_strategy
    from building import build_docx

    file_stem = file_path.stem
    file_suffix = file_path.suffix.lower()
    file_size = file_path.stat().st_size

    # ========== 路由决策 ==========
    if force_strategy:
        route = force_strategy
        logger.info(f"  [路由] 强制使用: {route}")
    elif ROUTE_STRATEGY != "auto":
        route = ROUTE_STRATEGY
        logger.info(f"  [路由] 配置策略: {route}")
    else:
        t0 = time.perf_counter()
        route = detect_strategy(file_path)
        detect_time = time.perf_counter() - t0
        logger.info(f"  [路由] 自动检测 → {route} ({_format_time(detect_time)})")

    # ========== 确定分块策略 ==========
    chunk_name = chunking_strategy or CHUNKING_STRATEGY
    chunker = get_strategy(chunk_name)
    logger.info(f"  [分块] 策略: {chunker.name}")

    # ========== 文件头部信息 ==========
    header = f"[{file_index}/{total_files}] {file_path.name}"
    logger.info("=" * 70)
    logger.info(f"{header}")
    logger.info(f"  文件大小: {_format_size(file_size)} | 类型: {file_suffix}")
    logger.info(f"  路径: {route} | 后端: {backend} | 分块: {chunker.name}")

    step_times: dict[str, float] = {}

    # ========== 快路径 ==========
    if route == "fast":
        return _process_fast_path(
            file_path=file_path,
            output_dir=output_dir,
            file_stem=file_stem,
            file_index=file_index,
            total_files=total_files,
            chunker=chunker,
        )

    # ========== minerU 路径 ==========
    from parsing import parse_pdf, load_content_list

    if file_suffix not in (".pdf",):
        logger.warning(f"  minerU 路径仅支持 PDF，{file_suffix} 文件将尝试作为 PDF 解析")

    # Step 1: PDF 解析
    t0 = time.perf_counter()
    logger.info("  [1/4] PDF 解析中...")
    parse_dir = parse_pdf(
        pdf_path=file_path,
        output_dir=output_dir,
        backend=backend,
        parse_method=parse_method,
        lang=lang,
        formula_enable=formula_enable,
        table_enable=table_enable,
        start_page_id=start_page_id,
        end_page_id=end_page_id,
        server_url=server_url,
    )
    step_times["PDF解析"] = time.perf_counter() - t0
    logger.info(f"  [1/4] PDF 解析完成 ({_format_time(step_times['PDF解析'])})")

    # Step 2: 加载内容列表
    t0 = time.perf_counter()
    content_list = load_content_list(parse_dir, file_stem)
    step_times["加载内容"] = time.perf_counter() - t0
    logger.info(
        f"  [2/4] 加载内容列表 ({_format_time(step_times['加载内容'])}) - "
        f"{len(content_list)} 个内容块"
    )

    # Step 3+4: 分块 + 生成段落（根据策略分支）
    doc_title_full = f"《{file_stem}》"

    if chunker.name == "default":
        # ═══ 原始旧逻辑：chunk_content_list + chunks_to_paragraphs ═══
        # 保证输出与重构前 100% 一致
        from text_chunker import chunk_content_list, chunks_to_paragraphs

        t0 = time.perf_counter()
        chunk_result = chunk_content_list(content_list, pdf_stem=file_stem)
        step_times["文本分块"] = time.perf_counter() - t0
        logger.info(
            f"  [3/5] 文本分块完成 ({_format_time(step_times['文本分块'])}) - "
            f"{len(chunk_result.chunks)} 个父子块"
        )

        t0 = time.perf_counter()
        paragraphs = chunks_to_paragraphs(chunk_result.chunks, pdf_stem=file_stem)
        step_times["段落生成"] = time.perf_counter() - t0
        logger.info(
            f"  [4/5] 段落生成完成 ({_format_time(step_times['段落生成'])}) - "
            f"{len(paragraphs)} 个段落"
        )

        if chunk_result.doc_title:
            doc_title_full = chunk_result.doc_title
    else:
        # ═══ 新架构：干净段落 → 策略分块 ═══
        from parsing import content_list_to_clean_paragraphs
        from chunking.strategy import ChunkContext

        t0 = time.perf_counter()
        clean_paragraphs, doc_title_clean, total_pages = content_list_to_clean_paragraphs(
            content_list, pdf_stem=file_stem,
        )
        step_times["干净段落"] = time.perf_counter() - t0
        logger.info(
            f"  [3/4] 干净段落生成 ({_format_time(step_times['干净段落'])}) - "
            f"{len(clean_paragraphs)} 个段落"
        )

        t0 = time.perf_counter()
        context = ChunkContext(
            doc_title=doc_title_clean,
            pdf_stem=file_stem,
            total_pages=total_pages,
            image_dir=str(parse_dir / "images"),
        )
        paragraphs = chunker.chunk(clean_paragraphs, context)
        step_times["分块"] = time.perf_counter() - t0
        logger.info(
            f"  [4/4] 分块完成 ({_format_time(step_times['分块'])}) - "
            f"策略: {chunker.name}"
        )

    # Step 5: 生成 DOCX
    t0 = time.perf_counter()
    docx_path = output_dir / f"{file_stem}.docx"

    build_docx(
        paragraphs=paragraphs,
        doc_title=doc_title_full,
        output_path=docx_path,
        pdf_stem=file_stem,
        image_dir=parse_dir / "images",
    )
    step_times["DOCX生成"] = time.perf_counter() - t0

    docx_size = docx_path.stat().st_size
    logger.info(
        f"  [5/5] DOCX 生成完成 ({_format_time(step_times['DOCX生成'])}) - "
        f"输出: {_format_size(docx_size)}"
    )

    total_time = sum(step_times.values())
    logger.info(f"  >> 总耗时: {_format_time(total_time)} | 输出: {docx_path}")

    return docx_path


def _process_fast_path(
    file_path: Path,
    output_dir: Path,
    file_stem: str,
    file_index: int,
    total_files: int,
    chunker,
) -> Path:
    """快路径处理。default 策略走原始旧逻辑，其他走新架构。"""
    from building import build_docx

    step_times: dict[str, float] = {}
    suffix = file_path.suffix.lower()
    doc_title_full = f"《{file_stem}》"

    # Step 1: 快路径解析
    t0 = time.perf_counter()
    logger.info("  [1/3] 快路径解析中...")

    # "default" 走旧逻辑输出标记段落，"none"/"unstructured" 等走干净段落+分块
    use_clean = chunker.name != "default"

    if suffix == ".pdf":
        from parsing.fast_pdf_parser import parse_pdf_fast
        paragraphs, doc_title_raw = parse_pdf_fast(file_path, clean=use_clean)
        image_dir = None
    elif suffix in (".docx", ".doc"):
        image_dir = output_dir / f"{file_stem}_images"
        if use_clean:
            from parsing.fast_docx_parser import parse_docx_fast_clean
            paragraphs, doc_title_raw = parse_docx_fast_clean(file_path, image_dir=image_dir)
        else:
            from parsing.fast_docx_parser import parse_docx_fast
            paragraphs, doc_title_raw = parse_docx_fast(file_path, image_dir=image_dir)
    else:
        raise ValueError(f"快路径不支持的文件格式: {suffix}")

    if doc_title_raw:
        doc_title_full = doc_title_raw

    if use_clean:
        from chunking.strategy import ChunkContext
        context = ChunkContext(
            doc_title=doc_title_full,
            pdf_stem=file_stem,
            image_dir=str(image_dir) if image_dir else None,
        )
        paragraphs = chunker.chunk(paragraphs, context)

    step_times["快解析"] = time.perf_counter() - t0
    logger.info(
        f"  [1/3] 快解析完成 ({_format_time(step_times['快解析'])}) - "
        f"{len(paragraphs)} 个段落"
    )

    # Step 2: 生成 DOCX
    t0 = time.perf_counter()
    docx_path = output_dir / f"{file_stem}.docx"

    build_docx(
        paragraphs=paragraphs,
        doc_title=doc_title_full,
        output_path=docx_path,
        pdf_stem=file_stem,
        image_dir=image_dir if suffix in (".docx", ".doc") else None,
    )
    step_times["DOCX生成"] = time.perf_counter() - t0

    docx_size = docx_path.stat().st_size
    logger.info(
        f"  [2/3] DOCX 生成完成 ({_format_time(step_times['DOCX生成'])}) - "
        f"输出: {_format_size(docx_size)}"
    )

    total_time = sum(step_times.values())
    logger.info(f"  >> 总耗时: {_format_time(total_time)} | 输出: {docx_path}")
    logger.info(f"-----------------------------------------------------------------------------------------------")

    return docx_path


def process_batch(
    input_files: list[Path],
    output_dir: Path,
    **kwargs,
) -> tuple[int, list[str]]:
    """批量处理文件。返回 (成功数, 失败列表)。"""
    success_count = 0
    fail_list: list[str] = []
    total_start = time.perf_counter()
    total_size = sum(f.stat().st_size for f in input_files)

    logger.info("=" * 70)
    logger.info("文档 → DOCX 转换器")
    logger.info(f"  待处理: {len(input_files)} 个文件")
    logger.info(f"  总大小:  {_format_size(total_size)}")
    if kwargs.get("force_strategy"):
        logger.info(f"  策略:    {kwargs['force_strategy']}（强制）")
    else:
        logger.info(f"  策略:    {ROUTE_STRATEGY}")
    logger.info(f"  后端:    {kwargs.get('backend', BACKEND)}")
    logger.info(f"  分块:    {kwargs.get('chunking_strategy', CHUNKING_STRATEGY)}")
    logger.info(f"  输出:    {output_dir}")
    logger.info("=" * 70)

    for i, file_path in enumerate(input_files, start=1):
        try:
            process_single_file(
                file_path=file_path,
                output_dir=output_dir,
                file_index=i,
                total_files=len(input_files),
                **kwargs,
            )
            success_count += 1
        except Exception as e:
            logger.error(f"  >>> 处理失败: {file_path.name} — {e}")
            fail_list.append(file_path.name)
            if kwargs.get("verbose"):
                import traceback
                traceback.print_exc()

    total_time = time.perf_counter() - total_start
    logger.info("=" * 70)
    logger.info("处理完成")
    logger.info(f"  成功: {success_count}/{len(input_files)}")
    logger.info(f"  失败: {len(fail_list)}/{len(input_files)}")
    logger.info(f"  总耗时: {_format_time(total_time)}")
    if fail_list:
        logger.info(f"  失败文件: {', '.join(fail_list)}")
    logger.info("=" * 70)

    return success_count, fail_list
