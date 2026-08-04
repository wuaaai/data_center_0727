"""
MinerU 解析核心 — 支持两种解析引擎。

  maas:  调内网 Maas /file_parse 接口（return_md + return_content_list + return_images）
  local: 封装 mineru.cli.common.do_parse 本地解析

maas 模式返回 md_content + content_list + 图片（保存到本地静态目录）。
"""
import base64
import json
import os
import threading
import time
import uuid
from pathlib import Path

import config

# 解析是否已加载（单例）
_model_loaded = False
_model_loading = False
_model_error = None
_load_lock = threading.Lock()
_start_time = time.time()


def load_model(blocking: bool = True) -> bool:
    """加载 MinerU 模型（HybridModelSingleton），可选阻塞等待。

    返回是否加载成功。模型只加载一次，线程安全。
    """
    global _model_loaded, _model_loading, _model_error
    with _load_lock:
        if _model_loaded:
            return True
        if _model_loading:
            if not blocking:
                return False
            # 已有加载线程，等待完成
        else:
            _model_loading = True
            _model_error = None

    if not blocking and _model_loading:
        return False

    try:
        from mineru.backend.pipeline.model_init import HybridModelSingleton
        HybridModelSingleton().get_model()
        with _load_lock:
            _model_loaded = True
        return True
    except Exception as e:
        with _load_lock:
            _model_error = str(e)
        print(f"[model] 模型加载失败: {e}")
        return False
    finally:
        with _load_lock:
            _model_loading = False


def model_status() -> dict:
    """返回模型加载状态（供健康检查/状态接口）。"""
    return {
        "model_loaded": _model_loaded,
        "model_loading": _model_loading,
        "model_error": _model_error,
        "backend": config.BACKEND,
        "model_path": str(config.MODEL_ROOT),
        "uptime": round(time.time() - _start_time, 1),
    }


def parse_pdf(pdf_bytes: bytes, filename: str, engine: str = None) -> dict:
    """解析 PDF 字节，返回 markdown 文本和 content_list。

    参数:
        pdf_bytes: PDF 文件内容（字节）
        filename: 原始文件名（用于取 stem 和展示）
        engine: 解析引擎，"maas"（内网）或 "local"（本地 do_parse），默认 config.PARSE_ENGINE

    返回:
        {
          "md_content": str,        # markdown 文本（图片链接已改写为本地静态 URL）
          "content_list": list|None, # 结构化 content_list（分块用）
          "stem": str,               # 文档 stem
          "images_saved": int,       # 保存的图片数
        }
    """
    engine = engine or config.PARSE_ENGINE
    if engine == "maas":
        return _parse_via_maas(pdf_bytes, filename)
    return _parse_via_local(pdf_bytes, filename)


# ═══════════════════════════════════════════════════════════════
# maas 模式：调内网接口
# ═══════════════════════════════════════════════════════════════

def _parse_via_maas(pdf_bytes: bytes, filename: str) -> dict:
    """调内网 Maas /file_parse 接口，解析 md + content_list + images。

    images 是 {文件名: "data:image/jpeg;base64,..."} dict。
    解码保存到 config.IMAGE_DIR，markdown 里 images/{key} 改写为静态 URL。
    """
    import urllib.request

    stem = Path(filename).stem
    # 构造 multipart/form-data
    boundary = "----FormBoundary" + uuid.uuid4().hex[:16]
    safe_name = filename.replace('"', "'").replace("\n", " ").replace("\r", " ")
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="files"; filename="{safe_name}"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n"
    ).encode("utf-8")
    # 附加参数
    tail_parts = [
        ("format", "markdown"),
    ]
    if config.RETURN_MD:
        tail_parts.append(("return_md", "true"))
    if config.RETURN_CONTENT_LIST:
        tail_parts.append(("return_content_list", "true"))
    if config.RETURN_IMAGES:
        tail_parts.append(("return_images", "true"))
    tail_parts.append(("return_middle_json", "true" if config.RETURN_MIDDLE_JSON else "false"))
    tail_parts.append(("return_model_output", "true" if config.RETURN_MODEL_OUTPUT else "false"))

    tail_buf = ""
    for name, val in tail_parts:
        tail_buf += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{val}\r\n"
    tail_buf += f"--{boundary}--\r\n"
    body = head + pdf_bytes + tail_buf.encode("utf-8")

    req = urllib.request.Request(
        config.MAAS_PARSE_URL,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req, timeout=config.MAAS_TIMEOUT) as resp:
        resp_data = json.loads(resp.read().decode("utf-8"))

    # 解析响应
    entry = {}
    results = resp_data.get("results") or {}
    for fname, e in results.items():
        entry = e
        break

    md_content = entry.get("md_content", "")
    # content_list 可能是字符串（JSON 文本）或 list
    content_list_raw = entry.get("content_list")
    content_list = None
    if isinstance(content_list_raw, str):
        try:
            content_list = json.loads(content_list_raw)
        except Exception:
            content_list = None
    elif isinstance(content_list_raw, list):
        content_list = content_list_raw

    # 图片：保存到本地 + 改写 markdown 链接
    images = entry.get("images") or {}
    md_content, images_saved = _save_images(md_content, images)

    return {
        "md_content": md_content,
        "content_list": content_list,
        "stem": stem,
        "images_saved": images_saved,
    }


def _save_images(md_content: str, images: dict) -> tuple[str, int]:
    """解码保存图片到 config.IMAGE_DIR，改写 markdown 图片链接。

    参数:
        md_content: 原始 markdown（含 ![](images/xxx.jpg)）
        images: {文件名: "data:image/jpeg;base64,..."} dict

    返回:
        (改写后的 markdown, 保存的图片数)
    """
    if not images:
        return md_content, 0
    config.IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    saved = 0
    for fname, data in images.items():
        if not isinstance(data, str) or "base64," not in data:
            continue
        try:
            b64 = data.split("base64,")[-1]
            img_bytes = base64.b64decode(b64)
            (config.IMAGE_DIR / fname).write_bytes(img_bytes)
            saved += 1
        except Exception as e:
            print(f"[image] 保存失败 {fname}: {e}")

    # 改写 markdown: images/{key} → IMAGE_STATIC_URL/{key}
    if saved and md_content:
        for fname in images:
            if images.get(fname):
                md_content = md_content.replace(
                    f"images/{fname}",
                    f"{config.IMAGE_STATIC_URL}{fname}",
                )
    return md_content, saved


# ═══════════════════════════════════════════════════════════════
# local 模式：本地 do_parse
# ═══════════════════════════════════════════════════════════════

def _parse_via_local(pdf_bytes: bytes, filename: str, output_dir: Path = None) -> dict:
    """本地 MinerU do_parse 解析（保留旧逻辑）。"""
    from mineru.cli.common import do_parse

    stem = Path(filename).stem
    out_dir = output_dir or (config.OUTPUT_DIR / f"{int(time.time())}_{stem}")
    out_dir.mkdir(parents=True, exist_ok=True)

    # do_parse 会原地修改传入的 list，每次调用传新的
    do_parse(
        output_dir=str(out_dir),
        pdf_file_names=[stem],
        pdf_bytes_list=[pdf_bytes],
        p_lang_list=[config.LANG],
        backend=config.BACKEND,
        parse_method=config.PARSE_METHOD,
        formula_enable=config.FORMULA_ENABLE,
        table_enable=config.TABLE_ENABLE,
        server_url=None,
        f_draw_layout_bbox=False,
        f_draw_span_bbox=False,
        f_dump_md=True,
        f_dump_middle_json=config.DUMP_MIDDLE_JSON,
        f_dump_model_output=False,
        f_dump_orig_pdf=False,
        f_dump_content_list=config.DUMP_CONTENT_LIST,
        start_page_id=config.START_PAGE_ID,
        end_page_id=config.END_PAGE_ID,
    )

    md_content = _read_markdown_from_dir(out_dir, stem)

    return {
        "md_content": md_content,
        "content_list": None,
        "stem": stem,
        "images_saved": 0,
    }


def parse_pdf_to_markdown(pdf_bytes: bytes, filename: str, output_dir: Path = None) -> str:
    """兼容入口：解析 PDF 只返回 markdown 文本。"""
    return parse_pdf(pdf_bytes, filename, output_dir)["md_content"]


def _read_markdown_from_dir(out_dir: Path, stem: str) -> str:
    """从 do_parse 输出目录读取 .md 文件。

    pipeline 后端输出在 {out}/{stem}/{parse_method}/{stem}.md。
    找不到则递归搜索任意 .md。
    """
    # 常见输出子目录
    candidates = [
        out_dir / stem / config.PARSE_METHOD / f"{stem}.md",
        out_dir / stem / "vlm" / f"{stem}.md",
        out_dir / stem / f"hybrid_{config.PARSE_METHOD}" / f"{stem}.md",
        out_dir / stem / "office" / f"{stem}.md",
    ]
    for c in candidates:
        if c.exists():
            return c.read_text(encoding="utf-8")

    # 递归兜底
    for md in out_dir.rglob("*.md"):
        return md.read_text(encoding="utf-8")
    return ""
