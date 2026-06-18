"""M2b-lifespan: 死亡危机/自然死亡/皇权处置后果 测试。"""

from src.agents.base_agent import PersonaCard
from src.recruitment.lifespan import (
    DeathCrisis,
    dismiss_consequences,
    execute_consequences,
    generate_death_crisis,
    is_natural_death,
    natural_death_year,
    resolve_crisis_to_natural_death,
    should_trigger_death_crisis,
)


def make_yuan():
    return PersonaCard.from_dict({
        "id": "yuan_chonghuan", "name": "袁崇焕", "born_year": 1584,
        "historical_death_year": 1630,
        "death_cause": {"type": "execution", "desc": "凌迟"},
    })


def make_wen():
    # 温体仁：病亡（自然）
    return PersonaCard.from_dict({
        "id": "wen", "name": "温体仁", "born_year": 1573,
        "historical_death_year": 1639,
        "death_cause": {"type": "natural", "desc": "病亡"},
    })


CONFIG = {"game": {"average_lifespan": 50}}


# ---------- 自然死亡年 ----------


def test_natural_death_year_official():
    yuan = make_yuan()
    # 1584 + 50 + 3(官员) = 1637
    assert natural_death_year(yuan, CONFIG, "official") == 1637


def test_natural_death_year_military_lower():
    yuan = make_yuan()
    # 1584 + 50 - 3(武将) = 1631
    assert natural_death_year(yuan, CONFIG, "military") == 1631


def test_natural_death_year_common():
    yuan = make_yuan()
    assert natural_death_year(yuan, CONFIG, "common") == 1634


# ---------- 死因判定 ----------


def test_is_natural_death():
    assert is_natural_death(make_wen()) is True
    assert is_natural_death(make_yuan()) is False


def test_should_trigger_death_crisis_non_natural_near_death_year():
    yuan = make_yuan()
    # 史实死亡年 1630，lead=1 -> 1629 起可触发
    assert should_trigger_death_crisis(yuan, 1628) is False
    assert should_trigger_death_crisis(yuan, 1629) is True
    assert should_trigger_death_crisis(yuan, 1630) is True


def test_should_trigger_death_crisis_natural_never():
    wen = make_wen()
    assert should_trigger_death_crisis(wen, 1638) is False


# ---------- 死亡危机事件 ----------


def test_generate_death_crisis_non_natural():
    yuan = make_yuan()
    crisis = generate_death_crisis(yuan, CONFIG)
    assert isinstance(crisis, DeathCrisis)
    assert crisis.agent_id == "yuan_chonghuan"
    assert crisis.cause_type == "execution"
    assert crisis.target_year == 1630
    assert "安全度" in crisis.resolve_conditions


def test_generate_death_crisis_natural_returns_none():
    wen = make_wen()
    assert generate_death_crisis(wen, CONFIG) is None


def test_resolve_crisis_to_natural_death():
    yuan = make_yuan()
    # 化解后转自然死亡：1584 + 50 + 3 = 1637
    assert resolve_crisis_to_natural_death(yuan, CONFIG, "official") == 1637


# ---------- 皇权处置后果 ----------


def test_execute_consequences_has_delta_and_loyalty():
    res = execute_consequences("辽东系")
    assert res["delta"]["民心"] == -10
    assert res["loyalty_impact"]["辽东系"] == -15
    assert res["event_hint"]


def test_execute_consequences_no_faction():
    res = execute_consequences(None)
    assert res["loyalty_impact"] == {}
    assert res["delta"]["民心"] == -10


def test_dismiss_consequences_light():
    res = dismiss_consequences("辽东系")
    assert res["delta"] == {}  # 免职无直接全局数值 delta
    assert res["loyalty_impact"]["辽东系"] == -5
    assert res["event_hint"]


def test_dismiss_consequences_no_faction():
    res = dismiss_consequences(None)
    assert res["loyalty_impact"] == {}
