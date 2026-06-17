"""招募/科举系统：角色库加载 + 按年份过滤 + 角色状态机 + 科举。"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml


ROSTER_STATUS = ["available", "active", "dismissed", "dead"]


class Roster:
    """角色库管理：加载、年份过滤、状态机、招募。"""

    def __init__(self, figures_path: Path):
        raw = yaml.safe_load(figures_path.read_text(encoding="utf-8"))
        self.figures: list[dict] = raw if isinstance(raw, list) else []
        self._by_id = {f["id"]: f for f in self.figures}
        # 角色状态存储 (id -> status)
        self._status: dict[str, str] = {}

    def filter_alive(self, year: int) -> list[dict]:
        """按当前年份返回仍在世的角色（born ≤ year < death）。"""
        result = []
        for f in self.figures:
            by = f.get("born_year", 0)
            dy = f.get("historical_death_year", 9999)
            if by <= year < dy:
                result.append(f)
        return result

    def filter_recruitable(self, year: int) -> list[dict]:
        """返回当前可招募的角色（在世 + available/dismissed 状态）。"""
        alive = self.filter_alive(year)
        return [
            f
            for f in alive
            if self._status.get(f["id"], "available") in (
                "available",
                "dismissed",
            )
        ]

    def recruit(self, figure_id: str) -> bool:
        """招募角色（available/dismissed → active）。"""
        status = self._status.get(figure_id, "available")
        if status not in ("available", "dismissed"):
            return False
        self._status[figure_id] = "active"
        return True

    def dismiss(self, figure_id: str) -> bool:
        """免职（active → dismissed）。"""
        if self._status.get(figure_id) != "active":
            return False
        self._status[figure_id] = "dismissed"
        return True

    def execute(self, figure_id: str) -> bool:
        """赐死（任意状态 → dead）。"""
        self._status[figure_id] = "dead"
        return True

    def get_status(self, figure_id: str) -> str:
        return self._status.get(figure_id, "available")

    def get_figure(self, figure_id: str) -> Optional[dict]:
        return self._by_id.get(figure_id)

    def get_active_agents(self) -> list[str]:
        return [
            fid for fid, st in self._status.items() if st == "active"
        ]


class ExamSystem:
    """科举系统（乡试→会试→殿试，玩家授官）。"""

    def __init__(self, cycle_years: int = 3):
        self.cycle_years = cycle_years
        self._next_year = 3  # 崇祯三年首科

    def is_exam_year(self, year: int) -> bool:
        return year >= self._next_year and (
            year - self._next_year
        ) % self.cycle_years == 0

    def generate_jinshi(self, count: int = 3) -> list[dict]:
        """生成进士列表（mock 版本）。"""
        names = [
            "张慎言",
            "李国英",
            "王铎",
            "陈演",
            "吴甡",
            "黄道周",
            "刘宗周",
        ]
        return [
            {
                "id": f"jinshi_{i}",
                "name": names[i % len(names)],
                "籍贯": "顺天府",
                "答卷": "策论…",
                "能力倾向": "政务",
                "背景": "书香门第",
            }
            for i in range(count)
        ]

    def appoint(
        self,
        figure_id: str,
        roster: Roster,
        position: str,
    ) -> bool:
        """授官→新增 agent。"""
        return roster.recruit(figure_id)
