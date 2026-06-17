"""寿命/死亡系统：平均寿命 + 死亡危机事件 + 皇权处置（赐死/免职）后果。"""
from __future__ import annotations

import random
from typing import Optional


def compute_natural_death_year(
    born_year: int, lifespan: int = 50, variance: int = 5
) -> int:
    """按平均寿命计算自然死亡年份。"""
    return born_year + lifespan + random.randint(-variance, variance)


def trigger_death_crisis(
    figure: dict, current_year: int, lead_months: int = 3
) -> Optional[dict]:
    """判定是否触发死亡危机事件。

    当游戏推进到角色史实死亡年附近且死因非自然时触发。
    返回死亡危机事件 dict 或 None。
    """
    death_year = figure.get("historical_death_year", 0)
    death_type = figure.get("death_cause", {}).get("type", "natural")
    if death_type == "natural":
        return None
    if abs(current_year - death_year) > 1:
        return None  # 还不在死亡窗口内

    return {
        "id": f"death_crisis_{figure['id']}",
        "name": f"{figure['name']}死亡危机",
        "type": "death_crisis",
        "target": figure["id"],
        "resolve_conditions": {"安全度": ">=80"},
        "fail_consequences": [
            f"{figure['name']}按史实{death_type}"
        ],
    }


def execute_consequences(figure: dict) -> dict:
    """赐死后果 delta。"""
    delta = {"民心": -5, "宗室不满": 3}
    return delta


def dismiss_consequences(figure: dict) -> dict:
    """免职后果 delta（较轻）。"""
    delta = {"宗室不满": 1}
    return delta
