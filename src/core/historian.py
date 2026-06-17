"""史官 agent：推演效果 delta + 财政结算 + 叙事 + 触发事件 + 汇总求见 + 生成预兆。

史官 = 推演层，不解析分派。负责：
- 收集各 agent 公开层输出
- 推演数值 delta（财政/军事/民政/人事类政令效果）
- 财政结算（年景/战事/民变调制）
- 生成回合叙事 + 支线涌现事件建议
- 生成下回合预兆 + 汇总求见队列
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

from src.core.world_state import WorldState
from src.finance.economy import FinanceState


@dataclass
class HistorianOutput:
    """史官输出。"""
    narrative: str = ""
    delta: dict = field(default_factory=dict)
    new_events: list[dict] = field(default_factory=list)
    factual_notes: list[str] = field(default_factory=list)
    audience_queue: list[dict] = field(default_factory=list)


class Historian:
    """史官 agent。"""

    def run(
        self,
        state: WorldState,
        agent_outputs: list[dict],
        edict: str = "",
        upcoming_events: Optional[list[dict]] = None,
        finance: Optional[FinanceState] = None,
        year_景: str = "平",
        war_factor: float = 1.0,
        rebellion_factor: float = 1.0,
    ) -> HistorianOutput:
        """执行史官推演。"""
        output = HistorianOutput()

        # 1. 收集 agent 公开层
        public_layer = []
        for ao in agent_outputs:
            if isinstance(ao, dict) and "public" in ao:
                public_layer.append(ao["public"])
            if isinstance(ao, dict) and "want_audience" in ao and ao["want_audience"]:
                output.audience_queue.append({
                    "agent_id": ao.get("agent_id", "unknown"),
                    "topic": ao.get("audience_topic", "有本奏"),
                    "urgency": "normal",
                })

        # 2. 财政结算
        if finance:
            settlement = finance.settle(year_景, war_factor, rebellion_factor)
            output.delta.update(settlement["delta"])
            output.narrative += f"财政结算：收入{settlement['收入']}，支出{settlement['支出']}，净{settlement['净']}。\n"

        # 3. 推演 delta（基于政令类型）
        if "赈" in edict or "拨银" in edict:
            output.delta["国库"] = output.delta.get("国库", 0) - 100_000
            output.delta["陕西_民心"] = output.delta.get("陕西_民心", 0) + 8
            output.factual_notes.append(f"帝拨银赈陕西（{state.era_label()}）")
        elif "加征" in edict or "辽饷" in edict:
            output.delta["民心"] = output.delta.get("民心", 0) - 5
            output.delta["国库"] = output.delta.get("国库", 0) + 50_000
        elif "军" in edict or "兵" in edict or "整饬" in edict:
            output.delta["军力"] = output.delta.get("军力", 0) + 5
            output.delta["军心"] = output.delta.get("军心", 0) + 3
            output.delta["国库"] = output.delta.get("国库", 0) - 30_000

        # 4. 生成叙事
        output.narrative += f"诏书已下，{state.era_label()}。"
        if output.delta:
            output.narrative += f"数值变化：{json.dumps(output.delta, ensure_ascii=False)}。"

        # 5. 预兆
        if upcoming_events:
            for ev in upcoming_events:
                output.narrative += f"【预兆】{ev.get('background', '')[:30]}..."

        return output
