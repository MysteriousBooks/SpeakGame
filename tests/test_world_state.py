"""M1a: world_state 数值层 + delta 校验 + 时间推进 测试。"""

import pytest

from src.core.world_state import (
    DAYS_PER_TURN,
    Bounds,
    WorldState,
)


def make_state(values=None, bounds=None):
    """便捷构造：默认 bounds 与测试数值。"""
    bounds = bounds or {
        "国库": Bounds(0, 10_000_000, 500_000),
        "民心": Bounds(0, 100, 30),
        "军力": Bounds(0, 100, 20),
    }
    values = values or {"国库": 1_000_000, "民心": 50, "军力": 60}
    return WorldState(values=values, bounds=bounds), bounds


# ---------- initial ----------


def test_initial_from_config():
    from src.llm.provider import load_config

    cfg = load_config("config.yaml")
    ws = WorldState.initial(cfg)
    assert ws.values["国库"] == 1_000_000
    assert ws.values["内帑"] == 5_000_000
    assert ws.values["朝堂清洗度"] == 0
    assert ws.values["陕西_民心"] == 30
    assert ws.era == "崇祯"
    assert (ws.start_year, ws.start_month) == (1, 1)
    # bounds 加载完整
    assert set(ws.bounds.keys()) >= {"国库", "民心", "军力", "宗室不满", "陕西_人口"}


# ---------- apply_delta ----------


def test_apply_delta_normal():
    ws, _ = make_state()
    res = ws.apply_delta({"国库": -100_000, "民心": 5})
    assert res.applied["国库"] == -100_000
    assert res.applied["民心"] == 5
    assert ws.values["国库"] == 900_000
    assert ws.values["民心"] == 55
    assert res.clipped == {}


def test_apply_delta_max_delta_clips():
    # 民心 max_delta=30，传 +50 应裁剪到 +30
    ws, _ = make_state()
    res = ws.apply_delta({"民心": 50})
    assert res.applied["民心"] == 30
    assert ws.values["民心"] == 80
    assert "民心" in res.clipped
    assert "max_delta" in res.clipped["民心"]


def test_apply_delta_negative_max_delta_clips():
    ws, _ = make_state()
    res = ws.apply_delta({"民心": -50})
    assert res.applied["民心"] == -30
    assert ws.values["民心"] == 20


def test_apply_delta_clamp_to_min():
    # 民心 50 - 30（已裁剪）= 20，再 -30 = -10 -> clamp 0
    ws, _ = make_state(values={"民心": 5, "国库": 1_000_000, "军力": 60})
    res = ws.apply_delta({"民心": -30})
    assert ws.values["民心"] == 0
    assert res.applied["民心"] == -5  # 实际只降了 5
    assert "民心" in res.clipped


def test_apply_delta_clamp_to_max():
    ws, _ = make_state(values={"军力": 95, "国库": 1_000_000, "民心": 50})
    res = ws.apply_delta({"军力": 20})
    assert ws.values["军力"] == 100
    assert res.applied["军力"] == 5
    assert "军力" in res.clipped


def test_apply_delta_unknown_key_rejected():
    ws, _ = make_state()
    res = ws.apply_delta({"不存在的项": 10, "民心": 5})
    assert res.applied.get("不存在的项") is None
    assert res.clipped["不存在的项"] == "unknown_key"
    # 合法项仍生效
    assert ws.values["民心"] == 55


def test_apply_delta_accumulates():
    ws, _ = make_state()
    ws.apply_delta({"民心": 10})
    ws.apply_delta({"民心": 10})
    assert ws.values["民心"] == 70


def test_apply_delta_empty():
    ws, _ = make_state()
    res = ws.apply_delta({})
    assert res.applied == {}
    assert ws.values["民心"] == 50


# ---------- 时间推进 ----------


def test_current_year_month_at_start():
    ws, _ = make_state()
    ws.day = 0
    assert ws.current_year_month() == (1, 1)
    assert ws.era_label() == "崇祯1年1月"


def test_advance_month_mode_crosses_one_month():
    ws, _ = make_state()
    crossed = ws.advance_time("month")
    assert crossed == [1]  # 跨入第1个月序号=1（崇祯1年2月）
    assert ws.day == 30
    assert ws.current_year_month() == (1, 2)
    # 再推一回合
    crossed2 = ws.advance_time("month")
    assert crossed2 == [2]
    assert ws.current_year_month() == (1, 3)


def test_advance_week_mode_multiple_turns_per_month():
    ws, _ = make_state()
    # 4 个 week 回合 ≈ 28 天，仍在第0月
    for _ in range(3):
        ws.advance_time("week")
    assert ws.day == 21
    assert ws.current_month_index() == 0
    # 第4个 week 回合 -> day=28 仍第0月
    ws.advance_time("week")
    assert ws.day == 28
    assert ws.current_month_index() == 0
    # 第5个 -> day=35 跨入第1月
    crossed = ws.advance_time("week")
    assert crossed == [1]


def test_advance_half_month_mode():
    ws, _ = make_state()
    ws.advance_time("half_month")  # day=15
    assert ws.current_month_index() == 0
    crossed = ws.advance_time("half_month")  # day=30
    assert crossed == [1]


def test_advance_year_rollover():
    ws, _ = make_state()
    # 推进 12 个月（month 模式 12 回合）-> 崇祯2年正月
    for _ in range(12):
        ws.advance_time("month")
    assert ws.current_year_month() == (2, 1)
    assert ws.era_label() == "崇祯2年1月"


def test_advance_crosses_multiple_months_in_one_turn():
    # month 模式每回合 30 天=1月，正常不跨多月；但若 last_month_index 落后则一次补齐
    ws, _ = make_state()
    ws.last_month_index = -1  # 模拟落后一月
    crossed = ws.advance_time("month")
    assert crossed == [0, 1]


def test_advance_invalid_turn_length():
    ws, _ = make_state()
    with pytest.raises(ValueError):
        ws.advance_time("year")


def test_days_per_turn_table():
    assert DAYS_PER_TURN == {"week": 7, "half_month": 15, "month": 30}


# ---------- 序列化 ----------


def test_serialize_roundtrip():
    from src.llm.provider import load_config

    cfg = load_config("config.yaml")
    ws = WorldState.initial(cfg)
    ws.apply_delta({"民心": 10, "军力": -5})
    ws.advance_time("month")
    data = ws.to_dict()
    restored = WorldState.from_dict(data, ws.bounds)
    assert restored.values == ws.values
    assert restored.day == ws.day
    assert restored.last_month_index == ws.last_month_index
    assert restored.era == ws.era
    # restored 可继续 apply_delta（bounds 完整）
    res = restored.apply_delta({"民心": 5})
    assert res.applied["民心"] == 5
