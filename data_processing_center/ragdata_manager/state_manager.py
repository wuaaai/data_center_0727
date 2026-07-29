"""
桥接模块 — 导入 mineru_core 的 state_manager，保持任务状态持久化一致。
mineru_core/web_app/state_manager.py 是唯一的 state_manager 数据源。
"""
import sys
from pathlib import Path
from .config import MINERU_APP

# 将 mineru_app 和 mineru_core 加入 sys.path
_MINERU_APP_PATH = str(MINERU_APP)
if _MINERU_APP_PATH not in sys.path:
    sys.path.insert(0, _MINERU_APP_PATH)

# 从 mineru_core/web_app/state_manager 导入（create_job_with_id 和 count_jobs 在这里）
_MINERU_CORE_PATH = str(Path(__file__).resolve().parent.parent / "mineru_core")
if _MINERU_CORE_PATH not in sys.path:
    sys.path.insert(0, _MINERU_CORE_PATH)

from web_app.state_manager import (  # noqa: E402, F401
    create_job,
    create_job_with_id,
    update_job,
    get_job,
    list_jobs,
    count_jobs,
    delete_job,
    replace_job_output,
)
