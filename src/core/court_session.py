"""早朝群聊：在朝 agent 共享公开上下文 + 请奏发言 + 论辩 + 玩家介入下政令。

设计要点（见计划第3节"早朝"、第4节信息可见性模型）：
- 早朝=公开层场域：所有在朝 agent 可见朝堂公开发言；私密层不在朝堂公开（密事走求见）。
- 按议题事件驱动激活相关子集发言（非全员每次都发言，控成本）。
- 控制每朝发言轮数（3-5 轮）控成本与上下文长度；用低成本模型跑角色发言。
- 发言者亦产出求见意愿（want_audience）。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.agents.base_agent import AgentOutput, BaseAgent
from src.core.audience import AudienceQueue, AudienceRequest

_COURT_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "court.md"


@dataclass
class CourtSpeech:
    """一条朝堂公开发言。"""

    speaker_id: str
    speaker_name: str
    public: str
    want_audience: bool = False
    audience_topic: str = ""

    def to_dict(self) -> dict:
        return {
            "speaker_id": self.speaker_id,
            "speaker_name": self.speaker_name,
            "public": self.public,
            "want_audience": self.want_audience,
            "audience_topic": self.audience_topic,
        }


def format_history(speeches: list[CourtSpeech]) -> str:
    """拼接朝堂公开对话历史（仅公开层）。"""
    if not speeches:
        return "（朝堂尚未发言）"
    return "\n".join(f"{s.speaker_name}：{s.public}" for s in speeches)


class CourtSession:
    """早朝群聊执行器。支持单轮执行，便于玩家实时插话。"""

    def __init__(self, *, max_turns: int = 3) -> None:
        self.max_turns = max_turns
        self.court_prompt = _COURT_PROMPT_PATH.read_text(encoding="utf-8") if _COURT_PROMPT_PATH.exists() else ""
        # 实时早朝状态（跨请求持久）
        self.speeches: list[CourtSpeech] = []
        self.current_turn: int = 0
        self.is_active: bool = False

    def start(self) -> None:
        """开始新一轮早朝。"""
        self.speeches = []
        self.current_turn = 0
        self.is_active = True

    def _build_scene(self, situation: str, history_text: str, turn_idx: int) -> str:
        """构造早朝场景文本（注入朝堂公开历史 + 发言约束）。"""
        return (
            f"早朝第{turn_idx + 1}轮议政。\n\n"
            f"当前局势与活跃事件：\n{situation}\n\n"
            f"朝堂已有公开对话历史（仅公开层）：\n{history_text}\n\n"
            "发言要求：只输出公开层表态（请奏/附和/论辩/攻讦），不得在朝堂泄露私密立场；"
            "发言须符合你的人格与派系立场。"
        )

    def _build_player_interject_scene(self, player_message: str, history_text: str) -> str:
        """构造玩家插话后的场景（皇帝发言，百官回应）。"""
        return (
            f"朝堂对话历史：\n{history_text}\n\n"
            f"皇帝突然开口：「{player_message}」\n\n"
            "请根据皇帝的话回应（可附和、进谏、补充奏报），须符合你的人格与立场。"
        )

    async def run_one_round(
        self,
        speaking_agents: list[BaseAgent],
        situation: str,
        player_message: str | None = None,
    ) -> list[CourtSpeech]:
        """执行一轮早朝。若有 player_message，则先注入皇帝发言再让百官回应。"""
        if not speaking_agents or not self.is_active:
            return []
        round_speeches: list[CourtSpeech] = []
        history_text = format_history(self.speeches)

        # 若玩家插话，注入皇帝发言到历史
        if player_message:
            emperor_speech = CourtSpeech(
                speaker_id="emperor",
                speaker_name="皇帝",
                public=player_message,
            )
            self.speeches.append(emperor_speech)
            round_speeches.append(emperor_speech)
            history_text = format_history(self.speeches)

        # 百官本轮发言
        for agent in speaking_agents:
            if player_message:
                scene = self._build_player_interject_scene(player_message, history_text)
            else:
                scene = self._build_scene(situation, history_text, self.current_turn)
            out: AgentOutput = await agent.respond(
                scene, "请在朝堂发言（请奏/附和/论辩），并表明是否求见。"
            )
            speech = CourtSpeech(
                speaker_id=agent.id,
                speaker_name=agent.name,
                public=out.public,
                want_audience=out.want_audience,
                audience_topic=out.audience_topic,
            )
            self.speeches.append(speech)
            round_speeches.append(speech)
            history_text = format_history(self.speeches)

        self.current_turn += 1
        if self.current_turn >= self.max_turns:
            self.is_active = False
        return round_speeches

    async def run(
        self,
        speaking_agents: list[BaseAgent],
        situation: str,
        audience_queue: AudienceQueue | None = None,
    ) -> tuple[list[CourtSpeech], list[AudienceRequest]]:
        """执行完整早朝群聊（兼容旧接口：一次性跑完所有轮）。"""
        speeches: list[CourtSpeech] = []
        new_requests: list[AudienceRequest] = []
        if not speaking_agents:
            return speeches, new_requests

        history_text = format_history(speeches)
        for turn_idx in range(self.max_turns):
            for agent in speaking_agents:
                scene = self._build_scene(situation, history_text, turn_idx)
                out: AgentOutput = await agent.respond(
                    scene, "请在朝堂发言（请奏/附和/论辩），并表明是否求见。"
                )
                speech = CourtSpeech(
                    speaker_id=agent.id,
                    speaker_name=agent.name,
                    public=out.public,
                    want_audience=out.want_audience,
                    audience_topic=out.audience_topic,
                )
                speeches.append(speech)
                if out.want_audience and out.audience_topic:
                    new_requests.append(
                        AudienceRequest(
                            agent_id=agent.id,
                            agent_name=agent.name,
                            topic=out.audience_topic,
                            urgency="normal",
                        )
                    )
                history_text = format_history(speeches)
        # 求见请求汇总入 audience_queue
        if audience_queue is not None:
            for req in new_requests:
                audience_queue.add(req)
        return speeches, new_requests
