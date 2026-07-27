"""
Web 应用配置。
"""

import sys
from pathlib import Path

# 项目根目录 (mineru/)
MINERU_BASE = Path(__file__).resolve().parent.parent

# 文件上传目录
UPLOAD_DIR = MINERU_BASE / "data" / "web_uploads"
# MinerU 输出目录
OUTPUT_DIR = MINERU_BASE / "output"

# RAG 入库脚本（已迁移至 mineru 项目内）
LANGCHAIN_VENV_PYTHON = Path(sys.executable)
LANGCHAIN_INGEST_SCRIPT = MINERU_BASE / "web_app" / "rag_ingest.py"
# # 旧：Langchain_160 路径（已废弃）
# LANGCHAIN_BASE = Path(r"D:\Shixi\Text2SQL_new\Langchain_160")
# LANGCHAIN_INGEST_SCRIPT = LANGCHAIN_BASE / "src" / "agent" / "db" / "ingest_data_pgvector_160.py"
# LANGCHAIN_DATA_DIR = LANGCHAIN_BASE / "data"

# 支持的文件格式
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc"}

# 限制
MAX_FILE_SIZE_MB = 200
JOB_TIMEOUT_SECONDS = 600  # 10 分钟

# 预览最大行数
PREVIEW_MAX_LINES = 200
