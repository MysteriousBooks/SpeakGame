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
    """早朝群聊执行器。"""

    def __init__(self, *, max_turns: int = 3) -> None:
        self.max_turns = max_turns
        self.court_prompt = _COURT_PROMPT_PATH.read_text(encoding="utf-8") if _COURT_PROMPT_PATH.exists() else ""

    def _build_scene(self, situation: str, history_text: str, turn_idx: int) -> str:
        """构造早朝场景文本（注入朝堂公开历史 + 发言约束）。"""
        return (
            f"早朝第{turn_idx + 1}轮议政。\n\n"
            f"当前局势与活跃事件：\n{situation}\n\n"
            f"朝堂已有公开对话历史（仅公开层）：\n{history_text}\n\n"
            "发言要求：只输出公开层表态（请奏/附和/论辩/攻讦），不得在朝堂泄露私密立场；"
            "发言须符合你的人格与派系立场。"
        )

    async def run(
        self,
        speaking_agents: list[BaseAgent],
        situation: str,
        audience_queue: AudienceQueue | None = None,
    ) -> tuple[list[CourtSpeech], list[AudienceRequest]]:
        """执行早朝群聊：每轮让 speaking_agents 发言，累积公开层历史，收集求见意愿。

        speaking_agents 由编排按议题/品级/事件相关性选定的发言子集。
        返回 (朝堂发言列表, 新增求见请求列表)。
        """
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
