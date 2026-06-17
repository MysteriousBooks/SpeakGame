"""事件引擎单元测试（纯逻辑，不需 LLM Key）。"""
import json
from pathlib import Path
import pytest

from src.core.world_state import WorldState
from src.events.event_engine import EventEngine

# 使用实际的事件文件
EVENTS_PATH = Path(__file__).resolve().parents[1] / "events" / "historical_events.yaml"


def _make_eng() -> EventEngine:
    return EventEngine(EVENTS_PATH)


def test_event_resolution_pure_code():
    """事件解决=纯代码数值阈值判定，不调 LLM。"""
    s = WorldState()
    eng = _make_eng()
    # 触发开局事件
    due = eng.due_events(s)
    assert len(due) >= 2  # 至少铲除魏忠贤+陕西旱灾
    s.active_events = [e["id"] for e in due]
    # 初始数值不满足陕西旱灾解决条件(陕西_民心>=60 且 国库>=500000)
    resolved, active = eng.check_resolutions(s)
    assert "shaanxi_drought_rebellion" not in resolved
    # 推高陕西民心、国库后应解决
    s.apply({"陕西_民心": 30})  # 30->60
    s.values["国库"] = 500_000
    resolved2, _ = eng.check_resolutions(s)
    assert "shaanxi_drought_rebellion" in resolved2


def test_fail_consequences_applied():
    s = WorldState()
    eng = _make_eng()
    s.active_events = ["shaanxi_drought_rebellion"]
    before = s.get("陕西_民心")
    eng.apply_fail_consequences(s)
    assert s.get("陕西_民心") < before  # 民心下降


def test_due_events_by_time():
    s = WorldState()
    eng = _make_eng()
    # 崇祯元年应触发开局事件
    due1 = eng.due_events(s)
    ids1 = [e["id"] for e in due1]
    assert "shaanxi_drought_rebellion" in ids1
    # 己巳之变（崇祯2年10月）还未到
    assert "ji_si_zhi_bian" not in ids1


def test_trigger_due_events():
    s = WorldState()
    eng = _make_eng()
    triggered = eng.trigger_events(s)
    assert len(triggered) >= 2
    assert "shaanxi_drought_rebellion" in s.active_events


def test_premonition_events():
    s = WorldState()
    eng = _make_eng()
    # 开局：己巳之变（崇祯2年10月）距崇祯元年超过3个月预兆窗口
    s.active_events = ["purge_wei_zhongxian", "shaanxi_drought_rebellion"]
    pre = eng.events_in_premonition(s)
    pre_ids = [e["id"] for e in pre]
    # 已激活/已解决的不在预兆列表
    assert "shaanxi_drought_rebellion" not in pre_ids
