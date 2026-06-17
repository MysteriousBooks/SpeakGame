"""任务系统：编排解析诏书为任务对象 + 进度跟踪 + 结算。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Task:
    task_id: str
    target_agent: str
    task: str
    affects: list[str] = field(default_factory=list)
    deadline: str = ""
    success_condition: str = ""
    status: str = "pending"  # pending | in_progress | done | failed | overdue
    progress: float = 0.0


class TaskManager:
    """任务管理。"""

    def __init__(self):
        self.tasks: dict[str, Task] = {}
        self._next_id = 0

    def create(self, target: str, task_desc: str, affects: list[str],
               deadline: str = "", success_cond: str = "") -> Task:
        t = Task(
            task_id=f"task_{self._next_id}",
            target_agent=target,
            task=task_desc,
            affects=affects,
            deadline=deadline,
            success_condition=success_cond,
        )
        self._next_id += 1
        self.tasks[t.task_id] = t
        return t

    def update_progress(self, task_id: str, delta: float):
        t = self.tasks.get(task_id)
        if not t:
            return
        t.progress = min(1.0, max(0.0, t.progress + delta))
        if t.progress >= 1.0:
            t.status = "done"

    def get_active(self) -> list[Task]:
        return [
            t for t in self.tasks.values()
            if t.status in ("pending", "in_progress")
        ]


def parse_edict_to_task(
    edict: str,
    target: str,
    task_mgr: TaskManager,
) -> Optional[Task]:
    """编排将诏书解析为任务对象（mock 版本，真实版本调 LLM）。"""
    # mock：识别关键字
    if "欠赋" in edict or "田赋" in edict:
        return task_mgr.create(
            target=target, task_desc="清查欠赋",
            affects=["田赋", "国库"], deadline="崇祯1年6月",
        )
    if "京营" in edict or "军" in edict:
        return task_mgr.create(
            target=target, task_desc="整饬京营",
            affects=["军力", "军心", "国库"],
        )
    return task_mgr.create(
        target=target, task_desc=edict[:30], affects=[],
    )
