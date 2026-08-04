"""
markdown / content_list 分块 — 父子召回策略，配合向量库父子召回。

两条路径:
  1. content_list 父子分块（优先）：用 mineru_0720 的 chunking 包
     chunk_content_list + chunks_to_paragraphs，按文档结构父子关系分块
  2. markdown 兜底分块：无 content_list 时按 "# " 标题 + 段落切分

父子召回: 子块(content)向量检索，父块(recall_context)召回上下文。
输出: {chunk_id, parent_id, title, content, recall_context, token_estimate}
"""
import config


# ═══════════════════════════════════════════════════════════════
# content_list 父子分块（复用 mineru_0720 chunking）
# ═══════════════════════════════════════════════════════════════

def chunk_content_list(content_list: list, pdf_stem: str) -> list[dict]:
    """用 mineru_0720 chunking 逻辑对 content_list 做父子分块。

    参数:
        content_list: MinerU content_list（block-based 或 page-based）
        pdf_stem: 文档 stem

    返回:
        [{chunk_id, parent_id, title, content, recall_context, token_estimate}]
    """
    from chunking.default_strategy import (
        chunk_content_list as _chunk,
        chunks_to_paragraphs,
    )
    from config import PARENT_SPLIT_MARKER, SPLIT_MARKER

    result = _chunk(content_list, pdf_stem=pdf_stem)
    paragraphs = chunks_to_paragraphs(result.chunks, pdf_stem=pdf_stem)

    doc_title = result.doc_title or pdf_stem
    chunks = []
    idx = 0
    current_parts = []
    current_title = ""
    pending_parent = False

    def flush():
        nonlocal idx, current_parts
        text = "\n".join(p for p in current_parts if p)
        if text.strip():
            parts_ = [f"文档名：{doc_title}"]
            if current_title and current_title not in parts_:
                parts_.append(current_title)
            parts_.append(text)
            content = "\n".join(p for p in parts_ if p)
            for sub in _enforce_limit(content):
                chunks.append({
                    "chunk_id": f"{pdf_stem}_c_{idx}",
                    "parent_id": f"{pdf_stem}_p_{current_title or idx}",
                    "title": current_title or doc_title,
                    "content": sub,
                    "recall_context": content,  # 完整父块上下文
                    "token_estimate": len(sub),
                })
                idx += 1
        current_parts = []

    for para in paragraphs:
        text = para.get("text", "")
        if text == SPLIT_MARKER:
            flush()
        elif text == PARENT_SPLIT_MARKER:
            flush()
            current_title = ""
            pending_parent = True
        else:
            if pending_parent and text.strip():
                current_title = text.strip()
                pending_parent = False
                continue
            # 图片段落：保留 caption + image 信息（相对路径改写成静态 URL）
            if para.get("image"):
                img_path = para["image"].get("path", "")
                if img_path.startswith("images/"):
                    img_path = config.IMAGE_STATIC_URL + img_path[len("images/"):]
                current_parts.append(f"![image]({img_path})")
                if text:
                    current_parts.append(text)
            elif text:
                current_parts.append(text)
    flush()
    return chunks


# ═══════════════════════════════════════════════════════════════
# markdown 兜底分块
# ═══════════════════════════════════════════════════════════════

def chunk_markdown(md_content: str, display_name: str) -> list[dict]:
    """对 markdown 文本做父子召回分块（无 content_list 时兜底）。

    按 "# " 一级标题分章节 = 父块，章节内段落切子块。
    """
    if not md_content or not md_content.strip():
        return []

    max_chars = config.MAX_CHUNK_CHARS  # 默认 600

    # 按 "# " 一级标题分章节（父块）
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
        parent_id = f"{display_name}_p_{idx}"
        recall_ctx = f"文档名：{display_name}"
        if title:
            recall_ctx += f"\n{title}"
        recall_ctx += f"\n{section}"

        for sub_title, sub_content in _split_section(title, section, max_chars):
            content = f"文档名：{display_name}"
            if sub_title:
                content += f"\n{sub_title}"
            content += f"\n{sub_content}"
            chunks.append({
                "chunk_id": f"{display_name}_c_{idx}",
                "parent_id": parent_id,
                "title": sub_title or display_name,
                "content": content,
                "recall_context": recall_ctx,
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


def _enforce_limit(content: str, max_chars: int = 600) -> list[str]:
    """超长块兜底：按段落切分，每段 ≤ max_chars 字符。"""
    if len(content) <= max_chars:
        return [content]
    lines = content.split("\n")
    prefix = lines[0] if lines else ""
    body = "\n".join(lines[1:])
    paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]
    if not paragraphs:
        return [content]
    result = []
    current = []
    current_len = 0
    for para in paragraphs:
        if len(para) > max_chars:
            if current:
                result.append(prefix + "\n" + "\n\n".join(current))
                current, current_len = [], 0
            for i in range(0, len(para), max_chars):
                result.append(prefix + "\n" + para[i:i + max_chars])
        elif current_len + len(para) <= max_chars:
            current.append(para)
            current_len += len(para)
        else:
            result.append(prefix + "\n" + "\n\n".join(current))
            current = [para]
            current_len = len(para)
    if current:
        result.append(prefix + "\n" + "\n\n".join(current))
    return result
