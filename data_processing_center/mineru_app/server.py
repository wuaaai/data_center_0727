"""
FastAPI 应用入口 — MinerU 模型服务 (端口 8003)。
从 mineru_0720 迁移到 data_processing_center，作为统一项目的一部分。
"""
import sys
from pathlib import Path
from contextlib import asynccontextmanager

# 项目根目录: data_processing_center/
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from mineru_app.config import UPLOAD_DIR, OUTPUT_DIR


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时创建目录 + 异步启动模型管理器（模型预热）。"""
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 启动模型管理器（异步加载模型，不阻塞服务启动）
    from mineru_app.model_manager import model_manager
    model_manager.start(warmup=True)
    yield
    model_manager.shutdown()


app = FastAPI(title="MinerU 模型服务", lifespan=lifespan)

# 模板
templates_dir = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))

# 静态文件
static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# 提供处理后文件的下载（output 目录）
app.mount("/output", StaticFiles(directory=str(OUTPUT_DIR)), name="output")

# 注册路由
from mineru_app.routes import upload, jobs, ingest, replace, parse, service  # noqa: E402

app.include_router(upload.router)
app.include_router(jobs.router)
app.include_router(ingest.router)
app.include_router(replace.router)
app.include_router(parse.router)
app.include_router(service.router)


@app.get("/")
async def index():
    """上传页面重定向。"""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/jobs")


if __name__ == "__main__":
    import uvicorn
    import os
    port = int(os.getenv("MINERU_PORT", "8003"))
    host = os.getenv("MINERU_HOST", "127.0.0.1")
    uvicorn.run(app, host=host, port=port)
