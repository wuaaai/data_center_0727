"""
空间文本合并模块：将图片/图表附近的短文本（图例/图注）合并为图片标题。
"""

from config import SPATIAL_MERGE_MIN_IMAGE_AREA

from chunking.text_utils import (
    _extract_text,
    _SKIP_TYPES,
    _TITLE_TYPES,
)
from chunking.image_analyzer import (
    FIGURE_TYPES,
    extract_image_path,
    extract_caption_text,
    text_to_image_distance,
    set_spatial_caption,
)


def _merge_spatial_text_to_images(
    flat_blocks: list[tuple[int, dict]],
) -> None:
    """将图片/图表附近的短文本（图例/图注）合并为图片标题（就地修改）。

    采用最近距离匹配：当两个图片距离很近时，文字归距离更近的图片，
    避免「串标题」。
    """
    pages: dict[int, list[tuple[int, int, dict]]] = {}
    for global_idx, (page_num, block) in enumerate(flat_blocks):
        pages.setdefault(page_num, []).append((global_idx, page_num, block))

    for _, page_blocks in pages.items():
        # 收集图片条目
        image_entries: list[tuple[int, dict, list[int]]] = []
        for global_idx, _, block in page_blocks:
            block_type = (block.get("type", "") or "").strip().lower()
            if block_type not in FIGURE_TYPES:
                continue
            bbox = block.get("bbox")
            if not bbox or len(bbox) != 4:
                continue
            area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
            if area < SPATIAL_MERGE_MIN_IMAGE_AREA:
                continue
            if not extract_image_path(block):
                continue
            image_entries.append((global_idx, block, bbox))

        if not image_entries:
            continue

        # 收集文本条目
        text_entries: list[tuple[int, dict, list[int], str]] = []
        for global_idx, _, block in page_blocks:
            block_type = (block.get("type", "") or "").strip().lower()
            if block_type in _SKIP_TYPES or block_type in FIGURE_TYPES:
                continue
            if block_type in _TITLE_TYPES:
                continue
            txt = _extract_text(block)
            if not txt:
                continue
            bbox = block.get("bbox")
            if not bbox or len(bbox) != 4:
                continue
            if block.get("_spatial_merged"):
                continue
            text_entries.append((global_idx, block, bbox, txt))

        if not text_entries:
            continue

        # 最近距离匹配
        img_text_map: dict[int, list[str]] = {img_e[0]: [] for img_e in image_entries}
        claimed: set[int] = set()

        for txt_global_idx, txt_block, txt_bbox, txt_content in text_entries:
            if len(txt_content) > 40:
                continue

            best_img_idx: int | None = None
            best_dist = float("inf")

            for img_global_idx, img_block, img_bbox in image_entries:
                dist = text_to_image_distance(img_bbox, txt_bbox)
                if dist is not None and dist < best_dist:
                    best_dist = dist
                    best_img_idx = img_global_idx

            if best_img_idx is not None:
                img_text_map[best_img_idx].append(txt_content)
                claimed.add(txt_global_idx)
                txt_block["_spatial_merged"] = True

        # 写回 caption
        for img_global_idx, img_block, img_bbox in image_entries:
            adjacent_texts = img_text_map[img_global_idx]
            if not adjacent_texts:
                continue
            existing = extract_caption_text(img_block)
            merged = " | ".join(adjacent_texts)
            if existing:
                merged = f"{existing} | {merged}"
            set_spatial_caption(img_block, merged)
