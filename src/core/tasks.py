"""任务系统：编排解析诏书为任务对象 + 进度跟踪 + 结算。

设计要点（见计划第3节"下诏即派任务"、第4节模块归属）：
- 玩家对话中下诏 → 编排解析为任务对象（目标角色/任务内容/影响数值/期限/成功条件）。
- 任务由目标角色按其能力执行，结果由史官推演 delta 落库。
- 任务可跨回合执行、设期限；完成/失败/逾期有反馈。
"""

from __future__ import annotations

from dataclasses import dataclass, field

# 任务状态
PENDING = "pending"
IN_PROGRESS = "in_progress"
COMPLETED = "completed"
FAILED = "failed"
OVERDUE = "overdue"


@dataclass
class Task:
    """一个下诏派生的任务。"""

    id: str
    target_agent: str  # agent_id
    content: str
    affects: list[str] = field(default_factory=list)  # 影响数值（田赋/国库/军力等）
    deadline_month: int = 0  # 期限（月序，0=不限）
    success_condition: str = ""
    progress: float = 0.0  # 0~1
    status: str = PENDING
    turn_created: int = 0
    turn_completed: int | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "target_agent": self.target_agent,
            "content": self.content,
            "affects": list(self.affects),
            "deadline_month": self.deadline_month,
            "success_condition": self.success_condition,
            "progress": self.progress,
            "status": self.status,
            "turn_created": self.turn_created,
            "turn_completed": self.turn_completed,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Task":
        return cls(
            id=d["id"],
            target_agent=d["target_agent"],
            content=d["content"],
            affects=list(d.get("affects", [])),
            deadline_month=int(d.get("deadline_month", 0)),
            success_condition=d.get("success_condition", ""),
            progress=float(d.get("progress", 0.0)),
            status=d.get("status", PENDING),
            turn_created=int(d.get("turn_created", 0)),
            turn_completed=d.get("turn_completed"),
        )


class TaskSystem:
    """任务集合：创建、更新、逾期检查。"""

    def __init__(self) -> None:
        self.tasks: dict[str, Task] = {}
        self._next_id = 1

    def create(
        self,
        target_agent: str,
        content: str,
        *,
        affects: list[str] | None = None,
        deadline_month: int = 0,
        success_condition: str = "",
        turn: int = 0,
    ) -> Task:
        task = Task(
            id=f"task_{self._next_id}",
            target_agent=target_agent,
            content=content,
            affects=list(affects or []),
            deadline_month=deadline_month,
            success_condition=success_condition,
            turn_created=turn,
        )
        self.tasks[task.id] = task
        self._next_id += 1
        return task

    def update(self, task_id: str, progress: float, turn: int | None = None) -> Task:
        task = self.tasks.get(task_id)
        if task is None:
            raise KeyError(f"未知任务: {task_id}")
        task.progress = max(0.0, min(1.0, float(progress)))
        if task.status == PENDING:
            task.status = IN_PROGRESS
        if task.progress >= 1.0:
            task.status = COMPLETED
            task.turn_completed = turn
        return task

    def complete(self, task_id: str, turn: int) -> Task:
        task = self.tasks.get(task_id)
        if task is None:
            raise KeyError(f"未知任务: {task_id}")
        task.progress = 1.0
        task.status = COMPLETED
        task.turn_completed = turn
        return task

    def fail(self, task_id: str, turn: int) -> Task:
        task = self.tasks.get(task_id)
        if task is None:
            raise KeyError(f"未知任务: {task_id}")
        task.status = FAILED
        task.turn_completed = turn
        return task

    def check_overdue(self, current_month: int) -> list[Task]:
        """检查逾期任务（有期限且未完成且已过期）。返回逾期任务列表并标记。"""
        overdue: list[Task] = []
        for task in self.tasks.values():
            if (
                task.deadline_month
                and task.status in (PENDING, IN_PROGRESS)
                and current_month > task.deadline_month
            ):
                task.status = OVERDUE
                overdue.append(task)
        return overdue

    def by_agent(self, agent_id: str) -> list[Task]:
        return [t for t in self.tasks.values() if t.target_agent == agent_id]

    def active(self) -> list[Task]:
        return [t for t in self.tasks.values() if t.status in (PENDING, IN_PROGRESS)]

    def to_dict(self) -> dict:
        return {
            "tasks": {k: v.to_dict() for k, v in self.tasks.items()},
            "next_id": self._next_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TaskSystem":
        ts = cls()
        ts.tasks = {k: Task.from_dict(v) for k, v in data.get("tasks", {}).items()}
        ts._next_id = int(data.get("next_id", len(ts.tasks) + 1))
        return ts
