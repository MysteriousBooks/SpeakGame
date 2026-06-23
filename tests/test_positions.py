"""测试职务管理模块。"""

import pytest

from src.recruitment.positions import CourtPosition, PositionManager


def test_default_positions_loaded():
    pm = PositionManager()
    assert len(pm.get_all()) == 22  # 默认 22 个职务
    assert pm.get_by_id("libu_rites") is not None


def test_vacant_positions():
    pm = PositionManager()
    vacant = pm.get_vacant()
    assert all(p.occupied_by is None for p in vacant)
    assert len(vacant) == 22  # 初始全部空缺


def test_occupy_position():
    pm = PositionManager()
    pos = pm.occupy("libu_rites", "wen_tiren")
    assert pos.occupied_by == "wen_tiren"
    assert pm.get_by_id("libu_rites").occupied_by == "wen_tiren"
    assert len(pm.get_vacant()) == 21
    assert len(pm.get_occupied()) == 1


def test_occupy_already_occupied_raises():
    pm = PositionManager()
    pm.occupy("libu_rites", "wen_tiren")
    with pytest.raises(ValueError, match="已被占用"):
        pm.occupy("libu_rites", "wang_yongguang")


def test_release_position():
    pm = PositionManager()
    pm.occupy("libu_rites", "wen_tiren")
    pos = pm.release("libu_rites")
    assert pos.occupied_by is None
    assert pm.get_by_id("libu_rites").occupied_by is None


def test_release_by_persona():
    pm = PositionManager()
    pm.occupy("libu_rites", "wen_tiren")
    pm.occupy("hubu_shangshu", "wen_tiren")
    released = pm.release_by_persona("wen_tiren")
    assert len(released) == 2
    assert pm.get_by_id("libu_rites").occupied_by is None
    assert pm.get_by_id("hubu_shangshu").occupied_by is None


def test_create_position():
    pm = PositionManager()
    pos = pm.create("东厂提督", "正四品", "掌东厂刑狱侦缉")
    assert pos.id == "custom_东厂提督"
    assert pm.get_by_id("custom_东厂提督") is not None
    assert len(pm.get_all()) == 23


def test_create_duplicate_raises():
    pm = PositionManager()
    pm.create("东厂提督", "正四品", "掌东厂")
    with pytest.raises(ValueError, match="已存在"):
        pm.create("东厂提督", "从四品", "重复")


def test_serialize_deserialize():
    pm = PositionManager()
    pm.occupy("libu_rites", "wen_tiren")
    pm.create("东厂提督", "正四品", "掌东厂")
    data = pm.to_dict()
    pm2 = PositionManager.from_dict(data)
    assert len(pm2.get_all()) == 23
    assert pm2.get_by_id("libu_rites").occupied_by == "wen_tiren"
    assert pm2.get_by_id("custom_东厂提督") is not None


def test_get_by_name():
    pm = PositionManager()
    pos = pm.get_by_name("礼部尚书")
    assert pos is not None
    assert pos.id == "libu_rites"
    assert pm.get_by_name("不存在的职务") is None
