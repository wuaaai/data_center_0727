"""
_merge_empty_heading_blocks — 从 mineru_0720/parsing/fast_pdf_parser.py 提取。

合并空标题块：*** + Heading + <-split-> + *** → 标题文字合并到下一正文开头。
仅依赖 PARENT_SPLIT_MARKER / SPLIT_MARKER 两个配置项。
"""
from config import PARENT_SPLIT_MARKER, SPLIT_MARKER


def _merge_empty_heading_blocks(paragraphs: list[dict]) -> list[dict]:
    """合并空标题块：*** + Heading + <-split-> + *** → 标题文字合并到下一正文开头。

    扫描 *** + Heading + <-split-> + *** 模式，
    将空标题文字插入到后一个 *** 节的第一个正文段落之前。
    """
    n = len(paragraphs)
    if n < 6:
        return paragraphs

    # 找到所有 *** 的位置
    star_positions = [i for i, p in enumerate(paragraphs) if p.get("text") == PARENT_SPLIT_MARKER]

    result: list[dict] = list(paragraphs)  # 复制，原位修改
    removed_count = 0  # 记录已删除的段落数，用于调整索引

    for idx in range(len(star_positions) - 1):
        # 当前 *** 位置（已考虑之前的删除）
        pos = star_positions[idx] - removed_count
        nxt_pos = star_positions[idx + 1] - removed_count

        if pos + 2 >= len(result):
            continue
        if nxt_pos <= pos + 2:
            continue

        # 检查是否为空标题：*** + Heading + <-split-> + ...
        h = result[pos + 1]
        s = result[pos + 2]
        if not h.get("style", "").startswith("Heading"):
            continue
        if s.get("text") != SPLIT_MARKER:
            continue

        # 找到下一节的第一段正文（跳过 *** / <-split-> / Heading）
        body_idx = nxt_pos + 1
        while body_idx < len(result):
            bp = result[body_idx]
            if bp.get("text") in (PARENT_SPLIT_MARKER, SPLIT_MARKER):
                body_idx += 1
                continue
            if bp.get("style", "").startswith("Heading"):
                body_idx += 1
                continue
            break

        if body_idx >= len(result):
            # 下一节无正文 → 跳到结尾
            nxt_split_idx = nxt_pos + 1
            while nxt_split_idx < len(result) and result[nxt_split_idx].get("text") == SPLIT_MARKER:
                nxt_split_idx += 1
            continue

        # 检查 pos 到 nxt_pos 之间是否只有 heading + split（无正文）
        has_body_between = any(
            result[j].get("text") not in (PARENT_SPLIT_MARKER, SPLIT_MARKER)
            and not result[j].get("style", "").startswith("Heading")
            for j in range(pos + 3, nxt_pos)
        )
        if has_body_between:
            continue

        # 空标题：删除 pos..nxt_pos（去除一个 ***），标题文字插入到下一节正文
        heading_text = h.get("text", "")
        # 在正文前插入标题文字
        result[body_idx]["text"] = heading_text + "\n" + result[body_idx]["text"]
        # 删除 pos 到 nxt_pos-1 的段落
        del result[pos:nxt_pos]
        removed_count += nxt_pos - pos

    return result
