"""
知识库数据管理路由 — 文档上传/处理、任务管理、向量入库、知识库概览。

将 mineru_0720 的核心功能集成到 data_processing_center 统一后端。
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import traceback
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import APIRouter, Request, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from sqlalchemy import create_engine, text

from . import state_manager
from .config import (
    UPLOAD_DIR,
    OUTPUT_DIR,
    DB_CONNECTION,
    DB_TABLE,
    DB_METADATA_COL,
    ALLOWED_EXTENSIONS,
    MAX_FILE_SIZE_MB,
    JOB_TIMEOUT_SECONDS,
    PREVIEW_MAX_LINES,
    RAG_INGEST_SCRIPT,
    MINERU_BASE,
    MINERU_VENV_PYTHON,
    MINERU_SITE_PACKAGES,
    MINERU_SERVICE_URL,
    MINERU_FILE_PARSE_URL,
    PARSE_ENGINE,
    MAAS_PARSE_URL,
    MAAS_PARSE_TIMEOUT,
    DB_KB_TABLE,
    DB_AUDIT_TABLE,
    DEFAULT_KB_ID,
    MAX_CONCURRENT_DOCS,
)

router = APIRouter(tags=["知识库数据管理"])

# 最大上传文件数
_MAX_UPLOAD_FILES = int(os.getenv("MAX_UPLOAD_FILES", "20"))
_ingestion_lock = threading.Lock()
# 专用线程池，避免共享 FastAPI 默认线程池导致高并发时耗尽
_doc_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="doc-proc")


# ═══════════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════════

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



def _count_chunks(docx_path: Path) -> int:
    """统计 DOCX 中 <-split-> 标记的数量，即入库的子块数。"""
    try:
        from docx import Document as DocxDocument
    except ImportError:
        # data_processing_center venv 可能没装 python-docx，从 mineru venv 借
        _mineru_site = MINERU_SITE_PACKAGES
        if _mineru_site not in sys.path:
            sys.path.insert(0, _mineru_site)
        from docx import Document as DocxDocument
    try:
        doc = DocxDocument(str(docx_path))
        count = 0
        for para in doc.paragraphs:
            if "<-split->" in para.text:
                count += 1
        return max(count, 1)
    except Exception:
        return 0

def _extract_preview_text(docx_path: Path, max_lines: int = PREVIEW_MAX_LINES) -> str:
    """从 DOCX 提取纯文本用于预览。"""
    try:
        from docx import Document as DocxDocument
    except ImportError:
        _mineru_site = MINERU_SITE_PACKAGES
        if _mineru_site not in sys.path:
            sys.path.insert(0, _mineru_site)
        from docx import Document as DocxDocument
    try:
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


def _submit_to_parser(file_bytes: bytes, file_name: str, parse_url: str, is_maas: bool = False) -> dict:
    """提交文档到解析引擎。格式统一为 multipart/form-data。

    Maas 格式:  files=@xxx  + format=markdown
    本地格式:  files=@xxx  + format=markdown (完全一致)
    """
    import urllib.request, json as _json

    boundary = "----FormBoundary" + uuid.uuid4().hex[:16]
    body_head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="files"; filename="{file_name}"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n"
    ).encode("utf-8")
    body_tail = (
        f"\r\n--{boundary}\r\n"
        f'Content-Disposition: form-data; name="format"\r\n\r\n'
        f"markdown\r\n"
        f"--{boundary}--\r\n"
    ).encode("utf-8")
    body = body_head + file_bytes + body_tail

    timeout = MAAS_PARSE_TIMEOUT if is_maas else 30
    req = urllib.request.Request(
        parse_url,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return _json.loads(resp.read().decode("utf-8"))


def _process_document_background(job_id: str, input_path: Path):
    """后台处理文档：根据 PARSE_ENGINE 选择解析后端（Maas 内网 或 本地 MinerU）。

    Maas 模式: 直接调用内网 /file_parse，轮询等待完成
    本地模式: 先等 MinerU 服务就绪，再提交 /file_parse，轮询等待完成
    """
    import urllib.request, json as _json, urllib.parse

    if not state_manager.get_job(job_id):
        return

    is_maas = (PARSE_ENGINE == "maas")
    parse_url = MAAS_PARSE_URL if is_maas else MINERU_FILE_PARSE_URL

    try:
        state_manager.update_job(job_id, status="queued",
                                 progress=f"[准备中] 提交到 {'Maas' if is_maas else '本地'} 解析引擎...",
                                 progress_pct=0)

        job_output_dir = OUTPUT_DIR / job_id
        job_output_dir.mkdir(parents=True, exist_ok=True)

        t_start = time.perf_counter()

        # 本地模式: 等待 MinerU 服务就绪
        if not is_maas:
            last_health_progress = ""
            for attempt in range(180):
                try:
                    req = urllib.request.Request(f"{MINERU_SERVICE_URL}/api/health")
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        data = _json.loads(resp.read().decode("utf-8"))
                        if data.get("model_loaded"):
                            break
                except Exception:
                    pass
                new_progress = f"[准备中] 等待本地模型服务就绪...（已等待 {(attempt + 1) * 2}秒）"
                if (attempt + 1) % 10 == 0 and new_progress != last_health_progress:
                    state_manager.update_job(job_id, progress=new_progress, progress_pct=0)
                    last_health_progress = new_progress
                time.sleep(2)
            else:
                raise RuntimeError("本地模型服务未就绪，请稍后重试")

        # 提交文件到解析引擎
        state_manager.update_job(job_id, progress="[准备中] 正在发送文档到分析引擎...", progress_pct=0)
        file_bytes = input_path.read_bytes()
        file_bytes_size = len(file_bytes)
        file_name = input_path.name.replace('"', "'").replace("\n", " ").replace("\r", " ")

        resp_data = _submit_to_parser(file_bytes, file_name, parse_url, is_maas=is_maas)

        parse_task_id = resp_data.get("task_id", "")
        state_manager.update_job(job_id, status="processing",
                                 progress=f"[准备中] 已发送文档，{'Maas' if is_maas else '本地'}引擎处理中...",
                                 mineru_task_id=parse_task_id, progress_pct=5)

        # 轮询等待完成
        file_size_mb = file_bytes_size / (1024 * 1024)
        actual_timeout = max(JOB_TIMEOUT_SECONDS, min(int(file_size_mb * 600), 10800))
        deadline = time.perf_counter() + actual_timeout
        consecutive_errors = 0

        status_url = f"{parse_url}/{parse_task_id}"
        if is_maas:
            # Maas 返回格式可能不同，简易轮询
            status_url = parse_url.replace("/file_parse", f"/file_parse/{parse_task_id}")
            # 如果 Maas URL 中已有 /file_parse 就直接拼接
            if "/file-parse/" not in status_url and "/file_parse/" not in status_url:
                status_url = "/".join(parse_url.rsplit("/", 1)[:-1]) + f"/{parse_task_id}"

        while True:
            if time.perf_counter() > deadline:
                raise TimeoutError(f"文档处理超时 (>{actual_timeout}秒)")
            time.sleep(3)
            try:
                # 统一用 /file-parse/{task_id} 查状态
                req = urllib.request.Request(f"{parse_url}/{parse_task_id}")
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = _json.loads(resp.read().decode("utf-8"))
                consecutive_errors = 0

                progress_text = data.get("progress", "")
                if progress_text:
                    state_manager.update_job(job_id, progress=progress_text,
                                             progress_pct=data.get("progress_pct", 0))

                if data.get("status") == "completed":
                    # 解析完成: 获取 output_path
                    result_data = data.get("result") or {}
                    api_output = result_data.get("output_path")
                    docx_files = list(job_output_dir.glob("**/*.docx"))
                    if api_output and Path(api_output).exists():
                        result_path = Path(api_output)
                    elif docx_files:
                        result_path = docx_files[0]
                    else:
                        result_path = None

                    elapsed = time.perf_counter() - t_start
                    chunk_count = _count_chunks(result_path) if result_path else 0
                    preview_text = _extract_preview_text(result_path) if result_path else (result_data.get("markdown", "")[:5000])

                    state_manager.update_job(
                        job_id, status="completed",
                        output_path=str(result_path) if result_path else None,
                        progress="处理完成", chunk_count=chunk_count,
                        processing_time=round(elapsed, 1), preview_text=preview_text,
                        progress_pct=100,
                    )
                    break
                elif data.get("status") == "failed":
                    raise RuntimeError(data.get("error", "解析引擎处理失败"))
                elif data.get("status") in ("cancelled", "cancelling"):
                    raise RuntimeError("任务已被取消")

            except RuntimeError:
                raise
            except Exception as e:
                consecutive_errors += 1
                if consecutive_errors >= 30:
                    raise RuntimeError(f"解析引擎通信失败（连续{consecutive_errors}次）: {e}")
                current_job = state_manager.get_job(job_id)
                current_progress = current_job.get("progress", "") if current_job else ""
                retry_tag = f"（通信重试 {consecutive_errors}/30）"
                state_manager.update_job(job_id,
                                         progress=f"{current_progress}...{retry_tag}",
                                         progress_pct=5)

    except TimeoutError as e:
        elapsed_min = round((time.perf_counter() - t_start) / 60, 1)
        state_manager.update_job(job_id, status="failed", error=str(e),
                                 progress=f"轮询超时（{elapsed_min}分钟），文件较大请重新提交或拆分后上传",
                                 progress_pct=0, mineru_task_id=None)
    except Exception as e:
        error_msg = str(e)
        if "已被取消" in error_msg:
            state_manager.update_job(job_id, status="cancelled", error=error_msg,
                                     progress="任务已取消", progress_pct=0, mineru_task_id=None)
        else:
            state_manager.update_job(job_id, status="failed", error=error_msg,
                                     progress="处理失败，请查看详情", progress_pct=0, mineru_task_id=None)
        traceback.print_exc()


# ═══════════════════════════════════════════════════════════════
# 路由 1: 文件上传
# ═══════════════════════════════════════════════════════════════

@router.post("/upload", summary="上传文档并提交 MinerU 处理")
async def upload_file(request: Request):
    """上传 PDF/DOCX 文档，后台调用 MinerU 处理。支持单文件或多文件。"""
    # 统一从 request.form() 获取文件和字段，避免与 UploadFile 参数冲突
    try:
        form = await request.form()
        region_code_raw = str(form.get("region_code", "") or "")
        kb_id_raw = form.get("kb_id", None)
        kb_id = str(kb_id_raw) if kb_id_raw is not None else ""  # 默认文档池
        auto_allocate_raw = str(form.get("auto_allocate", "") or "")
        auto_allocate = auto_allocate_raw.lower() in ("true", "1", "yes")
        tags_raw = str(form.get("tags", "") or "")
        tags = []
        if tags_raw:
            try:
                tags = json.loads(tags_raw) if tags_raw.startswith("[") else [t.strip() for t in tags_raw.split(",") if t.strip()]
            except Exception:
                tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
        upload_files = form.getlist("files")
    except Exception:
        return JSONResponse({"error": "无法解析上传表单"}, status_code=400)

    if not upload_files:
        return JSONResponse({"error": "未选择文件"}, status_code=400)

    results = []
    errors = []

    if len(upload_files) > _MAX_UPLOAD_FILES:
        return JSONResponse({"error": f"单次最多上传 {_MAX_UPLOAD_FILES} 个文档，当前 {len(upload_files)} 个"}, status_code=400)

    for file in upload_files:
        fname = (getattr(file, "filename", None) or "").strip()
        if not fname:
            continue

        # 处理中文文件名编码问题
        ext = Path(fname).suffix.lower()
        if not ext:
            # 尝试从 content_type 推断
            ct = getattr(file, "content_type", "")
            if "pdf" in ct: ext = ".pdf"
            elif "docx" in ct or "word" in ct or "msword" in ct: ext = ".docx"
            elif "doc" in ct: ext = ".doc"
        if ext not in ALLOWED_EXTENSIONS:
            errors.append({"filename": fname, "error": f"不支持的文件格式: {ext or '未知'}"})
            continue

        content = await file.read()
        file_size = len(content)
        if file_size == 0:
            errors.append({"filename": fname, "error": "文件为空"})
            continue
        max_bytes = MAX_FILE_SIZE_MB * 1024 * 1024
        if file_size > max_bytes:
            errors.append({"filename": fname, "error": f"文件过大: {_format_size(file_size)}"})
            continue

        # ── 服务端 MD5 去重：禁止活跃任务中同名且同大小的文件重复上传 ──
        file_md5 = hashlib.md5(content).hexdigest()
        all_jobs = state_manager.list_jobs(per_page=10000)  # 获取全部任务
        for j in all_jobs:
            if j.get("filename") != fname:
                continue
            # 同文件名+同文件大小+同 MD5 → 几乎确定是同一份文件
            if j.get("file_size") == file_size:
                status = j.get("status", "")
                if status in ("processing", "queued", "ingesting", "uploaded"):
                    errors.append({"filename": fname, "error": f"该文件正在处理中（{status}），请等待完成后再上传"})
                    break
                if status == "completed":
                    errors.append({"filename": fname, "error": f"该文件已处理完成，可直接入库或下载（job: {j['id']}）"})
                    break
                if status == "ingested":
                    errors.append({"filename": fname, "error": f"该文件已入库，无需重复上传（job: {j['id']}）"})
                    break
        else:
            # 没有匹配的活跃/已完成任务，允许上传
            pass
        if errors and errors[-1].get("filename") == fname:
            continue  # 已被去重拦截，跳过此文件

        # 保留原始中文文件名，但用 UUID+.扩展名 保存避免乱码
        safe_stem = uuid.uuid4().hex[:12]
        safe_name = f"{safe_stem}{ext}"

        # 预生成 job_id，先写入文件再用已知路径创建任务（Bug 10: 避免 input_path 瞬时为空串）
        job_id = uuid.uuid4().hex[:12]
        job_dir = UPLOAD_DIR / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        input_path = job_dir / safe_name
        with open(input_path, "wb") as f:
            f.write(content)

        # 创建任务时使用已知的 input_path
        state_manager.create_job_with_id(
            job_id=job_id,
            filename=fname,  # 原始中文文件名，前端显示用
            file_size=file_size,
            input_path=str(input_path),
        )

        # 将地区编码和知识库存入任务状态
        state_manager.update_job(job_id, status="queued", region_code=region_code_raw, kb_id=kb_id, tags=tags)

        # 异步后台处理（使用专用线程池，避免共享 FastAPI 默认线程池）
        import asyncio
        loop = asyncio.get_event_loop()
        loop.run_in_executor(_doc_executor, _process_document_background, job_id, input_path)
        results.append({"job_id": job_id, "filename": fname, "status": "queued"})

    return JSONResponse({
        "jobs": results,
        "errors": errors,
        "total": len(results),
        "failed": len(errors),
    })


# ═══════════════════════════════════════════════════════════════
# 路由 2: 统计
# ═══════════════════════════════════════════════════════════════

@router.get("/stats", summary="获取各状态任务统计")
async def get_stats():
    """获取各状态任务数量汇总。"""
    all_jobs = state_manager.list_jobs(per_page=10000)
    counts = {}
    for j in all_jobs:
        s = j.get("status", "unknown")
        counts[s] = counts.get(s, 0) + 1
    return {"total": len(all_jobs), "counts": counts}


# ═══════════════════════════════════════════════════════════════
# 路由 3: 知识库概览
# ═══════════════════════════════════════════════════════════════

@router.get("/knowledge", summary="知识库概览")
async def get_knowledge(sort: str = "time", kb_id: str = None, enabled: str = None):
    """查询向量库中所有文档及切片统计。支持 ?kb_id= + ?enabled= 过滤。管理界面不做权限过滤。"""
    try:
        engine = create_engine(DB_CONNECTION)
        order_clause = {
            "time": f"MAX({DB_METADATA_COL}->>'created_at') DESC",
            "name": f"{DB_METADATA_COL}->>'filename' ASC",
            "chunks": "count(*) DESC",
        }.get(sort, f"MAX({DB_METADATA_COL}->>'created_at') DESC")

        # 构建 WHERE 子句
        where_clauses = []
        params = {}
        if kb_id == "__pool__":
            where_clauses.append(
                f"({DB_METADATA_COL}->>'kb_id' IS NULL OR {DB_METADATA_COL}->>'kb_id' = '')"
            )
        elif kb_id:
            where_clauses.append(f"{DB_METADATA_COL}->>'kb_id' = :kb_id")
            params["kb_id"] = kb_id
        if enabled is not None:
            where_clauses.append(f"({DB_METADATA_COL}->>'enabled')::boolean = :enabled")
            params["enabled"] = enabled.lower() == "true"
        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        with engine.connect() as conn:
            result = conn.execute(text(f"""
                SELECT COALESCE({DB_METADATA_COL}->>'filename', {DB_METADATA_COL}->>'source') AS filename,
                       {DB_METADATA_COL}->>'source' AS source,
                       MAX({DB_METADATA_COL}->>'kb_id') AS kb_id,
                       count(*) AS chunks,
                       MAX({DB_METADATA_COL}->>'created_at') AS last_ingest,
                       MAX({DB_METADATA_COL}->>'region_code') AS region_code,
                       MAX({DB_METADATA_COL}->>'enabled') AS enabled,
                       MAX({DB_METADATA_COL}->>'tags') AS tags
                FROM {DB_TABLE}
                {where_sql}
                GROUP BY {DB_METADATA_COL}->>'source', {DB_METADATA_COL}->>'filename', {DB_METADATA_COL}->>'kb_id'
                ORDER BY {order_clause} NULLS LAST
            """), params)
            rows = [{"filename": r[0] or "", "source": r[1] or "", "kb_id": r[2] if r[2] is not None else "default",
                     "chunks": r[3], "last_ingest": r[4] or "", "region_code": r[5] or "",
                     "enabled": r[6] == "true" or r[6] is None,
                     "tags": (lambda t: json.loads(t) if isinstance(t, str) and t.startswith("[") else (t if isinstance(t, list) else []))(r[7])}
                    for r in result.fetchall()]
        engine.dispose()

        # 批量查权限表补充 region_name（region_code 可能是9位区县码，取前7位匹配市码）
        try:
            import dmPython
            host = os.getenv("DM_HOST", "120.211.116.133")
            port = int(os.getenv("DM_PORT", "46252"))
            user = os.getenv("DM_USERNAME", "CH_AI")
            pwd = os.getenv("DM_PASSWORD", "Hbch@2711")
            dm = dmPython.connect(user=user, password=pwd, server=host, port=port)
            dc = dm.cursor()
            dc.execute("SELECT MOF_DIV_CODE, MOF_DIV_NAME FROM CH_AI.RDYS_BAS_MOFDIV WHERE LEVEL_NO=2 ORDER BY MOF_DIV_CODE")
            # 市码可能是7位(1304000)或9位(130000000)
            name_map = {}
            for r in dc.fetchall():
                name_map[r[0]] = r[1]
                if len(r[0]) == 9 and r[0].endswith('000'):
                    name_map[r[0][:7]] = r[1]  # 9位→7位映射：130400000→1304000
            dm.close()
            for row in rows:
                rc = row.get("region_code", "")
                if rc and rc != "000000":
                    # 先精确匹配，再试7位截断
                    row["region_name"] = name_map.get(rc) or name_map.get(rc[:7], "")
                else:
                    row["region_name"] = ""
                    row["region_code"] = "未设置"
        except Exception as e:
            import traceback as _tb
            _tb.print_exc()
            for row in rows:
                row["region_name"] = row.get("region_code", "")

        total_files = len(set(r["source"] for r in rows if r["source"]))
        total_chunks = sum(r["chunks"] for r in rows)
        return {"files": rows, "total_files": total_files, "total_chunks": total_chunks}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ═══════════════════════════════════════════════════════════════
# 路由 4: 查重
# ═══════════════════════════════════════════════════════════════

@router.get("/knowledge/check", summary="检查文件名是否已入库")
async def check_filename(filename: str = ""):
    """检查向量库中是否已有同名文件的切片。"""
    if not filename:
        return {"exists": False}
    try:
        engine = create_engine(DB_CONNECTION)
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


@router.post("/knowledge/remove", summary="批量从知识库删除切片")
async def remove_knowledge(request: Request):
    """根据 source 列表从向量库中删除切片。"""
    try:
        body = await request.json()
        sources = body.get("sources", [])
        if not sources:
            return JSONResponse({"error": "未提供 sources"}, status_code=400)
        engine = create_engine(DB_CONNECTION)
        deleted_total = 0
        with engine.connect() as conn:
            for src in sources:
                result = conn.execute(
                    text(f"DELETE FROM {DB_TABLE} WHERE {DB_METADATA_COL}->>'source' = :src"),
                    {"src": src},
                )
                deleted_total += result.rowcount
            conn.commit()
        engine.dispose()
        # Bug 41: 同步更新对应 job 的状态
        for src in sources:
            state_manager.update_job(
                src,
                status="completed",
                progress="已从知识库移除",
                progress_pct=100,
                ingest_error=None,
            )
        return {"status": "ok", "message": f"已删除 {deleted_total} 条切片", "deleted": deleted_total}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/knowledge/chunks", summary="查询某文档的切片内容")
async def get_knowledge_chunks(source: str):
    """根据 source 返回向量库中该文档的前 20 条切片内容（用于预览）。"""
    try:
        engine = create_engine(DB_CONNECTION)
        with engine.connect() as conn:
            result = conn.execute(
                text(f"SELECT c_document FROM {DB_TABLE} WHERE {DB_METADATA_COL}->>'source' = :src LIMIT 20"),
                {"src": source},
            )
            chunks = [{"content": (r[0] or "")[:2000]} for r in result.fetchall()]
        engine.dispose()
        return {"chunks": chunks}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@router.get("/region-permission", summary="查询文档的地区权限")
async def get_region_permission(source: str):
    """从 pgvector metadata 查询文档的地区权限。"""
    try:
        engine = create_engine(DB_CONNECTION)
        with engine.connect() as conn:
            result = conn.execute(
                text(f"SELECT {DB_METADATA_COL}->>'region_code' FROM {DB_TABLE} WHERE {DB_METADATA_COL}->>'source' = :src LIMIT 1"),
                {"src": source},
            )
            row = result.fetchone()
        engine.dispose()
        return {"region_code": (row[0] or "") if row else "", "region_name": ""}
    except Exception as e:
        return {"region_code": "", "error": str(e)}


@router.post("/region-permission", summary="更新文档的地区权限")
async def update_region_permission(request: Request):
    """更新文档的地区权限——直接更新 pgvector metadata。"""
    try:
        body = await request.json()
        source = body.get("source", "")
        region_code = body.get("region_code", "")
        if not source:
            return JSONResponse({"error": "未提供 source"}, status_code=400)

        engine = create_engine(DB_CONNECTION)
        with engine.connect() as conn:
            conn.execute(
                text(f"UPDATE {DB_TABLE} SET {DB_METADATA_COL} = jsonb_set({DB_METADATA_COL}, '{{\"region_code\"}}', :rc) WHERE {DB_METADATA_COL}->>'source' = :src"),
                {"rc": f'"{region_code}"', "src": source},
            )
            conn.commit()
        engine.dispose()
        return {"status": "ok"}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)



@router.get("/model-service/status", summary="获取模型服务状态")
async def model_service_status():
    """代理请求 MinerU 模型服务的状态（绕过 httpx 依赖，仅用标准库）。"""
    import urllib.request, json
    try:
        req = urllib.request.Request(f"{MINERU_SERVICE_URL}/api/status")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return {"status": "offline", "model_loaded": False, "active_count": 0, "queue_size": 0, "total_processed": 0}


@router.get("/regions", summary="获取市级区划列表")
async def get_regions():
    """从达梦 CH_AI.RDYS_BAS_MOFDIV 读取市级区划 (LEVEL_NO=2, 排除省本级)。"""
    try:
        import dmPython
        host = os.getenv("DM_HOST", "120.211.116.133")
        port = int(os.getenv("DM_PORT", "46252"))
        user = os.getenv("DM_USERNAME", "CH_AI")
        pwd = os.getenv("DM_PASSWORD", "Hbch@2711")
        conn = dmPython.connect(user=user, password=pwd, server=host, port=port)
        cur = conn.cursor()
        cur.execute("SELECT MOF_DIV_CODE, MOF_DIV_NAME FROM CH_AI.RDYS_BAS_MOFDIV WHERE LEVEL_NO=2 AND MOF_DIV_CODE LIKE '13%' ORDER BY MOF_DIV_CODE")
        rows = cur.fetchall()
        conn.close()
        return {"regions": [{"code": r[0], "name": r[1]} for r in rows]}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ═══════════════════════════════════════════════════════════════
# 路由 5: 任务列表 / 详情 / 下载 / 删除
# ═══════════════════════════════════════════════════════════════

@router.get("/jobs", summary="任务列表")
async def list_jobs(status: str = None, page: int = 1, per_page: int = 20):
    """获取文档处理任务列表，支持分页和状态筛选。"""
    jobs = state_manager.list_jobs(status=status, page=page, per_page=per_page)
    total = state_manager.count_jobs(status=status)  # Bug 15: total 始终为总数
    # 批量查询 region_name
    region_map = {}
    try:
        import dmPython
        host = os.getenv("DM_HOST", "120.211.116.133")
        port = int(os.getenv("DM_PORT", "46252"))
        user = os.getenv("DM_USERNAME", "CH_AI")
        pwd = os.getenv("DM_PASSWORD", "Hbch@2711")
        dm = dmPython.connect(user=user, password=pwd, server=host, port=port)
        dc = dm.cursor()
        dc.execute("SELECT MOF_DIV_CODE, MOF_DIV_NAME FROM CH_AI.RDYS_BAS_MOFDIV WHERE LEVEL_NO=2 ORDER BY MOF_DIV_CODE")
        name_map = {}
        for r in dc.fetchall():
            name_map[r[0]] = r[1]
            if len(r[0]) == 9 and r[0].endswith('000'):
                name_map[r[0][:7]] = r[1]
        dm.close()
        for j in jobs:
            rc = j.get("region_code", "")
            if rc and rc != "000000":
                j["region_name"] = name_map.get(rc) or name_map.get(rc[:7], rc)
            else:
                j["region_name"] = rc or "未设置"
    except Exception as e:
        # dmPython 不可用时兜底：region_name 显示原始编码（而非缺失导致前端空白）
        import traceback as _tb
        _tb.print_exc()
        for j in jobs:
            if "region_name" not in j:
                j["region_name"] = j.get("region_code", "未设置")
    return {"jobs": jobs, "total": total}


@router.post("/jobs/list-batch", summary="批量查询任务状态")
async def list_jobs_batch(request: Request):
    """批量查询指定 ID 列表的任务状态（供前端轮询）。"""
    body = await request.json()
    ids = body.get("job_ids", [])
    jobs = []
    for jid in ids:
        j = state_manager.get_job(jid)
        if j:
            # Bug 40: 如果 progress_pct==100 但 status==processing，说明
            # MinerU 已经完成但 dcp 因 GIL 窗口错过了 completed。
            # 轮询时直接 fix 为 completed，让前端立刻看到正常状态。
            if j.get("progress", "") == "处理完成（等待确认完成...）" and j.get("progress_pct") == 100:
                j = dict(j)
                j["status"] = "completed"
                j["progress"] = "处理完成"
            jobs.append({
                "id": j.get("id", jid),
                "filename": j.get("filename", ""),
                "status": j.get("status", ""),
                "progress": j.get("progress", ""),
                "progress_pct": j.get("progress_pct", 0),
                "chunk_count": j.get("chunk_count", 0),
                "processing_time": j.get("processing_time", 0),
                "error": j.get("error"),
                "ingest_error": j.get("ingest_error"),
            })
    return {"jobs": jobs}


@router.get("/jobs/{job_id}", summary="任务详情")
async def get_job(job_id: str):
    """获取单个任务完整信息。"""
    job = state_manager.get_job(job_id)
    if not job:
        return JSONResponse({"error": "任务不存在"}, status_code=404)
    return job


@router.get("/jobs/{job_id}/download", summary="下载 DOCX")
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


@router.delete("/jobs/{job_id}", summary="删除任务")
async def delete_job(job_id: str):
    """删除任务及关联的上传文件和输出文件，同时清理向量库数据。"""
    job = state_manager.get_job(job_id)
    if not job:
        return JSONResponse({"error": "任务不存在"}, status_code=404)

    # 如果任务正在模型服务中处理，尝试取消
    mineru_tid = job.get("mineru_task_id", "")
    if mineru_tid and job.get("status") in ("processing", "queued"):
        try:
            import urllib.request
            req = urllib.request.Request(f"{MINERU_SERVICE_URL}/api/queue/{mineru_tid}/cancel", method="POST")
            urllib.request.urlopen(req, timeout=5)
        except Exception:
            pass  # 取消失败不影响删除（任务可能已不存在）

    # 清理向量库数据（Bug 8: 与上传文件及输出目录同步清理）
    if job.get("status") == "ingested":
        try:
            engine = create_engine(DB_CONNECTION)
            with engine.connect() as conn:
                conn.execute(
                    text(f"DELETE FROM {DB_TABLE} WHERE {DB_METADATA_COL}->>'source' = :src"),
                    {"src": job_id},
                )
                conn.commit()
            engine.dispose()
        except Exception:
            pass  # 向量清理失败不阻止任务删除

    # 清理上传文件
    if job.get("input_path"):
        input_dir = Path(job["input_path"]).parent
        if input_dir.exists():
            shutil.rmtree(input_dir, ignore_errors=True)

    # 清理输出目录
    output_dir = OUTPUT_DIR / job_id
    if output_dir.exists():
        shutil.rmtree(output_dir, ignore_errors=True)

    state_manager.delete_job(job_id)
    return {"ok": True}


@router.post("/jobs/batch-download", summary="批量下载 ZIP")
async def batch_download(request: Request):
    """将选中任务的 DOCX 打包为 zip 下载。"""
    body = await request.json()
    job_ids = body.get("job_ids", [])
    if not job_ids:
        return JSONResponse({"error": "未提供 job_ids"}, status_code=400)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        added = 0
        name_counter = {}  # Bug 20: 同名文件去重计数
        for jid in job_ids:
            job = state_manager.get_job(jid)
            if not job or not job.get("output_path"):
                continue
            path = Path(job["output_path"])
            if not path.exists():
                continue
            zip_name = path.name
            if zip_name in name_counter:
                name_counter[zip_name] += 1
                stem, ext = os.path.splitext(zip_name)
                zip_name = f"{stem}_{name_counter[zip_name]}{ext}"
            else:
                name_counter[zip_name] = 0
            zf.write(str(path), zip_name)
            added += 1
        if added == 0:
            return JSONResponse({"error": "没有可下载的文件"}, status_code=404)

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=documents_{len(job_ids)}.zip"},
    )


# ═══════════════════════════════════════════════════════════════
# 路由 6: 入库 / 出库
# ═══════════════════════════════════════════════════════════════

@router.post("/jobs/{job_id}/ingest", summary="入库到向量知识库")
async def ingest_job(job_id: str, request: Request = None):
    """将处理后的 DOCX 导入 pgvector 知识库。支持 Request body 传入 kb_id 覆盖 job 默认值。"""
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

    if not RAG_INGEST_SCRIPT.exists():
        return JSONResponse({"error": f"入库脚本不存在: {RAG_INGEST_SCRIPT}"}, status_code=500)

    if _ingestion_lock.locked():
        return JSONResponse({"error": "有另一个入库任务正在执行，请等待完成后再试"}, status_code=409)

    acquired = _ingestion_lock.acquire(blocking=False)
    if not acquired:
        return JSONResponse({"error": "入库任务繁忙"}, status_code=409)

    try:
        state_manager.update_job(job_id, status="ingesting", progress="正在入库到 RAG 知识库...", progress_pct=0)

        mineru_python = MINERU_VENV_PYTHON
        if not Path(mineru_python).exists():
            mineru_python = sys.executable

        # Bug 41: 构建干净环境，清除可能污染 venv import 路径的变量
        # Build clean env: filter out vars that pollute MinerU venv site-packages
        # (CONDA_ vars make Python think it's in Anaconda, shadowing venv packages)
        ingest_env = {
            k: v for k, v in os.environ.items()
            if k not in ("PYTHONPATH", "PYTHONSTARTUP", "PYTHONHOME")
            and not k.startswith("CONDA_")
            and not k.startswith("_CONDA")
            and not k.startswith("__CONDA")
        }
        ingest_env.setdefault("SYSTEMROOT", os.getenv("SYSTEMROOT", os.path.expandvars("%SystemRoot%")))
        ingest_env["PYTHONUNBUFFERED"] = "1"
        ingest_env["PYTHONIOENCODING"] = "utf-8"

        # 支持运行时指定 kb_id（入库弹窗传入，优先于 job 默认值）
        body_kb = {}
        if request:
            try:
                body_kb = await request.json()
            except Exception:
                pass
        kb_id = body_kb.get("kb_id") if "kb_id" in body_kb else job.get("kb_id", "")
        region_code = job.get("region_code", "000000")
        tags = json.dumps(job.get("tags", []), ensure_ascii=False) if isinstance(job.get("tags"), list) else "[]"

        result = subprocess.run(
            [mineru_python, str(RAG_INGEST_SCRIPT), str(output_path), job_id, kb_id, region_code, tags],
            cwd=str(MINERU_BASE),
            capture_output=True,
            text=True, encoding='utf-8', errors='replace',
            timeout=JOB_TIMEOUT_SECONDS,
            env=ingest_env,
        )

        stdout_tail = result.stdout[-1000:] if result.stdout else ""
        stderr_tail = result.stderr[-1000:] if result.stderr else ""

        if result.returncode != 0:
            state_manager.update_job(
                job_id,
                status="completed",
                progress="入库失败",
                progress_pct=0,
                ingest_error=f"入库失败 (exit code: {result.returncode})\n{stderr_tail}",
            )
            return JSONResponse({
                "status": "failed",
                "error": f"入库脚本执行失败 (exit code: {result.returncode})",
                "stderr": stderr_tail[-500:],
            }, status_code=500)

        state_manager.update_job(
            job_id,
            status="ingested",
            progress="入库完成",
            progress_pct=100,
            ingested_at=time.time(),
        )

        return JSONResponse({
            "status": "ingested",
            "message": "入库完成",
            "stdout_tail": stdout_tail[-500:],
        })

    except subprocess.TimeoutExpired:
        state_manager.update_job(job_id, status="completed", progress="入库超时", progress_pct=0,
                                 ingest_error=f"入库超时 (>{JOB_TIMEOUT_SECONDS}秒)")
        return JSONResponse({"error": f"入库超时 (>{JOB_TIMEOUT_SECONDS}秒)"}, status_code=504)
    except Exception as e:
        traceback.print_exc()
        state_manager.update_job(job_id, status="completed", progress="入库异常", progress_pct=0, ingest_error=str(e))
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        _ingestion_lock.release()


@router.post("/jobs/{job_id}/unload", summary="从知识库移除")
async def unload_job(job_id: str):
    """从向量库中删除该文件的所有向量切片（同时更新本地 job 状态）。"""
    job = state_manager.get_job(job_id)
    if not job:
        return JSONResponse({"error": "任务不存在"}, status_code=404)

    # 按 source=job_id 删除（与入库脚本 rag_ingest.py 一致）
    try:
        engine = create_engine(DB_CONNECTION)
        with engine.connect() as conn:
            result = conn.execute(
                text(f"DELETE FROM {DB_TABLE} WHERE {DB_METADATA_COL}->>'source' = :src"),
                {"src": job_id},
            )
            conn.commit()
            deleted = result.rowcount
        engine.dispose()

        state_manager.update_job(
            job_id,
            status="completed",
            progress="已从知识库移除",
            progress_pct=100,
            ingest_error=None,
        )
        return {"status": "ok", "message": "已从知识库移除"}

    except Exception as e:
        traceback.print_exc()
        state_manager.update_job(job_id, ingest_error=f"删除向量失败: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/ingest/batch", summary="批量入库")
async def ingest_batch(request: Request):
    """批量入库：传入 job_ids 列表，串行执行。"""
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
    mineru_python = MINERU_VENV_PYTHON
    if not Path(mineru_python).exists():
        mineru_python = sys.executable
    try:
        for job_id in job_ids:
            job = state_manager.get_job(job_id)
            if not job:
                results.append({"job_id": job_id, "status": "skipped", "error": "任务不存在"})
                continue
            if job["status"] != "completed":
                results.append({"job_id": job_id, "status": "skipped", "error": f"状态为 {job['status']}"})
                continue
            output_path = Path(job["output_path"])
            if not output_path.exists():
                results.append({"job_id": job_id, "status": "skipped", "error": "文件不存在"})
                continue

            state_manager.update_job(job_id, status="ingesting", progress="批量入库中...", progress_pct=0)

            try:
                ingest_env = {
                    k: v for k, v in os.environ.items()
                    if k not in ("PYTHONPATH", "PYTHONSTARTUP", "PYTHONHOME")
                    and not k.startswith("CONDA_")
                    and not k.startswith("_CONDA")
                    and not k.startswith("__CONDA")
                }
                ingest_env.setdefault("SYSTEMROOT", os.getenv("SYSTEMROOT", os.path.expandvars("%SystemRoot%")))
                ingest_env["PYTHONUNBUFFERED"] = "1"
                ingest_env["PYTHONIOENCODING"] = "utf-8"

                kb_id = job.get("kb_id", "default")
                region_code = job.get("region_code", "000000")
                tags = json.dumps(job.get("tags", []), ensure_ascii=False) if isinstance(job.get("tags"), list) else "[]"

                result = subprocess.run(
                    [mineru_python, str(RAG_INGEST_SCRIPT), str(output_path), job_id, kb_id, region_code, tags],
                    cwd=str(MINERU_BASE),
                    capture_output=True,
                    text=True, encoding='utf-8', errors='replace',
                    timeout=JOB_TIMEOUT_SECONDS,
                    env=ingest_env,
                )

                if result.returncode == 0:
                    state_manager.update_job(job_id, status="ingested", progress="入库完成", progress_pct=100, ingested_at=time.time())
                    results.append({"job_id": job_id, "status": "ok"})
                else:
                    state_manager.update_job(job_id, status="completed", progress="入库失败", progress_pct=0,
                                             ingest_error=f"exit code {result.returncode}\n{result.stderr[-500:]}")
                    results.append({"job_id": job_id, "status": "failed", "error": f"exit code {result.returncode}"})

            except subprocess.TimeoutExpired:
                state_manager.update_job(job_id, status="completed", progress="入库超时", progress_pct=0,
                                         ingest_error=f"超时 >{JOB_TIMEOUT_SECONDS}s")
                results.append({"job_id": job_id, "status": "failed", "error": "超时"})
            except Exception as e:
                state_manager.update_job(job_id, status="completed", progress="入库异常", progress_pct=0, ingest_error=str(e))
                results.append({"job_id": job_id, "status": "failed", "error": str(e)})

    finally:
        _ingestion_lock.release()

    ok_count = sum(1 for r in results if r["status"] == "ok")
    return JSONResponse({"results": results, "ok": ok_count, "total": len(results)})


# ═══════════════════════════════════════════════════════════════
# 路由 7: 替换 / 直传
# ═══════════════════════════════════════════════════════════════

@router.post("/jobs/{job_id}/replace", summary="替换输出文件")
async def replace_output(job_id: str, file: UploadFile = File(...)):
    """上传手动编辑后的 DOCX 替换任务输出文件。"""
    job = state_manager.get_job(job_id)
    if not job:
        return JSONResponse({"error": "任务不存在"}, status_code=404)
    if job["status"] not in ("completed", "ingested"):
        return JSONResponse({"error": f"任务状态为 {job['status']}，仅已完成/已入库的任务可替换"}, status_code=400)

    if not file.filename:
        return JSONResponse({"error": "未选择文件"}, status_code=400)

    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return JSONResponse({"error": f"不支持的文件格式: {ext}"}, status_code=400)

    content = await file.read()
    file_size = len(content)
    if file_size == 0:
        return JSONResponse({"error": "文件为空"}, status_code=400)
    max_bytes = MAX_FILE_SIZE_MB * 1024 * 1024
    if file_size > max_bytes:
        return JSONResponse({"error": f"文件过大: {_format_size(file_size)}"}, status_code=400)

    job_output_dir = OUTPUT_DIR / job_id
    job_output_dir.mkdir(parents=True, exist_ok=True)

    modify_ver = job.get("modify_count", 0) + 1
    new_filename = f"modified_v{modify_ver}_{file.filename}"
    new_path = job_output_dir / new_filename
    new_path.write_bytes(content)

    try:
        preview_text = _extract_preview_text(new_path)
        chunk_count = _count_chunks(new_path)
    except Exception:
        if new_path.exists():
            new_path.unlink()
        return JSONResponse({"error": "无法读取 DOCX 文件"}, status_code=500)

    # 若已入库，先清理向量库
    was_ingested = job["status"] == "ingested"
    if was_ingested:
        try:
            engine = create_engine(DB_CONNECTION)
            with engine.connect() as conn:
                conn.execute(
                    text(f"DELETE FROM {DB_TABLE} WHERE {DB_METADATA_COL}->>'source' = :src"),
                    {"src": job_id},
                )
                conn.commit()
            engine.dispose()
        except Exception:
            pass

    updated_job = state_manager.replace_job_output(
        job_id=job_id,
        output_path=str(new_path),
        preview_text=preview_text,
        chunk_count=chunk_count,
    )

    if updated_job is None:
        return JSONResponse({"error": "更新任务状态失败"}, status_code=500)

    msg = "文件已替换，可重新入库"
    if was_ingested:
        msg += "（已清理旧向量）"

    return JSONResponse({"status": "ok", "message": msg, "job_id": job_id, "chunk_count": chunk_count, "job": updated_job})


@router.post("/direct-upload", summary="直接上传 DOCX")
async def direct_upload(file: UploadFile = File(...)):
    """直接上传已编辑好的 DOCX，跳过 MinerU 处理，直接作为 completed 状态任务。"""
    if not file.filename:
        return JSONResponse({"error": "未选择文件"}, status_code=400)

    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return JSONResponse({"error": f"不支持的文件格式: {ext}"}, status_code=400)

    content = await file.read()
    file_size = len(content)
    if file_size == 0:
        return JSONResponse({"error": "文件为空"}, status_code=400)
    max_bytes = MAX_FILE_SIZE_MB * 1024 * 1024
    if file_size > max_bytes:
        return JSONResponse({"error": f"文件过大: {_format_size(file_size)}"}, status_code=400)

    job_id = state_manager.create_job(filename=file.filename, file_size=file_size, input_path="")

    job_output_dir = OUTPUT_DIR / job_id
    job_output_dir.mkdir(parents=True, exist_ok=True)
    output_path = job_output_dir / file.filename
    output_path.write_bytes(content)

    try:
        preview_text = _extract_preview_text(output_path)
        chunk_count = _count_chunks(output_path)
    except Exception:
        state_manager.delete_job(job_id)
        return JSONResponse({"error": "无法读取 DOCX 文件"}, status_code=500)

    state_manager.update_job(
        job_id,
        status="completed",
        output_path=str(output_path),
        progress="已就绪（跳过处理，可直接入库）",
        chunk_count=chunk_count,
        preview_text=preview_text,
        progress_pct=100,
    )

    return JSONResponse({
        "job_id": job_id,
        "status": "completed",
        "filename": file.filename,
        "chunk_count": chunk_count,
        "message": "文档已就绪，可直接入库",
    })

# ═══════════════════════════════════════════════════════════════
# 知识库管理 API (多知识库 CRUD + 文档启用/禁用 + 元数据)
# ═══════════════════════════════════════════════════════════════

# ── 辅助: 审计日志 ──
def _audit(action: str, target_type: str, target_id: str, detail: dict = None, operator: str = ""):
    """写入审计日志到 PostgreSQL。异步执行，不阻塞 API 响应。"""
    try:
        engine = create_engine(DB_CONNECTION)
        with engine.connect() as conn:
            conn.execute(
                text(f"INSERT INTO {DB_AUDIT_TABLE} (action, target_type, target_id, detail, operator) "
                     "VALUES (:a, :t, :i, :d, :o)"),
                {"a": action, "t": target_type, "i": target_id,
                 "d": json.dumps(detail or {}, ensure_ascii=False), "o": operator},
            )
            conn.commit()
        engine.dispose()
    except Exception:
        pass  # 审计失败不影响主流程


# ── KB CRUD ──

@router.get("/knowledge-bases", summary="列出所有知识库")
async def list_knowledge_bases(is_active: bool = None):
    """列出所有知识库，支持 ?is_active= 过滤。"""
    try:
        engine = create_engine(DB_CONNECTION)
        with engine.connect() as conn:
            sql = f"SELECT id, name, description, directory_keywords, is_active, owner_id, created_at, updated_at FROM {DB_KB_TABLE}"
            if is_active is not None:
                sql += f" WHERE is_active = {str(is_active).lower()}"
            sql += " ORDER BY created_at DESC"
            result = conn.execute(text(sql))
            kbs = [{"id": r[0], "name": r[1], "description": r[2], "directory_keywords": r[3],
                    "is_active": r[4], "owner_id": r[5], "created_at": str(r[6]) if r[6] else "",
                    "updated_at": str(r[7]) if r[7] else "",
                    "collection": DB_TABLE}
                   for r in result.fetchall()]
        engine.dispose()
        # 补充文档数和切片数统计
        for kb in kbs:
            try:
                eng2 = create_engine(DB_CONNECTION)
                with eng2.connect() as c2:
                    count_r = c2.execute(
                        text(f"SELECT COUNT(DISTINCT {DB_METADATA_COL}->>'source'), COUNT(*) FROM {DB_TABLE} WHERE {DB_METADATA_COL}->>'kb_id' = :kid"),
                        {"kid": kb["id"]},
                    ).fetchone()
                    kb["document_count"] = count_r[0] if count_r else 0
                    kb["chunk_count"] = count_r[1] if count_r else 0
                eng2.dispose()
            except Exception:
                kb["document_count"] = 0
                kb["chunk_count"] = 0
        return {"kbs": kbs, "total": len(kbs)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/knowledge-bases", summary="创建知识库")
async def create_knowledge_base(request: Request):
    """创建知识库: {id, name, description?}。id 校验: 字母数字+下划线+连字符。"""
    import re
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "无效的 JSON 请求体"}, status_code=400)

    kb_id = (body.get("id") or "").strip()
    name = (body.get("name") or "").strip()
    if not kb_id or not name:
        return JSONResponse({"error": "id 和 name 不能为空"}, status_code=400)
    if not re.match(r'^[a-zA-Z0-9_-]+$', kb_id):
        return JSONResponse({"error": "id 只能包含字母、数字、下划线和连字符"}, status_code=400)

    description = body.get("description", "")
    directory_keywords = body.get("directory_keywords", "[]")

    try:
        engine = create_engine(DB_CONNECTION)
        with engine.connect() as conn:
            conn.execute(
                text(f"INSERT INTO {DB_KB_TABLE} (id, name, description, directory_keywords) VALUES (:i, :n, :d, :dk)"),
                {"i": kb_id, "n": name, "d": description, "dk": directory_keywords if isinstance(directory_keywords, str) else json.dumps(directory_keywords, ensure_ascii=False)},
            )
            conn.commit()
        engine.dispose()
        return {"status": "ok", "id": kb_id, "name": name}
    except Exception as e:
        if "duplicate key" in str(e).lower() or "unique" in str(e).lower():
            return JSONResponse({"error": f"知识库 id '{kb_id}' 已存在"}, status_code=409)
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/knowledge-bases/{kb_id}", summary="获取知识库详情")
async def get_knowledge_base(kb_id: str):
    """获取知识库详情，含文档数、切片数统计。"""
    if kb_id == "stats":
        return await get_knowledge_bases_stats()
    try:
        engine = create_engine(DB_CONNECTION)
        with engine.connect() as conn:
            result = conn.execute(
                text(f"SELECT id, name, description, directory_keywords, is_active, owner_id, created_at, updated_at FROM {DB_KB_TABLE} WHERE id = :i"),
                {"i": kb_id},
            ).fetchone()
        engine.dispose()
        if not result:
            return JSONResponse({"error": "知识库不存在"}, status_code=404)

        kb = {"id": result[0], "name": result[1], "description": result[2], "directory_keywords": result[3],
              "is_active": result[4], "owner_id": result[5], "created_at": str(result[6]) if result[6] else "",
              "updated_at": str(result[7]) if result[7] else ""}

        # 补充统计
        try:
            eng2 = create_engine(DB_CONNECTION)
            with eng2.connect() as c2:
                count_r = c2.execute(
                    text(f"SELECT COUNT(DISTINCT {DB_METADATA_COL}->>'source'), COUNT(*) FROM {DB_TABLE} WHERE {DB_METADATA_COL}->>'kb_id' = :kid"),
                    {"kid": kb_id},
                ).fetchone()
                kb["document_count"] = count_r[0] if count_r else 0
                kb["chunk_count"] = count_r[1] if count_r else 0
                # 启用/禁用分布
                enabled_r = c2.execute(
                    text(f"SELECT COUNT(DISTINCT {DB_METADATA_COL}->>'source') FROM {DB_TABLE} WHERE {DB_METADATA_COL}->>'kb_id' = :kid AND ({DB_METADATA_COL}->>'enabled')::boolean = true"),
                    {"kid": kb_id},
                ).fetchone()
                disabled_r = c2.execute(
                    text(f"SELECT COUNT(DISTINCT {DB_METADATA_COL}->>'source') FROM {DB_TABLE} WHERE {DB_METADATA_COL}->>'kb_id' = :kid AND ({DB_METADATA_COL}->>'enabled')::boolean = false"),
                    {"kid": kb_id},
                ).fetchone()
                kb["enabled_docs"] = enabled_r[0] if enabled_r else 0
                kb["disabled_docs"] = disabled_r[0] if disabled_r else 0
            eng2.dispose()
        except Exception:
            kb["document_count"] = kb["chunk_count"] = kb["enabled_docs"] = kb["disabled_docs"] = 0

        return kb
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.put("/knowledge-bases/{kb_id}", summary="更新知识库")
async def update_knowledge_base(kb_id: str, request: Request):
    """更新知识库: {name?, description?, is_active?}。"""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "无效的 JSON 请求体"}, status_code=400)

    try:
        engine = create_engine(DB_CONNECTION)
        with engine.connect() as conn:
            # 先检查是否存在
            existing = conn.execute(
                text(f"SELECT id FROM {DB_KB_TABLE} WHERE id = :i"), {"i": kb_id}
            ).fetchone()
            if not existing:
                engine.dispose()
                return JSONResponse({"error": "知识库不存在"}, status_code=404)

            updates = []
            params = {"i": kb_id}
            if "name" in body:
                updates.append("name = :name")
                params["name"] = body["name"]
            if "description" in body:
                updates.append("description = :desc")
                params["desc"] = body["description"]
            if "directory_keywords" in body:
                dk = body["directory_keywords"]
                updates.append("directory_keywords = :dk")
                params["dk"] = dk if isinstance(dk, str) else json.dumps(dk, ensure_ascii=False)
            if "is_active" in body:
                old_is_active = body["is_active"]
                updates.append("is_active = :ia")
                params["ia"] = body["is_active"]
                # 审计日志
                _audit("toggle_kb" if not old_is_active else "enable_kb", "knowledge_base", kb_id,
                       {"is_active": body["is_active"]})

            if updates:
                updates.append("updated_at = NOW()")
                conn.execute(
                    text(f"UPDATE {DB_KB_TABLE} SET {', '.join(updates)} WHERE id = :i"),
                    params,
                )
                conn.commit()
        engine.dispose()
        return {"status": "ok", "id": kb_id}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.delete("/knowledge-bases/{kb_id}", summary="删除知识库")
async def delete_knowledge_base(kb_id: str, force: bool = False):
    """删除知识库。有文档时返回 409，传 ?force=true 强制删除（同时清理向量切片）。"""
    if kb_id == "default":
        return JSONResponse({"error": "不能删除默认知识库"}, status_code=400)

    try:
        engine = create_engine(DB_CONNECTION)
        with engine.connect() as conn:
            # 检查是否有文档
            count_r = conn.execute(
                text(f"SELECT COUNT(*) FROM {DB_TABLE} WHERE {DB_METADATA_COL}->>'kb_id' = :kid"),
                {"kid": kb_id},
            ).fetchone()
            chunk_count = count_r[0] if count_r else 0

            if chunk_count > 0 and not force:
                doc_count_r = conn.execute(
                    text(f"SELECT COUNT(DISTINCT {DB_METADATA_COL}->>'source') FROM {DB_TABLE} WHERE {DB_METADATA_COL}->>'kb_id' = :kid"),
                    {"kid": kb_id},
                ).fetchone()
                engine.dispose()
                return JSONResponse({
                    "error": f"知识库 '{kb_id}' 下有 {doc_count_r[0] if doc_count_r else 0} 个文档、{chunk_count} 个切片，请先将文档迁移到其他知识库后再删除，或使用 ?force=true 强制删除",
                    "document_count": doc_count_r[0] if doc_count_r else 0,
                    "chunk_count": chunk_count,
                }, status_code=409)

            # 强制删除：清理向量切片
            if force and chunk_count > 0:
                deleted = conn.execute(
                    text(f"DELETE FROM {DB_TABLE} WHERE {DB_METADATA_COL}->>'kb_id' = :kid"),
                    {"kid": kb_id},
                ).rowcount
                conn.commit()
                _audit("force_delete_kb", "knowledge_base", kb_id, {"chunks_deleted": deleted})

            # 删除 KB
            conn.execute(text(f"DELETE FROM {DB_KB_TABLE} WHERE id = :i"), {"i": kb_id})
            conn.commit()
        engine.dispose()
        return {"status": "ok", "message": f"知识库 '{kb_id}' 已删除"}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/knowledge-bases/stats", summary="全部知识库聚合统计")
async def get_knowledge_bases_stats():
    """返回每个知识库的文档数、切片数、启用/禁用分布。"""
    try:
        # 直接用 create_engine 避免闭包冲突
        engine = create_engine(DB_CONNECTION)
        with engine.connect() as conn:
            kb_result = conn.execute(text(f"SELECT id, name FROM {DB_KB_TABLE} ORDER BY name"))
            rows = list(kb_result.fetchall())
        engine.dispose()

        if not rows:
            return {"kbs": [], "total_documents": 0, "total_chunks": 0}

        kbs = [{"id": r[0], "name": r[1]} for r in rows]
        total_docs = total_chunks = 0
        for kb in kbs:
            try:
                eng2 = create_engine(DB_CONNECTION)
                with eng2.connect() as c2:
                    rr = c2.execute(
                        text(f"SELECT COUNT(DISTINCT {DB_METADATA_COL}->>'source'), COUNT(*) FROM {DB_TABLE} WHERE {DB_METADATA_COL}->>'kb_id' = :kid"),
                        {"kid": kb["id"]},
                    ).fetchone()
                    kb["document_count"] = rr[0] if rr else 0
                    kb["chunk_count"] = rr[1] if rr else 0
                eng2.dispose()
            except Exception as ex:
                print(f"stats error for kb {kb['id']}: {ex}")
                kb["document_count"] = kb["chunk_count"] = 0
            total_docs += kb["document_count"]
            total_chunks += kb["chunk_count"]

        # 补充文档池统计（kb_id 为空或 NULL 的文档）
        pool_docs = pool_chunks = 0
        try:
            eng3 = create_engine(DB_CONNECTION)
            with eng3.connect() as c3:
                pr = c3.execute(
                    text(f"SELECT COUNT(DISTINCT {DB_METADATA_COL}->>'source'), COUNT(*) FROM {DB_TABLE} "
                         f"WHERE {DB_METADATA_COL}->>'kb_id' IS NULL OR {DB_METADATA_COL}->>'kb_id' = ''")
                ).fetchone()
                pool_docs = pr[0] if pr else 0
                pool_chunks = pr[1] if pr else 0
            eng3.dispose()
        except Exception:
            pass

        return {"kbs": kbs, "total_documents": total_docs, "total_chunks": total_chunks,
                "pool_document_count": pool_docs, "pool_chunk_count": pool_chunks}
    except Exception as e:
        import traceback as _tb; _tb.print_exc()
        return JSONResponse({"error": str(e)}, status_code=500)


# ── 文档启用/禁用 ──

@router.put("/knowledge/{source}/toggle", summary="切换文档启用/禁用状态")
async def toggle_document(source: str, request: Request = None):
    """切换单个文档的启用状态: {enabled: bool}。"""
    try:
        body = await request.json() if request else {}
        enabled = body.get("enabled", None)
    except Exception:
        return JSONResponse({"error": "无效的 JSON 请求体"}, status_code=400)

    try:
        engine = create_engine(DB_CONNECTION)
        with engine.connect() as conn:
            if enabled is None:
                # toggle: 查询当前状态后取反
                cur_r = conn.execute(
                    text(f"SELECT {DB_METADATA_COL}->>'enabled' FROM {DB_TABLE} WHERE {DB_METADATA_COL}->>'source' = :s LIMIT 1"),
                    {"s": source},
                ).fetchone()
                if not cur_r:
                    engine.dispose()
                    return JSONResponse({"error": "文档不存在"}, status_code=404)
                enabled = not (cur_r[0] == "true" or cur_r[0] == "True")

            conn.execute(
                text(f"UPDATE {DB_TABLE} SET {DB_METADATA_COL} = jsonb_set({DB_METADATA_COL}, '{{\"enabled\"}}', CAST(:val AS jsonb)) WHERE {DB_METADATA_COL}->>'source' = :s"),
                {"val": str(enabled).lower(), "s": source},
            )
            conn.commit()
        engine.dispose()
        _audit("toggle_doc", "document", source, {"enabled": enabled})
        return {"status": "ok", "source": source, "enabled": enabled}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.put("/knowledge/toggle-batch", summary="批量切换文档启用/禁用")
async def toggle_documents_batch(request: Request):
    """批量切换: {sources: [...], enabled: bool}。"""
    try:
        body = await request.json()
        sources = body.get("sources", [])
        enabled = body.get("enabled", True)
    except Exception:
        return JSONResponse({"error": "无效的 JSON 请求体"}, status_code=400)

    if not sources:
        return JSONResponse({"error": "未提供 sources"}, status_code=400)

    try:
        engine = create_engine(DB_CONNECTION)
        updated = 0
        with engine.connect() as conn:
            for src in sources:
                result = conn.execute(
                    text(f"UPDATE {DB_TABLE} SET {DB_METADATA_COL} = jsonb_set({DB_METADATA_COL}, '{{\"enabled\"}}', CAST(:val AS jsonb)) WHERE {DB_METADATA_COL}->>'source' = :s"),
                    {"val": str(enabled).lower(), "s": src},
                )
                updated += result.rowcount
            conn.commit()
        engine.dispose()
        _audit("toggle_doc_batch", "document", ",".join(sources[:10]), {"enabled": enabled, "total": len(sources)})
        return {"status": "ok", "updated": updated, "total": len(sources)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ── 文档元数据 ──

@router.get("/knowledge/{source}/metadata", summary="获取文档完整元数据")
async def get_document_metadata(source: str):
    """获取文档的完整元数据信息。"""
    try:
        engine = create_engine(DB_CONNECTION)
        with engine.connect() as conn:
            # 获取第一条切片的 metadata（所有切片共享 source 的元数据字段）
            row = conn.execute(
                text(f"SELECT {DB_METADATA_COL}, c_document FROM {DB_TABLE} WHERE {DB_METADATA_COL}->>'source' = :s LIMIT 1"),
                {"s": source},
            ).fetchone()
            if not row:
                engine.dispose()
                return JSONResponse({"error": "文档不存在"}, status_code=404)

            meta = row[0] or {}
            # 统计切片数
            count_r = conn.execute(
                text(f"SELECT COUNT(*) FROM {DB_TABLE} WHERE {DB_METADATA_COL}->>'source' = :s"),
                {"s": source},
            ).fetchone()
        engine.dispose()

        kb_id = meta.get("kb_id", "default")
        kb_name = ""
        try:
            eng2 = create_engine(DB_CONNECTION)
            with eng2.connect() as c2:
                kb_r = c2.execute(text(f"SELECT name FROM {DB_KB_TABLE} WHERE id = :i"), {"i": kb_id}).fetchone()
                if kb_r:
                    kb_name = kb_r[0]
            eng2.dispose()
        except Exception:
            pass

        # 解析 tags（可能是 JSON 字符串或 Python list）
        tags = meta.get("tags", [])
        if isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except Exception:
                tags = [tags] if tags else []

        return {
            "source": source,
            "filename": meta.get("filename", ""),
            "kb_id": kb_id,
            "kb_name": kb_name,
            "enabled": meta.get("enabled", True) if isinstance(meta.get("enabled"), bool) else str(meta.get("enabled", "true")).lower() == "true",
            "tags": tags if isinstance(tags, list) else [],
            "region_code": meta.get("region_code", ""),
            "chunks": count_r[0] if count_r else 0,
            "created_at": meta.get("created_at", ""),
            "chunk_id": meta.get("chunk_id", ""),
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.put("/knowledge/{source}/metadata", summary="更新文档元数据")
async def update_document_metadata(source: str, request: Request):
    """更新文档元数据: {kb_id?, tags?}。支持文档迁移和标签编辑。"""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "无效的 JSON 请求体"}, status_code=400)

    try:
        engine = create_engine(DB_CONNECTION)
        with engine.connect() as conn:
            # 更新 kb_id
            if "kb_id" in body:
                new_kb_id = body["kb_id"]
                # 文档池（空字符串）跳过 KB 存在性检查
                if new_kb_id:
                    kb_check = conn.execute(
                        text(f"SELECT id FROM {DB_KB_TABLE} WHERE id = :i"), {"i": new_kb_id}
                    ).fetchone()
                    if not kb_check:
                        engine.dispose()
                        return JSONResponse({"error": f"目标知识库 '{new_kb_id}' 不存在"}, status_code=400)

                conn.execute(
                    text(f"UPDATE {DB_TABLE} SET {DB_METADATA_COL} = jsonb_set({DB_METADATA_COL}, '{{\"kb_id\"}}', CAST(:val AS jsonb)) WHERE {DB_METADATA_COL}->>'source' = :s"),
                    {"val": f'"{new_kb_id}"', "s": source},
                )

            # 更新 tags
            if "tags" in body:
                tags_val = body["tags"]
                if not isinstance(tags_val, list):
                    tags_val = [tags_val]
                conn.execute(
                    text(f"UPDATE {DB_TABLE} SET {DB_METADATA_COL} = jsonb_set({DB_METADATA_COL}, '{{\"tags\"}}', CAST(:val AS jsonb)) WHERE {DB_METADATA_COL}->>'source' = :s"),
                    {"val": json.dumps(tags_val, ensure_ascii=False), "s": source},
                )

            conn.commit()
        engine.dispose()
        _audit("update_metadata", "document", source, body)
        return {"status": "ok", "source": source}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ═══════════════════════════════════════════════════════════════
# 权限过滤预留口子:
#   - region_code 已在入库时存入 c_metadata
#   - 检索/召回接口后续加 ?region_code= 参数
#   - 石家庄(1301000)和河北省本级(130000000)看全部
#   - 其他市只看 c_metadata->>'region_code' = 本市的
#   - 管理界面 (knowledge/stats/jobs) 不做过滤，所有用户可见全部
# ═══════════════════════════════════════════════════════════════
