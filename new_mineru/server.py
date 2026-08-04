"""
new_mineru FastAPI 服务 — PDF → MinerU 解析 → markdown（可选分块）。

接口模式对齐内网 Maas:
  POST /file_parse         PDF → markdown（同步返回）
  POST /file_parse/chunk   PDF → markdown + 分块
  GET  /health             健康检查
  GET  /model/status       模型状态
"""
import json
import threading
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import config
import parser
import chunker

app = FastAPI(title="new_mineru 独立解析服务", version=config.VERSION)

# 图片静态服务（前端读取解析出的图片，URL 形如 /static/images/xxx.jpg）
config.IMAGE_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(config.PROJECT_ROOT / "static")), name="static")

# 全局解析锁：MinerU 模型单例只能串行使用，避免并发解析冲突
_parse_lock = threading.Lock()


# ── 解析历史存储 ──
_HISTORY_INDEX = config.HISTORY_DIR / "index.json"


def _save_history(filename: str, md_content: str, chunks: list) -> str:
    """保存解析结果到历史目录，返回记录 id。"""
    config.HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    rec_id = f"{int(time.time())}_{uuid.uuid4().hex[:6]}"
    rec = {
        "id": rec_id,
        "filename": filename,
        "created_at": time.time(),
        "md_chars": len(md_content),
        "chunk_count": len(chunks),
    }
    # 保存详情
    (config.HISTORY_DIR / f"{rec_id}.json").write_text(
        json.dumps({"filename": filename, "md_content": md_content, "chunks": chunks},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    # 更新索引
    index = []
    if _HISTORY_INDEX.exists():
        try:
            index = json.loads(_HISTORY_INDEX.read_text(encoding="utf-8"))
        except Exception:
            index = []
    index.insert(0, rec)
    _HISTORY_INDEX.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    return rec_id


def _load_history_list() -> list:
    """读取历史文件列表（不含详情）。"""
    if not _HISTORY_INDEX.exists():
        return []
    try:
        return json.loads(_HISTORY_INDEX.read_text(encoding="utf-8"))
    except Exception:
        return []


def _load_history_detail(rec_id: str) -> dict | None:
    """读取某个历史文件的详情。"""
    path = config.HISTORY_DIR / f"{rec_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None

_INDEX_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>new_mineru 文档解析</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: "Microsoft YaHei", system-ui, sans-serif; background: #f1f5f9; color: #1e293b; }
  .wrap { max-width: 1100px; margin: 0 auto; padding: 24px; }
  .card { background: #fff; border-radius: 12px; padding: 20px; margin-bottom: 16px;
          box-shadow: 0 2px 8px rgba(15,23,42,.06); }
  h1 { font-size: 22px; margin-bottom: 4px; }
  .sub { color: #64748b; font-size: 13px; margin-bottom: 16px; }
  .row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
  input[type=file] { flex: 1; min-width: 200px; padding: 8px; border: 1px solid #cbd5e1;
                     border-radius: 8px; background: #f8fafc; font-size: 14px; }
  button { padding: 9px 18px; border: none; border-radius: 8px; cursor: pointer;
           font-size: 14px; background: #4f7cff; color: #fff; }
  button:hover { background: #3b6bef; }
  button:disabled { background: #94a3b8; cursor: not-allowed; }
  .status { font-size: 13px; color: #64748b; margin-top: 8px; }
  .tabs { display: flex; gap: 6px; margin-top: 12px; }
  .tab { padding: 6px 14px; border-radius: 999px; cursor: pointer; font-size: 13px;
         border: 1px solid #cbd5e1; background: #f8fafc; color: #475569; }
  .tab.active { background: #4f7cff; color: #fff; border-color: #4f7cff; }
  .content { margin-top: 12px; }
  .md-box { white-space: pre-wrap; font-family: Consolas, monospace; font-size: 13px;
            line-height: 1.7; background: #f8fafc; border: 1px solid #e2e8f0;
            border-radius: 8px; padding: 14px; max-height: 500px; overflow-y: auto; }
  .chunk { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px;
           padding: 12px; margin-bottom: 10px; }
  .chunk-title { font-weight: 600; font-size: 14px; margin-bottom: 4px; }
  .chunk-meta { font-size: 12px; color: #64748b; margin-bottom: 6px; }
  .chunk-content { white-space: pre-wrap; font-size: 13px; line-height: 1.6; }
  .err { color: #dc2626; font-size: 13px; margin-top: 8px; }
</style>
</head>
<body>
<div class="wrap">
  <div class="card">
    <h1>new_mineru 文档解析</h1>
    <div class="sub">PDF 进 → MinerU 解析 → markdown / 分块预览</div>
    <div class="row">
      <input type="file" id="file" accept=".pdf,.docx,.doc">
      <button id="btn" onclick="parseFile()">解析</button>
    </div>
    <div class="status" id="status">选择 PDF 后点击解析（首次加载模型需等待几分钟）</div>
    <div class="err" id="err"></div>
    <div class="tabs" id="tabs" style="display:none">
      <span class="tab active" onclick="showTab('md')">Markdown</span>
      <span class="tab" onclick="showTab('chunks')">分块</span>
    </div>
    <div class="content" id="mdPanel" style="display:none">
      <div class="md-box" id="mdBox"></div>
    </div>
    <div class="content" id="chunkPanel" style="display:none">
      <div id="chunkList"></div>
    </div>
  </div>
  <div class="card">
    <h2 style="font-size:18px;margin-bottom:10px">历史文件</h2>
    <div id="historyList" class="status">加载中...</div>
  </div>
</div>
<script>
let rawResult = null;
async function loadHistory() {
  try {
    const resp = await fetch('/parse_history');
    const data = await resp.json();
    const items = data.items || [];
    const box = document.getElementById('historyList');
    if (!items.length) { box.innerHTML = '<div class="status">暂无历史记录，解析后可在此查看</div>'; return; }
    box.innerHTML = items.map(it => `
      <div style="padding:10px;border-bottom:1px solid #e2e8f0;cursor:pointer;display:flex;justify-content:space-between;align-items:center"
           onclick="showHistory('${it.id}')"
           onmouseover="this.style.background='#f1f5f9'" onmouseout="this.style.background=''">
        <div>
          <div style="font-weight:600;font-size:14px">${escapeHtml(it.filename)}</div>
          <div style="font-size:12px;color:#64748b">${formatTime(it.created_at)} | markdown ${it.md_chars} 字符 | ${it.chunk_count} 块</div>
        </div>
        <span style="color:#4f7cff">查看 ›</span>
      </div>`).join('');
  } catch (e) {
    document.getElementById('historyList').innerHTML = '加载历史失败: ' + e.message;
  }
}
function formatTime(ts) {
  const d = new Date(ts * 1000);
  return d.getFullYear() + '/' + (d.getMonth()+1) + '/' + d.getDate() + ' ' +
         String(d.getHours()).padStart(2,'0') + ':' + String(d.getMinutes()).padStart(2,'0');
}
async function showHistory(id) {
  try {
    document.getElementById('status').textContent = '加载历史记录...';
    const resp = await fetch('/parse_history/' + id);
    const data = await resp.json();
    if (!resp.ok) { document.getElementById('err').textContent = data.error || '加载失败'; return; }
    rawResult = { md_content: data.md_content || '', chunks: data.chunks || [] };
    document.getElementById('mdBox').textContent = rawResult.md_content || '（无内容）';
    document.getElementById('tabs').style.display = '';
    document.getElementById('mdPanel').style.display = '';
    document.getElementById('chunkPanel').style.display = 'none';
    document.querySelectorAll('.tab')[0].classList.add('active');
    document.querySelectorAll('.tab')[1].classList.remove('active');
    renderChunks(rawResult.chunks);
    document.getElementById('status').textContent =
      `历史文件: ${data.filename} | markdown ${rawResult.md_content.length} 字符 | ${rawResult.chunks.length} 块`;
  } catch (e) {
    document.getElementById('err').textContent = '加载历史失败: ' + e.message;
  }
}
loadHistory();
function showTab(name) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  event.target.classList.add('active');
  document.getElementById('mdPanel').style.display = name === 'md' ? '' : 'none';
  document.getElementById('chunkPanel').style.display = name === 'chunks' ? '' : 'none';
}
async function parseFile() {
  const file = document.getElementById('file').files[0];
  const err = document.getElementById('err');
  err.textContent = '';
  if (!file) { err.textContent = '请选择文件'; return; }
  const btn = document.getElementById('btn');
  btn.disabled = true;
  document.getElementById('status').textContent = '解析中... 大文件或首次运行可能需要几分钟';
  const fd = new FormData();
  fd.append('files', file);
  fd.append('format', 'markdown');
  try {
    const resp = await fetch('/file_parse/chunk', { method: 'POST', body: fd });
    const data = await resp.json();
    if (!resp.ok) { err.textContent = '解析失败: ' + (data.error || resp.status); return; }
    const filename = Object.keys(data.results)[0];
    rawResult = data.results[filename];
    document.getElementById('mdBox').textContent = rawResult.md_content || '（无内容）';
    document.getElementById('tabs').style.display = '';
    document.getElementById('mdPanel').style.display = '';
    document.getElementById('chunkPanel').style.display = 'none';
    document.querySelectorAll('.tab')[0].classList.add('active');
    document.querySelectorAll('.tab')[1].classList.remove('active');
    renderChunks(rawResult.chunks || []);
    document.getElementById('status').textContent =
      `解析完成: ${filename} | markdown ${(rawResult.md_content||'').length} 字符 | ${(rawResult.chunks||[]).length} 块`;
  } catch (e) {
    err.textContent = '请求失败: ' + e.message;
  } finally {
    btn.disabled = false;
  }
}
function renderChunks(chunks) {
  const box = document.getElementById('chunkList');
  if (!chunks.length) { box.innerHTML = '<div class="status">无分块</div>'; return; }
  box.innerHTML = chunks.map(c => `
    <div class="chunk">
      <div class="chunk-title">${c.chunk_id || ''} · ${escapeHtml(c.title || '')}</div>
      <div class="chunk-meta">估算 token: ${c.token_estimate || '-'}${c.parent_id ? ' | 父块: ' + escapeHtml(c.parent_id) : ''}</div>
      <div class="chunk-content">${escapeHtml(c.content || '')}</div>
    </div>`).join('');
}
function escapeHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
def index():
    """前端页面：选择文档 → 解析 → 查看 markdown / 分块。"""
    return HTMLResponse(_INDEX_HTML)


@app.on_event("startup")
def _startup():
    """启动时异步预热模型（不阻塞服务启动）。"""
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    config.HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    threading.Thread(target=parser.load_model, kwargs={"blocking": True}, daemon=True).start()


@app.get("/health")
def health():
    """健康检查。"""
    st = parser.model_status()
    return {"status": "ok" if st["model_loaded"] else "warming", **st}


@app.get("/model/status")
def model_status():
    """模型状态。"""
    return parser.model_status()


@app.get("/parse_history")
def parse_history():
    """历史解析文件列表。"""
    return {"items": _load_history_list()}


@app.get("/parse_history/{rec_id}")
def parse_history_detail(rec_id: str):
    """某个历史文件的 markdown / 分块详情。"""
    rec = _load_history_detail(rec_id)
    if not rec:
        return JSONResponse({"error": "记录不存在"}, status_code=404)
    return rec


def _save_upload(file: UploadFile, content: bytes) -> tuple[str, Path]:
    """校验并保存上传文件，返回 (原始文件名, 保存路径)。"""
    filename = (file.filename or "").strip()
    if not filename:
        raise ValueError("未选择文件")
    ext = Path(filename).suffix.lower()
    if ext not in config.ALLOWED_EXTENSIONS:
        raise ValueError(f"不支持的文件格式: {ext}")
    if len(content) > config.MAX_FILE_SIZE_MB * 1024 * 1024:
        raise ValueError(f"文件过大: {len(content)/1024/1024:.1f}MB")
    safe = f"{uuid.uuid4().hex[:8]}_{filename}"
    path = config.UPLOAD_DIR / safe
    path.write_bytes(content)
    return filename, path


def _build_response(filename: str, md_content: str, with_chunks: bool) -> dict:
    """构造对齐内网 Maas 的响应结构。"""
    entry = {"md_content": md_content}
    if with_chunks:
        entry["chunks"] = chunker.chunk_markdown(md_content, filename)
    return {
        "backend": config.BACKEND_NAME,
        "version": config.VERSION,
        "results": {filename: entry},
    }


@app.post("/file_parse")
def file_parse(
    files: UploadFile = File(...),
    format: str = Form("markdown"),
):
    """PDF → markdown（同步返回）。对齐内网 Maas 格式。

    用同步 def（FastAPI 放入线程池运行），避免阻塞事件循环导致
    健康检查和前端页面无法响应。
    """
    try:
        content = files.file.read()
        filename, _path = _save_upload(files, content)
        with _parse_lock:
            result = parser.parse_pdf(content, filename)
        md_content = result.get("md_content", "")
        if not md_content:
            return JSONResponse({"code": 500, "error": "解析结果为空"}, status_code=500)
        chunks = _get_chunks(result, filename)
        _save_history(filename, md_content, chunks)
        return _build_response(filename, md_content, with_chunks=False)
    except ValueError as e:
        return JSONResponse({"code": 400, "error": str(e)}, status_code=400)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({"code": 500, "error": str(e)}, status_code=500)


def _get_chunks(parse_result: dict, filename: str) -> list:
    """分块：content_list 优先（结构化父子分块），否则 markdown 兜底。"""
    content_list = parse_result.get("content_list")
    stem = parse_result.get("stem", "")
    if content_list:
        try:
            return chunker.chunk_content_list(content_list, stem or filename)
        except Exception as e:
            print(f"[chunk] content_list 分块失败，回退 markdown: {e}")
    return chunker.chunk_markdown(parse_result.get("md_content", ""), filename)


@app.post("/file_parse/chunk")
def file_parse_chunk(
    files: UploadFile = File(...),
    format: str = Form("markdown"),
):
    """PDF → markdown + 分块（同步返回）。"""
    try:
        content = files.file.read()
        filename, _path = _save_upload(files, content)
        with _parse_lock:
            result = parser.parse_pdf(content, filename)
        md_content = result.get("md_content", "")
        if not md_content:
            return JSONResponse({"code": 500, "error": "解析结果为空"}, status_code=500)
        chunks = _get_chunks(result, filename)
        _save_history(filename, md_content, chunks)
        return _build_response(filename, md_content, with_chunks=True)
    except ValueError as e:
        return JSONResponse({"code": 400, "error": str(e)}, status_code=400)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({"code": 500, "error": str(e)}, status_code=500)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=config.SERVER_HOST, port=config.SERVER_PORT)
