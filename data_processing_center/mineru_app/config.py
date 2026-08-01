"""
mineru_app Web 应用配置 — 基于 data_processing_center 项目根目录。
"""
import sys
from pathlib import Path

# data_processing_center 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 文件上传目录
UPLOAD_DIR = PROJECT_ROOT / "data" / "web_uploads"
# MinerU 输出目录
OUTPUT_DIR = PROJECT_ROOT / "output"

# RAG 入库脚本（使用当前 Python 环境，不需要外部 venv）
LANGCHAIN_VENV_PYTHON = Path(sys.executable)
LANGCHAIN_INGEST_SCRIPT = Path(__file__).resolve().parent / "rag_ingest.py"

# 支持的文件格式
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc"}

# 限制
MAX_FILE_SIZE_MB = 200
JOB_TIMEOUT_SECONDS = 600  # 10 分钟

# 预览最大行数
PREVIEW_MAX_LINES = 200

# MinerU 核心代码路径（旧组件兼容）
MINERU_BASE = PROJECT_ROOT / "mineru_core"
