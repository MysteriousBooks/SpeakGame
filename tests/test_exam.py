"""M2b-exam: 科举系统 三级流程 + 进士人格生成 + 难度可见性 测试。"""

from src.llm.provider import MockProvider
from src.recruitment.exam import (
    Candidate,
    ExamSystem,
    exam_display,
    generate_candidates,
    generate_jinshi_persona,
)
from src.recruitment.roster import Roster

CONFIG = {"game": {"average_lifespan": 50, "exam_cycle_years": 3, "difficulty": "normal"}}


# ---------- 考生生成 ----------


def test_generate_candidates_count_and_fields():
    cands = generate_candidates(5, seed=42)
    assert len(cands) == 5
    for c in cands:
        assert c.name
        assert c.origin_province
        assert c.answer_text
        assert c.ability_tendency
        assert c.answer_style
        assert c.id.startswith("candidate_")


def test_generate_candidates_unique_names():
    cands = generate_candidates(20, seed=1)
    names = [c.name for c in cands]
    assert len(set(names)) == len(names)  # 不重复


# ---------- 难度可见性 ----------


def make_candidate():
    return Candidate(
        id="c1", name="张三", origin_province="陕西",
        answer_text="臣对：经世之论", ability_tendency="经世",
        background="寒门苦读", answer_style="刚直",
    )


def test_exam_display_easy_shows_ability():
    info = exam_display(make_candidate(), "easy")
    assert info["ability_tendency"] == "经世"
    assert info["origin_province"] == "陕西"
    assert "answer_text" in info


def test_exam_display_normal_hides_ability():
    info = exam_display(make_candidate(), "normal")
    assert info["origin_province"] == "陕西"
    assert "ability_tendency" not in info
    assert "answer_text" in info


def test_exam_display_hard_only_answer():
    info = exam_display(make_candidate(), "hard")
    assert "answer_text" in info
    assert "ability_tendency" not in info
    assert "origin_province" not in info


# ---------- 进士人格生成 ----------


def test_generate_jinshi_persona_uses_real_year():
    cand = make_candidate()
    p = generate_jinshi_persona(cand, rank=1, config=CONFIG, chongzhen_year=3)
    # 崇祯3年=1630，状元 rank=1 -> age=25+1%10=26 -> born=1604
    assert p.name == "张三"
    assert p.born_year == 1630 - 26
    assert p.historical_death_year == p.born_year + 50 + 3
    assert p.death_cause == {"type": "natural", "desc": "自然病亡"}
    assert p.historical_alignment == ""  # 无历史评价
    assert "崇祯3年" in p.recruitment_condition
    assert "状元" in p.recruitment_condition


def test_generate_jinshi_persona_no_meta_info():
    cand = make_candidate()
    p = generate_jinshi_persona(cand, rank=2, config=CONFIG, chongzhen_year=3)
    text = p.to_prompt_card()
    # 人格卡不含死因/正反派（本就无）
    assert "张三" in text
    assert p.historical_alignment == ""


def test_generate_jinshi_persona_skills_by_ability():
    cand_jing = Candidate("c", "李四", "浙江", "对", "经世", "耕读", "务实")
    p = generate_jinshi_persona(cand_jing, rank=1, config=CONFIG, chongzhen_year=6)
    assert "经世" in p.skills
    assert "理财" in p.skills  # 经世附理财

    cand_bing = Candidate("c2", "王五", "山西", "对", "兵略", "边地", "宏阔")
    p2 = generate_jinshi_persona(cand_bing, rank=1, config=CONFIG, chongzhen_year=6)
    assert "兵略" in p2.skills
    assert "军事" in p2.skills


# ---------- 三级流程 ----------


def test_exam_system_is_exam_year():
    exam = ExamSystem(CONFIG)
    assert exam.is_exam_year(3) is True  # 崇祯三年首科
    assert exam.is_exam_year(6) is True
    assert exam.is_exam_year(9) is True
    assert exam.is_exam_year(1) is False
    assert exam.is_exam_year(2) is False
    assert exam.is_exam_year(4) is False


def test_exam_system_three_stages():
    exam = ExamSystem(CONFIG)
    juren = exam.xiangshi(3, n=20, seed=7)
    assert len(juren) == 20
    gongshi = exam.huishi(juren, n_passed=8)
    assert len(gongshi) == 8
    # 殿试按玩家给出的 id 顺序定名次
    ranking = [gongshi[0].id, gongshi[1].id, gongshi[2].id]
    ranked = exam.dianshi(gongshi, ranking=ranking)
    assert ranked[0][1] == 1  # 状元
    assert ranked[1][1] == 2
    assert ranked[2][1] == 3
    # 其余追加为二甲
    assert ranked[3][1] >= 4


def test_exam_system_dianshi_default_ranking():
    exam = ExamSystem(CONFIG)
    gongshi = exam.huishi(exam.xiangshi(3, n=10, seed=1), n_passed=5)
    ranked = exam.dianshi(gongshi)
    assert [r[1] for r in ranked] == [1, 2, 3, 4, 5]


# ---------- 授官加入 roster ----------


def test_appoint_adds_agents_to_roster():
    exam = ExamSystem(CONFIG)
    roster = Roster(CONFIG)
    assert len(roster.active_agents()) == 0
    gongshi = exam.huishi(exam.xiangshi(3, n=10, seed=3), n_passed=3)
    ranked = exam.dianshi(gongshi, ranking=[gongshi[0].id, gongshi[1].id, gongshi[2].id])
    agents = exam.appoint(ranked, roster, MockProvider(), year=3, era="崇祯3年4月")
    assert len(agents) == 3
    assert len(roster.active_agents()) == 3
    # 状元名次=1，授官
    assert roster.status_of(agents[0].id) == "active"
