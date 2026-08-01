"""
markdown 父子召回分块 — 基于 markdown 结构分块，配合向量库父子召回策略。

策略（对齐 data_processing_center 入库逻辑）:
  1. 按 "# " 一级标题分章节 = 父块（recall_context，召回时的完整上下文）
  2. 章节内按段落切子块 = 子块（content，向量 embedding 用）
  3. 每个子块带 recall_context（所属章节完整内容）+ parent_id

输出: {chunk_id, parent_id, title, content, recall_context, token_estimate}
"""
import config


def chunk_markdown(md_content: str, display_name: str) -> list[dict]:
    """对 markdown 文本做父子召回分块。

    参数:
        md_content: MinerU 输出的 markdown 文本
        display_name: 展示名（用于 chunk_id 和标题前缀）

    返回:
        [{chunk_id, parent_id, title, content, recall_context, token_estimate}] 列表
        每个元素是一个子块：content 用于向量检索，recall_context 是父块完整内容。
    """
    if not md_content or not md_content.strip():
        return []

    max_chars = config.MAX_CHUNK_CHARS  # 默认 600

    # 1) 按 "# " 一级标题分章节（父块）
    sections = []  # [(title, text)]
    current_title = ""
    current_lines = []
    for line in md_content.split("\n"):
        stripped = line.strip()
        if stripped.startswith("# "):
            if current_title or any(l.strip() for l in current_lines):
                sections.append((current_title, "\n".join(current_lines)))
            current_title = stripped[2:].strip()
            current_lines = []
        else:
            current_lines.append(line)
    if current_title or any(l.strip() for l in current_lines):
        sections.append((current_title, "\n".join(current_lines)))

    chunks = []
    idx = 0
    for title, section in sections:
        section = section.strip()
        if not section:
            continue
        # 父块：完整章节内容（recall_context）
        parent_id = f"{display_name}_p_{idx}"
        recall_ctx = f"文档名：{display_name}"
        if title:
            recall_ctx += f"\n{title}"
        recall_ctx += f"\n{section}"

        # 2) 章节内按段落切子块
        sub_chunks = _split_section(title, section, max_chars)
        for sub_title, sub_content in sub_chunks:
            content = f"文档名：{display_name}"
            if sub_title:
                content += f"\n{sub_title}"
            content += f"\n{sub_content}"
            chunks.append({
                "chunk_id": f"{display_name}_c_{idx}",
                "parent_id": parent_id,
                "title": sub_title or display_name,
                "content": content,              # 子块，向量检索用
                "recall_context": recall_ctx,     # 父块，召回上下文
                "token_estimate": len(content),
            })
            idx += 1
    return chunks


def _split_section(title: str, content: str, max_chars: int) -> list[tuple[str, str]]:
    """把章节内容切成 ≤max_chars 的子块（子块）。优先段落边界，段落超长硬切。"""
    if len(content) <= max_chars:
        return [(title, content)]
    paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
    if not paragraphs:
        return [(title, content)]
    result = []
    current = []
    current_len = 0
    for para in paragraphs:
        if len(para) > max_chars:
            if current:
                result.append((title, "\n\n".join(current)))
                current, current_len = [], 0
            for i in range(0, len(para), max_chars):
                result.append((title, para[i:i + max_chars]))
        elif current_len + len(para) <= max_chars:
            current.append(para)
            current_len += len(para)
        else:
            result.append((title, "\n\n".join(current)))
            current = [para]
            current_len = len(para)
    if current:
        result.append((title, "\n\n".join(current)))
    return result
