"""事实记忆：结构化条目，按 tag 检索，不压缩、全保留。

设计要点（见计划第2节记忆决策、第5节文件结构）：
- 防关键承诺/事件丢失：所有事实条目永久保留，不衰减、不压缩。
- 按 tag 检索加载相关事实到 agent 提示词。
- 每回合新 session 加载（从存档恢复）。
- 检索模式：any（任一 tag 命中）/ all（全部 tag 命中）。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FactualNote:
    """一条事实记忆条目。"""

    id: int
    content: str
    tags: list[str] = field(default_factory=list)
    turn: int = 0  # 发生回合号
    importance: float = 0.5  # 0~1，可选，用于检索排序

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "content": self.content,
            "tags": list(self.tags),
            "turn": self.turn,
            "importance": self.importance,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FactualNote":
        return cls(
            id=int(data["id"]),
            content=data["content"],
            tags=list(data.get("tags", [])),
            turn=int(data.get("turn", 0)),
            importance=float(data.get("importance", 0.5)),
        )


class FactualMemory:
    """事实记忆库：全保留、按 tag 检索。"""

    def __init__(self) -> None:
        self.notes: list[FactualNote] = []
        self._next_id = 1

    def add(self, content: str, tags: list[str] | None = None, turn: int = 0, importance: float = 0.5) -> int:
        note = FactualNote(
            id=self._next_id,
            content=content,
            tags=list(tags or []),
            turn=turn,
            importance=importance,
        )
        self.notes.append(note)
        self._next_id += 1
        return note.id

    def search(self, tags: list[str] | None = None, match: str = "any") -> list[FactualNote]:
        """按 tag 检索。match='any' 任一命中，'all' 全部命中。无 tags 返回全部。"""
        if not tags:
            return list(self.notes)
        if match == "all":
            return [n for n in self.notes if all(t in n.tags for t in tags)]
        # any
        return [n for n in self.notes if any(t in n.tags for t in tags)]

    def search_text(self, keyword: str) -> list[FactualNote]:
        """关键词检索（内容包含）。"""
        return [n for n in self.notes if keyword in n.content]

    def get(self, note_id: int) -> FactualNote | None:
        for n in self.notes:
            if n.id == note_id:
                return n
        return None

    def all(self) -> list[FactualNote]:
        return list(self.notes)

    def to_dict(self) -> dict:
        return {
            "notes": [n.to_dict() for n in self.notes],
            "next_id": self._next_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FactualMemory":
        mem = cls()
        mem.notes = [FactualNote.from_dict(n) for n in data.get("notes", [])]
        mem._next_id = int(data.get("next_id", len(mem.notes) + 1))
        return mem
