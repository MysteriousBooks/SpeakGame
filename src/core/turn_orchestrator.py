"""编排 agent：解析诏书→分类→分派/处置/识别类型。

编排 = 路由层，不推演数值。负责：
- 解析自然语言诏书为可执行指令
- 识别皇权处置（赐死/免职）、财政划拨（内帑→国库）、宗禄改革
- 普通政令解析为任务对象
- 主持早朝流程控制
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class EdictPlan:
    """编排解析诏书后的分派计划。"""
    type: str  # task | execute | dismiss | finance_transfer | zonglu_reform | unknown
    target_agent: Optional[str] = None
    task: Optional[str] = None
    affects: list[str] = field(default_factory=list)
    deadline: Optional[str] = None
    success_condition: Optional[str] = None
    amount: Optional[int] = None  # 财政划拨金额
    reform_params: dict = field(default_factory=dict)  # 宗禄改革参数
    raw_edict: str = ""


class TurnOrchestrator:
    """回合编排器。"""

    def parse_edict(self, edict: str) -> EdictPlan:
        """解析自然语言诏书，返回分派计划。"""
        plan = EdictPlan(raw_edict=edict)

        # 皇权处置识别
        if m := re.search(r"(?:赐死|处死|赐|杀)\s*(.+)", edict):
            plan.type = "execute"
            plan.target_agent = m.group(1).strip()
            return plan
        if m := re.search(r"(?:免职|罢免|革职|罢)\s*(.+)", edict):
            plan.type = "dismiss"
            plan.target_agent = m.group(1).strip()
            return plan

        # 财政划拨识别
        if re.search(r"(?:内帑|内库|内承运库).*(?:充|拨|划|转).*(?:国库|太仓)", edict):
            plan.type = "finance_transfer"
            m = re.search(r"(\d+)\s*(?:万|两|银)", edict)
            plan.amount = int(m.group(1)) * 10000 if m else 100000
            return plan
        if re.search(r"(?:国库|太仓).*(?:入|拨|划).*(?:内帑|内库)", edict):
            plan.type = "finance_transfer"
            plan.amount = 0  # 拒绝
            return plan

        # 宗禄改革识别
        if re.search(r"(?:宗室|宗禄|岁禄|宗藩).*(?:削减|折钞|限制|查革|改革)", edict):
            plan.type = "zonglu_reform"
            if re.search(r"削减|减", edict):
                m = re.search(r"(\d+)\s*成", edict)
                plan.reform_params["cut_ratio"] = int(m.group(1)) / 10 if m else 0.3
            if re.search(r"折钞", edict):
                plan.reform_params["zhechao"] = True
            return plan

        # 普通政令 → 任务
        plan.type = "task"
        plan.task = edict
        # 识别目标角色
        if "户部" in edict or "财政" in edict or "赋税" in edict or "赈" in edict:
            plan.target_agent = "minister_finance"
            plan.affects = ["国库", "田赋"]
        elif "兵部" in edict or "军" in edict or "边" in edict or "辽东" in edict:
            plan.target_agent = "minister_war"
            plan.affects = ["军力", "军心"]
        elif "民" in edict or "百姓" in edict or "陕西" in edict:
            plan.target_agent = "common_people"
            plan.affects = ["民心", "陕西_民心"]
        else:
            plan.target_agent = "minister_finance"
            plan.affects = ["国库"]

        # 期限
        m = re.search(r"(\d+)\s*(?:月|年|日)", edict)
        if m:
            plan.deadline = f"崇祯{int(m.group(1))}年"
        return plan

    def activate_subset(self, plan: EdictPlan, available_agents: list[str]) -> list[str]:
        """按事件相关性激活 agent 子集（成本控制）。"""
        if plan.target_agent and plan.target_agent in available_agents:
            return [plan.target_agent]
        return available_agents[:1]
