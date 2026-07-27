"""
桥接模块 — 导入 mineru_app 的 state_manager，保持任务状态持久化一致。
mineru_app 和 ragdata_manager 共享同一份 _jobs.json（data_processing_center/output/_jobs.json）。
"""
import sys
from pathlib import Path
from .config import MINERU_APP

# 将 mineru_app 加入 sys.path，以便导入其模块
_MINERU_APP_PATH = str(MINERU_APP)
if _MINERU_APP_PATH not in sys.path:
    sys.path.insert(0, _MINERU_APP_PATH)

from mineru_app.state_manager import (  # noqa: E402, F401
    create_job,
    create_job_with_id,
    update_job,
    get_job,
    list_jobs,
    count_jobs,
    delete_job,
    replace_job_output,
)
