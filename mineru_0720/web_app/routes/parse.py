"""
MinerU 解析 API 路由 — 异步文档解析，任务队列管理。
POST /api/parse       - 提交解析任务
GET  /api/parse/{id}  - 查询任务状态
GET  /api/parse/{id}/progress - SSE 实时进度
GET  /api/queue       - 队列状态
POST /api/parse/batch - 批量提交
"""
import os
import time
import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, Form, UploadFile, File, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from web_app.model_manager import model_manager
from web_app.config import ALLOWED_EXTENSIONS, MAX_FILE_SIZE_MB, UPLOAD_DIR

router = APIRouter(prefix="/api", tags=["parse"])


class ParseResult(BaseModel):
    task_id: str
    status: str
    position: int | None = None


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
            break
        await asyncio.sleep(1)


# ── 路由 ──

@router.post("/parse", summary="提交文档解析任务")
async def submit_parse(file: UploadFile = File(...), output_dir: str = Form("")):
    """提交 PDF/DOCX 文档到 MinerU 模型服务解析。返回 task_id 供轮询。"""
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return JSONResponse({"error": f"不支持的文件格式: {ext}"}, status_code=400)

    content = await file.read()
    if len(content) > MAX_FILE_SIZE_MB * 1024 * 1024:
        return JSONResponse({"error": f"文件过大: {len(content)/1024/1024:.1f}MB"}, status_code=413)

    # 保存临时文件
    task_dir = UPLOAD_DIR / "parse_tasks" / f"{int(time.time())}_{file.filename}"
    task_dir.mkdir(parents=True, exist_ok=True)
    input_path = task_dir / file.filename
    input_path.write_bytes(content)

    out_dir = Path(output_dir) if output_dir else task_dir / "output"
    out_dir.mkdir(parents=True, exist_ok=True)

    task_id = model_manager.submit(file_path=input_path, output_dir=out_dir)
    queue_size = model_manager.get_status()["queue_size"]

    return JSONResponse({
        "task_id": task_id,
        "status": "queued",
        "position": queue_size,
    }, status_code=202)


@router.get("/parse/{task_id}", summary="查询任务状态")
async def get_task(task_id: str):
    """查询单个解析任务的状态、进度和结果。"""
    task = model_manager.get_task(task_id)
    if not task:
        return JSONResponse({"error": "任务不存在"}, status_code=404)
    return {
        "task_id": task.task_id,
        "status": task.status,
        "progress": task.progress,
        "progress_pct": task.progress_pct,
        "elapsed": task.elapsed,
        "result": {
            "output_path": task.result_path,
            "chunk_count": task.chunk_count,
        } if task.status == "completed" else None,
        "error": task.error,
    }


@router.get("/parse/{task_id}/progress", summary="SSE 实时进度")
async def get_task_progress(task_id: str):
    """通过 Server-Sent Events 推送实时处理进度。"""
    return StreamingResponse(
        progress_events(task_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.get("/queue", summary="队列状态")
async def get_queue():
    """查看模型服务的任务队列状态。"""
    return model_manager.get_status()


@router.post("/queue/{task_id}/cancel", summary="取消任务")
async def cancel_task(task_id: str):
    """取消正在排队或处理中的任务。"""
    ok = model_manager.cancel_task(task_id)
    return {"ok": ok, "task_id": task_id}


@router.post("/parse/batch", summary="批量提交解析任务")
async def batch_parse(files: list[UploadFile] = File(...)):
    """批量提交多个文档到模型服务。"""
    results = []
    for file in files:
        if not file.filename: continue
        ext = Path(file.filename).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS: continue
        content = await file.read()
        task_dir = UPLOAD_DIR / "parse_tasks" / f"batch_{int(time.time())}_{file.filename}"
        task_dir.mkdir(parents=True, exist_ok=True)
        input_path = task_dir / file.filename
        input_path.write_bytes(content)
        out_dir = task_dir / "output"
        out_dir.mkdir(parents=True, exist_ok=True)
        task_id = model_manager.submit(file_path=input_path, output_dir=out_dir)
        results.append({"task_id": task_id, "filename": file.filename})
    return {"tasks": results, "total": len(results)}
