"""寿命与处置：平均寿命/自然死亡 + 死亡危机事件 + 皇权处置（赐死/免职）后果。

设计要点（见计划第3节"死亡避免系统""皇权处置"）：
- 非自然死因（暗杀/处决/战死/早病）在接近史实死亡年时触发角色级死亡危机事件。
- 死亡危机复用 event_engine 的"纯代码数值阈值判定解决"逻辑（resolve_conditions）。
- 化解后角色转按当时年代平均寿命自然死亡（重新计算自然死亡时间）。
- 皇权处置（赐死/免职）绕过死亡危机，但皆有数值与连锁后果。
"""

from __future__ import annotations

from dataclasses import dataclass

# 阶层寿命微调（士绅官员略高、军镇武将略低）
SOCIAL_CLASS_LIFESPAN_ADJUST: dict[str, int] = {
    "official": 3,
    "military": -3,
    "common": 0,
}

# 死亡危机提前可触发的年限（接近史实死亡年前 N 年可生成危机）
DEATH_CRISIS_LEAD = 1

NATURAL = "natural"


def natural_death_year(persona, config: dict, social_class: str = "official") -> int:
    """按平均寿命 + 阶层微调计算自然死亡年。"""
    base = int(config.get("game", {}).get("average_lifespan", 50))
    adj = SOCIAL_CLASS_LIFESPAN_ADJUST.get(social_class, 0)
    return persona.born_year + base + adj


@dataclass
class DeathCrisis:
    """角色级死亡危机事件（复用 event_engine 数值阈值判定）。"""

    agent_id: str
    agent_name: str
    target_year: int  # 史实死亡年
    cause_type: str  # execution | assassination | battle | illness
    cause_desc: str
    resolve_conditions: dict  # 数值阈值，如 {"安全度": ">=60"}


def is_natural_death(persona) -> bool:
    cause = (persona.death_cause or {}).get("type", NATURAL)
    return cause == NATURAL


def should_trigger_death_crisis(persona, year: int) -> bool:
    """当前年份是否进入该角色死亡危机可触发窗口。"""
    if is_natural_death(persona):
        return False
    return year >= persona.historical_death_year - DEATH_CRISIS_LEAD


def generate_death_crisis(persona, config: dict) -> DeathCrisis | None:
    """为非自然死因角色生成死亡危机事件。自然死因返回 None。"""
    cause = persona.death_cause or {}
    cause_type = cause.get("type", NATURAL)
    if cause_type == NATURAL:
        return None
    return DeathCrisis(
        agent_id=persona.id,
        agent_name=persona.name,
        target_year=persona.historical_death_year,
        cause_type=cause_type,
        cause_desc=cause.get("desc", ""),
        # MVP 简化阈值：角色安全度达标即化解（由保护/调动/施策提升）
        resolve_conditions={"安全度": ">=60"},
    )


def resolve_crisis_to_natural_death(persona, config: dict, social_class: str = "official") -> int:
    """化解死亡危机后，转按平均寿命自然死亡（重新计算自然死亡年）。"""
    return natural_death_year(persona, config, social_class)


# ---------- 皇权处置后果 ----------


def execute_consequences(target_faction: str | None = None) -> dict:
    """赐死后果：民心-, 朝野震动；相关派系忠诚-；触发后续事件（由史官生成）。

    返回 delta dict 与忠诚影响，由史官/上层合并落库。
    """
    return {
        "delta": {"民心": -10},
        "loyalty_impact": ({target_faction: -15} if target_faction else {}),
        "event_hint": "赐死重臣，朝野震动",  # 史官据此生成具体后续事件
    }


def dismiss_consequences(target_faction: str | None = None) -> dict:
    """免职后果较轻：被免者不满+, 其派系忠诚微降；心怀怨望者后续可能另投他处。"""
    return {
        "delta": {},  # 免职无直接全局数值 delta
        "loyalty_impact": ({target_faction: -5} if target_faction else {}),
        "event_hint": "免职大臣，其心或怨",
    }
