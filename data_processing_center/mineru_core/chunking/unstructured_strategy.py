"""
结构感知分块策略：使用 Unstructured 库的 chunk_by_title 进行分块。

基于文档的标题层级结构进行智能分块，利用 Unstructured 官方内置的
结构感知分块函数，按章节、段落边界切分，保留文档的逻辑结构。

原理：
  1. 将干净段落映射为 Unstructured Elements（Title / NarrativeText）
  2. 调用 chunk_by_title() 按标题边界 + 字符限制自动分块
  3. 每个 chunk 的标题 → *** 父块，正文 → <-split-> 子块
  4. 图片段落不参与分块，追加到输出末尾

与 DefaultChunkingStrategy 的区别：
  - Default 基于 bbox 高度判断父级标题（启发式规则）
  - Unstructured 基于元素类型（Title vs NarrativeText）识别结构边界
  - Unstructured 内建了更成熟的合并/拆分策略（combine_text_under_n_chars 等）
"""

from typing import Optional

from config import (
    PARENT_SPLIT_MARKER,
    SPLIT_MARKER,
    MAX_SUB_BLOCK_TOKENS,
    UNSTRUCTURED_MAX_CHARACTERS,
    UNSTRUCTURED_NEW_AFTER_N_CHARS,
    UNSTRUCTURED_OVERLAP,
    UNSTRUCTURED_COMBINE_TEXT_UNDER_N_CHARS,
    UNSTRUCTURED_MULTIPAGE_SECTIONS,
)
from chunking.strategy import ChunkingStrategy, ChunkContext
from chunking.text_utils import _split_text_by_token_limit


class UnstructuredChunkingStrategy(ChunkingStrategy):
    """使用 Unstructured 的 chunk_by_title 进行结构感知分块。

    将干净段落转换为 Unstructured Elements，调用 chunk_by_title
    按文档结构边界（标题层级）分块，再映射回 ***/<-split-> 标记格式。

    图片段落不参与分块，直接追加到末尾输出。
    """

    @property
    def name(self) -> str:
        return "unstructured"

    def chunk(
        self,
        paragraphs: list[dict],
        context: Optional[ChunkContext] = None,
    ) -> list[dict]:
        """对干净段落插入 *** / <-split-> 标记。

        Parameters
        ----------
        paragraphs : list[dict]
            干净段落，每项 {"text", "style", "level", "image"(optional)}。
        context : ChunkContext, optional
            文档上下文（标题、文件名等）。

        Returns
        -------
        list[dict]
            插入分块标记后的段落列表。
        """
        from unstructured.chunking.title import chunk_by_title
        from unstructured.documents.elements import Title, NarrativeText

        # ---- 1. 分离文本段落和图片段落 ----
        text_paragraphs: list[dict] = []
        image_paragraphs: list[dict] = []

        for para in paragraphs:
            if para.get("image"):
                image_paragraphs.append(para)
            elif para.get("text", "").strip():
                text_paragraphs.append(para)
            # 空文本段落直接丢弃

        if not text_paragraphs:
            # 无文本可切分，原样返回（全部是图片）
            return list(paragraphs)

        # ---- 2. 转换为 Unstructured Elements ----
        # minerU 通过 text_level 字段标识标题（映射到 level），
        # 同时 type 字段中的 _TITLE_TYPES 也会被标记为标题。
        # 综合 level > 0（来自 text_level）和 style（来自 type）判断标题。
        elements = []
        for para in text_paragraphs:
            style = para.get("style", "Normal")
            level = para.get("level", 0)
            text = para.get("text", "")
            is_heading = level > 0 or style in ("Title", "Heading 1", "Heading 2", "Heading 3")
            if is_heading:
                elements.append(Title(text))
            else:
                elements.append(NarrativeText(text))

        # ---- 3. 结构感知分块 ----
        chunks = chunk_by_title(
            elements,
            max_characters=UNSTRUCTURED_MAX_CHARACTERS,
            new_after_n_chars=UNSTRUCTURED_NEW_AFTER_N_CHARS,
            overlap=UNSTRUCTURED_OVERLAP,
            combine_text_under_n_chars=UNSTRUCTURED_COMBINE_TEXT_UNDER_N_CHARS,
            multipage_sections=UNSTRUCTURED_MULTIPAGE_SECTIONS,
        )

        # ---- 4. 转换为 *** / <-split-> 标记段落 ----
        result = []
        for chunk in chunks:
            chunk_text = chunk.text.strip()
            if not chunk_text:
                continue

            # 从原始元素中区分标题和正文
            orig_elements = getattr(chunk.metadata, "orig_elements", None) or []
            title_texts: list[str] = []
            body_texts: list[str] = []

            for elem in orig_elements:
                text = str(elem.text).strip()
                if not text:
                    continue
                if isinstance(elem, Title):
                    title_texts.append(text)
                else:
                    body_texts.append(text)

            # 提取父级标题
            if title_texts:
                parent = title_texts[0]
                # 剩余的 title_texts（如果有多个标题）合并到正文
                if len(title_texts) > 1:
                    body_texts = title_texts[1:] + body_texts
            elif body_texts:
                # 无标题 → 取第一段正文作为父级
                parent = body_texts.pop(0)
            else:
                # 无标题也无正文（理论上不会到这里）
                lines = chunk_text.split("\n")
                parent = lines[0].strip()
                body_texts = [l.strip() for l in lines[1:] if l.strip()]

            # 输出 *** 父块标记
            if parent:
                result.append({
                    "text": PARENT_SPLIT_MARKER,
                    "style": "Normal",
                    "level": 0,
                })
                result.append({
                    "text": parent,
                    "style": "Heading 2",
                    "level": 2,
                })

            # 输出 <-split-> 子块标记和正文
            result.append({
                "text": SPLIT_MARKER,
                "style": "Normal",
                "level": 0,
            })

            for bi, body_line in enumerate(body_texts):
                # 不同 body 段落之间插入 <-split->
                if bi > 0:
                    result.append({
                        "text": SPLIT_MARKER,
                        "style": "Normal",
                        "level": 0,
                    })

                parts = _split_text_by_token_limit(body_line, MAX_SUB_BLOCK_TOKENS)
                for j, part in enumerate(parts):
                    result.append({
                        "text": part,
                        "style": "Normal",
                        "level": 0,
                    })
                    if j + 1 < len(parts):
                        result.append({
                            "text": SPLIT_MARKER,
                            "style": "Normal",
                            "level": 0,
                        })

        # ---- 5. 追加图片段落 ----
        result.extend(image_paragraphs)

        return result
