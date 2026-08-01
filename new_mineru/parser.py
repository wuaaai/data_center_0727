"""
MinerU 解析核心 — 封装 mineru.cli.common.do_parse，PDF 字节 → markdown 文本。

只做解析（pipeline backend 输出 .md），不做 DOCX 生成/入库，保持服务独立简洁。
"""
import os
import threading
import time
from pathlib import Path

import config

# 解析是否已加载（单例）
_model_loaded = False
_model_loading = False
_model_error = None
_load_lock = threading.Lock()
_start_time = time.time()


def load_model(blocking: bool = True) -> bool:
    """加载 MinerU 模型（HybridModelSingleton），可选阻塞等待。

    返回是否加载成功。模型只加载一次，线程安全。
    """
    global _model_loaded, _model_loading, _model_error
    with _load_lock:
        if _model_loaded:
            return True
        if _model_loading:
            if not blocking:
                return False
            # 已有加载线程，等待完成
        else:
            _model_loading = True
            _model_error = None

    if not blocking and _model_loading:
        return False

    try:
        from mineru.backend.pipeline.model_init import HybridModelSingleton
        HybridModelSingleton().get_model()
        with _load_lock:
            _model_loaded = True
        return True
    except Exception as e:
        with _load_lock:
            _model_error = str(e)
        print(f"[model] 模型加载失败: {e}")
        return False
    finally:
        with _load_lock:
            _model_loading = False


def model_status() -> dict:
    """返回模型加载状态（供健康检查/状态接口）。"""
    return {
        "model_loaded": _model_loaded,
        "model_loading": _model_loading,
        "model_error": _model_error,
        "backend": config.BACKEND,
        "model_path": str(config.MODEL_ROOT),
        "uptime": round(time.time() - _start_time, 1),
    }


def parse_pdf_to_markdown(pdf_bytes: bytes, filename: str, output_dir: Path = None) -> str:
    """解析 PDF 字节为 markdown 文本。

    参数:
        pdf_bytes: PDF 文件内容（字节）
        filename: 原始文件名（用于取 stem 和展示）
        output_dir: 输出目录（默认 config.OUTPUT_DIR 下的随机子目录）

    返回:
        markdown 文本字符串；解析失败抛异常。
    """
    from mineru.cli.common import do_parse

    stem = Path(filename).stem
    out_dir = output_dir or (config.OUTPUT_DIR / f"{int(time.time())}_{stem}")
    out_dir.mkdir(parents=True, exist_ok=True)

    # do_parse 会原地修改传入的 list，每次调用传新的
    do_parse(
        output_dir=str(out_dir),
        pdf_file_names=[stem],
        pdf_bytes_list=[pdf_bytes],
        p_lang_list=[config.LANG],
        backend=config.BACKEND,
        parse_method=config.PARSE_METHOD,
        formula_enable=config.FORMULA_ENABLE,
        table_enable=config.TABLE_ENABLE,
        server_url=None,
        f_draw_layout_bbox=False,
        f_draw_span_bbox=False,
        f_dump_md=True,
        f_dump_middle_json=config.DUMP_MIDDLE_JSON,
        f_dump_model_output=False,
        f_dump_orig_pdf=False,
        f_dump_content_list=config.DUMP_CONTENT_LIST,
        start_page_id=config.START_PAGE_ID,
        end_page_id=config.END_PAGE_ID,
    )

    return _read_markdown_from_dir(out_dir, stem)


def _read_markdown_from_dir(out_dir: Path, stem: str) -> str:
    """从 do_parse 输出目录读取 .md 文件。

    pipeline 后端输出在 {out}/{stem}/{parse_method}/{stem}.md。
    找不到则递归搜索任意 .md。
    """
    # 常见输出子目录
    candidates = [
        out_dir / stem / config.PARSE_METHOD / f"{stem}.md",
        out_dir / stem / "vlm" / f"{stem}.md",
        out_dir / stem / f"hybrid_{config.PARSE_METHOD}" / f"{stem}.md",
        out_dir / stem / "office" / f"{stem}.md",
    ]
    for c in candidates:
        if c.exists():
            return c.read_text(encoding="utf-8")

    # 递归兜底
    for md in out_dir.rglob("*.md"):
        return md.read_text(encoding="utf-8")
    return ""
