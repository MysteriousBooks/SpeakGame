"""事实记忆：结构化条目，按 tag 检索，不压缩，全保留。

每回合 agent 加载相关事实记忆（按 tag 过滤），确保关键承诺/事件不因压缩丢失。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


@dataclass
class FactualNote:
    note_id: str
    agent_id: str
    content: str
    tags: list[str] = field(default_factory=list)
    importance: int = 1  # 1-5
    timestamp: str = ""


class FactualMemory:
    """事实记忆存储。"""

    def __init__(self, path: Optional[Path] = None):
        self.notes: list[FactualNote] = []
        self._path = path

    def add(self, note: FactualNote):
        self.notes.append(note)

    def query_by_tags(self, tags: list[str]) -> list[FactualNote]:
        """按 tag 检索（OR 逻辑）。"""
        if not tags:
            return list(self.notes)
        tag_set = set(tags)
        return [
            n
            for n in self.notes
            if tag_set.intersection(set(n.tags))
        ]

    def query_by_agent(self, agent_id: str) -> list[FactualNote]:
        return [n for n in self.notes if n.agent_id == agent_id]

    def save(self, path: Optional[Path] = None):
        p = path or self._path
        if p:
            p.parent.mkdir(parents=True, exist_ok=True)
            data = [asdict(n) for n in self.notes]
            p.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    def load(self, path: Optional[Path] = None):
        p = path or self._path
        if p and p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            self.notes = [FactualNote(**d) for d in data]
