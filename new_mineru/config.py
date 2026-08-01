"""
new_mineru 独立解析服务配置 — PDF → MinerU 解析 → markdown（可选分块）。

模型复用 E:/Develop_docu/sql_0722_center/modelscope（OpenDataLab/PDF-Extract-Kit-1___0）。
接口模式模仿内网 Maas: POST /file_parse 同步返回 markdown。
"""
import os
import sys
from pathlib import Path

# ── 项目根目录 ──
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

# ── 模型配置环境变量（必须在 import mineru 前设置） ──
MINERU_CONFIG_JSON = PROJECT_ROOT / "mineru.json"
os.environ["MINERU_TOOLS_CONFIG_JSON"] = str(MINERU_CONFIG_JSON)
os.environ["MINERU_MODEL_SOURCE"] = "local"

# ── MinerU 解析参数（对应 mineru_0720/config.py 已验证值） ──
BACKEND = os.getenv("NEW_MINERU_BACKEND", "pipeline")      # pipeline 纯本地
PARSE_METHOD = os.getenv("NEW_MINERU_PARSE_METHOD", "auto")  # auto/txt/ocr
LANG = os.getenv("NEW_MINERU_LANG", "ch")
FORMULA_ENABLE = True
TABLE_ENABLE = True
START_PAGE_ID = 0
END_PAGE_ID = None
DUMP_MIDDLE_JSON = True
DUMP_CONTENT_LIST = True

# ── markdown 分块参数 ──
# 目标切片长度上限（字符数）。分块时预留标题前缀空间，
# 600 字符正文 + 前缀 ≈ 630 字符，中文约 400-500 token，保证 rerank 512 token 内。
MAX_CHUNK_CHARS = int(os.getenv("NEW_MINERU_MAX_CHUNK_CHARS", "600"))

# ── 服务限制 ──
MAX_FILE_SIZE_MB = int(os.getenv("NEW_MINERU_MAX_FILE_MB", "200"))
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc"}
SERVER_HOST = os.getenv("NEW_MINERU_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("NEW_MINERU_PORT", "8004"))

# ── 输出目录 ──
OUTPUT_DIR = PROJECT_ROOT / "output"
UPLOAD_DIR = PROJECT_ROOT / "uploads"
HISTORY_DIR = PROJECT_ROOT / "history"   # 解析历史记录

# ── 模型路径（仅用于状态展示） ──
MODEL_ROOT = PROJECT_ROOT.parent / "modelscope" / "models" / "OpenDataLab" / "PDF-Extract-Kit-1___0"

# 接口元信息（对齐内网 Maas 返回格式）
BACKEND_NAME = "hybrid-auto-engine"
VERSION = "2.7.1"
