"""早朝群聊：在朝 agent 共享公开上下文 + 请奏发言 + agent 间论辩 + 玩家介入下政令。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CourtSpeech:
    """早朝发言记录。"""
    agent_id: str
    speech: str
    to: Optional[str] = None      # 论辩对象
    stance: str = "neutral"       # for | against | neutral


class CourtSession:
    """早朝会话。"""

    def __init__(self):
        self.log: list[CourtSpeech] = []
        self.topic: str = ""
        self.active_speakers: list[str] = []

    def open(self, topic: str, affairs: str,
             premonitions: list[str],
             audience_topics: list[str]) -> str:
        """开场呈上（局势/预兆/求见队列）。"""
        self.topic = topic
        intro = f"【早朝开始】{topic}\n【局势】{affairs}\n"
        if premonitions:
            intro += f"【预兆】{'; '.join(premonitions)}\n"
        if audience_topics:
            intro += f"【求见】{'; '.join(audience_topics)}"
        return intro

    def speak(self, agent_id: str, speech: str,
              to: Optional[str] = None, stance: str = "neutral"):
        """请奏发言。"""
        self.log.append(CourtSpeech(
            agent_id=agent_id, speech=speech,
            to=to, stance=stance,
        ))

    def close(self) -> list[CourtSpeech]:
        """朝会结束，返回发言记录（公开层）。"""
        log = list(self.log)
        self.log.clear()
        self.topic = ""
        return log
