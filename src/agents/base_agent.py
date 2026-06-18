"""Agent 基类：人格卡加载 + 两层记忆 + 公开/私密层 + 拜访 + 求见意愿产出。

设计要点（见计划第4节"信息可见性模型"、第6节"agent 通用"）：
- 信息隔离硬约束：只看公开层，私密层不公开，不预知自己未来命运。
- 元信息隔离：死因/正反派是系统元数据，不注入 agent 提示词（to_prompt_card 不输出）。
- 输出 JSON：{public, private, want_audience, audience_topic}。
- 拜访接口：接收对方 public 层作为输入，产出自己的 public/private。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from src.llm.provider import LLMProvider, Message
from src.memory.factual_memory import FactualMemory
from src.memory.narrative_memory import NarrativeMemory

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
_PERSONAS_DIR = Path(__file__).resolve().parent / "personas"

AGENT_OUTPUT_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "public": {"type": "string", "description": "公开层：朝堂表态/请奏/执行结果，他人可见"},
        "private": {"type": "string", "description": "私密层：内心真实想法，仅自己与皇帝密奏可见"},
        "want_audience": {"type": "boolean", "description": "是否请求拜见皇帝"},
        "audience_topic": {"type": "string", "description": "求见主题概要，模糊化以保信息隔离"},
    },
    "required": ["public", "private", "want_audience"],
}


@dataclass
class PersonaCard:
    """角色卡（含系统元数据，但 to_prompt_card 不输出元信息）。"""

    id: str = ""
    name: str = ""
    courtesy: str = ""
    faction: str = ""
    skills: list[str] = field(default_factory=list)
    personality: str = ""
    relations: dict = field(default_factory=dict)
    # 系统元数据（不注入 agent 提示词）
    historical_alignment: str = ""
    born_year: int = 0
    historical_death_year: int = 9999
    death_cause: dict = field(default_factory=dict)
    recruitment_condition: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "PersonaCard":
        return cls(
            id=d["id"],
            name=d["name"],
            courtesy=d.get("courtesy", ""),
            faction=d.get("faction", ""),
            skills=list(d.get("skills", [])),
            personality=d.get("personality", ""),
            relations=dict(d.get("relations", {})),
            historical_alignment=d.get("historical_alignment", ""),
            born_year=int(d.get("born_year", 0)),
            historical_death_year=int(d.get("historical_death_year", 9999)),
            death_cause=dict(d.get("death_cause", {})),
            recruitment_condition=d.get("recruitment_condition", ""),
        )

    def to_prompt_card(self) -> str:
        """输出给 agent 的人格卡片段（元信息隔离：不含死因/正反派）。"""
        lines = [
            f"姓名：{self.name}" + (f"（字 {self.courtesy}）" if self.courtesy else ""),
            f"派系：{self.faction}",
            f"擅长：{'、'.join(self.skills) if self.skills else '无'}",
            f"性格：{self.personality}",
            f"关系网：{self._fmt_relations()}",
        ]
        return "\n".join(lines)

    def _fmt_relations(self) -> str:
        if not self.relations:
            return "无"
        return "；".join(f"{k}：{v}" for k, v in self.relations.items())

    def is_alive_in(self, year: int) -> bool:
        """当前游戏年份是否在世（用于招募池过滤）。"""
        return self.born_year <= year < self.historical_death_year


@dataclass
class AgentOutput:
    """agent 单次输出（公开层 + 私密层 + 求见意愿）。"""

    public: str = ""
    private: str = ""
    want_audience: bool = False
    audience_topic: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "AgentOutput":
        return cls(
            public=str(d.get("public", "")),
            private=str(d.get("private", "")),
            want_audience=bool(d.get("want_audience", False)),
            audience_topic=str(d.get("audience_topic", "")),
        )


def load_agent_base_prompt(filename: str = "agent_base.md") -> str:
    """加载 agent 通用 system prompt。"""
    return (_PROMPTS_DIR / filename).read_text(encoding="utf-8")


def load_persona(filename: str) -> PersonaCard:
    """加载单个角色卡 YAML（如 minister_finance.yaml）。"""
    with open(_PERSONAS_DIR / filename, encoding="utf-8") as f:
        return PersonaCard.from_dict(yaml.safe_load(f))


def load_historical_figures(filename: str = "historical_figures.yaml") -> list[PersonaCard]:
    """加载历史角色库（figures 列表）。"""
    with open(_PERSONAS_DIR / filename, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return [PersonaCard.from_dict(d) for d in data.get("figures", [])]


class BaseAgent:
    """角色 agent：人格卡 + 两层记忆 + 信息隔离 + 公开/私密层输出。"""

    def __init__(
        self,
        persona: PersonaCard,
        factual: FactualMemory,
        narrative: NarrativeMemory,
        llm: LLMProvider,
        *,
        agent_base_prompt: str | None = None,
        era: str = "崇祯1年1月",
    ) -> None:
        self.persona = persona
        self.factual = factual
        self.narrative = narrative
        self.llm = llm
        self.agent_base_prompt = agent_base_prompt or load_agent_base_prompt()
        self.era = era

    @property
    def id(self) -> str:
        return self.persona.id

    @property
    def name(self) -> str:
        return self.persona.name

    def _build_system(self, scene: str, tags: list[str] | None = None) -> str:
        factual_notes = self.factual.search(tags)
        factual_text = "\n".join(f"- {n.content}" for n in factual_notes) or "（无相关条目）"
        narrative_text = self.narrative.summary() or "（无）"
        prompt = self.agent_base_prompt
        prompt = (
            prompt.replace("{{era}}", self.era)
            .replace("{{persona_card}}", self.persona.to_prompt_card())
            .replace("{{factual_memory}}", factual_text)
            .replace("{{narrative_memory}}", narrative_text)
            .replace("{{scene}}", scene)
        )
        return prompt

    async def respond(
        self,
        scene: str,
        user_msg: str,
        *,
        tags: list[str] | None = None,
    ) -> AgentOutput:
        """对场景与用户消息作出回应，产出公开/私密层 + 求见意愿。"""
        system = self._build_system(scene, tags)
        out = await self.llm.chat_json(
            [Message("user", user_msg)], schema=AGENT_OUTPUT_SCHEMA, system=system
        )
        return AgentOutput.from_dict(out)

    async def visit(self, other_public: str, *, tags: list[str] | None = None) -> AgentOutput:
        """拜访：接收对方公开层，产出自己的公开/私密层。"""
        scene = (
            "你正在拜访/接触他人。对方的公开表态如下（你只能看到这些公开信息）：\n"
            f"{other_public}\n\n请基于此作出你的回应。"
        )
        return await self.respond(scene, "请产出你的公开层回应与私密层想法。", tags=tags)

    def add_factual(self, content: str, tags: list[str], turn: int) -> int:
        """记录一条事实记忆。"""
        return self.factual.add(content, tags=tags, turn=turn)
