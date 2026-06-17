"""M2 核心模块测试（agent/招募/科举/任务/求见/早朝）。"""
import pytest
from pathlib import Path

from src.agents.base_agent import AgentOutput, Persona
from src.recruitment.roster import Roster, ExamSystem
from src.recruitment.lifespan import (
    compute_natural_death_year,
    trigger_death_crisis,
    execute_consequences, dismiss_consequences,
)
from src.core.tasks import TaskManager, parse_edict_to_task
from src.core.audience import AudienceQueue, AudienceRequest
from src.core.court_session import CourtSession

FIGURES_PATH = Path(__file__).resolve().parents[1] / "src" / "agents" / "personas" / "historical_figures.yaml"

# 游戏年转 AD 年（崇祯元年 = 1628）
def _ad(game_year):
    return game_year + 1627


# ─── Roster ─────────────────────────────────────────

def test_roster_filter_alive():
    # 崇祯元年 = 1628 AD（game_year + 1627 = AD_year）
    def _ad(year):
        return year + 1627

    r = Roster(FIGURES_PATH)
    alive = r.filter_alive(_ad(1))  # 1628
    ids = [f["id"] for f in alive]
    assert "yuan_chonghuan" in ids
    alive_1640 = r.filter_alive(1640)
    ids2 = [f["id"] for f in alive_1640]
    assert "yuan_chonghuan" not in ids2


def test_roster_recruit():
    r = Roster(FIGURES_PATH)
    assert r.recruit("yuan_chonghuan") is True
    assert r.get_status("yuan_chonghuan") == "active"
    # 已 active 不可再招募
    assert r.recruit("yuan_chonghuan") is False


def test_roster_dismiss_and_execute():
    r = Roster(FIGURES_PATH)
    r.recruit("yuan_chonghuan")
    r.dismiss("yuan_chonghuan")
    assert r.get_status("yuan_chonghuan") == "dismissed"
    r.execute("yuan_chonghuan")
    assert r.get_status("yuan_chonghuan") == "dead"


def test_roster_filter_recruitable():
    r = Roster(FIGURES_PATH)
    rec = r.filter_recruitable(_ad(1))
    ids = [f["id"] for f in rec]
    assert "yuan_chonghuan" in ids
    r.recruit("yuan_chonghuan")
    rec2 = r.filter_recruitable(1)
    ids2 = [f["id"] for f in rec2]
    assert "yuan_chonghuan" not in ids2


# ─── Exam ───────────────────────────────────────────

def test_exam_year():
    e = ExamSystem(3)
    assert e.is_exam_year(3) is True
    assert e.is_exam_year(2) is False
    assert e.is_exam_year(6) is True


def test_exam_generate():
    e = ExamSystem()
    jinshi = e.generate_jinshi(3)
    assert len(jinshi) == 3
    assert all("id" in j for j in jinshi)


# ─── Lifespan ───────────────────────────────────────

def test_lifespan():
    year = compute_natural_death_year(1584, lifespan=50)
    assert year >= 1629
    assert year <= 1639  # 50 ± 5


def test_death_crisis():
    fig = {"id": "test", "name": "某人",
           "historical_death_year": 3,
           "death_cause": {"type": "execution"}}
    # 未到死亡窗口
    crisis1 = trigger_death_crisis(fig, 1)
    assert crisis1 is None
    # 到窗口
    crisis2 = trigger_death_crisis(fig, 3)
    assert crisis2 is not None
    assert crisis2["type"] == "death_crisis"


def test_natural_no_crisis():
    fig = {"id": "test", "name": "某人",
           "historical_death_year": 10,
           "death_cause": {"type": "natural"}}
    crisis = trigger_death_crisis(fig, 10)
    assert crisis is None


def test_execute_consequences():
    d = execute_consequences({"id": "test"})
    assert "民心" in d
    assert d["民心"] < 0


# ─── Tasks ──────────────────────────────────────────

def test_task_manager():
    tm = TaskManager()
    t = tm.create("minister_finance", "清查欠赋",
                  ["田赋", "国库"], "崇祯1年6月")
    assert t.status == "pending"
    tm.update_progress(t.task_id, 1.0)
    assert tm.tasks[t.task_id].status == "done"


def test_parse_edict():
    tm = TaskManager()
    t = parse_edict_to_task("清查各省欠赋", "minister_finance", tm)
    assert t is not None
    assert "欠赋" in t.task


# ─── Audience ───────────────────────────────────────

def test_audience_build_queue():
    q = AudienceQueue()
    outputs = [
        {"agent_id": "a1", "want_audience": True, "audience_topic": "言边事"},
        {"agent_id": "a2", "want_audience": False},
    ]
    reqs = q.build_from_agent_outputs(outputs)
    assert len(reqs) == 1
    assert reqs[0].agent_id == "a1"


def test_audience_deny():
    q = AudienceQueue()
    req = AudienceRequest(agent_id="a1", topic="言边事")
    q.requests = [req]
    result = q.deny(req)
    assert result["loyalty_change"] == -5


# ─── CourtSession ───────────────────────────────────

def test_court_session():
    c = CourtSession()
    c.open("议赈灾", "陕西旱灾", ["民变预兆"], ["户部尚书求见:言财用"])
    c.speak("minister_finance", "臣请拨银十万赈济陕西")
    c.speak("common_people", "陕西民心已失，速赈为宜", stance="for")
    assert len(c.log) == 2
    log = c.close()
    assert len(log) == 2
    assert c.log == []  # 关闭后清空
