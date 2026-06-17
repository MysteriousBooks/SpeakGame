"""科举系统：乡试→会试→殿试（玩家定名次授官）+ 进士人格生成。

科举是 agent 池的新生输入通道（与招募真实历史人物互补）。
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class Gongshi:
    """贡士（殿试考生）。"""
    name: str
    hometown: str  # 籍贯
    essay: str  # 答卷
    skill: str = ""  # 能力倾向
    rank: int = 0  # 殿试名次
    appointed: bool = False


@dataclass
class Jinshi:
    """进士（授官后成为 agent）。"""
    name: str
    hometown: str
    skill: str
    position: str  # 授官
    personality: str = ""
    loyalty: int = 60
    agent_id: str = ""


class ExamSystem:
    """科举系统。"""

    def __init__(self, cycle_years: int = 3):
        self.cycle_years = cycle_years
        self._names = [
            "张居正", "李贽", "王夫之", "顾炎武", "黄宗羲",
            "方以智", "朱之瑜", "傅山", "钱谦益", "吴伟业",
        ]
        self._hometowns = [
            "浙江", "江西", "湖广", "福建", "南直隶",
            "北直隶", "山东", "山西", "河南", "陕西",
        ]
        self._skills = ["财政", "军事", "政务", "谋略", "外交", "学术"]

    def is_exam_year(self, year: int) -> bool:
        """判断某年是否为科举年（明制三年一科）。"""
        return year % self.cycle_years == 0

    def generate_gongshi(self, count: int = 10) -> list[Gongshi]:
        """生成贡士名单。"""
        gongshi = []
        for i in range(count):
            gongshi.append(Gongshi(
                name=random.choice(self._names),
                hometown=random.choice(self._hometowns),
                essay=f"论{random.choice(['治道', '边防', '财政', '吏治'])}策",
                skill=random.choice(self._skills),
            ))
        return gongshi

    def appoint(
        self, gongshi: Gongshi, position: str
    ) -> Jinshi:
        """授官：贡士→进士→agent。"""
        jinshi = Jinshi(
            name=gongshi.name,
            hometown=gongshi.hometown,
            skill=gongshi.skill,
            position=position,
            personality=f"{gongshi.skill}型、{random.choice(['刚直', '圆滑', '务实', '激进'])}",
            loyalty=random.randint(50, 80),
            agent_id=f"jinshi_{gongshi.name}",
        )
        gongshi.appointed = True
        gongshi.rank = 1
        return jinshi

    def generate_persona(self, jinshi: Jinshi) -> dict:
        """生成进士人格卡（用于创建 agent）。"""
        return {
            "agent_id": jinshi.agent_id,
            "name": jinshi.name,
            "hometown": jinshi.hometown,
            "skill": jinshi.skill,
            "position": jinshi.position,
            "personality": jinshi.personality,
            "loyalty": jinshi.loyalty,
            "born_year": 1600 + random.randint(1, 20),
            "faction": random.choice(["东林", "阉党余孽", "楚党", "中立"]),
        }
