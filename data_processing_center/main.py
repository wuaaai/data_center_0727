"""数据处理中心后端启动入口。"""

from fastapi import FastAPI
import uvicorn
from fastapi.middleware.cors import CORSMiddleware

from data_manage import router as data_manage_router
from metadata_manage import router as metadata_manage_router
from ragdata_manager.routes import router as ragdata_router, _doc_executor

app = FastAPI(
    title="Data Processing Center API",
    version="0.1.0",
    description="数据处理中心最简 FastAPI 启动入口。",
)

origins = ["http://localhost:8000"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(data_manage_router)
app.include_router(metadata_manage_router)
app.include_router(ragdata_router, prefix="/ragdata")


@app.on_event("shutdown")
def _shutdown_executor():
    """应用关闭时清理后台线程池。"""
    _doc_executor.shutdown(wait=True)


@app.get("/")
def health_check() -> dict[str, str]:
    """健康检查接口。"""

    return {"message": "Data Processing Center API is running."}


if __name__ == "__main__":
    uvicorn.run(app, host="localhost", port=8001)
