"""
项目配置：PDF → DOCX 转换参数。
"""

import os
from pathlib import Path

# === 路径配置 ===
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
PDF_DIR = DATA_DIR / "pdf"
WORD_DIR = DATA_DIR / "word"
OUTPUT_DIR = BASE_DIR / "output"
MODELS_DIR = BASE_DIR / "models"

# === minerU 本地模型配置 ===
# 模型已经下载到 models/ 目录，通过环境变量告知 minerU 使用本地模型
_MINERU_CONFIG_PATH = BASE_DIR / "mineru.json"
os.environ["MINERU_TOOLS_CONFIG_JSON"] = str(_MINERU_CONFIG_PATH)
os.environ["MINERU_MODEL_SOURCE"] = "local"

# === minerU 解析配置 ===
# 后端选择:
#   "pipeline"          - 纯本地 pipeline（需 pipeline 模型）
#   "vlm-auto-engine"    - 纯 VLM 引擎，精度最高（需 VLM 模型，仅此已安装）
#   "hybrid-auto-engine" - 混合引擎精度最高（需 pipeline + VLM 模型）
#   "vlm-http-client"    - 远程 VLM 客户端（无需本地模型）
#   "hybrid-http-client" - 远程混合客户端
BACKEND = "pipeline"


# # 远程 VLM API 服务器地址（pipeline 模式下不需要）
# VLM_SERVER_URL = "http://10.32.10.160:30000"

# 解析方法: "auto" 自动选择 / "txt" 文本提取 / "ocr" OCR 识别
PARSE_METHOD = "auto"

# 文档语言
LANG = "ch"

# 是否启用公式解析
FORMULA_ENABLE = True

# 是否启用表格解析
TABLE_ENABLE = True

# 图片保留模式（仅对 minerU 标记为 "image" 的块生效，chart/table 不受影响）：
#   "all"     — 所有 image 都保留（含无意义的风景照、装饰图）
#   "auto"    — 只有带 caption（图注/脚注）的 image 保留
#   "none"    — 所有 image 全部过滤
#   "content" — 规则过滤：desc 或 caption 含中文保留，text_image 短标签丢弃
#   "llm"     — 规则 + DeepSeek：规则预筛后用 DeepSeek 判断模糊候选
INCLUDE_IMAGES = "llm"

# === DeepSeek API 配置（仅 llm 模式使用）===
# API Key: 写入环境变量 DEEPSEEK_API_KEY，不要直接写在代码里
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"
# 每文档最多发给 LLM 的图片数（控制成本）
LLM_MAX_IMAGES_PER_DOC = 20

# 是否生成中间 JSON（调试用）
DUMP_MIDDLE_JSON = True

# 是否生成 content_list（块级结构化内容，分块必需）
DUMP_CONTENT_LIST = True

# 起始/结束页（0-based，None 表示到最后一页）
START_PAGE_ID = 0
END_PAGE_ID = None

# === 标题分块配置 ===
# 父级标题高度比例阈值：中位标题高度 × 此比例 = 父级阈值
# 低于此阈值的标题变为子块内容，不再独立创建父块
TITLE_PARENT_HEIGHT_RATIO = 1.5

# 父级标题最小高度（px），确保小字标题不会全部成为子块
TITLE_PARENT_MIN_HEIGHT = 25

# === 文本合并配置 ===

# 合并所有连续正文段落（同一父块内）
# True  → 连续正文始终合并为一个子块，大幅减少 <-split->
# False → 仅当段落未以句号结尾时才合并（旧行为）
MERGE_ALL_PARAGRAPHS = True

# 文本合并最小长度：前一段落至少这么多字符才触发合并判断
TEXT_MERGE_MIN_LENGTH = 15

# 句子结束标点集合：用于判断段落是否完整
# 不以这些标点结尾的段落可能被 minerU 版面分析截断，需要与下一段合并
SENTENCE_END_CHARS = frozenset("。！？…!?.\"'》）")

# === 文本分块配置 ===
# 用于识别父级块的类型
PARENT_BLOCK_TYPES = {
    "title",           # 文档标题
    "doc_title",       # 文档标题(v2)
    "paragraph_title", # 段落标题
    "abstract",        # 摘要
}

# 子级块类型（详细内容）
CHILD_BLOCK_TYPES = {
    "paragraph",       # 正文段落
    "text",            # 纯文本
    "list",            # 列表
    "index",           # 索引
    "text_list",       # 文本列表
}

# === Token 限制配置 ===
# 单个子块最大 token 数（仅约束子块 <-split->，父块 *** 不受限制）
MAX_SUB_BLOCK_TOKENS = 512

# 是否启用 LLM 语义拆分（False = 纯规则拆分，零 API 调用）
USE_LLM_SPLITTING = True

# LLM 拆分时告知模型的字数上限（保守估算，给 token 差异留余量）
LLM_SPLIT_MAX_CHARS = int(MAX_SUB_BLOCK_TOKENS * 0.85)  # ≈ 435

# 需要跳过的块类型（页眉页脚页码等）
SKIP_BLOCK_TYPES = {
    "page_header",
    "page_footer",
    "page_number",
    "page_footnote",
    "page_aside_text",
    "header",
    "footer",
    "footnote",
    "image_footnote",
    "table_footnote",
    "chart_footnote",
    "code_footnote",
}

# 表格/图表块类型
FIGURE_BLOCK_TYPES = {
    "image", "table", "chart",
    "image_body", "table_body", "chart_body",
    "image_caption", "table_caption", "chart_caption",
    "simple_table", "complex_table",
}

# 公式块类型
EQUATION_BLOCK_TYPES = {
    "equation", "equation_interline", "interline_equation",
}

# === 路由决策配置 ===
# 路由策略:
#   "auto"   — 自动检测文件内容复杂度，选择最优路径
#   "mineru" — 强制使用 minerU 路径
#   "fast"   — 强制使用快路径（PyMuPDF / python-docx 直接提取）
ROUTE_STRATEGY = "auto"

# === 分块策略配置 ===
# 分块策略（可插拔）:
#   "default"      — 当前默认分块（*** + <-split-> + token 拆分 + 列表合并）
#   "none"         — 无分块，直接输出干净段落
#   "unstructured" — Unstructured 结构感知分块（chunk_by_title，按标题层级切分）
#   可通过 CLI --chunking-strategy 覆盖
CHUNKING_STRATEGY = "default"

# === Unstructured 结构感知分块配置 ===
# 每个 chunk 的最大字符数（硬限制），超过会被强制切分
UNSTRUCTURED_MAX_CHARACTERS = 1000

# 软限制：超过此字符数后，优先在当前段落边界处切分
UNSTRUCTURED_NEW_AFTER_N_CHARS = 800

# chunk 之间的重叠字符数
UNSTRUCTURED_OVERLAP = 0

# 小于此字符数的连续文本段会被合并到更大的段落中
UNSTRUCTURED_COMBINE_TEXT_UNDER_N_CHARS = 500

# 是否允许一个 section 跨多页
UNSTRUCTURED_MULTIPAGE_SECTIONS = True

# 快路径 PDF 标题推断：字号（像素）大于此值的文本行视为标题
FAST_PDF_TITLE_FONT_THRESHOLD = 14

# 检测时扫描的采样页数（用于判断 PDF 是否含图片/表格）
DETECT_SAMPLE_PAGES = 5

# PDF 文本量阈值（字符数），平均每页低于此值视为扫描件，走 minerU
DETECT_MIN_TEXT_PER_PAGE = 100

# 支持的文件扩展名
SUPPORTED_INPUT_EXTENSIONS = {".pdf", ".docx", ".doc"}

# === DOCX 输出配置 ===
# 页面宽度（厘米）
PAGE_WIDTH_CM = 21.0
PAGE_HEIGHT_CM = 29.7

# 页边距
MARGIN_TOP_CM = 2.54
MARGIN_BOTTOM_CM = 2.54
MARGIN_LEFT_CM = 3.18
MARGIN_RIGHT_CM = 3.18

# 正文字体
FONT_NAME = "仿宋"
FONT_SIZE_PT = 16  # 三号

# 标题字体
TITLE_FONT_NAME = "黑体"
TITLE_FONT_SIZE_PT = 17  # 二号

# 一级标题
H1_FONT_NAME = "黑体"
H1_FONT_SIZE_PT = 16  # 三号

# 二级标题
H2_FONT_NAME = "楷体"
H2_FONT_SIZE_PT = 16  # 三号

# 行间距（倍数）
LINE_SPACING = 1.5

# 分块标记
PARENT_SPLIT_MARKER = "***"        # 父块分隔符（部分/章节之间）
SPLIT_MARKER = "<-split->"         # 子块分隔符（段落之间）

# === 空间文本合并配置 ===
# 将图表/图片附近的文本块（如图例说明）合并为图片标题

# 文本块与图片之间的最大水平间距（像素），在此范围内的文本视为图例
SPATIAL_MERGE_HORIZONTAL_GAP = 100

# 文本块与图片之间的最大垂直间距（像素），在此范围内的文本视为关联文字
SPATIAL_MERGE_VERTICAL_GAP = 40

# 图片最小面积（px²），低于此值的视为装饰图标，不做空间文本合并
SPATIAL_MERGE_MIN_IMAGE_AREA = 10000
