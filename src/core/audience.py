"""大臣求见队列管理：汇总各 agent want_audience + 玩家见/不见处理 + 不见后果。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AudienceRequest:
    agent_id: str
    topic: str          # 模糊主题，如"言边事"
    urgency: str = "normal"  # high | normal | low


class AudienceQueue:
    """求见队列。"""

    def __init__(self):
        self.requests: list[AudienceRequest] = []

    def build_from_agent_outputs(self, agent_outputs: list[dict]) -> list[AudienceRequest]:
        """从各 agent 的输出 JSON 中汇总 want_audience。"""
        self.requests = []
        for output in agent_outputs:
            if isinstance(output, dict) and output.get("want_audience"):
                self.requests.append(AudienceRequest(
                    agent_id=output.get("agent_id", ""),
                    topic=output.get("audience_topic", "有本奏"),
                    urgency="normal",
                ))
        return self.requests

    def grant(self, req: AudienceRequest) -> dict:
        """同意求见：返回空（后续进入一对一对话 session）。"""
        self.requests.remove(req)
        return {"action": "grant", "agent": req.agent_id}

    def deny(self, req: AudienceRequest) -> dict:
        """拒绝求见：agent 忠诚-、错过情报。"""
        self.requests.remove(req)
        return {"action": "deny", "agent": req.agent_id,
                "loyalty_change": -5, "missed_info": True}
