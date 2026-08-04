# new_mineru — 独立 MinerU 文档解析服务

PDF 进 → 解析 → markdown + content_list + 图片。对接内网 Maas 接口（`return_content_list` + `return_images`），独立运行，方便查看和调试。

## 环境

- Python: 复用 `mineru_0720/.venv`（已装 mineru 3.2.3 + 全部依赖）
- 内网域名: `910b.hbmaas.com` → hosts 映射 `10.246.5.75`

## 启动服务（端口 8004）

```bash
cd E:\Develop_docu\sql_0722_center\new_mineru
..\mineru_0720\.venv\Scripts\python.exe server.py
```

访问 `http://localhost:8004` 打开测试前端页面。图片静态服务在 `http://localhost:8004/static/images/`。

## 解析引擎（config.py 或环境变量）

| 变量 | 默认 | 说明 |
|------|------|------|
| `NEW_MINERU_PARSE_ENGINE` | maas | maas=内网接口 / local=本地 MinerU |
| `NEW_MINERU_MAAS_URL` | 内网 file_parse | 内网解析地址 |

maas 模式调内网接口，带 `return_md + return_content_list + return_images`。

## 接口

| 接口 | 说明 |
|------|------|
| `GET /` | 前端页面（选文件解析 + 历史文件查看） |
| `POST /file_parse` | PDF → markdown + 图片 |
| `POST /file_parse/chunk` | PDF → markdown + content_list 分块 |
| `GET /parse_history` | 历史解析文件列表 |
| `GET /parse_history/{id}` | 某个历史文件的 markdown/分块详情 |
| `GET /static/images/{file}` | 解析出的图片（静态服务） |
| `GET /health` | 健康检查 |
| `GET /model/status` | 模型状态 |

## 请求示例（模仿内网 Maas）

```bash
curl -X POST "http://localhost:8004/file_parse" \
  -F "files=@./test.pdf" -F "format=markdown"
```

响应格式：
```json
{
  "backend": "hybrid-auto-engine",
  "version": "2.7.1",
  "results": {
    "test.pdf": {
      "md_content": "# 前言\n...",
      "chunks": [
        {"chunk_id": "test.pdf_md_0", "title": "前言", "content": "...", "token_estimate": 380}
      ]
    }
  }
}
```

## CLI 单独测试

```bash
python main.py C:/path/test.pdf --chunk   # 打印 markdown + 分块
python main.py C:/path/test.pdf -o out.md # markdown 存文件
```

## 分块说明（content_list 父子召回）

- **优先用 content_list 分块**（内网 `return_content_list=true` 返回，复用 mineru_0720 chunking）
  - `chunk_content_list` + `chunks_to_paragraphs`，按文档结构父子关系分块
  - 图片保留在分块中（`INCLUDE_IMAGES=all`，不依赖 LLM）
- **markdown 兜底**：无 content_list 时按 `# ` 标题 + 段落切分
- 每个子块输出：`{chunk_id, parent_id, title, content, recall_context, token_estimate}`
- 子块 ≤600 字符，保证 rerank 512 token 上限内

## 图片链路（对齐 data_processing_center）

```
内网返回 images（{文件名: base64 data URL}）
  → 解码保存到 static/images/{文件名}
  → markdown/分块里 images/{文件名} 改写为 http://localhost:8004/static/images/{文件名}
  → 前端 /static/images/{文件名} 直接读取
```

## 配置（config.py 或环境变量）

| 变量 | 默认 | 说明 |
|------|------|------|
| `NEW_MINERU_PORT` | 8004 | 服务端口 |
| `NEW_MINERU_BACKEND` | pipeline | MinerU 后端 |
| `NEW_MINERU_PARSE_METHOD` | auto | 解析方法 |
| `NEW_MINERU_MAX_CHUNK_CHARS` | 600 | 分块最大字符数 |
| `NEW_MINERU_MAX_FILE_MB` | 200 | 文件大小限制 |
