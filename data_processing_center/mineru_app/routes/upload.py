"""
文件上传 + MinerU 处理路由（线程池队列，限制并发数）。
"""

import time
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import APIRouter, Request, UploadFile, File
from fastapi.responses import JSONResponse

from mineru_app import state_manager
from mineru_app.config import (
    UPLOAD_DIR,
    OUTPUT_DIR,
    ALLOWED_EXTENSIONS,
    MAX_FILE_SIZE_MB,
)

router = APIRouter(prefix="/api", tags=["upload"])

# 线程池：最多同时处理 3 个文件，其余排队
_MAX_WORKERS = 3
_executor = ThreadPoolExecutor(max_workers=_MAX_WORKERS)
_pool_lock = threading.Lock()
_pending_count = 0


def _get_queue_status() -> dict:
    """获取当前队列状态（用于统计）。"""
    with _pool_lock:
        return {"pending": _pending_count}


def _count_chunks(docx_path: Path) -> int:
    """统计 DOCX 中 *** 标记的数量，估算 chunk 数。"""
    try:
        from docx import Document as DocxDocument
        doc = DocxDocument(str(docx_path))
        count = 0
        for para in doc.paragraphs:
            if "***" in para.text:
                count += 1
        return count
    except Exception:
        return 0


def _extract_preview_text(docx_path: Path, max_lines: int = 200) -> str:
    """从 DOCX 提取纯文本用于预览。"""
    try:
        from docx import Document as DocxDocument
        doc = DocxDocument(str(docx_path))
        lines = []
        for para in doc.paragraphs:
            text = para.text.strip()
            if text:
                lines.append(text)
            if len(lines) >= max_lines:
                lines.append("... (预览截断，完整内容请下载查看)")
                break
        return "\n".join(lines)
    except Exception as e:
        return f"[预览提取失败: {e}]"


def _process_document_background(job_id: str, input_path: Path, filename: str):
    """后台处理：排队 → 处理 → 完成，由线程池调度。"""
    global _pending_count
    try:
        # 标记排队（线程池已调度，但可能还在等待空闲 worker）
        state_manager.update_job(job_id, status="queued", progress="排队等待处理...")
        with _pool_lock:
            _pending_count -= 1

        state_manager.update_job(job_id, status="processing", progress="初始化 MinerU...")

        job_output_dir = OUTPUT_DIR / job_id
        job_output_dir.mkdir(parents=True, exist_ok=True)

        from loguru import logger
        handler_id = logger.add(
            lambda msg: _on_progress(job_id, msg),
            level="INFO",
            format="{message}",
        )

        t_start = time.perf_counter()

        try:
            from main import process_single_file

            result_path = process_single_file(
                file_path=input_path,
                output_dir=job_output_dir,
            )
        finally:
            logger.remove(handler_id)

        elapsed = time.perf_counter() - t_start
        chunk_count = _count_chunks(result_path)
        preview_text = _extract_preview_text(result_path)

        state_manager.update_job(
            job_id,
            status="completed",
            output_path=str(result_path),
            progress="处理完成",
            chunk_count=chunk_count,
            processing_time=round(elapsed, 1),
            preview_text=preview_text,
        )

    except Exception as e:
        import traceback
        state_manager.update_job(
            job_id,
            status="failed",
            error=str(e),
            progress=f"处理失败: {e}",
        )
        traceback.print_exc()


def _on_progress(job_id: str, msg):
    """loguru 消息回调：提取步骤信息更新进度。"""
    record = msg.record
    text = record["message"]
    if any(kw in text for kw in ["[路由]", "[1/", "[2/", "[3/", "[4/", "[5/",
                                   "PDF 解析", "加载内容", "文本分块", "段落生成",
                                   "生成 DOCX"]):
        state_manager.update_job(job_id, progress=text)


def _save_and_start(file_bytes: bytes, filename: str) -> dict:
    """保存文件并提交到线程池排队处理。"""
    global _pending_count

    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return {"error": f"不支持的文件格式: {ext}"}

    file_size = len(file_bytes)
    max_bytes = MAX_FILE_SIZE_MB * 1024 * 1024
    if file_size > max_bytes:
        return {"error": f"文件过大: {file_size / 1024 / 1024:.1f}MB"}

    job_id = state_manager.create_job(
        filename=filename,
        file_size=file_size,
        input_path="",
    )

    job_dir = UPLOAD_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    input_path = job_dir / filename

    with open(input_path, "wb") as f:
        f.write(file_bytes)

    state_manager.update_job(job_id, input_path=str(input_path), status="queued")

    with _pool_lock:
        _pending_count += 1

    _executor.submit(_process_document_background, job_id, input_path, filename)

    return {"job_id": job_id, "status": "queued", "filename": filename}


@router.post("/upload")
async def upload_file(
    request: Request,
    files: list[UploadFile] = File(...),
):
    """上传文档并提交到处理队列。支持单文件或多文件上传。"""
    if not files:
        return JSONResponse({"error": "未选择文件"}, status_code=400)

    results = []
    errors = []

    for file in files:
        if not file.filename:
            continue

        content = await file.read()
        result = _save_and_start(content, file.filename)

        if "error" in result:
            errors.append({"filename": file.filename, "error": result["error"]})
        else:
            results.append(result)

    return JSONResponse({
        "jobs": results,
        "errors": errors,
        "total": len(results),
        "failed": len(errors),
    })
