"""
任务管理路由 — 列表、详情、下载、删除。
"""

import os
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse, RedirectResponse

from mineru_app import state_manager
from mineru_app.config import OUTPUT_DIR

DB_TABLE = "parent_child_db_1024"
DB_METADATA_COL = "c_metadata"

DB_CONNECTION = "postgresql+psycopg2://postgres:123456@10.32.10.161:5432/text2sql_vector"

router = APIRouter(tags=["jobs"])
templates_ref = None  # 将由 server.py 延迟注入


def _get_templates():
    """延迟获取 templates 对象，避免循环导入。"""
    import mineru_app.server as srv
    return srv.templates


# ---------- 页面路由 ----------

@router.get("/jobs", response_class=HTMLResponse)
async def job_list_page(
    request: Request,
    page: int = 1,
    per_page: int = 20,
    status: str = None,
    embed: bool = False,
):
    """上传页 + 任务列表（分页）。支持 ?status= 筛选和 ?embed=1 嵌入模式。"""
    all_jobs = state_manager.list_jobs(status=status, per_page=10000)
    total = len(all_jobs)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    start = (page - 1) * per_page
    jobs = all_jobs[start:start + per_page]
    return _get_templates().TemplateResponse(
        request=request,
        name="index.html",
        context={
            "jobs": jobs,
            "page": page,
            "total_pages": total_pages,
            "total": total,
            "per_page": per_page,
            "status_filter": status or "",
            "embed": embed,
        },
    )


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job_detail_page(request: Request, job_id: str, embed: bool = False):
    """任务详情 + 预览页面。支持 ?embed=1 嵌入模式。"""
    job = state_manager.get_job(job_id)
    if not job:
        return HTMLResponse("任务不存在", status_code=404)
    return _get_templates().TemplateResponse(
        request=request,
        name="job_detail.html",
        context={"job": job, "embed": embed},
    )


# ---------- API 路由 ----------

@router.get("/api/jobs")
async def list_jobs(status: str = None, page: int = 1, per_page: int = 20):
    """获取任务列表。"""
    jobs = state_manager.list_jobs(status=status, page=page, per_page=per_page)
    return {"jobs": jobs, "total": len(jobs)}


@router.post("/api/jobs/list-batch")
async def list_jobs_batch(request: Request):
    """批量查询指定 ID 列表的任务状态（供前端轮询用）。"""
    body = await request.json()
    ids = body.get("job_ids", [])
    jobs = []
    for jid in ids:
        j = state_manager.get_job(jid)
        if j:
            jobs.append({
                "id": j["id"],
                "filename": j.get("filename", ""),
                "status": j.get("status", ""),
                "progress": j.get("progress", ""),
                "chunk_count": j.get("chunk_count", 0),
                "processing_time": j.get("processing_time", 0),
                "error": j.get("error"),
                "ingest_error": j.get("ingest_error"),
            })
    return {"jobs": jobs}


@router.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    """获取单个任务状态。"""
    job = state_manager.get_job(job_id)
    if not job:
        return JSONResponse({"error": "任务不存在"}, status_code=404)
    return job


@router.get("/api/jobs/{job_id}/download")
async def download_job(job_id: str):
    """下载处理后的 DOCX 文件。"""
    job = state_manager.get_job(job_id)
    if not job or not job.get("output_path"):
        return JSONResponse({"error": "文件尚未处理完成或不存在"}, status_code=404)

    output_path = Path(job["output_path"])
    if not output_path.exists():
        return JSONResponse({"error": "输出文件已被清理"}, status_code=404)

    return FileResponse(
        path=str(output_path),
        filename=output_path.name,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


@router.delete("/api/jobs/{job_id}")
async def delete_job(job_id: str):
    """删除任务及关联文件（若已入库则先从向量库移除）。"""
    job = state_manager.get_job(job_id)
    if not job:
        return JSONResponse({"error": "任务不存在"}, status_code=404)

    # 若已入库，先清理向量数据
    if job.get("status") == "ingested":
        try:
            from sqlalchemy import create_engine, text
            db_conn = __import__("os").getenv(
                "PGVECTOR_CONNECTION",
                DB_CONNECTION,
            )
            engine = create_engine(db_conn)
            with engine.connect() as conn:
                conn.execute(text(f"DELETE FROM {DB_TABLE} WHERE {DB_METADATA_COL}->>'source' = :src"), {"src": job_id})
                conn.commit()
            engine.dispose()
        except Exception:
            pass

    # 删除上传文件
    if job.get("input_path"):
        input_dir = Path(job["input_path"]).parent
        if input_dir.exists():
            import shutil
            shutil.rmtree(input_dir, ignore_errors=True)

    # 删除输出目录
    output_dir = OUTPUT_DIR / job_id
    if output_dir.exists():
        import shutil
        shutil.rmtree(output_dir, ignore_errors=True)

    state_manager.delete_job(job_id)
    return {"ok": True}


@router.get("/api/knowledge/check")
async def check_filename(filename: str = ""):
    """检查向量库中是否已存在同名文件（供前端入库前提醒）。"""
    if not filename:
        return {"exists": False}
    try:
        from sqlalchemy import create_engine, text
        db_conn = __import__("os").getenv(
            "PGVECTOR_CONNECTION",
            DB_CONNECTION,
        )
        engine = create_engine(db_conn)
        with engine.connect() as conn:
            result = conn.execute(
                text(f"SELECT count(*) FROM {DB_TABLE} WHERE {DB_METADATA_COL}->>'filename' = :fn"),
                {"fn": filename},
            )
            count = result.scalar()
        engine.dispose()
        return {"exists": count > 0, "chunks": count}
    except Exception as e:
        return {"exists": False, "error": str(e)}


@router.get("/api/stats")
async def get_stats():
    """获取各状态任务数量统计。"""
    all_jobs = state_manager.list_jobs(per_page=10000)
    counts = {}
    for j in all_jobs:
        s = j.get("status", "unknown")
        counts[s] = counts.get(s, 0) + 1
    return {
        "total": len(all_jobs),
        "counts": counts,
    }


@router.get("/api/knowledge")
async def get_knowledge():
    """查询向量库中实际存储的文档列表与切片数。"""
    try:
        from sqlalchemy import create_engine, text
        db_conn = __import__("os").getenv(
            "PGVECTOR_CONNECTION",
            DB_CONNECTION,
        )
        engine = create_engine(db_conn)
        with engine.connect() as conn:
            result = conn.execute(text(f"""
                SELECT {DB_METADATA_COL}->>'source' AS filename,
                       {DB_METADATA_COL}->>'source' AS source,
                       count(*) AS chunks
                FROM {DB_TABLE}
                GROUP BY {DB_METADATA_COL}->>'source'
                ORDER BY filename
            """))
            rows = [{"filename": r[0] or "", "source": r[1] or "", "chunks": r[2]} for r in result.fetchall()]
        engine.dispose()

        total_files = len(set(r["source"] for r in rows if r["source"]))
        total_chunks = sum(r["chunks"] for r in rows)
        return {"files": rows, "total_files": total_files, "total_chunks": total_chunks}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/api/jobs/batch-download")
async def batch_download(request: Request):
    """批量下载：将选中文件的 DOCX 打包为 zip 返回。"""
    import zipfile
    import io

    body = await request.json()
    job_ids = body.get("job_ids", [])
    if not job_ids:
        return JSONResponse({"error": "未提供 job_ids"}, status_code=400)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        added = 0
        for jid in job_ids:
            job = state_manager.get_job(jid)
            if not job or not job.get("output_path"):
                continue
            path = Path(job["output_path"])
            if not path.exists():
                continue
            zf.write(str(path), path.name)
            added += 1
        if added == 0:
            return JSONResponse({"error": "没有可下载的文件"}, status_code=404)

    buf.seek(0)
    from fastapi.responses import StreamingResponse
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=documents_{len(job_ids)}.zip"},
    )
