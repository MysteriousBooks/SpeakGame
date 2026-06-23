"""M2b-roster: 角色注册表/状态机/招募池/难度可见性 测试。"""

import pytest

from src.agents.base_agent import PersonaCard
from src.llm.provider import MockProvider
from src.recruitment.roster import (
    ACTIVE,
    AVAILABLE,
    DEAD,
    DISMISSED,
    Roster,
    recruit_display,
)


def make_figures():
    return [
        PersonaCard.from_dict({
            "id": "yuan", "name": "袁崇焕", "born_year": 1584,
            "historical_death_year": 1630,
            "death_cause": {"type": "execution", "desc": "凌迟"},
            "faction": "辽东系", "skills": ["军事"],
            "historical_alignment": "争议", "personality": "刚烈",
            "recruitment_condition": "辽东紧张可召",
        }),
        PersonaCard.from_dict({
            "id": "later", "name": "晚生者", "born_year": 1640,
            "historical_death_year": 1700,
            "death_cause": {"type": "natural"}, "skills": [],
            "personality": "", "recruitment_condition": "",
        }),
    ]


def make_roster():
    return Roster({"game": {"difficulty": "normal"}}, historical_figures=make_figures())


# ---------- 状态机与招募 ----------


def test_roster_loads_figures_available():
    r = make_roster()
    assert r.status_of("yuan") == AVAILABLE
    assert r.status_of("later") == AVAILABLE


def test_available_for_recruit_filters_by_year():
    r = make_roster()
    # 崇祯元年(=1628)：袁崇焕 1584~1630 在世，晚生者 1640 出生未在世
    avail = r.available_for_recruit(1)
    ids = {p.id for p in avail}
    assert "yuan" in ids
    assert "later" not in ids


def test_available_for_recruit_year_progress():
    r = make_roster()
    # 崇祯3年(1630)：袁崇焕已死(1630不在区间)
    avail = r.available_for_recruit(3)
    assert all(p.id != "yuan" for p in avail)
    # 崇祯14年(1641)：晚生者(1640生)在世
    avail14 = r.available_for_recruit(14)
    assert any(p.id == "later" for p in avail14)


def test_recruit_changes_status_to_active():
    r = make_roster()
    agent = r.recruit("yuan", MockProvider(), era="崇祯1年1月")
    assert r.status_of("yuan") == ACTIVE
    assert agent.name == "袁崇焕"
    assert len(r.active_agents()) == 1


def test_recruit_dismissed_then_reinstate():
    r = make_roster()
    r.recruit("yuan", MockProvider(), era="崇祯1年1月")
    r.dismiss("yuan")
    assert r.status_of("yuan") == DISMISSED
    assert r.active_agents() == []
    # dismissed 保留记忆，可重新启用
    r.reinstate("yuan", MockProvider(), era="崇祯1年2月")
    assert r.status_of("yuan") == ACTIVE
    assert len(r.active_agents()) == 1


def test_dismiss_preserves_memory():
    r = make_roster()
    agent = r.recruit("yuan", MockProvider(), era="崇祯1年1月")
    agent.add_factual("帝许诺升官", ["承诺"], turn=2)
    r.dismiss("yuan")
    inst = r.get("yuan")
    assert inst.factual.search(["承诺"])  # 记忆保留


def test_recruit_invalid_status_raises():
    r = make_roster()
    r.recruit("yuan", MockProvider(), era="崇祯1年1月")
    with pytest.raises(ValueError):
        r.recruit("yuan", MockProvider(), era="崇祯1年1月")  # 已 active


def test_kill_changes_to_dead():
    r = make_roster()
    r.recruit("yuan", MockProvider(), era="崇祯1年1月")
    r.kill("yuan")
    assert r.status_of("yuan") == DEAD
    assert r.active_agents() == []


def test_kill_unknown_raises():
    r = make_roster()
    with pytest.raises(KeyError):
        r.kill("nobody")


# ---------- 难度可见性 ----------


def test_recruit_display_easy_shows_meta():
    p = make_figures()[0]
    info = recruit_display(p, "easy")
    assert info["historical_alignment"] == "争议"
    assert info["skills"] == ["军事"]
    assert info["death_cause"]["type"] == "execution"


def test_recruit_display_normal_hides_meta():
    p = make_figures()[0]
    info = recruit_display(p, "normal")
    assert info["skills"] == ["军事"]
    assert "historical_alignment" not in info
    assert "death_cause" not in info


def test_recruit_display_hard_zero_spoiler():
    p = make_figures()[0]
    info = recruit_display(p, "hard")
    assert "skills" not in info
    assert "historical_alignment" not in info
    assert "death_cause" not in info
    assert info["name"] == "袁崇焕"


# ---------- 虚构角色注入 ----------


def test_add_fictional_active():
    r = make_roster()
    persona = PersonaCard(id="jinshi_1", name="新科进士甲", born_year=1600, historical_death_year=1650)
    agent = r.add_fictional(persona, MockProvider(), era="崇祯3年4月")
    assert r.status_of("jinshi_1") == ACTIVE
    assert agent in r.active_agents()


def test_add_fictional_duplicate_id_raises():
    r = make_roster()
    persona = PersonaCard(id="yuan", name="重名", born_year=1600, historical_death_year=1650)
    with pytest.raises(ValueError):
        r.add_fictional(persona, MockProvider(), era="崇祯1年1月")


# ---------- 人才库 ----------


def test_get_talent_pool_includes_available_and_dismissed():
    r = make_roster()
    # 初始：袁崇焕 available
    pool = r.get_talent_pool()
    ids = {p["id"] for p in pool}
    assert "yuan" in ids
    assert "later" in ids
    # 招募后 dismiss
    r.recruit("yuan", MockProvider(), era="崇祯1年1月")
    r.dismiss("yuan")
    pool2 = r.get_talent_pool()
    assert any(p["id"] == "yuan" and p["status"] == "dismissed" for p in pool2)


def test_talent_pool_has_gender_and_weaknesses():
    r = make_roster()
    pool = r.get_talent_pool()
    for p in pool:
        assert "gender" in p
        assert "weaknesses" in p


# ---------- find_by_name ----------


def test_find_by_name_finds_active():
    r = make_roster()
    r.recruit("yuan", MockProvider(), era="崇祯1年1月")
    inst = r.find_by_name("袁崇焕")
    assert inst is not None
    assert inst.persona.id == "yuan"


def test_find_by_name_returns_none_for_missing():
    r = make_roster()
    assert r.find_by_name("不存在的人") is None


def test_find_by_name_finds_available():
    r = make_roster()
    inst = r.find_by_name("晚生者")
    assert inst is not None
    assert inst.status == AVAILABLE
