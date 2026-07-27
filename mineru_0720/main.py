"""
文档 → DOCX 转换主程序。

支持 PDF、DOCX 输入格式。
根据文件内容复杂度自动选择处理路径：
  - 纯文字文件 → 快路径（PyMuPDF / python-docx 直接提取）
  - 含图/表的复杂文件 → minerU 路径（结构化解析）

处理顺序：解析 → 生成干净段落 → 分块（可插拔策略）→ 生成 DOCX

用法:
    python main.py                          # 处理 data/pdf 下所有文件
    python main.py -i input.pdf             # 处理单个文件
    python main.py -i data/pdf -o output    # 指定输入输出目录
    python main.py --backend pipeline       # 使用 pipeline 后端
    python main.py --force-mineru           # 强制使用 minerU
    python main.py --force-fast             # 强制使用快路径
    python main.py --chunking-strategy none # 无分块输出
    python main.py -i input.pdf --chunking-strategy none
    python main.py -i input.pdf --chunking-strategy default
    python main.py -i input.pdf --chunking-strategy unstructured
"""



import argparse
import sys
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
    PDF_DIR,
    OUTPUT_DIR,
    ROUTE_STRATEGY,
    SUPPORTED_INPUT_EXTENSIONS,
    CHUNKING_STRATEGY,
)
from pipeline import process_batch
from chunking import list_strategies


def configure_logger(verbose: bool = False) -> None:
    """配置日志输出。"""
    logger.remove()
    level = "DEBUG" if verbose else "INFO"
    logger.add(
        sys.stderr,
        level=level,
        format=(
            "<green>{time:HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<level>{message}</level>"
        ),
    )


def main():
    parser = argparse.ArgumentParser(
        description="文档 → DOCX 转换（解析 → 分块 → 生成）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python main.py                                    # 处理 data/pdf 下所有文件
  python main.py -i input.pdf                       # 处理单个 PDF
  python main.py -i input.docx                      # 处理单个 DOCX
  python main.py -i data/pdf -o output/docx         # 指定输入输出
  python main.py --backend pipeline                 # 使用 pipeline 后端
  python main.py --force-mineru                     # 强制使用 minerU 路径
  python main.py --force-fast                       # 强制使用快路径
  python main.py --chunking-strategy none           # 无分块输出
  python main.py --chunking-strategy default        # 默认分块（*** + <-split->）
  python main.py --list-chunking-strategies         # 列出可用分块策略
        """,
    )
    parser.add_argument(
        "-i", "--input", type=str, default=None,
        help=f"输入文件或目录（默认: {PDF_DIR}）",
    )
    parser.add_argument(
        "-o", "--output", type=str, default=None,
        help=f"输出目录（默认: {OUTPUT_DIR}）",
    )
    parser.add_argument(
        "-b", "--backend", type=str, default=BACKEND,
        choices=["pipeline", "vlm-http-client", "hybrid-http-client",
                 "vlm-auto-engine", "hybrid-auto-engine"],
        help=f"minerU 后端引擎（默认: {BACKEND}）",
    )
    parser.add_argument(
        "-m", "--method", type=str, default=PARSE_METHOD,
        choices=["auto", "txt", "ocr"],
        help=f"解析方法（默认: {PARSE_METHOD}）",
    )
    parser.add_argument(
        "-l", "--lang", type=str, default=LANG,
        help=f"文档语言（默认: {LANG}）",
    )
    parser.add_argument(
        "--no-formula", action="store_true",
        help="禁用公式识别",
    )
    parser.add_argument(
        "--no-table", action="store_true",
        help="禁用表格识别",
    )
    parser.add_argument(
        "--start", type=int, default=START_PAGE_ID,
        help="起始页（0-based）",
    )
    parser.add_argument(
        "--end", type=int, default=None,
        help="结束页（0-based）",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="详细日志输出",
    )
    parser.add_argument(
        "--force-mineru", action="store_true",
        help="强制使用 minerU 路径（所有文件均经 minerU 结构化解析）",
    )
    parser.add_argument(
        "--force-fast", action="store_true",
        help="强制使用快路径（PyMuPDF / python-docx 直接提取）",
    )
    parser.add_argument(
        "--chunking-strategy", type=str, default=None,
        help=f"分块策略（默认: {CHUNKING_STRATEGY}）。可用: {', '.join(list_strategies())}",
    )
    parser.add_argument(
        "--list-chunking-strategies", action="store_true",
        help="列出所有可用的分块策略并退出",
    )

    args = parser.parse_args()

    if args.list_chunking_strategies:
        print("可用的分块策略:")
        for name in list_strategies():
            print(f"  - {name}")
        return

    if args.force_mineru and args.force_fast:
        logger.error("--force-mineru 和 --force-fast 不能同时使用")
        sys.exit(1)

    configure_logger(verbose=args.verbose)

    # 确定输入路径
    if args.input:
        input_path = Path(args.input)
    else:
        input_path = PDF_DIR

    if not input_path.exists():
        logger.error(f"输入路径不存在: {input_path}")
        sys.exit(1)

    # 确定输出目录
    output_dir = Path(args.output) if args.output else OUTPUT_DIR

    # 收集文件列表
    if input_path.is_file():
        input_files = [input_path]
    else:
        input_files: list[Path] = []
        for ext in SUPPORTED_INPUT_EXTENSIONS:
            input_files.extend(sorted(input_path.glob(f"*{ext}")))
            input_files.extend(sorted(input_path.glob(f"*{ext.upper()}")))

    if not input_files:
        logger.error(f"未找到支持的文件（{SUPPORTED_INPUT_EXTENSIONS}）: {input_path}")
        sys.exit(1)

    # 确定强制策略
    force_strategy: str | None = None
    if args.force_mineru:
        force_strategy = "mineru"
    elif args.force_fast:
        force_strategy = "fast"

    # 委托给 pipeline
    formula_enable = not args.no_formula
    table_enable = not args.no_table

    process_batch(
        input_files=input_files,
        output_dir=output_dir,
        backend=args.backend,
        parse_method=args.method,
        lang=args.lang,
        formula_enable=formula_enable,
        table_enable=table_enable,
        start_page_id=args.start,
        end_page_id=args.end,
        server_url=None,
        force_strategy=force_strategy,
        chunking_strategy=args.chunking_strategy,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    main()
