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

## 分块说明

- 按 `# ` 一级标题分章，超长章节按段落切成 ≤600 字符子块
- 保证每块在 rerank 模型 512 token 上限内
- 图片相对路径 `images/xxx.jpg` 保留为纯文本

## 配置（config.py 或环境变量）

| 变量 | 默认 | 说明 |
|------|------|------|
| `NEW_MINERU_PORT` | 8004 | 服务端口 |
| `NEW_MINERU_BACKEND` | pipeline | MinerU 后端 |
| `NEW_MINERU_PARSE_METHOD` | auto | 解析方法 |
| `NEW_MINERU_MAX_CHUNK_CHARS` | 600 | 分块最大字符数 |
| `NEW_MINERU_MAX_FILE_MB` | 200 | 文件大小限制 |
