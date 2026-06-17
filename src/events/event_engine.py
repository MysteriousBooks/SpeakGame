"""动态事件引擎：按史实时间线触发历史事件 + 纯代码数值阈值判定解决。

主线史实事件：预定义于 historical_events.yaml，按史实时间线触发，代码判定解决。
支线涌现事件：由史官建议（new_events），按数值阈值动态触发。
两者都经纯代码数值阈值判定（不依赖 LLM 主观）。
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from src.core.world_state import WorldState


def _parse_time(label: str, era: str = "崇祯") -> tuple[int, int]:
    """'崇祯2年10月' -> (2, 10)。"""
    m = re.search(r"(\d+)年(\d+)月", label)
    if not m:
        return (0, 0)
    return (int(m.group(1)), int(m.group(2)))


class EventEngine:
    def __init__(self, events_path: Path):
        raw = yaml.safe_load(events_path.read_text(encoding="utf-8"))
        self.events: list[dict] = raw["events"]
        self._by_id = {e["id"]: e for e in self.events}

    def due_events(self, state: WorldState) -> list[dict]:
        """返回到当前时间点应触发、且尚未激活/解决的事件。"""
        due = []
        for e in self.events:
            ty, tm = _parse_time(e["trigger_time"])
            triggered = (state.year > ty) or (
                state.year == ty and state.month >= tm
            )
            if (
                triggered
                and e["id"] not in state.active_events
                and e["id"] not in state.resolved_events
            ):
                due.append(e)
        return due

    def trigger_events(self, state: WorldState) -> list[dict]:
        """触发到期事件，加入 active_events。"""
        due = self.due_events(state)
        for e in due:
            state.active_events.append(e["id"])
        return due

    def events_in_premonition(self, state: WorldState) -> list[dict]:
        """返回在 premonition_lead 月内即将触发的事件（用于生成预兆）。"""
        near = []
        for e in self.events:
            if e["id"] in state.active_events or e["id"] in state.resolved_events:
                continue
            ty, tm = _parse_time(e["trigger_time"])
            lead = e.get("premonition_lead", 0)
            # 计算距离触发还有多少月
            months_away = (ty - state.year) * 12 + (tm - state.month)
            if 0 <= months_away <= lead:
                near.append(e)
        return near

    @staticmethod
    def _check_condition(value, cond: str) -> bool:
        """'>=60' 之类阈值比较。"""
        m = re.match(r"(>=|<=|>|<|==)\s*(-?\d+)", cond)
        if not m:
            return False
        op, num = m.group(1), float(m.group(2))
        ops = {
            ">=": lambda v, n: v >= n,
            "<=": lambda v, n: v <= n,
            ">": lambda v, n: v > n,
            "<": lambda v, n: v < n,
            "==": lambda v, n: v == n,
        }
        return ops[op](value, num)

    def check_resolutions(
        self, state: WorldState
    ) -> tuple[list[str], list[dict]]:
        """检查活跃事件是否解决。

        纯代码数值阈值判定，不调 LLM。
        返回 (本次解决的id列表, 仍活跃事件列表)。
        """
        resolved_now: list[str] = []
        still_active: list[dict] = []
        for eid in list(state.active_events):
            e = self._by_id.get(eid)
            if not e:
                continue
            conds = e.get("resolve_conditions", {})
            ok = all(
                self._check_condition(state.get(k), c)
                for k, c in conds.items()
            )
            if ok:
                resolved_now.append(eid)
                state.resolved_events.append(eid)
            else:
                still_active.append(e)
        state.active_events = [
            e for e in state.active_events if e not in resolved_now
        ]
        return resolved_now, still_active

    def apply_fail_consequences(
        self, state: WorldState, bounds: dict | None = None
    ) -> list[str]:
        """对仍挂起事件施加 fail_consequences（每回合调用一次）。"""
        delta: dict = {}
        notes: list[str] = []
        # 合法数值键列表，按长度降序（避免"民心"误匹配"陕西_民心-8"）
        known_keys = sorted(state.values.keys(), key=len, reverse=True)
        for eid in state.active_events:
            e = self._by_id.get(eid)
            if not e:
                continue
            for cons in e.get("fail_consequences", []):
                # 遍历所有已知键，看是否在 cons 中后跟 +/-数字
                for key in known_keys:
                    m = re.search(
                        re.escape(key) + r"\s*([+\-])\s*(\d+)", cons
                    )
                    if m:
                        val = int(m.group(2))
                        if m.group(1) == "-":
                            val = -val
                        delta[key] = delta.get(key, 0) + val
                        notes.append(f"[{e['name']}] {cons}")
                        break
        if delta:
            applied, _ = state.validate_delta(delta, bounds)
            state.apply(applied)
        return notes

    def register_spontaneous_event(
        self, event_data: dict, state: WorldState
    ):
        """注册支线涌现事件（史官 new_events）。"""
        eid = event_data.get("id", f"spontaneous_{len(state.active_events)}")
        self._by_id[eid] = event_data
        state.active_events.append(eid)
