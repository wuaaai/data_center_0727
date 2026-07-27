"""
知识库管理配置 — 路径、数据库连接、限制参数。
所有依赖已整合到 data_processing_center 项目内。
"""
import os
import sys
from pathlib import Path

# ── 项目根目录 ──
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ── mineru 核心代码路径（从 mineru_0720 复制） ──
MINERU_BASE = PROJECT_ROOT / "mineru_core"
sys.path.insert(0, str(MINERU_BASE))

# ── 上传 & 输出目录（项目内） ──
UPLOAD_DIR = PROJECT_ROOT / "data" / "web_uploads"
OUTPUT_DIR = PROJECT_ROOT / "data" / "output"

# ── PostgreSQL / pgvector 连接 ──
DB_CONNECTION = "postgresql+psycopg2://postgres:123456@10.32.10.161:5432/text2sql_vector"
DB_TABLE = "parent_child_db_1024"
DB_METADATA_COL = "c_metadata"

# ── 限制 ──
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc"}
MAX_FILE_SIZE_MB = 200
# 基础超时（秒），大文件会根据大小自动延长，可通过环境变量覆盖
JOB_TIMEOUT_SECONDS = int(os.getenv("JOB_TIMEOUT_SECONDS", "600"))
PREVIEW_MAX_LINES = 200

# ── RAG 入库脚本路径（本项目内） ──
RAG_INGEST_SCRIPT = MINERU_BASE / "web_app" / "rag_ingest.py"

# ── MinerU venv Python 路径（统一引用，避免不一致） ──
# mineru_0720 在 sql_0722_center 目录下（PROJECT_ROOT 的父级），不在 data_processing_center 内
_MINERU_VENV = PROJECT_ROOT.parent / "mineru_0720" / ".venv"
# Windows 下 python.exe 在 Scripts 目录
_python_exe = "python.exe" if sys.platform == "win32" else "python"
MINERU_VENV_PYTHON = str(_MINERU_VENV / "Scripts" / _python_exe) if sys.platform == "win32" else str(_MINERU_VENV / "bin" / _python_exe)
# MinerU site-packages 路径（运行时导入 python-docx 备用，避免硬编码绝对路径）
MINERU_SITE_PACKAGES = str(_MINERU_VENV / "Lib" / "site-packages") if sys.platform == "win32" else str(_MINERU_VENV / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages")
