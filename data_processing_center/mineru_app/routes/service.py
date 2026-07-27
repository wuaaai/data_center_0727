"""
模型服务控制 API — 健康检查、状态查询、模型预热、服务关闭。
"""
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from mineru_app.model_manager import model_manager

router = APIRouter(prefix="/api", tags=["service"])


@router.get("/health", summary="健康检查")
async def health():
    """返回模型服务健康状态。"""
    status = model_manager.get_status()
    return {
        "status": "healthy" if status["model_loaded"] else ("warming_up" if status["model_loading"] else "error"),
        "model_loaded": status["model_loaded"],
        "model_loading": status["model_loading"],
        "model_error": status["model_error"],
        "uptime": status["uptime"],
        "active_count": status["active_count"],
        "queue_size": status["queue_size"],
    }


@router.get("/status", summary="详细服务状态")
async def service_status():
    """返回模型服务的详细运行状态。"""
    s = model_manager.get_status()
    return {
        "model_loaded": s["model_loaded"],
        "model_loading": s["model_loading"],
        "model_error": s["model_error"],
        "model_path": str(Path(__file__).resolve().parent.parent.parent / "modelscope" / "models" / "OpenDataLab" / "PDF-Extract-Kit-1___0"),
        "uptime": int(s["uptime"]),
        "active_count": s["active_count"],
        "queue_size": s["queue_size"],
        "max_workers": s["max_workers"],
        "total_processed": s["total_processed"],
        "total_failed": s["total_failed"],
    }


@router.post("/warmup", summary="手动预热模型")
async def warmup():
    """手动触发模型预热（加载模型到内存）。"""
    if model_manager.get_status()["model_loaded"]:
        return {"status": "already_ready"}
    if model_manager.get_status()["model_loading"]:
        return {"status": "already_warming_up"}
    import threading
    threading.Thread(target=model_manager._warmup_model, daemon=True).start()
    return JSONResponse({"status": "warming_up"}, status_code=202)


@router.post("/shutdown", summary="优雅关闭服务")
async def shutdown(force: bool = False):
    """关闭模型服务。force=true 立即终止，默认等待当前任务完成。"""
    model_manager.shutdown()
    return {"status": "shutting_down"}
