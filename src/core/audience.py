"""大臣求见队列管理：汇总各 agent 求见意愿 → 展示 → 玩家见/不见处理 + 后果。

设计要点（见计划第3节"大臣主动求见"）：
- agent 在执行时输出 want_audience，史官汇总成 audience_queue。
- 开局奏报呈现求见队列（含主题概要，隐藏具体内容以保信息隔离）。
- 玩家选择见或不见：见→进入对话 session；不见→该 agent 忠诚-（小）、可能错过情报/预警。
- 求见主题概要模糊化（"言边事""言财用""有密奏"），保留信息不透明博弈。
"""

from __future__ import annotations

from dataclasses import dataclass

# 拒见的忠诚惩罚（小）
DECLINE_LOYALTY_PENALTY = -3


@dataclass
class AudienceRequest:
    """一条求见请求。"""

    agent_id: str
    agent_name: str
    topic: str  # 模糊主题概要
    urgency: str = "normal"  # high/normal/low

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "topic": self.topic,
            "urgency": self.urgency,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AudienceRequest":
        return cls(
            agent_id=d["agent_id"],
            agent_name=d.get("agent_name", ""),
            topic=d.get("topic", ""),
            urgency=d.get("urgency", "normal"),
        )


@dataclass
class AudienceOutcome:
    """见/不见处理结果。"""

    granted: bool
    agent_id: str
    loyalty_delta: int = 0
    missed_info: bool = False  # 是否错过情报/预警
    message: str = ""


class AudienceQueue:
    """求见队列：管理本回合 agent 求见意愿与玩家处理。"""

    def __init__(self) -> None:
        self._queue: list[AudienceRequest] = []
        self._handled: set[str] = set()  # 已处理的 agent_id

    def add(self, request: AudienceRequest) -> None:
        # 同一 agent 不重复入队
        if any(r.agent_id == request.agent_id for r in self._queue):
            return
        self._queue.append(request)

    def add_from_historian(self, audience_list: list[dict], roster=None) -> None:
        """从史官输出的 audience_queue 汇总（含 agent_name 补全）。"""
        for item in audience_list:
            agent_id = item.get("agent_id")
            name = item.get("agent_name", "")
            if not name and roster is not None:
                inst = roster.get(agent_id)
                if inst:
                    name = inst.persona.name
            self.add(
                AudienceRequest(
                    agent_id=agent_id,
                    agent_name=name,
                    topic=item.get("topic", ""),
                    urgency=item.get("urgency", "normal"),
                )
            )

    def items(self) -> list[AudienceRequest]:
        """开局奏报呈现的求见队列（未处理项）。"""
        return [r for r in self._queue if r.agent_id not in self._handled]

    def grant(self, agent_id: str) -> AudienceOutcome:
        """见：进入对话 session，无惩罚。"""
        self._handled.add(agent_id)
        return AudienceOutcome(
            granted=True,
            agent_id=agent_id,
            loyalty_delta=0,
            missed_info=False,
            message=f"召见 {agent_id}",
        )

    def decline(self, agent_id: str) -> AudienceOutcome:
        """不见：该 agent 忠诚-（小），可能错过其本要提供的情报/预警。

        实际忠诚扣减由上层应用到 AgentInstance.loyalty（返回 loyalty_delta）。
        """
        self._handled.add(agent_id)
        return AudienceOutcome(
            granted=False,
            agent_id=agent_id,
            loyalty_delta=DECLINE_LOYALTY_PENALTY,
            missed_info=True,
            message=f"拒见 {agent_id}，其心或有怨",
        )

    def clear(self) -> None:
        self._queue.clear()
        self._handled.clear()

    def to_dict(self) -> dict:
        return {
            "queue": [r.to_dict() for r in self._queue],
            "handled": list(self._handled),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AudienceQueue":
        q = cls()
        q._queue = [AudienceRequest.from_dict(r) for r in data.get("queue", [])]
        q._handled = set(data.get("handled", []))
        return q
