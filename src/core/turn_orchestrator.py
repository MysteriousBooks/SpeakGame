"""编排 agent（Orchestrator）：解析诏书 → 激活子集 → 拜访关系 → 调度。

设计要点（见计划第6节"编排 agent"）：
- 路由层：解析诏书 → 分类 → 分派/处置/识别类型。不推演数值（史官职责）。
- 皇权处置识别（赐死/免职）→ 直接处置，不经死亡危机 resolve。
- 财政划拨识别（内帑→国库允许；国库→内帑拒绝/触发哗然）。
- 任务解析：把诏书解析为任务对象（目标角色/影响数值/期限/成功条件）。
- 早朝流程控制：开场呈上 → 排序请奏 → agent 论辩 → 玩家介入 → 朝会结束。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from src.agents.base_agent import BaseAgent
from src.llm.provider import LLMProvider, Message

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


def _load_orchestrator_prompt() -> str:
    return (_PROMPTS_DIR / "orchestrator.md").read_text(encoding="utf-8")


ORCHESTRATOR_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["execute", "dismiss", "execute_death", "finance_transfer", "court_only", "noop", "appoint"],
        },
        "dispatch_targets": {"type": "array", "items": {"type": "string"}},
        "visits": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "from": {"type": "string"},
                    "to": {"type": "string"},
                    "purpose": {"type": "string"},
                },
            },
        },
        "activation_order": {"type": "array", "items": {"type": "string"}},
        "task": {
            "type": "object",
            "properties": {
                "target_agent": {"type": "string"},
                "content": {"type": "string"},
                "affects": {"type": "array", "items": {"type": "string"}},
                "deadline": {"type": "string"},
                "success_condition": {"type": "string"},
            },
        },
        "finance_action": {
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "enum": [
                        "inner_to_treasury",
                        "treasury_to_inner",
                        "tax_adjust",
                        "expense_adjust",
                        "zonglu_reform",
                    ],
                },
                "amount": {"type": "number"},
                "detail": {"type": "string"},
            },
        },
        "appointments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "person_name": {"type": "string"},
                    "position_name": {"type": "string"},
                    "action": {"type": "string", "enum": ["appoint", "dismiss"]},
                },
                "required": ["person_name", "action"],
            },
        },
        "reason": {"type": "string"},
    },
    "required": ["action", "dispatch_targets"],
}


@dataclass
class OrchestratorPlan:
    """编排解析诏书的分派/处置/财政计划。"""

    action: str = "noop"
    dispatch_targets: list[str] = field(default_factory=list)
    visits: list[dict] = field(default_factory=list)
    activation_order: list[str] = field(default_factory=list)
    task: dict | None = None
    finance_action: dict | None = None
    target: str | None = None  # 处置对象（赐死/免职）
    reason: str = ""
    appointments: list[dict] = field(default_factory=list)

    @property
    def is_dismiss(self) -> bool:
        return self.action == "dismiss"

    @property
    def is_execute_death(self) -> bool:
        return self.action == "execute_death"

    @property
    def is_finance_transfer(self) -> bool:
        return self.action == "finance_transfer"

    @property
    def is_appoint(self) -> bool:
        return self.action == "appoint"

    @classmethod
    def from_dict(cls, d: dict) -> "OrchestratorPlan":
        task = d.get("task")
        fin = d.get("finance_action")
        return cls(
            action=d.get("action", "noop"),
            dispatch_targets=list(d.get("dispatch_targets", [])),
            visits=list(d.get("visits", [])),
            activation_order=list(d.get("activation_order", [])),
            task=task if isinstance(task, dict) and task else None,
            finance_action=fin if isinstance(fin, dict) and fin else None,
            target=d.get("target") or (task.get("target_agent") if isinstance(task, dict) else None),
            reason=d.get("reason", ""),
            appointments=list(d.get("appointments", [])),
        )


class TurnOrchestrator:
    """编排 agent。"""

    def __init__(
        self,
        llm: LLMProvider,
        *,
        config: dict | None = None,
        prompt: str | None = None,
        schema: dict | None = None,
    ) -> None:
        self.llm = llm
        self.config = config or {}
        self.prompt = prompt or _load_orchestrator_prompt()
        self.schema = schema or ORCHESTRATOR_SCHEMA

    def _build_system(
        self,
        era: str,
        available_agents: str,
        situation: str,
    ) -> str:
        return (
            self.prompt.replace("{{era}}", era)
            .replace("{{available_agents}}", available_agents)
            .replace("{{situation}}", situation)
        )

    async def parse_edict(
        self,
        edict: str,
        *,
        turn: int,
        available_agents: list[dict],
        situation: str,
        era: str,
        max_retries: int = 2,
    ) -> OrchestratorPlan:
        """解析诏书为分派/处置/财政计划。available_agents 为 [{id,name,skills,faction}]。"""
        agents_text = "\n".join(
            f"- {a['id']}（{a.get('name', '')}，擅长：{'、'.join(a.get('skills', []))}，派系：{a.get('faction', '')}）"
            for a in available_agents
        ) or "（无可用 agent）"
        system = self._build_system(era, agents_text, situation)
        out = await self.llm.chat_json(
            [Message("user", f"诏书：{edict}\n\n请解析为可执行的 JSON 计划。")],
            schema=self.schema,
            system=system,
            max_retries=max_retries,
        )
        return OrchestratorPlan.from_dict(out)

    @staticmethod
    def select_speaking_agents(plan: OrchestratorPlan, active_agents: list[BaseAgent]) -> list[BaseAgent]:
        """根据 plan.dispatch_targets 从在朝 agent 中选发言子集（事件驱动激活相关子集）。

        未指定 dispatch_targets 时返回全部在朝 agent（默认早朝全员列席）。
        """
        if not plan.dispatch_targets:
            return list(active_agents)
        targets = set(plan.dispatch_targets)
        return [a for a in active_agents if a.id in targets]
