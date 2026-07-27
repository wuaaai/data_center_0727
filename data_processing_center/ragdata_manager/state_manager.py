"""
桥接模块 — 导入 mineru_0720 的 state_manager，保持任务状态持久化一致。
"""
from .config import MINERU_BASE
import sys
sys.path.insert(0, str(MINERU_BASE))

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
