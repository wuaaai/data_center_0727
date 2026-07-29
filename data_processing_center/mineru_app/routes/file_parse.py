"""
统一文档解析路由 — 接口格式对齐内网 Maas。

POST   /file-parse                   - 提交解析 (对齐 Maas: files + format)
GET    /file-parse/{task_id}         - 查询状态
GET    /file-parse/{task_id}/progress - SSE 实时进度
GET    /file-parse/queue             - 队列状态
POST   /file-parse/{task_id}/cancel  - 取消任务

Maas 内网接口格式:
  curl -X POST ".../file_parse" \
    -F "files=@./xxx.pdf" \
    -F "format=markdown"

返回格式 (对齐 Maas):
  {"code": 200, "task_id": "...", "status": "queued", "filename": "..."}

设计决策:
  - 本地 MinerU 的 parse_pdf() 本身就产出 .md 中间文件。
    本接口解析完成后读取 .md 内容作为 markdown 字段返回，
    同时后台继续 build_docx() 流水线生成 DOCX 供下游 rag_ingest.py 切片入库。
  - 旧路由 POST /api/parse 保留不删，dcp 逐步迁移到 /file-parse。
"""
import os
import time
import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, Form, UploadFile, File
from fastapi.responses import JSONResponse, StreamingResponse

from mineru_app.model_manager import model_manager
from mineru_app.config import ALLOWED_EXTENSIONS, MAX_FILE_SIZE_MB, UPLOAD_DIR, OUTPUT_DIR

router = APIRouter(tags=["file_parse"])


# ── 辅助: 从 parse_pdf 输出目录读取 .md 内容 ──
def _read_markdown_output(parse_result_dir: Path, pdf_stem: str) -> str:
    """从 MinerU parse_pdf() 输出目录读取 .md 文件内容。"""
    md_path = parse_result_dir / f"{pdf_stem}.md"
    if md_path.exists():
        return md_path.read_text(encoding="utf-8")
    # 回退: 在其他子目录查找 (MinerU 有时输出到子目录)
    for md in parse_result_dir.rglob("*.md"):
        return md.read_text(encoding="utf-8")
    return ""


# ── SSE 进度事件流 ──
async def progress_events(task_id: str):
    """Server-Sent Events 流，推送任务实时进度。"""
    yield f"data: {json.dumps({'task_id': task_id, 'stage': 'init', 'message': '已连接'})}\n\n"
    last_progress = ""
    while True:
        task = model_manager.get_task(task_id)
        if not task:
            yield f"event: error\ndata: {json.dumps({'error': '任务不存在'})}\n\n"
            break
        if task.progress != last_progress:
            yield f"data: {json.dumps({'stage': task.status, 'message': task.progress, 'elapsed': task.elapsed})}\n\n"
            last_progress = task.progress
        if task.status in ("completed", "failed"):
            yield f"event: complete\ndata: {json.dumps({'task_id': task_id, 'status': task.status})}\n\n"
            break
        await asyncio.sleep(1)


# ── 路由 ──

@router.post("/file-parse", summary="统一文档解析入口（对齐 Maas 格式）")
async def file_parse(
    files: UploadFile = File(...),
    format: str = Form("markdown"),
):
    """
    提交文档到 MinerU 模型服务解析。

    参数格式对齐内网 Maas 的 /file_parse:
      -F "files=@./xxx.pdf"   文件 (PDF/DOCX/DOC)
      -F "format=markdown"    输出格式

    返回格式:
      {"code": 200, "task_id": "...", "status": "queued", "filename": "..."}

    解析完成后可通过 GET /file-parse/{task_id} 获取状态和 markdown 内容。
    """
    ext = Path(files.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return JSONResponse(
            {"code": 400, "error": f"不支持的文件格式: {ext}"}, status_code=400
        )

    content = await files.read()
    if len(content) > MAX_FILE_SIZE_MB * 1024 * 1024:
        return JSONResponse(
            {"code": 413, "error": f"文件过大: {len(content)/1024/1024:.1f}MB"},
            status_code=413,
        )

    # 保存临时文件
    task_dir = UPLOAD_DIR / "parse_tasks" / f"{int(time.time())}_{files.filename}"
    task_dir.mkdir(parents=True, exist_ok=True)
    input_path = task_dir / files.filename
    input_path.write_bytes(content)

    out_dir = task_dir / "output"
    out_dir.mkdir(parents=True, exist_ok=True)

    task_id = model_manager.submit(file_path=input_path, output_dir=out_dir)

    return JSONResponse({
        "code": 200,
        "task_id": task_id,
        "status": "queued",
        "filename": files.filename,
    }, status_code=202)


@router.get("/file-parse/{task_id}", summary="查询任务状态和结果")
async def get_task(task_id: str):
    """查询解析任务的状态、进度和结果。完成时包含 markdown 内容。"""
    task = model_manager.get_task(task_id)
    if not task:
        return JSONResponse({"code": 404, "error": "任务不存在"}, status_code=404)

    response = {
        "code": 200,
        "task_id": task.task_id,
        "status": task.status,
        "progress": task.progress,
        "progress_pct": task.progress_pct,
        "elapsed": task.elapsed,
    }

    if task.status == "completed":
        # 回读 MinerU 输出的 .md 文件作为 markdown 字段
        markdown = ""
        if task.result_path:
            result_path = Path(task.result_path)
            pdf_stem = result_path.stem  # 去掉 .docx 后缀 即原始 stem
            markdown = _read_markdown_output(result_path.parent, pdf_stem)
            # 如果 docx 的父目录找不到，尝试 output_dir 下的子目录
            if not markdown and task.output_dir:
                markdown = _read_markdown_output(Path(task.output_dir), pdf_stem)

        response["result"] = {
            "output_path": task.result_path,
            "chunk_count": task.chunk_count,
            "markdown": markdown[:50000] if markdown else "",  # 最大 50KB
        }
    elif task.status == "failed":
        response["error"] = task.error

    return response


@router.get("/file-parse/{task_id}/progress", summary="SSE 实时进度")
async def get_task_progress(task_id: str):
    """通过 Server-Sent Events 推送实时处理进度。"""
    return StreamingResponse(
        progress_events(task_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.get("/file-parse/queue", summary="队列状态")
async def get_queue():
    """查看模型服务的任务队列状态。"""
    return model_manager.get_status()


@router.post("/file-parse/{task_id}/cancel", summary="取消任务")
async def cancel_task(task_id: str):
    """取消正在排队或处理中的任务。"""
    ok = model_manager.cancel_task(task_id)
    return {"code": 200, "ok": ok, "task_id": task_id}
