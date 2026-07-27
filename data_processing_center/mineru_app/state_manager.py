"""
任务状态管理器 — 线程安全 + JSON 文件持久化。
"""
import json
import time
import uuid
import threading
from pathlib import Path
from typing import Optional

_LOCK = threading.Lock()
_JOBS: dict[str, dict] = {}

# 持久化文件路径
_STORE_FILE = Path(__file__).resolve().parent.parent / "output" / "_jobs.json"  # data_processing_center/output/_jobs.json


def _load_from_disk():
    """启动时从磁盘恢复任务记录。"""
    global _JOBS
    if _STORE_FILE.exists():
        try:
            with open(_STORE_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                _JOBS = loaded
        except Exception:
            _JOBS = {}


def _save_to_disk():
    """将当前任务字典写入磁盘。"""
    try:
        _STORE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_STORE_FILE, "w", encoding="utf-8") as f:
            json.dump(_JOBS, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# 启动时加载
_load_from_disk()


def create_job(filename: str, file_size: int, input_path: str) -> str:
    """创建任务记录，返回 job_id。"""
    job_id = uuid.uuid4().hex[:12]
    with _LOCK:
        _JOBS[job_id] = {
            "id": job_id,
            "filename": filename,
            "file_size": file_size,
            "input_path": input_path,
            "output_path": None,
            "strategy": None,
            "status": "uploaded",
            "progress": "等待处理...",
            "error": None,
            "ingest_error": None,
            "chunk_count": 0,
            "processing_time": 0,
            "created_at": time.time(),
            "ingested_at": None,
            "preview_text": None,
            "modified_at": None,
            "modify_count": 0,
        }
        _save_to_disk()
    return job_id


def update_job(job_id: str, **kwargs):
    """更新任务字段。"""
    with _LOCK:
        if job_id in _JOBS:
            _JOBS[job_id].update(kwargs)
            _save_to_disk()


def get_job(job_id: str) -> Optional[dict]:
    """获取单个任务。"""
    with _LOCK:
        job = _JOBS.get(job_id)
        return dict(job) if job else None


def list_jobs(status: Optional[str] = None, page: int = 1, per_page: int = 20) -> list[dict]:
    """列出任务，按创建时间倒序。"""
    with _LOCK:
        jobs = list(_JOBS.values())
        if status:
            jobs = [j for j in jobs if j["status"] == status]
        jobs.sort(key=lambda j: j.get("created_at", 0), reverse=True)
        start = (page - 1) * per_page
        return [dict(j) for j in jobs[start : start + per_page]]


def delete_job(job_id: str) -> bool:
    """删除任务记录。返回是否成功。"""
    with _LOCK:
        if job_id in _JOBS:
            del _JOBS[job_id]
            _save_to_disk()
            return True
        return False


def replace_job_output(
    job_id: str,
    output_path: str,
    preview_text: str,
    chunk_count: int,
) -> dict | None:
    """用修改后的 DOCX 替换任务的输出文件。

    如果任务原状态为 ingested，重置为 completed（允许重新入库）。
    每次替换递增 modify_count，记录 modified_at 时间戳。
    """
    with _LOCK:
        if job_id not in _JOBS:
            return None
        job = _JOBS[job_id]
        was_ingested = job.get("status") == "ingested"
        job.update({
            "output_path": output_path,
            "preview_text": preview_text,
            "chunk_count": chunk_count,
            "modified_at": time.time(),
            "modify_count": job.get("modify_count", 0) + 1,
        })
        if was_ingested:
            job["status"] = "completed"
            job["ingested_at"] = None
            job["ingest_error"] = None
            job["progress"] = "已替换修改版，可重新入库"
        else:
            job["progress"] = "已更新修改版"
        _save_to_disk()
        return dict(job)
