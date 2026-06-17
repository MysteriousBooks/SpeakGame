"""叙事记忆：压缩的自然语言印象，持久化到文件，每回合加载。

每回合 agent 加载压缩后的叙事记忆（主观印象），与事实记忆互补。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


@dataclass
class NarrativeMemory:
    """单个 agent 的压缩叙事记忆。"""

    agent_id: str
    summary: str = ""  # 压缩后的主观印象
    updated_at: str = ""


class NarrativeStore:
    """叙事记忆存储（每 agent 一个文件）。"""

    def __init__(self, base_path: Path):
        self.base_path = base_path
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _path_for(self, agent_id: str) -> Path:
        return self.base_path / f"{agent_id}_narrative.json"

    def save(self, memory: NarrativeMemory):
        p = self._path_for(memory.agent_id)
        p.write_text(
            json.dumps(asdict(memory), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def load(self, agent_id: str) -> NarrativeMemory:
        p = self._path_for(agent_id)
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            return NarrativeMemory(**data)
        return NarrativeMemory(agent_id=agent_id)

    def compress(self, agent_id: str, new_summary: str):
        """压缩更新叙事记忆。"""
        mem = self.load(agent_id)
        mem.summary = new_summary
        mem.updated_at = "回合N"  # 实际应传回合号
        self.save(mem)
