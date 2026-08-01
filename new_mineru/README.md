# new_mineru — 独立 MinerU 文档解析服务

PDF 进 → MinerU 解析 → markdown（可选分块）。模仿内网 Maas 接口模式，独立运行，方便查看和调试。

## 环境

- Python: 复用 `mineru_0720/.venv`（已装 mineru 3.2.3 + 全部依赖）
- 模型: `E:/Develop_docu/sql_0722_center/modelscope/models/OpenDataLab/PDF-Extract-Kit-1___0`（已在 mineru.json 配置）

## 启动服务（端口 8004）

```bash
cd E:\Develop_docu\sql_0722_center\new_mineru
..\mineru_0720\.venv\Scripts\python.exe server.py
```

启动后模型后台预热（约 80 秒），访问 `http://localhost:8004` 打开测试前端页面。

## 接口

| 接口 | 说明 |
|------|------|
| `GET /` | 前端页面（选文件解析 + 历史文件查看） |
| `POST /file_parse` | PDF → markdown（同步返回） |
| `POST /file_parse/chunk` | PDF → markdown + 分块 |
| `GET /parse_history` | 历史解析文件列表 |
| `GET /parse_history/{id}` | 某个历史文件的 markdown/分块详情 |
| `GET /health` | 健康检查（模型加载状态） |
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

## 分块说明（父子召回策略）

- **统一对 MinerU 输出的 markdown 文本分块**（不依赖 content_list，内网只有 markdown 也适用）
- 按 `# ` 一级标题分章节 = **父块**（recall_context，召回时的完整上下文）
- 章节内按段落切 **子块**（content，向量 embedding 用）
- 每个子块输出：`{chunk_id, parent_id, title, content, recall_context, token_estimate}`
- 子块 ≤600 字符，保证 rerank 512 token 上限内

父子召回：检索命中子块（精确），返回父块完整内容（上下文），与 data_processing_center 入库逻辑一致。

## 配置（config.py 或环境变量）

| 变量 | 默认 | 说明 |
|------|------|------|
| `NEW_MINERU_PORT` | 8004 | 服务端口 |
| `NEW_MINERU_BACKEND` | pipeline | MinerU 后端 |
| `NEW_MINERU_PARSE_METHOD` | auto | 解析方法 |
| `NEW_MINERU_MAX_CHUNK_CHARS` | 600 | 分块最大字符数 |
| `NEW_MINERU_MAX_FILE_MB` | 200 | 文件大小限制 |
