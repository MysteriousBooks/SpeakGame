"""测试吏部任命/卸任系统。"""

import pytest

from src.core.game_engine import GameEngine
from src.llm.provider import MockProvider, load_config


@pytest.fixture
def engine():
    cfg = load_config("config.yaml")
    return GameEngine(
        cfg,
        orchestrator_llm=MockProvider(),
        historian_llm=MockProvider(),
        role_llm=MockProvider(),
    )


def test_appoint_available_to_vacant_position(engine):
    """任命 available 历史人物到空缺职务。"""
    pool = engine.roster.get_talent_pool()
    available = [p for p in pool if p["status"] == "available"]
    assert len(available) > 0
    target = available[0]
    vacant = engine.get_vacant_positions()
    assert len(vacant) > 0
    result = engine.appoint_official(target["id"], vacant[0]["id"])
    assert result["ok"] is True
    assert result["name"] == target["name"]


def test_appoint_to_occupied_raises(engine):
    """任命到已占用职务应拒绝。"""
    pool = engine.roster.get_talent_pool()
    available = [p for p in pool if p["status"] == "available"]
    vacant = engine.get_vacant_positions()
    engine.appoint_official(available[0]["id"], vacant[0]["id"])
    available2 = [p for p in engine.roster.get_talent_pool() if p["status"] == "available"]
    if available2:
        result = engine.appoint_official(available2[0]["id"], vacant[0]["id"])
        assert result["ok"] is False
        assert "已被占用" in result["error"]


def test_dismiss_official(engine):
    """卸任在朝官员。"""
    pool = engine.roster.get_talent_pool()
    available = [p for p in pool if p["status"] == "available"]
    vacant = engine.get_vacant_positions()
    engine.appoint_official(available[0]["id"], vacant[0]["id"])
    result = engine.dismiss_official(available[0]["id"])
    assert result["ok"] is True
    pos = engine.positions.get_by_id(vacant[0]["id"])
    assert pos.occupied_by is None


def test_dismiss_then_reappoint(engine):
    """卸任后重新任命同一人。"""
    pool = engine.roster.get_talent_pool()
    available = [p for p in pool if p["status"] == "available"]
    vacant = engine.get_vacant_positions()
    pid = available[0]["id"]
    pos_id = vacant[0]["id"]
    engine.appoint_official(pid, pos_id)
    engine.dismiss_official(pid)
    result = engine.appoint_official(pid, pos_id)
    assert result["ok"] is True


def test_create_position(engine):
    """创建自定义职务。"""
    result = engine.create_position("东厂提督", "正四品", "掌东厂刑狱侦缉")
    assert result["ok"] is True
    vacant = engine.get_vacant_positions()
    assert any(p["name"] == "东厂提督" for p in vacant)


def test_create_duplicate_position(engine):
    """创建重名职务应拒绝。"""
    engine.create_position("东厂提督", "正四品", "掌东厂")
    result = engine.create_position("东厂提督", "从四品", "重复")
    assert result["ok"] is False
    assert "已存在" in result["error"]


def test_get_position_management(engine):
    """吏部面板全量数据。"""
    mgmt = engine.get_position_management()
    assert "active_officials" in mgmt
    assert "talent_pool" in mgmt
    assert "vacant_positions" in mgmt
    assert "all_positions" in mgmt
