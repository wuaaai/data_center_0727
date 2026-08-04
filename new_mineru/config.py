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

# ── 解析引擎选择 ──
# maas = 内网 Maas 接口（生产）/ local = 本地 do_parse
PARSE_ENGINE = os.getenv("NEW_MINERU_PARSE_ENGINE", "maas")

# ── 内网 Maas 接口配置 ──
MAAS_PARSE_URL = os.getenv(
    "NEW_MINERU_MAAS_URL",
    "https://910b.hbmaas.com/idp-model-1000000232-9093/file_parse",
)
MAAS_TIMEOUT = int(os.getenv("NEW_MINERU_MAAS_TIMEOUT", "900"))
RETURN_MD = True               # 返回 markdown
RETURN_CONTENT_LIST = True     # 返回结构化 content_list（分块用）
RETURN_IMAGES = True           # 返回图片（base64 data URL）
RETURN_MIDDLE_JSON = False
RETURN_MODEL_OUTPUT = False

# ── 图片处理 ──
IMAGE_DIR = PROJECT_ROOT / "static" / "images"
IMAGE_STATIC_URL = os.getenv(
    "NEW_MINERU_IMAGE_STATIC_URL",
    f"http://localhost:{SERVER_PORT}/static/images/",
)

# ── 输出目录 ──
OUTPUT_DIR = PROJECT_ROOT / "output"
UPLOAD_DIR = PROJECT_ROOT / "uploads"
HISTORY_DIR = PROJECT_ROOT / "history"   # 解析历史记录

# ── 模型路径（仅用于状态展示） ──
MODEL_ROOT = PROJECT_ROOT.parent / "modelscope" / "models" / "OpenDataLab" / "PDF-Extract-Kit-1___0"

# 接口元信息（对齐内网 Maas 返回格式）
BACKEND_NAME = "hybrid-auto-engine"
VERSION = "2.7.1"

# ── 分块策略配置（content_list 父子分块，从 mineru_0720/config.py 迁移） ──
CHUNKING_STRATEGY = "default"
PARENT_SPLIT_MARKER = "***"        # 父块分隔符（部分/章节之间）
SPLIT_MARKER = "<-split->"         # 子块分隔符（段落之间）
# 图片保留模式: all=保留所有图片(不依赖 LLM) / llm=需 DeepSeek
INCLUDE_IMAGES = "all"
TITLE_PARENT_HEIGHT_RATIO = 1.5
TITLE_PARENT_MIN_HEIGHT = 25
MERGE_ALL_PARAGRAPHS = True
TEXT_MERGE_MIN_LENGTH = 15
SENTENCE_END_CHARS = frozenset("。！？…!?.\"'》）")
MAX_SUB_BLOCK_TOKENS = 512
# new_mineru 不接 DeepSeek，禁用 LLM 切分（text_utils 兜底走规则切分）
USE_LLM_SPLITTING = False
LLM_SPLIT_MAX_CHARS = int(MAX_SUB_BLOCK_TOKENS * 0.85)  # ≈ 435
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"
UNSTRUCTURED_MAX_CHARACTERS = 1000
UNSTRUCTURED_NEW_AFTER_N_CHARS = 800
UNSTRUCTURED_OVERLAP = 0
UNSTRUCTURED_COMBINE_TEXT_UNDER_N_CHARS = 500
UNSTRUCTURED_MULTIPAGE_SECTIONS = True
SPATIAL_MERGE_HORIZONTAL_GAP = 100
SPATIAL_MERGE_VERTICAL_GAP = 40
SPATIAL_MERGE_MIN_IMAGE_AREA = 10000
