"""叙事记忆：压缩、持久化到文件、每回合加载。

设计要点（见计划第2节记忆决策）：
- 叙事记忆是已压缩的回合叙事摘要（由史官 LLM 产出），本模块只负责存取与持久化。
- 每回合新 session 加载，提供 agent 上下文的"压缩历史"。
- 与事实记忆互补：事实不压缩全保留（防承诺丢失），叙事压缩给上下文（控 token）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass
class NarrativeEntry:
    """一条叙事记忆（一段已压缩的叙事摘要）。"""

    turn: int
    text: str

    def to_dict(self) -> dict:
        return {"turn": self.turn, "text": self.text}

    @classmethod
    def from_dict(cls, data: dict) -> "NarrativeEntry":
        return cls(turn=int(data["turn"]), text=data["text"])


class NarrativeMemory:
    """叙事记忆库：按回合追加压缩叙事，持久化到 JSON 文件。"""

    def __init__(self) -> None:
        self.entries: list[NarrativeEntry] = []

    def append(self, turn: int, text: str) -> None:
        """追加一回合的压缩叙事。"""
        self.entries.append(NarrativeEntry(turn=turn, text=text))

    def summary(self, max_turns: int | None = None) -> str:
        """拼接最近 max_turns 回合的叙事为一段文本。无则返回空串。"""
        items = self.entries[-max_turns:] if max_turns else self.entries
        return "\n".join(f"【第{e.turn}回合】{e.text}" for e in items)

    def all(self) -> list[NarrativeEntry]:
        return list(self.entries)

    def to_dict(self) -> dict:
        return {"entries": [e.to_dict() for e in self.entries]}

    @classmethod
    def from_dict(cls, data: dict) -> "NarrativeMemory":
        mem = cls()
        mem.entries = [NarrativeEntry.from_dict(e) for e in data.get("entries", [])]
        return mem

    def save(self, path: str) -> None:
        """持久化到 JSON 文件。"""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, path: str) -> "NarrativeMemory":
        """从 JSON 文件加载（每回合新 session 调用）。"""
        try:
            with open(path, encoding="utf-8") as f:
                return cls.from_dict(json.load(f))
        except FileNotFoundError:
            return cls()
