"""
文本处理工具模块：清洗、token 估算、文本拆分。

从 text_chunker.py 提取的纯工具函数，无内部业务依赖。
"""

import json
import math
import re
from html.parser import HTMLParser

from config import (
    SENTENCE_END_CHARS,
    MAX_SUB_BLOCK_TOKENS,
    USE_LLM_SPLITTING,
    LLM_SPLIT_MAX_CHARS,
)

# ======================================================================
# 文本清洗
# ======================================================================

_INVALID_XML_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")

# PDF 字体 CMap 错误导致的无意义 Unicode（常见于政府 PDF 的编号/符号）
# 这些区块的字符不可能出现在中文文档中，一律移除
_GARBAGE_UNICODE_RE = re.compile(
    "[ɐ-˿"     # IPA Extensions + Spacing Modifier Letters
    "̀-ͯ"      # Combining Diacritical Marks
    "Ͱ-ӿ"      # Greek + Cyrillic
    "֐-ۿ"      # Hebrew + Arabic
    "ऀ-๿"      # Devanagari / Bengali / Gurmukhi / Gujarati / Oriya / Tamil / Telugu / Kannada / Malayalam / Sinhala / Thai / Lao
    "ༀ-྿"      # Tibetan + Myanmar
    "ᄀ-ᇿ"      # Hangul Jamo
    "ሀ-᳿"      # Ethiopic + Cherokee + Canadian Aboriginal + Ogham + Runic + Khmer + Mongolian + various SE Asian scripts
    "ᴀ-᷿"      # Phonetic Extensions
    "Ḁ-ỿ"      # Latin Extended Additional
    "℀-⅏"      # Letterlike Symbols
    "]"
)

_CJK = (
    r"[　-〿぀-ゟ゠-ヿ㄀-ㄯㇰ-ㇿ㈀-㏿"
    r"㐀-䶿一-鿿豈-﫿"
    r"＀-￯\U00020000-\U0002a6df\U0002f800-\U0002fa1f]"
)

_DIGIT_CJK_SPACE_RE = re.compile(r"([\d%])\s+(" + _CJK + r")")
_CJK_DIGIT_SPACE_RE = re.compile(r"(" + _CJK + r")\s+([\d])")
_LETTER_CJK_SPACE_RE = re.compile(r"([a-zA-Z])\s+(" + _CJK + r")")
_CJK_LETTER_SPACE_RE = re.compile(r"(" + _CJK + r")\s+([a-zA-Z])")
_COMMA_CN_RE = re.compile(r"\s*,\s*(" + _CJK + r")")
_CN_COMMA_RE = re.compile(r"(" + _CJK + r")\s*,\s*")
_CN_SPACE_PUNCT_RE = re.compile(r"\s+([，。、；：！？》）])")
_CN_PUNCT_CN_RE = re.compile(r"([，。、；：！？])\s+(" + _CJK + r")")
_MULTI_SPACE_RE = re.compile(r"[ \t]+")

# PDF 文本流顺序问题：% 符号有时跑到了数字前面
_PERCENT_SWAP_RE = re.compile(r"(?<!\d)%\s*([^%\d]{1,30}?)(\d+\.?\d*)")

# 匹配: % 前面非数字，后面隔着中文/符号出现的数字
_WORDART_PERCENT_RE = re.compile(
    r"([^\d])%"
    r"([一-鿿　-〿＀-￯]*)"
    r"(\d+\.?\d*)"
)


def clean_text(text: str) -> str:
    """清洗 minerU 提取的文本：去控制字符、无意义 Unicode、修复中英文/数字间多余空格。"""
    text = _INVALID_XML_RE.sub("", text)
    text = _GARBAGE_UNICODE_RE.sub("", text)
    text = _PERCENT_SWAP_RE.sub(r"\2%\1", text)
    text = _DIGIT_CJK_SPACE_RE.sub(r"\1\2", text)
    text = _CJK_DIGIT_SPACE_RE.sub(r"\1\2", text)
    text = _LETTER_CJK_SPACE_RE.sub(r"\1\2", text)
    text = _CJK_LETTER_SPACE_RE.sub(r"\1\2", text)
    text = _COMMA_CN_RE.sub(r"，\1", text)
    text = _CN_COMMA_RE.sub(r"\1，", text)
    text = _CN_SPACE_PUNCT_RE.sub(r"\1", text)
    text = _CN_PUNCT_CN_RE.sub(r"\1\2", text)
    text = _MULTI_SPACE_RE.sub(" ", text)
    return text.strip()


def fix_wordart_percent_ordering(text: str) -> str:
    """修复艺术字数字在百分号后被错误放置的问题。"""
    if "%" not in text:
        return text
    return _WORDART_PERCENT_RE.sub(r"\1\3%\2", text)


# ======================================================================
# 句子/段落判断
# ======================================================================

def _is_sentence_end(text: str) -> bool:
    """判断文本是否以句子结束标点结尾。"""
    if not text:
        return True
    stripped = text.rstrip()
    if not stripped:
        return True
    return stripped[-1] in SENTENCE_END_CHARS


_SUB_HEADING_RE = re.compile(
    r'^[（]\s*[一二三四五六七八九十百千\d]+[）]'   # （一）（1）等
    r'|^\d+\s*[.、]'                                 # 1. 1、
    r'|^[一二三四五六七八九十]+[、]'                    # 一、
    r'|^★[^★]'                                        # ★质量强省战略★（非★★）
    r'|^\d+[、]'                                      # 1、
)

_LIST_ITEM_RE = re.compile(
    r'^[（]\s*\d+[）]'                               # （1）（2）
    r'|^\d+\s*[.、．]'                                 # 1. 1、10.
    r'|^[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳]'          # 带圈数字
    r'|^[★—●·•○◆■□▪▸➢☑✓✔✗✘]'                       # 符号项目
    r'|^——'                                           # 中文破折号
    r'|^[一二三四五六七八九十]+[、．]'                    # 一、二、
    r'|^第[一二三四五六七八九十百千\d]+[条条款项]'         # 第X条
    r'|^(一是|二是|三是|四是|五是|六是|七是|八是|九是|十是)'  # 一是二是
    r'|^\d{1,2}(?=[一-鿿])'
)


def _is_sub_heading_merged(text: str) -> bool:
    """判断一行文本是否为子标题（须与下一正文行合并）。"""
    t = text.strip()
    if len(t) > 50:
        return False
    if _is_sentence_end(t):
        return False
    return bool(_SUB_HEADING_RE.match(t))


def _is_list_item(text: str) -> bool:
    """判断一行文本是否为列表项（编号、符号开头）。"""
    t = text.lstrip()
    if not t:
        return False
    return bool(_LIST_ITEM_RE.match(t))


# ======================================================================
# 块类型常量
# ======================================================================

_SKIP_TYPES = {
    "page_header", "page_footer", "page_number",
    "page_footnote", "page_aside_text",
    "header", "footer", "footnote",
}

_TITLE_TYPES = {"title", "doc_title", "paragraph_title", "abstract"}


# ======================================================================
# 表格 HTML → 文本
# ======================================================================

class _TableRowParser(HTMLParser):
    """解析 HTML <table>，按行提取单元格文本。"""

    def __init__(self):
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] = []
        self._cell: list[str] = []
        self._in_cell = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th"):
            self._in_cell = True
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th"):
            self._in_cell = False
            self._row.append("".join(self._cell).strip())
        elif tag == "tr":
            if self._row:
                self.rows.append(self._row)

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._cell.append(data)


def _extract_table_html(block: dict) -> str:
    """提取表格 HTML 字符串，兼容 v1（table_body）和 v2（content.html）。"""
    content = block.get("content", {})
    if isinstance(content, dict):
        html = content.get("html", "")
        if isinstance(html, str) and html.strip():
            return html
    html = block.get("table_body", "")
    if isinstance(html, str) and html.strip():
        return html
    return ""


def _parse_table_rows(block: dict) -> list[str]:
    """解析表格块，按行返回文本列表。"""
    html = _extract_table_html(block)
    if not html:
        return []
    parser = _TableRowParser()
    try:
        parser.feed(html)
    except Exception:
        return []
    return [" | ".join(row) for row in parser.rows if row]


# ======================================================================
# 文本提取
# ======================================================================

def _resolve_item_text(span: dict) -> str:
    """从嵌套的 span/item 结构中递归提取文本。"""
    text = span.get("content", "") or span.get("text", "")
    if isinstance(text, str) and text.strip():
        return text
    item_content = span.get("item_content", [])
    if isinstance(item_content, list):
        parts = []
        for ic in item_content:
            if isinstance(ic, dict):
                parts.append(_resolve_item_text(ic))
            elif isinstance(ic, str):
                parts.append(ic)
        return "".join(parts)
    return ""


def _extract_text(block: dict) -> str:
    """从 minerU block（兼容 v1/v2 格式）中提取纯文本。"""
    # v2 格式: text 在顶层
    text = block.get("text", "")
    if isinstance(text, str) and text.strip():
        return clean_text(text)

    # v1 格式: text 在 content 内
    content = block.get("content", "")
    if isinstance(content, str):
        return clean_text(content)
    if isinstance(content, dict):
        parts = []
        for key, value in content.items():
            if key in ("level", "image_source", "list_type", "attribute"):
                continue
            if isinstance(value, list):
                for span in value:
                    if isinstance(span, dict):
                        parts.append(_resolve_item_text(span))
                    elif isinstance(span, str):
                        parts.append(span)
            elif isinstance(value, str):
                parts.append(value)
        return clean_text("".join(parts))
    if isinstance(content, list):
        parts = []
        for span in content:
            if isinstance(span, dict):
                parts.append(_resolve_item_text(span))
            elif isinstance(span, str):
                parts.append(span)
        return clean_text("".join(parts))
    return ""


def _get_title_level(block: dict) -> int:
    """从 minerU block 中提取标题层级。"""
    raw_level = block.get("text_level")
    if raw_level is None:
        content = block.get("content", {})
        if isinstance(content, dict):
            raw_level = content.get("level", 2)
        else:
            raw_level = 2
    try:
        raw_level = int(raw_level)
    except (TypeError, ValueError):
        raw_level = 2
    if raw_level <= 1:
        return 0
    if raw_level == 2:
        return 1
    return 2


# ======================================================================
# Token 估算
# ======================================================================

def _estimate_tokens(text: str) -> int:
    """逐字符估算 token 数，无外部依赖。"""
    total = 0.0
    for ch in text:
        code = ord(ch)
        if (
            0x4E00 <= code <= 0x9FFF or
            0x3400 <= code <= 0x4DBF or
            0x20000 <= code <= 0x2A6DF or
            0x2A700 <= code <= 0x2B73F or
            0x2B740 <= code <= 0x2B81F or
            0x2B820 <= code <= 0x2CEAF or
            0x2CEB0 <= code <= 0x2EBEF or
            0x30000 <= code <= 0x3134F or
            0x2F800 <= code <= 0x2FA1F or
            0xF900 <= code <= 0xFAFF
        ):
            total += 1.0
        elif 0x3040 <= code <= 0x309F or 0x30A0 <= code <= 0x30FF:
            total += 1.0
        elif 0xAC00 <= code <= 0xD7AF or 0x1100 <= code <= 0x11FF:
            total += 1.0
        elif 0x3000 <= code <= 0x303F or 0xFF00 <= code <= 0xFFEF:
            total += 1.0
        elif ch.isspace():
            total += 0.0
        else:
            total += 0.25
    return math.ceil(total)


# ======================================================================
# 规则拆分
# ======================================================================

_RETRACT_RE = re.compile(
    r'。[ \t\n]*(?='
    r'第[零一二三四五六七八九十百千\d]+[章节条款项部分编类款目]|'
    r'[零一二三四五六七八九十百千]+[、．.]|'
    r'[（][零一二三四五六七八九十百千\d]+[）]|'
    r'\d+[、．.]|'
    r'[A-Za-z][、．.)]\s*|'
    r'第[零一二三四五六七八九十百千\d]+[部分篇章节]'
    r')'
)


def _retract_to_last_boundary(text: str) -> tuple[str, str]:
    """从 text 末尾向前找最近的语义边界，返回 (保留部分, 移出部分)。"""
    last_match = None
    for m in _RETRACT_RE.finditer(text):
        last_match = m
    if last_match:
        boundary = last_match.end()
        return text[:boundary].strip(), text[boundary:].lstrip()

    last_period = text.rfind('。')
    if last_period > 0:
        return text[:last_period + 1].strip(), text[last_period + 1:].lstrip()

    return text, ''


def _split_by_rules(text: str, max_tokens: int) -> list[str]:
    """规则兜底拆分：按标点优先级在 token 限制内断开。"""
    if not text:
        return [text]

    parts: list[str] = []
    remaining = text

    while remaining:
        if _estimate_tokens(remaining) <= max_tokens:
            parts.append(remaining.strip())
            break

        accumulated = 0.0
        best_break = -1
        best_break2 = -1
        best_break3 = -1
        hard_break = -1

        for i, ch in enumerate(remaining):
            code = ord(ch)

            if (
                0x4E00 <= code <= 0x9FFF or 0x3400 <= code <= 0x4DBF or
                0x20000 <= code <= 0x2A6DF or 0xF900 <= code <= 0xFAFF or
                0x2F800 <= code <= 0x2FA1F or 0x30000 <= code <= 0x3134F or
                0x2A700 <= code <= 0x2CEAF or 0x2CEB0 <= code <= 0x2EBEF or
                0x3040 <= code <= 0x309F or 0x30A0 <= code <= 0x30FF or
                0xAC00 <= code <= 0xD7AF or 0x1100 <= code <= 0x11FF or
                0x3000 <= code <= 0x303F or 0xFF00 <= code <= 0xFFEF
            ):
                accumulated += 1.0
            elif not ch.isspace():
                accumulated += 0.25

            if accumulated > max_tokens:
                hard_break = i
                break

            if ch in ('。', '！', '？', '；', '!', '?', ';') or (
                ch == '\n' and i + 1 < len(remaining) and remaining[i + 1] == '\n'
            ):
                best_break = i + 1

            if ch in ('，', '、', ',', '\n'):
                best_break2 = i + 1

            if ch == ' ':
                best_break3 = i + 1

        split_at = best_break or best_break2 or best_break3 or hard_break
        if split_at <= 0:
            split_at = max(1, hard_break)

        if accumulated <= max_tokens and not hard_break:
            parts.append(remaining.strip())
            break

        part = remaining[:split_at].strip()
        if part:
            parts.append(part)
        remaining = remaining[split_at:]

    return parts or [text.strip()]


# ======================================================================
# LLM 语义拆分
# ======================================================================

def _call_deepseek_split(text: str, max_chars: int) -> list[str]:
    """调用 DeepSeek API 做语义拆分。"""
    from config import DEEPSEEK_API_KEY, DEEPSEEK_API_URL, DEEPSEEK_MODEL

    if not DEEPSEEK_API_KEY:
        return []

    prompt = (
        "你是文本分块助手。将以下长文本在语义自然边界处拆分为多个段落。\n\n"
        "要求：\n"
        f"-每个段落不超过{max_chars}字符\n"
        "-在主题转换、段落边界、意群结束处断开\n"
        "-保持每个段落的语义完整性，不要在有关联的句子之间断开\n"
        "-当段落长度和语义之间优先根据语义划分，尽量不要在同一大标题下分割以接近最大长度，而是回退到大标题之前进行分割以保证分块下的语义连贯\n"
        "-不要在句子中间截断\n"
        "-只返回JSON数组，每个元素是一个段落字符串，不要其他内容\n\n"
        f"待拆分文本：\n{text}"
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
                "max_tokens": 2048,
            },
            timeout=30,
        )
        resp.raise_for_status()
        body = resp.json()
        reply = body["choices"][0]["message"]["content"].strip()

        if reply.startswith("```"):
            reply = reply.split("\n", 1)[-1]
            if reply.endswith("```"):
                reply = reply[:-3]

        parts = json.loads(reply)

        if not isinstance(parts, list) or len(parts) == 0:
            return []

        result = [str(p) for p in parts if p]
        if not result:
            return []

        return result

    except Exception:
        from loguru import logger
        logger.debug("DeepSeek 语义拆分失败，回退规则拆分")
        return []


# ======================================================================
# 边界修复 & 主入口
# ======================================================================

def _fix_split_boundaries(parts: list[str]) -> list[str]:
    """后处理：检查相邻 part 的拼接点是否切在了语义单元内部。"""
    if len(parts) <= 1:
        return parts

    fixed: list[str] = []
    i = 0
    while i < len(parts):
        if i + 1 < len(parts):
            next_starts_section = _RETRACT_RE.search(parts[i + 1])
            if next_starts_section and next_starts_section.start() == 0:
                fixed.append(parts[i])
                i += 1
                continue

            combined = parts[i] + parts[i + 1]
            if _estimate_tokens(combined) <= MAX_SUB_BLOCK_TOKENS:
                fixed.append(combined)
                i += 2
                continue

            kept, moved = _retract_to_last_boundary(parts[i])
            if kept and moved and _estimate_tokens(moved + parts[i + 1]) <= MAX_SUB_BLOCK_TOKENS:
                fixed.append(kept)
                parts[i + 1] = moved + parts[i + 1]
            else:
                fixed.append(parts[i])
            i += 1
        else:
            fixed.append(parts[i])
            i += 1

    return fixed


def _split_text_by_token_limit(text: str, max_tokens: int) -> list[str]:
    """主入口：协调 LLM 语义拆分和规则兜底。"""
    if not text:
        return [text]

    if _estimate_tokens(text) <= max_tokens:
        return [text]

    parts: list[str] = []
    if USE_LLM_SPLITTING:
        parts = _call_deepseek_split(text, LLM_SPLIT_MAX_CHARS)
        if parts and any(_estimate_tokens(p) > max_tokens for p in parts):
            parts = []

    if not parts:
        parts = _split_by_rules(text, max_tokens)

    if len(parts) > 1:
        parts = _fix_split_boundaries(parts)

    return parts
