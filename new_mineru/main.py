"""
new_mineru CLI 测试入口 — 独立解析一个 PDF 并打印 markdown / 分块结果。

用法:
  python main.py <file.pdf> [--chunk] [--output out.md]

示例:
  python main.py C:/path/test.pdf              # 只输出 markdown
  python main.py C:/path/test.pdf --chunk      # 输出 markdown + 分块
  python main.py C:/path/test.pdf -o out.md    # markdown 保存到文件
"""
import argparse
import json
import sys
from pathlib import Path

import config
import parser
import chunker


def main():
    ap = argparse.ArgumentParser(description="new_mineru 独立解析测试")
    ap.add_argument("file", help="PDF/DOCX 文件路径")
    ap.add_argument("--chunk", action="store_true", help="同时输出分块结果")
    ap.add_argument("-o", "--output", help="markdown 保存路径")
    args = ap.parse_args()

    file_path = Path(args.file)
    if not file_path.exists():
        print(f"文件不存在: {file_path}")
        sys.exit(1)

    print(f"解析引擎: {config.PARSE_ENGINE}")
    if config.PARSE_ENGINE != "maas":
        # local 模式才需要加载本地 MinerU 模型
        print(f"加载模型...")
        if not parser.load_model(blocking=True):
            print(f"模型加载失败: {parser.model_status().get('model_error')}")
            sys.exit(1)
        print("模型就绪 [OK]")

    print(f"解析: {file_path.name} ...")
    content = file_path.read_bytes()
    result = parser.parse_pdf(content, file_path.name)
    md = result.get("md_content", "")
    print(f"图片保存: {result.get('images_saved', 0)} 张")
    if not md:
        print("解析结果为空")
        sys.exit(1)

    print(f"\n=== markdown（前 2000 字符）===")
    print(md[:2000])

    if args.output:
        Path(args.output).write_text(md, encoding="utf-8")
        print(f"\nmarkdown 已保存: {args.output}")

    if args.chunk:
        # content_list 优先分块，否则 markdown 兜底
        if result.get("content_list"):
            chunks = chunker.chunk_content_list(result["content_list"], result.get("stem", ""))
            print(f"\n=== 分块结果（content_list 分块，共 {len(chunks)} 块）===")
        else:
            chunks = chunker.chunk_markdown(md, file_path.name)
            print(f"\n=== 分块结果（markdown 分块，共 {len(chunks)} 块）===")
        for c in chunks:
            print(f"\n[{c['chunk_id']}] 标题: {c['title']} | 估算token: {c['token_estimate']}")
            print(f"  内容: {c['content'][:120]}...")
        print(f"\n=== 分块 JSON 预览（前 5 块）===")
        print(json.dumps(chunks[:5], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
