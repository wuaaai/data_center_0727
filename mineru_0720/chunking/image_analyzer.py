"""
图片分析与过滤模块：从 minerU 解析结果中识别、分类、过滤图片块。

职责：
  - 图片数据提取（路径、标题、VLM 描述）
  - 图片内容分类（是否含中文、是否为实质内容）
  - 空间距离计算（文本与图片的相邻关系）
  - DeepSeek LLM 判断（区分实质内容 vs 照片标签）
  - 图片过滤策略（none / auto / content / llm / all）
  - 孤立图注回溯合并、caption 文字保留
"""

import json
import re
from typing import Optional

import sys
from pathlib import Path as _Path
sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

from config import (
    INCLUDE_IMAGES,
    SPATIAL_MERGE_HORIZONTAL_GAP,
    SPATIAL_MERGE_VERTICAL_GAP,
    SPATIAL_MERGE_MIN_IMAGE_AREA,
)

# ---------- 类型常量 ----------

IMAGE_TYPES = {"image", "image_body", "image_caption"}

FIGURE_TYPES = {
    "image", "image_body", "image_caption",
    "table", "table_body", "table_caption",
    "chart", "chart_body", "chart_caption",
    "simple_table", "complex_table",
}

TABLE_TYPES = {"table", "simple_table", "complex_table", "table_body", "table_caption"}

# ---------- 中文检测 ----------

_CHINESE_RE = re.compile(r"[一-鿿㐀-䶿豈-﫿]")


def contains_chinese(text: str) -> bool:
    """判断文本是否包含中文字符。"""
    return bool(_CHINESE_RE.search(text))


# ---------- 图片数据提取 ----------

def extract_image_path(block: dict) -> str:
    """从 v1/v2 格式的 block 中提取图片文件路径。"""
    # v2 格式: img_path 在顶层
    path = block.get("img_path", "")
    if isinstance(path, str) and path.strip():
        return path
    # v1 格式: image_source 在 content 内
    content = block.get("content", {})
    if isinstance(content, dict):
        source = content.get("image_source", {})
        if isinstance(source, dict):
            return source.get("path", "")
        if isinstance(source, str):
            return source
    return ""


def extract_caption_text(block: dict) -> str:
    """提取图片/表格标题文本，兼容 v1(content 内) 和 v2(顶层) 两种格式。"""
    for source in (block, block.get("content", {})):
        if not isinstance(source, dict):
            continue
        for key in ("image_caption", "chart_caption", "table_caption", "caption",
                     "image_footnote", "chart_footnote", "table_footnote"):
            captions = source.get(key, [])
            if isinstance(captions, list):
                parts = []
                for c in captions:
                    if isinstance(c, dict):
                        parts.append(c.get("content", "") or c.get("text", ""))
                    elif isinstance(c, str):
                        parts.append(c)
                text = "".join(parts).strip()
                if text:
                    return text
            elif isinstance(captions, str):
                text = captions.strip()
                if text:
                    return text
    return ""


def extract_content_desc(block: dict) -> str:
    """提取 minerU VLM 生成的图片内容描述（content.content）。"""
    content = block.get("content", {})
    if isinstance(content, dict):
        return (content.get("content", "") or "").strip()
    return ""


def image_has_chinese(block: dict) -> bool:
    """检查图片的 content.content 或 image_caption 是否包含中文。"""
    desc = extract_content_desc(block)
    if contains_chinese(desc):
        return True
    caption = extract_caption_text(block)
    if contains_chinese(caption):
        return True
    return False


# ---------- 图片条目构造 ----------

def make_image_entry(block: dict) -> dict:
    """构造标准图片条目字典。"""
    return {
        "type": "image",
        "path": extract_image_path(block),
        "caption": extract_caption_text(block),
    }


def format_figure_text(block: dict) -> str:
    """格式化图表占位文字，如 [图] / [表] / [图表]。"""
    block_type = block.get("type", "").strip().lower()
    caption_text = extract_caption_text(block)
    labels = {
        "image": "[图]", "image_body": "[图]", "image_caption": "[图]",
        "table": "[表]", "table_body": "[表]", "table_caption": "[表]",
        "chart": "[图表]", "chart_body": "[图表]", "chart_caption": "[图表]",
        "simple_table": "[表]", "complex_table": "[表]",
    }
    label = labels.get(block_type, f"[{block_type}]")
    if caption_text:
        return f"{label} {caption_text}"
    return label


# ---------- 孤立图注处理 ----------

def merge_caption_to_prev_image(caption: str, child_parts: list) -> None:
    """将孤立图注合并到最近的上一个图片条目中（就地修改 child_parts）。"""
    if not caption or not child_parts:
        return
    for j in range(len(child_parts) - 1, -1, -1):
        prev = child_parts[j]
        if isinstance(prev, dict) and prev.get("type") == "image":
            if prev.get("caption"):
                prev["caption"] = prev["caption"] + " | " + caption
            else:
                prev["caption"] = caption
            return
    # 没有前置图片条目 → 作为纯文本保留
    child_parts.append(caption)


def keep_caption_as_text(block: dict, child_parts: list) -> None:
    """丢弃图片但保留有意义的 caption 文字（就地修改 child_parts）。"""
    caption = extract_caption_text(block)
    if caption:
        child_parts.append(caption)


# ---------- 空间距离计算 ----------

def text_to_image_distance(
    img_bbox: list[int],
    txt_bbox: list[int],
) -> float | None:
    """计算文本块到图片块的最近距离，None 表示不相关。

    支持三种位置关系（均要求 x/y 轴各至少一侧有重叠或接近）：
    1. 水平相邻 — 文本在图片左右两侧，y 轴有重叠
    2. 垂直相邻 — 文本在图片上方/下方，x 轴有重叠
    3. 角相邻   — 文本在图片四角方向，x/y 轴均无重叠但距离很近
    """
    ix1, iy1, ix2, iy2 = img_bbox
    tx1, ty1, tx2, ty2 = txt_bbox

    # x 轴重叠量
    x_overlap = max(0.0, min(ix2, tx2) - max(ix1, tx1))
    # y 轴重叠量
    y_overlap = max(0.0, min(iy2, ty2) - max(iy1, ty1))

    img_w = ix2 - ix1
    img_h = iy2 - iy1
    txt_w = tx2 - tx1
    txt_h = ty2 - ty1

    if img_w <= 0 or img_h <= 0 or txt_w <= 0 or txt_h <= 0:
        return None

    # 全宽通栏文字（宽度 > 图片宽度×2 且接近页面宽度）不作为图例
    if txt_w > img_w * 2.0:
        return None

    # 文本过小（可能是噪音碎片）
    if txt_w < 8 or txt_h < 8:
        return None

    # 场景1: 水平相邻 — 文本在图片左右，y 轴有重叠
    if y_overlap > 0:
        h_gap = 0.0 if x_overlap > 0 else min(
            abs(tx2 - ix1) if tx2 <= ix1 else float("inf"),
            abs(ix2 - tx1) if tx1 >= ix2 else float("inf"),
        )
        if h_gap <= SPATIAL_MERGE_HORIZONTAL_GAP:
            return h_gap

    # 场景2: 垂直相邻 — 文本在图片上方/下方，x 轴有重叠
    if x_overlap > max(img_w * 0.3, 30):  # x 轴至少重叠 30% 或 30px
        v_gap = 0.0 if y_overlap > 0 else min(
            abs(ty2 - iy1) if ty2 <= iy1 else float("inf"),
            abs(iy2 - ty1) if ty1 >= iy2 else float("inf"),
        )
        if v_gap <= SPATIAL_MERGE_VERTICAL_GAP:
            return v_gap

    # 场景3: 角相邻 — x/y 均无重叠但距离很近（如角落图例）
    dx = 0.0 if x_overlap > 0 else min(
        abs(tx2 - ix1), abs(ix2 - tx1),
    )
    dy = 0.0 if y_overlap > 0 else min(
        abs(ty2 - iy1), abs(iy2 - ty1),
    )
    if dx <= max(SPATIAL_MERGE_HORIZONTAL_GAP, 60) and dy <= max(SPATIAL_MERGE_VERTICAL_GAP, 30):
        return (dx ** 2 + dy ** 2) ** 0.5

    return None


def set_spatial_caption(block: dict, caption_text: str) -> None:
    """将合并后的标题写入图片/图表/表格块的 content 中。"""
    block_type = (block.get("type", "") or "").strip().lower()
    if "chart" in block_type:
        caption_key = "chart_caption"
    elif "table" in block_type:
        caption_key = "table_caption"
    else:
        caption_key = "image_caption"

    content = block.setdefault("content", {})
    if not isinstance(content, dict):
        content = {}
        block["content"] = content
    content[caption_key] = [{"type": "text", "content": caption_text}]


# ---------- DeepSeek LLM 判断 ----------

def _call_deepseek_judge(candidates: list[dict]) -> dict[int, dict]:
    """调用 DeepSeek 纯文本 API 判断图片是否有用。

    Parameters
    ----------
    candidates : list[dict]
        [{"index": int, "desc": str, "caption": str}, ...]

    Returns
    -------
    dict[int, dict]
        {index: {"decision": "keep"/"discard", "reason": str}}
    """
    from config import (
        DEEPSEEK_API_KEY, DEEPSEEK_API_URL, DEEPSEEK_MODEL,
    )

    if not DEEPSEEK_API_KEY:
        from loguru import logger
        logger.warning("DEEPSEEK_API_KEY 未设置，LLM 判断跳过，候选图片默认保留")
        return {}

    desc_list = ""
    for c in candidates:
        extra = f' [caption: {c["caption"]}]' if c.get("caption") else ""
        desc_list += f'[{c["index"]}] "{c["desc"]}"{extra}\n'

    prompt = (
        '你是文档图片分类器。判断以下图片描述是"实质性文字内容"还是"照片上的标签文字"。\n\n'
        "保留 (keep) — 具备以下特征:\n"
        "  - 包含具体数字、百分比、金额、年份、数量等数据\n"
        "  - 完整的政策条文、法规原文、长段论述（通常 > 50 字）\n"
        "  - 明确的表格/清单内容，包含数据和对应关系\n"
        "  - 数据图表/流程图的文字说明\n"
        "丢弃 (discard) — 照片上的标签文字，没有实质信息:\n"
        "  - 活动/展会/会议/论坛/博览会的名称和开幕信息\n"
        "  - 建筑/机构/项目/产品的名称和地点（如\"XX市XX服务中心\"）\n"
        "  - 只有几个名词/短语/标题排列，没有具体数据\n"
        "  - 新闻发布会/发布会标题\n"
        "  - 任何看起来是从照片上 OCR 下来的简短标签，而非完整的文字内容\n\n"
        "重要: 宁可多丢，不要保留没有实质数据的描述。\n"
        "只返回 JSON 数组，不要其他内容:\n"
        '[{"index": 0, "decision": "keep", "reason": "含完整政策条文和分类"}, ...]\n\n'
        f"图片描述列表:\n{desc_list}"
    )

    try:
        import httpx
        resp = httpx.post(
            DEEPSEEK_API_URL,
            headers={
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": DEEPSEEK_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "max_tokens": 1024,
            },
            timeout=30,
        )
        resp.raise_for_status()
        body = resp.json()
        reply = body["choices"][0]["message"]["content"].strip()

        # 解析 JSON（支持 markdown 代码块包裹）
        if reply.startswith("```"):
            reply = reply.split("\n", 1)[-1]
            if reply.endswith("```"):
                reply = reply[:-3]
        decisions = json.loads(reply)
        return {d["index"]: d for d in decisions}

    except Exception as e:
        from loguru import logger
        logger.warning(f"DeepSeek 调用失败: {e}，候选图片默认保留")
        return {}


def precompute_llm_decisions(flat_blocks: list) -> dict[int, dict]:
    """收集 text_image 候选图片，调用 DeepSeek 批量判断。

    仅对 INCLUDE_IMAGES == "llm" 时调用。
    返回 {global_idx: {"decision": "keep"|"discard", "reason": str}}
    """
    if INCLUDE_IMAGES != "llm":
        return {}

    candidates = []
    for gidx, (page_num, block) in enumerate(flat_blocks):
        if (block.get("type", "") or "").strip().lower() not in IMAGE_TYPES:
            continue
        st = block.get("sub_type", "") or ""
        if st != "text_image":
            continue
        cand_desc = extract_content_desc(block)
        if not contains_chinese(cand_desc):
            continue
        if len(cand_desc) < 20:
            continue
        candidates.append({
            "index": gidx,
            "desc": cand_desc,
            "caption": extract_caption_text(block),
        })

    if candidates:
        return _call_deepseek_judge(candidates)
    return {}


# ---------- 图片过滤核心 ----------

def process_image_block(
    block: dict,
    global_idx: int = -1,
    mode: str = "all",
    llm_decisions: dict | None = None,
) -> tuple[str, list]:
    """处理单个图片块：根据过滤模式决定保留/丢弃/转文字。

    Parameters
    ----------
    block : dict
        minerU 图片块数据。
    global_idx : int
        图片在 flat_blocks 中的全局索引（LLM 模式需要）。
    mode : str
        过滤模式: "none" | "auto" | "content" | "llm" | "all"
    llm_decisions : dict, optional
        LLM 预计算的结果 {idx: {"decision": "keep"|"discard", "reason": str}}

    Returns
    -------
    tuple[str, list]
        (action, entries) 其中:
        - action: "keep"        — 保留图片（fall through 到通用图表嵌入逻辑）
                  "discard"     — 丢弃图片
                  "text_only"   — 保留文字描述，不嵌入图片
                  "caption_only"— 仅保留标题文字
        - entries: 要添加到 child_parts 的文本/条目列表（text_only/caption_only 时使用）
    """
    if llm_decisions is None:
        llm_decisions = {}

    if mode == "none":
        return ("discard", [])

    if mode == "auto":
        caption = extract_caption_text(block)
        if caption:
            return ("keep", [])
        return ("discard", [])

    if mode in ("content", "llm"):
        img_desc = extract_content_desc(block)

        # desc 和 caption 都无中文 → 丢弃
        if not image_has_chinese(block):
            return ("discard", [])

        # desc 无中文但 caption 有中文 → 保留文字，丢弃图片
        if not contains_chinese(img_desc):
            caption = extract_caption_text(block)
            return ("caption_only", [caption] if caption else [])

        # flowchart 始终保留
        if block.get("sub_type") == "flowchart":
            return ("keep", [])

        # text_image: 照片上的文字标签
        if block.get("sub_type") == "text_image":
            if len(img_desc) < 20:
                # desc 太短 → 照片标签，全部丢弃
                return ("discard", [])

            # llm 模式: desc >= 20 → 查 LLM 判断
            if mode == "llm":
                decision = llm_decisions.get(global_idx)
                if decision and decision.get("decision") == "keep":
                    # LLM 判为有用内容 → 保留 desc 文字，不嵌图
                    return ("text_only", [img_desc])
                if decision and decision.get("decision") == "discard":
                    # LLM 判为无用照片 → 全部丢弃
                    return ("discard", [])
                # 无 LLM 决策（API 失败/default）→ 保留文字
                return ("text_only", [img_desc])

            # content 模式: text_image + desc >= 20 → 保留文字，不嵌图
            return ("text_only", [img_desc])

        # 含中文、非 flowchart、非 text_image → 保留图片
        return ("keep", [])

    # mode == "all" → 全保留，fall through 到通用图表嵌入
    return ("keep", [])
