"""
模型管理器 — 单例模式，管理 MinerU 模型生命周期和解析任务队列。

模型只加载一次，所有解析任务复用已加载的模型。
"""
import os
import sys
import threading
import time
import uuid
from pathlib import Path
from queue import Queue
from concurrent.futures import ThreadPoolExecutor, Future
from dataclasses import dataclass, field

# 确保项目根在 path 中，model_manager 从 mineru_core/ 加载核心代码
_PROJECT_ROOT = Path(__file__).resolve().parent.parent  # data_processing_center/
_MINERU_CORE = _PROJECT_ROOT / "mineru_core"
if str(_MINERU_CORE) not in sys.path:
    sys.path.insert(0, str(_MINERU_CORE))
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


@dataclass
class ParseTask:
    task_id: str
    file_path: Path
    output_dir: Path
    status: str = "queued"
    progress: str = "等待处理..."
    progress_pct: int = 0
    result_path: str = None
    chunk_count: int = 0
    preview_text: str = None
    error: str = None
    elapsed: float = 0
    created_at: float = field(default_factory=time.time)


class ModelManager:
    """全局单例，管理 MinerU 模型加载与解析任务。"""

    _instance: 'ModelManager | None' = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        self._model_loaded = False
        self._model_loading = False
        self._model_error = None
        self._start_time = None
        self._tasks: dict[str, ParseTask] = {}
        self._task_queue = Queue()
        self._executor = None
        self._running = False
        self._active_count = 0
        self._total_processed = 0
        self._total_failed = 0
        self._max_workers = int(os.getenv("MINERU_WORKERS", "2"))

    def start(self, warmup: bool = True):
        """启动任务处理循环，可选预热模型。"""
        self._running = True
        self._start_time = time.time()
        self._executor = ThreadPoolExecutor(max_workers=self._max_workers)
        # 启动任务处理器
        threading.Thread(target=self._process_loop, daemon=True).start()
        # 异步预热模型
        if warmup:
            threading.Thread(target=self._warmup_model, daemon=True).start()

    def _warmup_model(self):
        """预热：加载 MinerU 模型到内存（仅触发 lazy-load 初始化，不处理完整文档）。"""
        self._model_loading = True
        try:
            os.environ["MINERU_TOOLS_CONFIG_JSON"] = str(_MINERU_CORE / "mineru.json")
            os.environ["MINERU_MODEL_SOURCE"] = "local"
            from mineru.backend.pipeline.model_init import (
                HybridModelSingleton,
            )
            model = HybridModelSingleton()
            model.get_model()
            self._model_loaded = True
        except Exception as e:
            self._model_error = str(e)
        finally:
            self._model_loading = False

    def _process_loop(self):
        """后台循环：从队列取任务，在线程池中执行。"""
        while self._running:
            try:
                task = self._task_queue.get(timeout=1)
                if task is None:
                    break
                self._active_count += 1
                def _wrapped_execute(t):
                    # Bug 38: 取出队列后、执行前检查是否已被取消
                    if t.status == "cancelled" or getattr(t, "_cancel_flag", False):
                        return
                    try:
                        self._execute_task(t)
                    finally:
                        self._active_count -= 1
                self._executor.submit(_wrapped_execute, task)
            except Exception:
                continue

    def _execute_task(self, task: ParseTask):
        """执行单个解析任务，实时更新中文进度。

        进度文本前缀：MinerU 使用 "[环节 X/4]" 标识 4 个处理阶段。
        dcp 侧使用 "[准备中]" 标识其排队/提交阶段，两者不重叠。
        """
        import re, io as _io

        # ---- 环节定义：MinerU 流水线 4 个阶段 ----
        # 每个阶段匹配的日志关键词（包含 pipeline.py loguru 输出的中文日志）
        _S = [
            ("提交任务", "正在发送文档，准备分析...", [
                "提交", "排队",
            ]),
            ("解析文档", "正在逐页识别文字与表格...", [
                "Layout Predict", "OCR-det", "OCR-rec", "MFR Predict",
                "Seal Predict", "Table-ocr", "Table-wired", "Table-wireless",
                "PDF 解析中", "PDF 解析完成",
                "快路径解析", "快解析",   # Bug 30: 快路径日志匹配
            ]),
            ("整理结果", "正在按章节整理文档结构...", [
                "加载内容", "文本分块", "段落生成",
                "加载内容列表", "文本分块完成", "段落生成完成",
                "干净段落生成", "分块完成",   # Bug 30: 补充遗漏的关键词
            ]),
            ("生成文档", "正在生成可下载 Word 文件...", [
                "生成 DOCX", "Processing pages",
                "DOCX 生成", "DOCX 生成完成",
            ]),
        ]

        # 阶段 → 对应的 progress_pct 范围起始值
        # 阶段 0: 0-24, 阶段 1: 25-74, 阶段 2: 75-89, 阶段 3: 90-99
        _STAGE_PCT_BASE = [0, 25, 75, 90]

        _current_stage_idx = [0]  # 环节索引，只在 _on_log/stderr 中单调递增写入 (Bug 22: 单一声明)

        # Bug 38: 取消检查点 — 在提交给 pipeline 前检查是否已被取消
        if getattr(task, "_cancel_flag", False) or task.status == "cancelled":
            if task.status != "cancelled":
                task.status = "cancelled"
            task.progress = "已取消"
            return

        # 启动时进度
        task.progress = "[环节 1/4] 提交任务：正在发送文档，准备分析..."
        task.progress_pct = 0
        task.status = "processing"

        def _match_stage(text: str) -> int | None:
            """根据日志文本匹配当前环节，返回环节索引或 None。"""
            for i, (_name, _desc, keywords) in enumerate(_S):
                for kw in keywords:
                    if kw in text:
                        return i
            return None

        def _set(detail: str, stage_idx: int, pct: int = 0):
            """设置环节文本和 progress_pct（仅在阶段切换时调用，始终前进）。"""
            name = _S[stage_idx][0]
            task.progress = f"[环节 {stage_idx + 1}/{len(_S)}] {name}：{detail}"
            task.progress_pct = max(pct, _STAGE_PCT_BASE[stage_idx])

        # ---- tqdm 英文描述 → 中文 ----
        _TQDM_CN = {
            "Layout Predict": "版面检测",
            "OCR-det ch": "OCR文字检测",
            "OCR-rec Predict": "OCR文字识别",
            "MFR Predict": "公式识别",
            "Table-ocr det": "表格OCR检测",
            "Table-wireless Predict": "无线表格识别",
            "Table-wired Predict": "有线表格识别",
            "Seal Predict": "印章检测",
            "Processing pages": "页面合成",
        }

        # tqdm 输出正则
        _tqdm_pattern = re.compile(
            r'^\s*(.+?):\s+(\d{1,3})%\s*\|.*?\|\s*(\d+)/(\d+)\s*\['
        )

        # ---- stderr 拦截器：线程局部替换，避免多任务互相干扰 (Bug 31) ----
        _real_stderr = sys.stderr

        class _ProgressStderr(_io.StringIO):
            """每任务独立的 stderr 拦截器，捕获 tqdm 进度条。"""

            def write(self, s):
                _real_stderr.write(s)  # 保留原始输出到终端
                for line in s.splitlines():
                    m = _tqdm_pattern.match(line)
                    if m:
                        desc_en, pct_str, cur, total = m.group(1), m.group(2), m.group(3), m.group(4)
                        cn = _TQDM_CN.get(desc_en.strip(), desc_en.strip())
                        si2 = _match_stage(desc_en.strip())
                        if si2 is not None and si2 > _current_stage_idx[0]:
                            _current_stage_idx[0] = si2
                        # ★ 用 tqdm 描述精确匹配的阶段号，而非全局 _current_stage_idx。
                        # "版面检测"=阶段2，"页面合成"=阶段4 —— 标签必须与任务对齐。
                        si = si2 if si2 is not None else _current_stage_idx[0]
                        name = _S[si][0]
                        task.progress = f"[环节 {si + 1}/{len(_S)}] {name}：{cn} {pct_str}% ({cur}/{total})"
                        task.progress_pct = max(int(pct_str), _STAGE_PCT_BASE[si])
                return len(s)

            def flush(self):
                _real_stderr.flush()

        # ---- loguru handler：从 pipeline.py 日志匹配阶段推进 ----
        try:
            from loguru import logger

            def _on_log(msg):
                text = str(msg).strip()
                if not text:
                    return
                si = _match_stage(text)
                if si is not None and si > _current_stage_idx[0]:
                    _current_stage_idx[0] = si
                    _set(_S[si][1], si)

            hid = logger.add(_on_log, level="INFO", format="{message}")
            try:
                # Bug 31 修复: 捕获完 tqdm 后恢复到原始 _real_stderr，
                # 避免保存 → 恢复链在 max_workers>1 时形成脏链
                sys.stderr = _ProgressStderr()
                try:
                    from pipeline import process_single_file

                    t0 = time.perf_counter()
                    result_path = process_single_file(
                        file_path=task.file_path,
                        output_dir=task.output_dir,
                    )
                    task.elapsed = time.perf_counter() - t0
                finally:
                    sys.stderr = _real_stderr  # 始终恢复到终端，而非另一个线程的拦截器
            finally:
                logger.remove(hid)

            task.result_path = str(result_path) if result_path else None
            # 统计 <-split-> 标记作为 chunk_count
            if result_path:
                try:
                    from docx import Document as DocxDocument
                    doc = DocxDocument(str(result_path))
                    count = sum(1 for p in doc.paragraphs if "<-split->" in p.text)
                    task.chunk_count = max(count, 1)
                except Exception:
                    task.chunk_count = 0
            # ★ 写入顺序必须 progress → progress_pct → status
            task.progress = "处理完成"
            task.progress_pct = 100
            task.status = "completed"          # ★ 最后写入
            self._total_processed += 1
        except Exception as e:
            task.progress = f"处理失败：{e}"
            task.error = str(e)
            task.status = "failed"             # ★ 最后写入
            self._total_failed += 1

    def _on_task_done(self, task: ParseTask, future: Future):
        self._active_count -= 1

    def submit(self, file_path: Path, output_dir: Path) -> str:
        """提交解析任务，返回 task_id。"""
        task_id = uuid.uuid4().hex[:12]
        task = ParseTask(task_id=task_id, file_path=Path(file_path), output_dir=Path(output_dir))
        with self._lock:
            self._tasks[task_id] = task
        self._task_queue.put(task)
        return task_id

    def cancel_task(self, task_id: str) -> bool:
        """取消任务。排队中的直接取消，处理中的标记取消（线程在检查点自行退出）。"""
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return False
            if task.status == "queued":
                task.status = "cancelled"
                task.progress = "已取消"
                # 不设置 _cancel_flag — _wrapped_execute 检查 status=="cancelled" 即可
                return True
            # Bug 38: 设置取消标记，_execute_task 在 process_single_file 前检查并提前退出
            if task.status in ("processing",):
                task._cancel_flag = True
                task.status = "cancelling"
                task.progress = "正在取消..."
                return True
            return False

    def get_task(self, task_id: str) -> ParseTask | None:
        with self._lock:
            return self._tasks.get(task_id)

    def get_status(self) -> dict:
        return {
            "model_loaded": self._model_loaded,
            "model_loading": self._model_loading,
            "model_error": self._model_error,
            "uptime": time.time() - self._start_time if self._start_time else 0,
            "active_count": self._active_count,
            "queue_size": self._task_queue.qsize(),
            "total_processed": self._total_processed,
            "total_failed": self._total_failed,
            "max_workers": self._max_workers,
        }

    def shutdown(self):
        """优雅关闭。"""
        self._running = False
        self._task_queue.put(None)
        if self._executor:
            self._executor.shutdown(wait=False)


# 全局单例
model_manager = ModelManager()
