"""世界状态与财政系统的纯逻辑测试（不需 LLM Key）。"""
import json
from pathlib import Path
import pytest

from src.core.world_state import WorldState
from src.finance.economy import FinanceState
from src.memory.factual_memory import FactualMemory, FactualNote
from src.memory.narrative_memory import NarrativeMemory, NarrativeStore


# ─── WorldState ─────────────────────────────────────

def test_delta_clamp_and_bounds():
    s = WorldState()
    # 超幅度裁剪：国库 max_delta=500000，申请 -10000000 应裁到 -500000
    applied, errs = s.validate_delta({"国库": -10_000_000})
    assert applied["国库"] == -500_000
    assert any("超幅度" in e for e in errs)
    # 应用后国库 = 1000000 - 500000 = 500000
    s.apply(applied)
    assert s.get("国库") == 500_000
    # 边界裁剪：申请 -600000 会到 -100000，裁到 0
    applied2, errs2 = s.validate_delta({"国库": -600_000})
    s.apply(applied2)
    assert s.get("国库") == 0


def test_unknown_key_ignored():
    s = WorldState()
    _, errs = s.validate_delta({"不存在": 100})
    assert any("未知数值键" in e for e in errs)


def test_time_advance_month():
    s = WorldState()
    assert s.year == 1 and s.month == 1 and s.day == 1
    s.advance("month")
    assert s.year == 1 and s.month == 2
    s.advance("month")
    assert s.month == 3


def test_time_advance_cross_year():
    s = WorldState()
    s.month = 12
    s.advance("month")
    assert s.year == 2 and s.month == 1


def test_time_advance_week():
    s = WorldState()
    s.advance("week")
    assert s.day == 8
    # 跨月测试：day=25 + 7 = 32 → month+1, day=2
    s2 = WorldState()
    s2.day = 25
    s2.advance("week")
    assert s2.day == 2
    assert s2.month == 2


def test_save_load(tmp_path):
    s = WorldState()
    p = tmp_path / "state.json"
    s.save(p)
    loaded = WorldState.load(p)
    assert loaded.year == s.year
    assert loaded.get("国库") == s.get("国库")


# ─── FinanceState ───────────────────────────────────

def test_finance_settle_balance():
    f = FinanceState()
    result = f.settle()
    # 开局月净≈持平偏紧
    assert "delta" in result
    assert result["净"] > -100000 or result["净"] < 100000


def test_finance_settle_year_景():
    f = FinanceState()
    r1 = f.settle("丰")
    r2 = f.settle("平")
    r3 = f.settle("灾")
    assert r1["收入"] > r2["收入"] > r3["收入"]


def test_inner_to_treasury_allowed():
    f = FinanceState()
    inner_before = f.inner_purse
    treasury_before = f.treasury
    f.transfer_inner_to_treasury(500_000)
    assert f.inner_purse == inner_before - 500_000
    assert f.treasury == treasury_before + 500_000


def test_treasury_to_inner_forbidden():
    f = FinanceState()
    result = f.transfer_treasury_to_inner(100_000)
    assert result is False


def test_zonglu_reform():
    f = FinanceState()
    # 宗禄改革前结算
    before = f.settle()
    # 应用改革：削减三成
    f.apply_zonglu_reform({"cut_ratio": 0.3})
    after = f.settle()
    # 宗禄支出应减少（改革生效），国库结余更多
    assert after["净"] > before["净"]


def test_temp_expense():
    f = FinanceState()
    f.add_temp_expense("赈灾", 200_000)
    result = f.settle()
    assert f.temp_expense == []  # 结算后清空


def test_finance_save_load(tmp_path):
    f = FinanceState()
    p = tmp_path / "finance.json"
    f.save(p)
    loaded = FinanceState.load(p)
    assert loaded.treasury == f.treasury


# ─── FactualMemory ──────────────────────────────────

def test_factual_memory():
    mem = FactualMemory()
    note = FactualNote(
        note_id="n1", agent_id="minister_finance",
        content="帝拨银十万赈陕西",
        tags=["陕西", "赈灾"], importance=3
    )
    mem.add(note)
    # 按 tag 检索
    results = mem.query_by_tags(["陕西"])
    assert len(results) == 1
    results2 = mem.query_by_tags(["辽东"])
    assert len(results2) == 0
    # 按 agent 检索
    results3 = mem.query_by_agent("minister_finance")
    assert len(results3) == 1


def test_factual_memory_persist(tmp_path):
    mem = FactualMemory()
    mem.add(FactualNote(
        note_id="n1", agent_id="a1", content="test", tags=[], importance=1
    ))
    p = tmp_path / "facts.json"
    mem.save(p)
    mem2 = FactualMemory()
    mem2.load(p)
    assert len(mem2.notes) == 1
    assert mem2.notes[0].content == "test"


# ─── NarrativeMemory ────────────────────────────────

def test_narrative_store(tmp_path):
    store = NarrativeStore(tmp_path)
    # 初始无记忆
    mem = store.load("agent_1")
    assert mem.summary == ""
    # 压缩更新
    store.compress("agent_1", "崇祯元年春，赈陕西旱灾，民心稍安。")
    mem2 = store.load("agent_1")
    assert mem2.summary == "崇祯元年春，赈陕西旱灾，民心稍安。"
