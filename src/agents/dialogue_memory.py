from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DialogueEntry:
    """单轮对话记录。"""
    role: str  # "player" | "agent"
    content: str
    turn: int

    def to_dict(self) -> dict:
        return {"role": self.role, "content": self.content, "turn": self.turn}

    @classmethod
    def from_dict(cls, d: dict) -> DialogueEntry:
        return cls(role=d["role"], content=d["content"], turn=int(d.get("turn", 0)))


@dataclass
class DialogueMemory:
    """Agent 的对话记忆：压缩摘要 + 当前回合原始记录。"""
    compressed_summary: str = ""
    exchanges: list[DialogueEntry] = field(default_factory=list)

    def add_exchange(self, role: str, content: str, turn: int) -> None:
        self.exchanges.append(DialogueEntry(role=role, content=content, turn=turn))

    def clear_exchanges(self) -> None:
        self.exchanges.clear()

    def to_dict(self) -> dict:
        return {
            "compressed_summary": self.compressed_summary,
            "exchanges": [e.to_dict() for e in self.exchanges],
        }

    @classmethod
    def from_dict(cls, d: dict) -> DialogueMemory:
        return cls(
            compressed_summary=d.get("compressed_summary", ""),
            exchanges=[DialogueEntry.from_dict(e) for e in d.get("exchanges", [])],
        )
