"""
知识库管理配置 — 路径、数据库连接、限制参数。
所有依赖已整合到 data_processing_center 项目内，不再依赖外部 mineru_0720。
"""
import os
import sys
from pathlib import Path

# ── 项目根目录 ──
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ── mineru 核心代码路径（本项目内的 mineru_core） ──
MINERU_BASE = PROJECT_ROOT / "mineru_core"
sys.path.insert(0, str(MINERU_BASE))

# ── mineru_app 服务代码路径 ──
MINERU_APP = PROJECT_ROOT / "mineru_app"

# ── 上传 & 输出目录（项目内） ──
UPLOAD_DIR = PROJECT_ROOT / "data" / "web_uploads"
OUTPUT_DIR = PROJECT_ROOT / "data" / "output"

# ── PostgreSQL / pgvector 连接 ──
DB_CONNECTION = os.getenv(
    "PGVECTOR_CONNECTION",
    "postgresql+psycopg2://postgres:123456@10.32.10.161:5432/text2sql_vector",
)
DB_TABLE = os.getenv("PGVECTOR_COLLECTION_NAME", "parent_child_db_1024")
DB_METADATA_COL = "c_metadata"

# ── 限制 ──
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc"}
MAX_FILE_SIZE_MB = 200
# 基础超时（秒），大文件会根据大小自动延长，可通过环境变量覆盖
JOB_TIMEOUT_SECONDS = int(os.getenv("JOB_TIMEOUT_SECONDS", "600"))
PREVIEW_MAX_LINES = 200

# ── RAG 入库脚本路径（本项目内） ──
RAG_INGEST_SCRIPT = MINERU_APP / "rag_ingest.py"

# ── MinerU Python 路径 ──
# 优先使用环境变量 MINERU_PYTHON，否则使用当前运行中的 Python（本项目 .venv）
# 用户需要确保当前 .venv 安装了 langchain-postgres、python-docx 等依赖
MINERU_VENV_PYTHON = os.getenv("MINERU_PYTHON", sys.executable)

# MinerU site-packages 路径（运行时导入 python-docx 备用）
# 如果当前 venv 缺少 python-docx，从 mineru 的 site-packages 借用
# 可通过环境变量 MINERU_SITE_PACKAGES 覆盖
if sys.platform == "win32":
    _default_site = str(PROJECT_ROOT / ".venv" / "Lib" / "site-packages")
else:
    _default_site = str(PROJECT_ROOT / ".venv" / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages")
MINERU_SITE_PACKAGES = os.getenv("MINERU_SITE_PACKAGES", _default_site)
