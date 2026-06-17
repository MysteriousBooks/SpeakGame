"""Agent 基类：人格卡加载 + 两层记忆 + 公开私密层 + 求见意愿产出。"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class AgentOutput:
    """agent 执行产出。"""
    public: str = ""              # 公开层（其他 agent/史官可读）
    private: str = ""             # 私密层（仅自身+密奏可见）
    want_audience: bool = False  # 是否求见
    audience_topic: str = ""     # 求见主题（模糊，如"言边事"）


@dataclass
class Persona:
    """角色人格卡。"""
    id: str
    name: str
    courtesy: str = ""
    faction: str = ""
    skills: list = field(default_factory=list)
    personality: str = ""
    relations: dict = field(default_factory=dict)
    # per-agent 属性初值
    loyalty: int = 50
    dissatisfaction: int = 0
    safety: int = 50

    @classmethod
    def load_yaml(cls, path: Path) -> "Persona":
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return cls(**data)


class BaseAgent:
    """角色 agent 基类。"""

    def __init__(
        self,
        persona: Persona,
        factual_memory: list,
        narrative_summary: str = "",
    ):
        self.persona = persona
        self.factual_memory = factual_memory        # 相关事实记忆条目
        self.narrative_summary = narrative_summary  # 压缩叙事记忆
        self.loyalty = persona.loyalty
        self.dissatisfaction = persona.dissatisfaction
        self.safety = persona.safety

    def build_system_prompt(self) -> str:
        """构建 system prompt（含角色信息+信息隔离+行为约束）。"""
        return f"""你是{self.persona.name}（{self.persona.personality}）。
派系：{self.persona.faction}。擅长：{', '.join(self.persona.skills)}。
关系网：{self.persona.relations}

【信息隔离硬约束】
- 你不知道其他官员的私下立场，只能看到公开的军情/灾情/表态。
- 你的真实立场属私密层，仅在玩家密奏或必要时吐露。
- 不得主动在朝堂或拜访中泄露他人的私密信息。

【性格与历史驱动】
- 你的表态须符合你的性格与当前处境。
- 不得做出超越该历史节点合理行为范围的反应。

【输出格式】
请输出 JSON：{{"public":"公开表态/执行结果","private":"内心真实想法","want_audience":bool,"audience_topic":"模糊主题"}}
"""

    def build_context(self, current_affairs: str, public_info: list[str]) -> str:
        """构建当前回合上下文。"""
        parts = [f"【当前局势】{current_affairs}"]
        if self.narrative_summary:
            parts.append(f"【你的记忆】{self.narrative_summary}")
        if self.factual_memory:
            parts.append("【你知悉的事实】" + "; ".join(
                n["content"] for n in self.factual_memory[-5:]
            ))
        if public_info:
            parts.append("【你看到的公开信息】" + "; ".join(public_info))
        return "\n".join(parts)

    def process_edict(self, edict: str) -> AgentOutput:
        """处理玩家诏书（调用 LLM 执行，此处放 mock 占位）。"""
        # 实际调用：provider.chat([system_prompt, user_message])
        # MVP 用 mock 占位，详见 src/llm/provider.py
        return AgentOutput(
            public=f"[{self.persona.name}] 臣接旨。诏书已阅，当依旨而行。",
            private=f"[{self.persona.name} 内心] 此诏…须谨慎处之。",
            want_audience=False,
        )

    def respond_to_audience(self, question: str) -> AgentOutput:
        """回应玩家召见/求见问话。"""
        return AgentOutput(
            public=f"[{self.persona.name}] 臣对曰：{question}…",
            private=f"[{self.persona.name} 内心] 此问…须留三分余地。",
        )

    def visit(self, other_public: str) -> AgentOutput:
        """拜访某 agent，接收对方 public 层，产出自己的回应。"""
        return AgentOutput(
            public=f"[{self.persona.name}] 闻阁下所言：{other_public[:20]}…",
            private=f"[{self.persona.name} 内心] 此言虚实当查。",
        )
