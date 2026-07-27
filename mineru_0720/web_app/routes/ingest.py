"""
RAG 入库触发路由。
"""

import shutil
import subprocess
import threading
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from web_app import state_manager
from web_app.config import (
    MINERU_BASE,
    LANGCHAIN_VENV_PYTHON,
    LANGCHAIN_INGEST_SCRIPT,
    JOB_TIMEOUT_SECONDS,
)

router = APIRouter(prefix="/api", tags=["ingest"])

_ingestion_lock = threading.Lock()


@router.post("/jobs/{job_id}/ingest")
async def ingest_job(job_id: str):
    """触发 RAG 入库：将处理后的 DOCX 导入 pgvector 知识库。"""
    job = state_manager.get_job(job_id)
    if not job:
        return JSONResponse({"error": "任务不存在"}, status_code=404)
    if job["status"] not in ("completed", "ingested"):
        return JSONResponse({"error": f"任务状态为 {job['status']}，无法入库"}, status_code=400)
    if not job.get("output_path"):
        return JSONResponse({"error": "输出文件不存在"}, status_code=400)

    output_path = Path(job["output_path"])
    if not output_path.exists():
        return JSONResponse({"error": f"输出文件已被清理: {output_path}"}, status_code=404)

    # 检查入库脚本是否存在
    if not LANGCHAIN_INGEST_SCRIPT.exists():
        return JSONResponse(
            {"error": f"入库脚本不存在: {LANGCHAIN_INGEST_SCRIPT}"},
            status_code=500,
        )

    # 加锁，防止并发入库
    if _ingestion_lock.locked():
        return JSONResponse({"error": "有另一个入库任务正在执行，请等待完成后再试"}, status_code=409)

    acquired = _ingestion_lock.acquire(blocking=False)
    if not acquired:
        return JSONResponse({"error": "有另一个入库任务正在执行"}, status_code=409)

    try:
        state_manager.update_job(job_id, status="ingesting", progress="正在入库到 RAG 知识库...")

        # # 旧逻辑：复制文件到 Langchain_160 的 data/ 目录，再全量删库重建
        # dest_filename = output_path.name
        # dest_path = LANGCHAIN_DATA_DIR / dest_filename
        # shutil.copy2(str(output_path), str(dest_path))

        try:
            # # 旧逻辑：执行入库脚本（无参数，全量清除 + 全量重建）
            # result = subprocess.run(
            #     [str(LANGCHAIN_VENV_PYTHON), str(LANGCHAIN_INGEST_SCRIPT)],
            #     cwd=str(MINERU_BASE),
            #     ...
            # )
            # 新逻辑：直接传文件路径，脚本只入库该文件（追加写入，不删库）
            result = subprocess.run(
                [str(LANGCHAIN_VENV_PYTHON), str(LANGCHAIN_INGEST_SCRIPT), str(output_path), job_id],
                cwd=str(MINERU_BASE),
                capture_output=True,
                text=True,
                timeout=JOB_TIMEOUT_SECONDS,
                env={**__import__("os").environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"},
            )

            stdout_tail = result.stdout[-1000:] if result.stdout else ""
            stderr_tail = result.stderr[-1000:] if result.stderr else ""

            if result.returncode != 0:
                state_manager.update_job(
                    job_id,
                    status="completed",
                    progress="入库失败",
                    ingest_error=f"入库失败 (exit code: {result.returncode})\n{stderr_tail}",
                )
                return JSONResponse({
                    "status": "failed",
                    "error": f"入库脚本执行失败 (exit code: {result.returncode})",
                    "stderr": stderr_tail[-500:],
                }, status_code=500)

            # 统计入库的 chunk 数
            ingested_count = 0
            for line in stdout_tail.split("\n"):
                if "个切片" in line:
                    try:
                        # "  - xxx.docx: 生成 15 个切片"
                        ingested_count += int(line.split("生成")[1].split("个")[0].strip())
                    except (IndexError, ValueError):
                        pass

            import time
            state_manager.update_job(
                job_id,
                status="ingested",
                progress="入库完成",
                ingested_at=time.time(),
            )

            return JSONResponse({
                "status": "ingested",
                "message": "入库完成",
                "stdout_tail": stdout_tail[-500:],
            })

        finally:
            # # 旧逻辑：清理临时复制的文件（新逻辑不再复制，无需清理）
            # if dest_path.exists():
            #     dest_path.unlink()
            pass

    except subprocess.TimeoutExpired:
        state_manager.update_job(
            job_id,
            status="completed",
            progress="入库超时",
            ingest_error=f"入库超时 (>{JOB_TIMEOUT_SECONDS}秒)",
        )
        return JSONResponse({"error": f"入库超时 (>{JOB_TIMEOUT_SECONDS}秒)"}, status_code=504)
    except Exception as e:
        import traceback
        traceback.print_exc()
        state_manager.update_job(
            job_id,
            status="completed",
            progress="入库异常",
            ingest_error=str(e),
        )
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        _ingestion_lock.release()


@router.post("/jobs/{job_id}/unload")
async def unload_job(job_id: str):
    """从向量库中删除该文件的所有向量内容。"""
    import sys
    import os

    job = state_manager.get_job(job_id)
    if not job:
        return JSONResponse({"error": "任务不存在"}, status_code=404)

    # 用 job_id 作为 source 唯一标识，避免同名文件冲突
    source_key = job_id

    db_conn = os.getenv(
        "PGVECTOR_CONNECTION",
        "postgresql+psycopg2://postgres:123456@10.32.10.161:5432/text2sql_vector",
    )

    try:
        from sqlalchemy import create_engine, text
        engine = create_engine(db_conn)
        with engine.connect() as conn:
            result = conn.execute(
                text("DELETE FROM parent_child_db_1024 WHERE c_metadata->>'source' = :src"),
                {"src": source_key},
            )
            conn.commit()
            deleted = result.rowcount
        engine.dispose()
        print(f"[unload] 已从向量库删除 {deleted} 条 (source={source_key})")

        state_manager.update_job(
            job_id,
            status="completed",
            progress="已从知识库移除",
            ingest_error=None,
        )
        return {"status": "ok", "message": f"已删除 {source_key} 的向量内容"}

    except Exception as e:
        import traceback
        traceback.print_exc()
        state_manager.update_job(
            job_id,
            ingest_error=f"删除向量失败: {e}",
        )
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/ingest/batch")
async def ingest_batch(request: Request):
    """批量入库：传入 job_ids 列表，串行入库，返回每个结果。"""
    import time
    body = await request.json()
    job_ids = body.get("job_ids", [])
    if not job_ids:
        return JSONResponse({"error": "未提供 job_ids"}, status_code=400)

    if _ingestion_lock.locked():
        return JSONResponse({"error": "有另一个入库任务正在执行"}, status_code=409)

    acquired = _ingestion_lock.acquire(blocking=False)
    if not acquired:
        return JSONResponse({"error": "入库任务繁忙"}, status_code=409)

    results = []
    try:
        for job_id in job_ids:
            job = state_manager.get_job(job_id)
            if not job:
                results.append({"job_id": job_id, "status": "skipped", "error": "任务不存在"})
                continue
            if job["status"] != "completed":
                results.append({"job_id": job_id, "status": "skipped",
                                "error": f"状态为 {job['status']}"})
                continue
            output_path = Path(job["output_path"])
            if not output_path.exists():
                results.append({"job_id": job_id, "status": "skipped", "error": "文件不存在"})
                continue

            state_manager.update_job(job_id, status="ingesting", progress="批量入库中...")

            try:
                result = subprocess.run(
                    [str(LANGCHAIN_VENV_PYTHON), str(LANGCHAIN_INGEST_SCRIPT), str(output_path), job_id],
                    cwd=str(MINERU_BASE),
                    capture_output=True,
                    text=True,
                    timeout=JOB_TIMEOUT_SECONDS,
                    env={**__import__("os").environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"},
                )

                if result.returncode == 0:
                    state_manager.update_job(
                        job_id,
                        status="ingested",
                        progress="入库完成",
                        ingested_at=time.time(),
                    )
                    results.append({"job_id": job_id, "status": "ok"})
                else:
                    state_manager.update_job(
                        job_id,
                        status="completed",
                        progress="入库失败",
                        ingest_error=f"exit code {result.returncode}\n{result.stderr[-500:]}",
                    )
                    results.append({"job_id": job_id, "status": "failed",
                                    "error": f"exit code {result.returncode}"})

            except subprocess.TimeoutExpired:
                state_manager.update_job(job_id, status="completed", progress="入库超时",
                                         ingest_error=f"超时 >{JOB_TIMEOUT_SECONDS}s")
                results.append({"job_id": job_id, "status": "failed", "error": "超时"})
            except Exception as e:
                state_manager.update_job(job_id, status="completed", progress="入库异常", ingest_error=str(e))
                results.append({"job_id": job_id, "status": "failed", "error": str(e)})

    finally:
        _ingestion_lock.release()

    ok_count = sum(1 for r in results if r["status"] == "ok")
    return JSONResponse({"results": results, "ok": ok_count, "total": len(results)})
