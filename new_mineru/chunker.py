"""
markdown 分块 — 按 "# " 一级标题分章，超长章节按段落切成 ≤MAX_CHUNK_CHARS 子块。

保证每块在 rerank 模型 512 token 上限内。图片相对路径保留为纯文本。
"""
import config


def _split_long_section(title, content, max_chars=None):
    """把超长章节按段落切成多个子块，每个 ≤ max_chars 字符。"""
    max_chars = max_chars or config.MAX_CHUNK_CHARS
    paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
    if not paragraphs:
        return [(title, content)]
    chunks = []
    current = []
    current_len = 0
    for para in paragraphs:
        if len(para) > max_chars:
            if current:
                chunks.append((title, "\n\n".join(current)))
                current, current_len = [], 0
            for i in range(0, len(para), max_chars):
                chunks.append((title, para[i:i + max_chars]))
        elif current_len + len(para) <= max_chars:
            current.append(para)
            current_len += len(para)
        else:
            chunks.append((title, "\n\n".join(current)))
            current = [para]
            current_len = len(para)
    if current:
        chunks.append((title, "\n\n".join(current)))
    return chunks


def chunk_markdown(md_content: str, display_name: str) -> list[dict]:
    """把 markdown 文本分块。

    参数:
        md_content: markdown 文本
        display_name: 展示名（用于 chunk_id）

    返回:
        [{chunk_id, title, content, token_estimate}] 列表
    """
    if not md_content or not md_content.strip():
        return []

    # 按 "# " 一级标题分章
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
    for title, content in sections:
        content = content.strip()
        if not content:
            continue
        for sub_title, sub_content in _split_long_section(title, content):
            full_title = f"文档名：{display_name}"
            if sub_title:
                full_title += f"\n{sub_title}"
            full_content = f"{full_title}\n{sub_content}"
            chunks.append({
                "chunk_id": f"{display_name}_md_{idx}",
                "title": sub_title or display_name,
                "content": full_content,
                "token_estimate": len(full_content),  # 完整内容长度，保守估算 token
            })
            idx += 1
    return chunks
