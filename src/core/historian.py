"""史官 agent：收公开层 → 推演 delta → 财政结算 → 叙事 → 预兆 → 求见汇总。

设计要点（见计划第6节"史官 agent"）：
- 推演层：推演效果 delta + 财政结算 + 叙事 + 触发事件 + 汇总求见 + 生成预兆。不解析分派。
- 历史与性格 grounding 硬约束：基于当前时间点史实背景与明末时代边界推演。
- 防数值崩：guided thinking 强制结构化推理；delta 走代码 max_delta 裁剪 + min/max clamp。
- 输出符合 delta_schema.json 的结构化 JSON。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from src.llm.provider import LLMProvider, Message

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


def _load_delta_schema() -> dict:
    with open(_PROMPTS_DIR / "delta_schema.json", encoding="utf-8") as f:
        return json.load(f)


def _load_historian_prompt() -> str:
    return (_PROMPTS_DIR / "historian.md").read_text(encoding="utf-8")


@dataclass
class TurnResult:
    """史官一回合推演结果。"""

    narrative: str = ""
    delta: dict = field(default_factory=dict)
    finance_delta: dict = field(default_factory=dict)
    new_events: list[dict] = field(default_factory=list)
    factual_notes: list[str] = field(default_factory=list)
    audience_queue: list[dict] = field(default_factory=list)
    premonitions: list[dict] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "TurnResult":
        return cls(
            narrative=str(d.get("narrative", "")),
            delta=dict(d.get("delta", {})),
            finance_delta=dict(d.get("finance_delta", {})),
            new_events=list(d.get("new_events", [])),
            factual_notes=list(d.get("factual_notes", [])),
            audience_queue=list(d.get("audience_queue", [])),
            premonitions=list(d.get("premonitions", [])),
        )

    def to_dict(self) -> dict:
        return {
            "narrative": self.narrative,
            "delta": self.delta,
            "finance_delta": self.finance_delta,
            "new_events": self.new_events,
            "factual_notes": self.factual_notes,
            "audience_queue": self.audience_queue,
            "premonitions": self.premonitions,
        }


class Historian:
    """史官 agent。"""

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
        self.prompt = prompt or _load_historian_prompt()
        self.schema = schema or _load_delta_schema()

    def _build_system(
        self,
        era: str,
        public_outputs: str,
        world_snapshot: dict,
        finance_params,
        edict_and_dispatch: str,
        upcoming_events: str,
    ) -> str:
        prompt = self.prompt
        return (
            prompt.replace("{{era}}", era)
            .replace("{{public_outputs}}", public_outputs)
            .replace("{{world_snapshot}}", json.dumps(world_snapshot, ensure_ascii=False, indent=2))
            .replace(
                "{{finance_params}}",
                json.dumps(_finance_params_snapshot(finance_params), ensure_ascii=False, indent=2),
            )
            .replace("{{edict_and_dispatch}}", edict_and_dispatch)
            .replace("{{upcoming_events}}", upcoming_events)
        )

    async def deduce(
        self,
        *,
        public_outputs: str,
        world_snapshot: dict,
        finance_params,
        edict_and_dispatch: str,
        upcoming_events: str,
        era: str,
        max_retries: int = 2,
    ) -> TurnResult:
        """收集公开层，推演 delta/财政/叙事/事件/求见/预兆。"""
        system = self._build_system(
            era, public_outputs, world_snapshot, finance_params, edict_and_dispatch, upcoming_events
        )
        out = await self.llm.chat_json(
            [Message("user", "请基于以上信息推演本回合结果，输出符合 schema 的 JSON。")],
            schema=self.schema,
            system=system,
            max_retries=max_retries,
        )
        return TurnResult.from_dict(out)

    @staticmethod
    def validate_delta(delta: dict, bounds: dict) -> tuple[bool, list[str]]:
        """校验 delta 是否都在 bounds 中（供重推判断）。实际裁剪由 world_state.apply_delta 完成。"""
        errors: list[str] = []
        for key, change in delta.items():
            if key not in bounds:
                errors.append(f"未知数值项: {key}")
                continue
            if not isinstance(change, (int, float)):
                errors.append(f"数值非数字: {key}={change!r}")
        return (len(errors) == 0, errors)


def _finance_params_snapshot(params) -> dict:
    """把 FinanceParams 转为可序列化快照。"""
    try:
        return {
            "income_monthly": params.income_monthly,
            "expense_monthly": params.expense_monthly,
            "tax_rates": params.tax_rates,
            "zonglu_reform": params.zonglu_reform,
        }
    except AttributeError:
        return dict(params) if params else {}
