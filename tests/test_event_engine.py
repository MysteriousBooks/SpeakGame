"""M3-event_engine: 预兆 + 史实时间线触发 + 数值阈值判定 测试。"""

import pytest

from src.events.event_engine import (
    EventEngine,
    HistoricalEvent,
    _check_condition,
    parse_condition,
    parse_trigger_time,
)

# ---------- 解析工具 ----------


def test_parse_trigger_time():
    assert parse_trigger_time("崇祯1年1月") == 0  # 开局
    assert parse_trigger_time("崇祯1年2月") == 1
    assert parse_trigger_time("崇祯2年10月") == 21
    assert parse_trigger_time("崇祯3年1月") == 24


def test_parse_condition():
    assert parse_condition(">=70") == (">=", 70)
    assert parse_condition("<=20") == ("<=", 20)
    assert parse_condition(">50") == (">", 50)
    assert parse_condition("<30") == ("<", 30)


def test_parse_condition_invalid():
    with pytest.raises(ValueError):
        parse_condition("约70")


def test_check_condition():
    assert _check_condition(75, ">=70") is True
    assert _check_condition(65, ">=70") is False
    assert _check_condition(20, "<=30") is True
    assert _check_condition(35, "<=30") is False


# ---------- 加载 ----------


def test_load_historical_events():
    from src.llm.provider import load_config

    eng = EventEngine(load_config("config.yaml"))
    ids = {e.id for e in eng.events}
    assert {"chu_chu_wei_zhong_xian", "shan_xi_han_zai", "ji_si_zhi_bian", "ke_ju"} <= ids


def test_ji_si_trigger_month():
    from src.llm.provider import load_config

    eng = EventEngine(load_config("config.yaml"))
    ji_si = next(e for e in eng.events if e.id == "ji_si_zhi_bian")
    assert ji_si.trigger_month == 21  # 崇祯2年10月
    assert ji_si.premonition_lead == 3


# ---------- 开局挂起 ----------


def test_trigger_initial_hangs_opening_events():
    from src.llm.provider import load_config

    eng = EventEngine(load_config("config.yaml"))
    eng.trigger_initial()
    ids = {ae.event.id for ae in eng.active}
    assert "chu_chu_wei_zhong_xian" in ids  # 铲除魏忠贤开局
    assert "shan_xi_han_zai" in ids  # 陕西旱灾开局
    assert "ji_si_zhi_bian" not in ids  # 己巳之变崇祯2年10月才触发


# ---------- 按史实时间线触发 ----------


def test_trigger_by_months_ji_si():
    from src.llm.provider import load_config

    eng = EventEngine(load_config("config.yaml"))
    eng.trigger_initial()
    # 推进到崇祯2年10月（month_index=21）
    newly = eng.trigger_by_months([21])
    ids = {e.id for e in newly}
    assert "ji_si_zhi_bian" in ids
    assert any(ae.event.id == "ji_si_zhi_bian" for ae in eng.active)


def test_trigger_by_months_no_duplicate():
    from src.llm.provider import load_config

    eng = EventEngine(load_config("config.yaml"))
    eng.trigger_initial()
    eng.trigger_by_months([21])
    # 再次推进同月不应重复挂起
    newly = eng.trigger_by_months([21])
    assert all(e.id != "ji_si_zhi_bian" for e in newly)


# ---------- 预兆 ----------


def test_upcoming_premonitions_ji_si():
    from src.llm.provider import load_config

    eng = EventEngine(load_config("config.yaml"))
    eng.trigger_initial()
    # 崇祯2年7月（month_index=18），距己巳之变(21)=3月 -> 远期
    prems = eng.upcoming_premonitions(18)
    ji_si_prem = [p for p in prems if p["event_id"] == "ji_si_zhi_bian"]
    assert len(ji_si_prem) == 1
    assert ji_si_prem[0]["level"] == "远期"


def test_premonition_level_escalates():
    from src.llm.provider import load_config

    eng = EventEngine(load_config("config.yaml"))
    # 距离=2 -> 近期
    assert eng.upcoming_premonitions(19)[0]["level"] == "近期"
    # 距离=1 -> 迫近
    assert eng.upcoming_premonitions(20)[0]["level"] == "迫近"


def test_premonitions_exclude_triggered():
    from src.llm.provider import load_config

    eng = EventEngine(load_config("config.yaml"))
    eng.trigger_initial()
    eng.trigger_by_months([21])  # 己巳之变已触发
    prems = [p for p in eng.upcoming_premonitions(20) if p["event_id"] == "ji_si_zhi_bian"]
    assert prems == []  # 已触发不再出预兆


# ---------- 解决判定（纯代码数值阈值） ----------


def test_check_resolve_when_conditions_met():
    from src.llm.provider import load_config

    eng = EventEngine(load_config("config.yaml"))
    eng.trigger_initial()
    # 陕西旱灾 resolve: 陕西_民心>=60 且 国库>=200000
    values = {"陕西_民心": 65, "国库": 300000}
    resolved = eng.check_resolve(values)
    ids = {ae.event.id for ae in resolved}
    assert "shan_xi_han_zai" in ids
    assert any(ae.resolved for ae in eng.active if ae.event.id == "shan_xi_han_zai")


def test_check_resolve_not_met_keeps_pending():
    from src.llm.provider import load_config

    eng = EventEngine(load_config("config.yaml"))
    eng.trigger_initial()
    values = {"陕西_民心": 40, "国库": 300000}  # 民心不达标
    resolved = eng.check_resolve(values)
    assert all(ae.event.id != "shan_xi_han_zai" for ae in resolved)
    ae = next(ae for ae in eng.active if ae.event.id == "shan_xi_han_zai")
    assert ae.resolved is False


def test_check_resolve_wei_zhong_xian():
    from src.llm.provider import load_config

    eng = EventEngine(load_config("config.yaml"))
    eng.trigger_initial()
    values = {"朝堂清洗度": 65}
    resolved = eng.check_resolve(values)
    assert any(ae.event.id == "chu_chu_wei_zhong_xian" for ae in resolved)


def test_check_resolve_skips_empty_conditions():
    """科举 resolve_conditions 为空，不自动解决（需玩家操作）。"""
    from src.llm.provider import load_config

    eng = EventEngine(load_config("config.yaml"))
    eng.trigger_by_months([24])  # 科举崇祯3年=24
    resolved = eng.check_resolve({})
    assert all(ae.event.id != "ke_ju" for ae in resolved)
    ae = next(ae for ae in eng.active if ae.event.id == "ke_ju")
    assert ae.resolved is False


def test_mark_resolved_manually():
    from src.llm.provider import load_config

    eng = EventEngine(load_config("config.yaml"))
    eng.trigger_by_months([24])
    eng.mark_resolved("ke_ju")
    assert next(ae for ae in eng.active if ae.event.id == "ke_ju").resolved is True


# ---------- 恶化 ----------


def test_apply_fail_consequences():
    # 用自定义单事件隔离测试，避免开局多事件合并 delta
    shanxi = HistoricalEvent(
        id="shanxi", name="陕西旱灾", trigger_time="崇祯1年1月", trigger_month=0,
        premonition_lead=0,
        resolve_conditions={"陕西_民心": ">=60", "国库": ">=200000"},
        fail_consequences=[{"desc": "民变升级", "delta": {"陕西_民心": -15, "民心": -5}}],
    )
    eng = EventEngine({}, events=[shanxi])
    eng.trigger_initial()
    delta = eng.apply_fail_consequences({"陕西_民心": 30, "民心": 50}, current_month=5)
    assert delta == {"陕西_民心": -15, "民心": -5}


def test_apply_fail_consequences_skips_before_trigger():
    shanxi = HistoricalEvent(
        id="shanxi", name="陕西旱灾", trigger_month=0, premonition_lead=0,
        resolve_conditions={"陕西_民心": ">=60"},
        fail_consequences=[{"desc": "x", "delta": {"陕西_民心": -15}}],
    )
    eng = EventEngine({}, events=[shanxi])
    eng.trigger_initial()
    # current_month=0（开局当月）未过期
    delta = eng.apply_fail_consequences({}, current_month=0)
    assert delta == {}


def test_apply_fail_consequences_skips_resolved():
    wei = HistoricalEvent(
        id="wei", name="铲除魏忠贤", trigger_month=0, premonition_lead=0,
        resolve_conditions={"朝堂清洗度": ">=60"},
        fail_consequences=[{"desc": "阉党未除", "delta": {"民心": -2}}],
    )
    eng = EventEngine({}, events=[wei])
    eng.trigger_initial()
    eng.check_resolve({"朝堂清洗度": 65})  # 铲除魏忠贤已解决
    delta = eng.apply_fail_consequences({}, current_month=5)
    assert delta == {}  # 已解决的不恶化


# ---------- 序列化 ----------


def test_event_engine_serialize_roundtrip():
    from src.llm.provider import load_config

    eng = EventEngine(load_config("config.yaml"))
    eng.trigger_initial()
    eng.trigger_by_months([21])
    data = eng.to_dict()
    restored = EventEngine.from_dict(data, load_config("config.yaml"))
    assert len(restored.active) == len(eng.active)
    assert any(ae.event.id == "ji_si_zhi_bian" for ae in restored.active)


def test_active_unresolved():
    from src.llm.provider import load_config

    eng = EventEngine(load_config("config.yaml"))
    eng.trigger_initial()
    assert len(eng.active_unresolved()) >= 2
    eng.check_resolve({"朝堂清洗度": 65})
    assert all(ae.event.id != "chu_chu_wei_zhong_xian" for ae in eng.active_unresolved())
