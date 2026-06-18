"""事件引擎：预兆（每回合开局）+ 史实时间线触发 + 纯代码数值阈值判定解决。

设计要点（见计划第3节"真实历史事件系统""事件预兆系统"）：
- 主线史实事件由 event_engine 按史实时间线触发、代码判定解决。
- 事件解决判定（纯代码数值阈值比较）：遍历活跃事件，检查 resolve_conditions 是否全部满足。
- premonition_lead 以月为单位；每回合开局检查"将在 lead 月内触发"的事件并展示预兆，分级递进。
- 不满足 resolve_conditions 则继续挂起，按 fail_consequences 恶化。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

_EVENTS_DIR = Path(__file__).resolve().parent.parent.parent / "events"

# 数值阈值比较运算符解析
_COND_RE = re.compile(r"^\s*(>=|<=|==|>|<)\s*(-?\d+(?:\.\d+)?)\s*$")

# 预兆分级阈值（距触发月数）
PREMONITION_LEVELS = [
    (3, "远期"),
    (2, "近期"),
    (1, "迫近"),
]


@dataclass
class HistoricalEvent:
    """一个真实历史事件。"""

    id: str
    name: str
    trigger_time: str = ""  # "崇祯X年Y月"
    trigger_month: int = 0  # 月序（开局=0）
    premonition_lead: int = 3
    background: str = ""
    involved_agents: list = field(default_factory=list)
    task_desc: str = ""
    resolve_conditions: dict = field(default_factory=dict)
    fail_consequences: list = field(default_factory=list)
    is_periodic: bool = False  # 周期性事件（如科举）

    @classmethod
    def from_dict(cls, d: dict) -> "HistoricalEvent":
        return cls(
            id=d["id"],
            name=d["name"],
            trigger_time=d.get("trigger_time", ""),
            trigger_month=parse_trigger_time(d.get("trigger_time", "")),
            premonition_lead=int(d.get("premonition_lead", 3)),
            background=d.get("background", ""),
            involved_agents=list(d.get("involved_agents", [])),
            task_desc=d.get("task_desc", ""),
            resolve_conditions=dict(d.get("resolve_conditions", {})),
            fail_consequences=list(d.get("fail_consequences", [])),
            is_periodic=bool(d.get("is_periodic", False)),
        )


@dataclass
class ActiveEvent:
    """已触发并挂起的活跃事件（带进度/期限/解决状态）。"""

    event: HistoricalEvent
    resolved: bool = False
    triggered_month: int = 0
    fail_applied_months: int = 0  # 已应用 fail_consequences 的月数

    def to_dict(self) -> dict:
        return {
            "id": self.event.id,
            "name": self.event.name,
            "resolved": self.resolved,
            "triggered_month": self.triggered_month,
            "fail_applied_months": self.fail_applied_months,
            "task_desc": self.event.task_desc,
            "resolve_conditions": self.event.resolve_conditions,
            "fail_consequences": self.event.fail_consequences,
        }


def parse_trigger_time(text: str) -> int:
    """'崇祯2年10月' -> 月序（开局崇祯1年1月=0）。"""
    m = re.match(r"崇祯(\d+)年(\d+)月", text)
    if not m:
        return 0
    year = int(m.group(1))
    month = int(m.group(2))
    return (year - 1) * 12 + (month - 1)


def parse_condition(cond: str) -> tuple[str, float]:
    """'>=70' -> ('>=', 70)。"""
    m = _COND_RE.match(cond)
    if not m:
        raise ValueError(f"无法解析条件: {cond!r}")
    return m.group(1), float(m.group(2))


def _check_condition(value: float, cond: str) -> bool:
    op, threshold = parse_condition(cond)
    if op == ">=":
        return value >= threshold
    if op == "<=":
        return value <= threshold
    if op == "==":
        return value == threshold
    if op == ">":
        return value > threshold
    if op == "<":
        return value < threshold
    return False


class EventEngine:
    """事件引擎：触发、预兆、解决判定、恶化。"""

    def __init__(self, config: dict, *, events: list[HistoricalEvent] | None = None) -> None:
        self.config = config
        self.events: list[HistoricalEvent] = events if events is not None else self._load_events()
        self.active: list[ActiveEvent] = []

    @staticmethod
    def _load_events(path: str | Path | None = None) -> list[HistoricalEvent]:
        p = Path(path) if path else _EVENTS_DIR / "historical_events.yaml"
        with open(p, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return [HistoricalEvent.from_dict(d) for d in data.get("events", [])]

    # ---------- 触发 ----------
    def trigger_by_months(self, crossed_months: list[int]) -> list[HistoricalEvent]:
        """按史实时间线触发：遍历未触发的非周期事件，trigger_month 在 crossed_months 内则挂起。"""
        triggered_ids = {ae.event.id for ae in self.active}
        newly: list[HistoricalEvent] = []
        for ev in self.events:
            if ev.is_periodic:
                continue  # 周期事件单独处理
            if ev.id in triggered_ids:
                continue
            if ev.trigger_month in crossed_months and ev.trigger_month >= 0:
                self.active.append(ActiveEvent(event=ev, triggered_month=ev.trigger_month))
                newly.append(ev)
        return newly

    def trigger_initial(self) -> list[HistoricalEvent]:
        """开局挂起开局事件（trigger_month=0）。"""
        return self.trigger_by_months([0])

    # ---------- 预兆 ----------
    def upcoming_premonitions(self, current_month: int) -> list[dict]:
        """生成将在 premonition_lead 内触发的事件的预兆（分级递进）。

        返回 [{"event_id","name","level","text"}]。已触发或已解决的不出预兆。
        """
        active_ids = {ae.event.id for ae in self.active}
        premonitions: list[dict] = []
        for ev in self.events:
            if ev.id in active_ids:
                continue
            if ev.premonition_lead <= 0:
                continue
            distance = ev.trigger_month - current_month
            if 0 < distance <= ev.premonition_lead:
                level = _level_for_distance(distance, ev.premonition_lead)
                premonitions.append(
                    {
                        "event_id": ev.id,
                        "name": ev.name,
                        "level": level,
                        "text": f"{ev.name}预兆：{ev.background[:30]}…",
                    }
                )
        return premonitions

    # ---------- 解决判定（纯代码） ----------
    def check_resolve(self, values: dict) -> list[ActiveEvent]:
        """遍历活跃事件，检查 resolve_conditions 是否全部满足（纯数值阈值）。

        满足 → 标记 resolved；空 conditions（如科举）不在此自动解决，需玩家操作。
        返回本回合新解决的事件列表。
        """
        newly_resolved: list[ActiveEvent] = []
        for ae in self.active:
            if ae.resolved:
                continue
            if not ae.event.resolve_conditions:
                continue  # 非数值阈值事件，由玩家操作解决
            if self._conditions_met(ae.event, values):
                ae.resolved = True
                newly_resolved.append(ae)
        return newly_resolved

    @staticmethod
    def _conditions_met(event: HistoricalEvent, values: dict) -> bool:
        for key, cond in event.resolve_conditions.items():
            if key not in values:
                return False
            if not _check_condition(float(values[key]), cond):
                return False
        return True

    # ---------- 恶化 ----------
    def apply_fail_consequences(self, values: dict, current_month: int) -> dict:
        """对未解决且已过触发月的活跃事件应用 fail_consequences（每事件每回合一次）。

        返回合并的 delta（由上层 apply_delta 落库）。MVP：每事件每回合应用第一条后果。
        """
        delta: dict[str, float] = {}
        for ae in self.active:
            if ae.resolved:
                continue
            if not ae.event.fail_consequences:
                continue
            if current_month <= ae.event.trigger_month:
                continue  # 未到期不恶化
            # 每事件每回合应用第一条后果
            conseq = ae.event.fail_consequences[0]
            for k, v in conseq.get("delta", {}).items():
                delta[k] = delta.get(k, 0) + v
            ae.fail_applied_months += 1
        return delta

    # ---------- 状态 ----------
    def active_unresolved(self) -> list[ActiveEvent]:
        return [ae for ae in self.active if not ae.resolved]

    def mark_resolved(self, event_id: str) -> None:
        """手动标记事件解决（如科举玩家授官后）。"""
        for ae in self.active:
            if ae.event.id == event_id:
                ae.resolved = True
                return

    def to_dict(self) -> dict:
        return {"active": [ae.to_dict() for ae in self.active]}

    @classmethod
    def from_dict(cls, data: dict, config: dict) -> "EventEngine":
        eng = cls(config)
        eng.active = []
        for d in data.get("active", []):
            ev = next((e for e in eng.events if e.id == d["id"]), None)
            if ev is None:
                continue
            ae = ActiveEvent(
                event=ev,
                resolved=d.get("resolved", False),
                triggered_month=int(d.get("triggered_month", 0)),
                fail_applied_months=int(d.get("fail_applied_months", 0)),
            )
            eng.active.append(ae)
        return eng


def _level_for_distance(distance: int, lead: int) -> str:
    """按距触发月数分级（绝对距离）：迫近(1)→近期(2)→远期(>=3)。lead 仅控制是否出现。"""
    if distance <= 1:
        return "迫近"
    if distance <= 2:
        return "近期"
    return "远期"
