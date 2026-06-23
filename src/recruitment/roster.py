"""角色注册表：按当前年份过滤在世可招募 + 角色状态机 + 难度可见性。

设计要点（见计划第3节"招募系统""角色状态机""难度等级"）：
- 状态机：available（在野可招募）→ active（在朝任官，是 agent）
         ↻ dismissed（免职在野，可重新启用）/ dead（已故）。
- 按当前游戏年份过滤在世角色（born_year <= 当前年 < historical_death_year，且未招募/已死）。
- 难度等级控制招募界面信息可见性（easy 显示正反派/擅长/死因；normal 仅擅长；hard 零剧透）。
- dismissed 复用带历史记忆与怨气；dead 角色移除 agent。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.agents.base_agent import BaseAgent, PersonaCard, load_historical_figures
from src.agents.dialogue_memory import DialogueMemory
from src.llm.provider import LLMProvider
from src.memory.factual_memory import FactualMemory
from src.memory.narrative_memory import NarrativeMemory

# 角色状态
AVAILABLE = "available"
ACTIVE = "active"
DISMISSED = "dismissed"
DEAD = "dead"

VALID_STATUSES = {AVAILABLE, ACTIVE, DISMISSED, DEAD}


@dataclass
class AgentInstance:
    """一个角色实例：人格卡 + 状态 + 两层记忆（状态机各态均保留记忆）+ per-agent 属性。"""

    persona: PersonaCard
    status: str = AVAILABLE
    factual: FactualMemory = field(default_factory=FactualMemory)
    narrative: NarrativeMemory = field(default_factory=NarrativeMemory)
    agent: BaseAgent | None = None  # active 时持有可对话 agent
    # per-agent 属性（非全局数值，存角色状态）
    loyalty: int = 70  # 官员忠诚 0~100
    dissatisfaction: int = 0  # 不满 0~100
    safety: int = 50  # 安全度 0~100（死亡危机 resolve_conditions 用）
    dialogue_memory: DialogueMemory = field(default_factory=DialogueMemory)

    def to_dict(self) -> dict:
        return {
            "persona_id": self.persona.id,
            "status": self.status,
            "factual": self.factual.to_dict(),
            "narrative": self.narrative.to_dict(),
            "loyalty": self.loyalty,
            "dissatisfaction": self.dissatisfaction,
            "safety": self.safety,
            "dialogue_memory": self.dialogue_memory.to_dict(),
        }


def recruit_display(persona: PersonaCard, difficulty: str) -> dict:
    """按难度等级返回招募界面可见信息（hard 零剧透）。"""
    info: dict = {"id": persona.id, "name": persona.name}
    if persona.recruitment_condition:
        info["recruitment_condition"] = persona.recruitment_condition
    if difficulty == "easy":
        info["historical_alignment"] = persona.historical_alignment
        info["skills"] = list(persona.skills)
        info["death_cause"] = dict(persona.death_cause)
    elif difficulty == "normal":
        info["skills"] = list(persona.skills)
    # hard: 仅 id/name/condition
    return info


class Roster:
    """角色注册表：管理所有角色（历史 + 虚构）的状态机与记忆。"""

    def __init__(
        self,
        config: dict,
        *,
        historical_figures: list[PersonaCard] | None = None,
    ) -> None:
        self.config = config
        self.instances: dict[str, AgentInstance] = {}
        figures = historical_figures if historical_figures is not None else load_historical_figures()
        for persona in figures:
            self.instances[persona.id] = AgentInstance(persona=persona, status=AVAILABLE)

    @property
    def difficulty(self) -> str:
        return self.config.get("game", {}).get("difficulty", "normal")

    # ---------- 查询 ----------
    def available_for_recruit(self, game_year: int) -> list[PersonaCard]:
        """按当前游戏年份（崇祯纪年）过滤在世且 available 的可招募角色。

        历史角色卡用真实公元年（如袁崇焕 1584-1630），内部转换为真实年比较。
        """
        real_year = 1627 + game_year
        return [
            inst.persona
            for inst in self.instances.values()
            if inst.status == AVAILABLE and inst.persona.is_alive_in(real_year)
        ]

    def get(self, persona_id: str) -> AgentInstance | None:
        return self.instances.get(persona_id)

    def active_instances(self) -> list[AgentInstance]:
        return [inst for inst in self.instances.values() if inst.status == ACTIVE]

    def active_agents(self) -> list[BaseAgent]:
        return [inst.agent for inst in self.active_instances() if inst.agent is not None]

    def status_of(self, persona_id: str) -> str | None:
        inst = self.instances.get(persona_id)
        return inst.status if inst else None

    def get_talent_pool(self) -> list[dict]:
        """返回人才库列表：available 历史人物 + dismissed 官员。"""
        pool = []
        for inst in self.instances.values():
            if inst.status in (AVAILABLE, DISMISSED):
                pool.append({
                    "id": inst.persona.id,
                    "name": inst.persona.name,
                    "gender": inst.persona.gender,
                    "skills": list(inst.persona.skills),
                    "weaknesses": list(inst.persona.weaknesses),
                    "status": inst.status,
                    "position": inst.persona.position,
                })
        return pool

    def find_by_name(self, name: str) -> AgentInstance | None:
        """按姓名查找角色实例（用于编排解析任免指令时定位目标）。
        返回第一个匹配项；历史人物姓名唯一，重名场景极少。"""
        for inst in self.instances.values():
            if inst.persona.name == name:
                return inst
        return None

    # ---------- 状态转换 ----------
    def make_agent(self, persona_id: str, llm: LLMProvider, era: str) -> BaseAgent:
        """用该角色已存的两层记忆构造可对话 BaseAgent。"""
        inst = self.instances.get(persona_id)
        if inst is None:
            raise KeyError(f"未知角色: {persona_id}")
        return BaseAgent(inst.persona, inst.factual, inst.narrative, llm, era=era)

    def recruit(self, persona_id: str, llm: LLMProvider, era: str) -> BaseAgent:
        """招募：available -> active。返回可对话 agent。"""
        inst = self.instances.get(persona_id)
        if inst is None:
            raise KeyError(f"未知角色: {persona_id}")
        if inst.status not in (AVAILABLE, DISMISSED):
            raise ValueError(f"{persona_id} 当前状态 {inst.status}，不可招募（需 available/dismissed）")
        inst.status = ACTIVE
        inst.agent = self.make_agent(persona_id, llm, era)
        return inst.agent

    def reinstate(self, persona_id: str, llm: LLMProvider, era: str) -> BaseAgent:
        """重新启用：dismissed -> active（复用历史记忆与怨气）。"""
        inst = self.instances.get(persona_id)
        if inst is None or inst.status != DISMISSED:
            raise ValueError(f"{persona_id} 非 dismissed，不可重新启用")
        inst.status = ACTIVE
        inst.agent = self.make_agent(persona_id, llm, era)
        return inst.agent

    def dismiss(self, persona_id: str) -> None:
        """免职：active -> dismissed（保留记忆与怨气，可重新招募）。"""
        inst = self.instances.get(persona_id)
        if inst is None or inst.status != ACTIVE:
            raise ValueError(f"{persona_id} 非 active，不可免职")
        inst.status = DISMISSED
        inst.agent = None

    def kill(self, persona_id: str) -> None:
        """赐死/死亡：any -> dead，移除 agent。"""
        inst = self.instances.get(persona_id)
        if inst is None:
            raise KeyError(f"未知角色: {persona_id}")
        inst.status = DEAD
        inst.agent = None

    # ---------- 虚构角色注入（科举进士） ----------
    def add_fictional(
        self,
        persona: PersonaCard,
        llm: LLMProvider,
        era: str,
        *,
        factual: FactualMemory | None = None,
        narrative: NarrativeMemory | None = None,
    ) -> BaseAgent:
        """科举授官新增虚构 agent：直接 active 在朝。"""
        if persona.id in self.instances:
            raise ValueError(f"角色 id 冲突: {persona.id}")
        inst = AgentInstance(
            persona=persona,
            status=ACTIVE,
            factual=factual or FactualMemory(),
            narrative=narrative or NarrativeMemory(),
        )
        self.instances[persona.id] = inst
        inst.agent = self.make_agent(persona.id, llm, era)
        return inst.agent

    # ---------- 存档 ----------
    def to_dict(self) -> dict:
        return {"instances": {k: v.to_dict() for k, v in self.instances.items()}}
