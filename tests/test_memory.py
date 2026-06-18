"""M1c: 两层记忆（事实记忆 + 叙事记忆）测试。"""

from src.memory.factual_memory import FactualMemory
from src.memory.narrative_memory import NarrativeMemory

# ---------- 事实记忆：增删检索 ----------


def test_factual_add_and_search_any():
    mem = FactualMemory()
    mem.add("帝许诺给袁崇焕升官", tags=["承诺", "袁崇焕"], turn=5, importance=0.9)
    mem.add("陕西旱灾持续", tags=["灾情", "陕西"], turn=5)
    mem.add("户部奏请加征", tags=["财政", "户部"], turn=6)
    # 按"袁崇焕" tag 检索
    res = mem.search(["袁崇焕"])
    assert len(res) == 1
    assert res[0].content == "帝许诺给袁崇焕升官"


def test_factual_search_any_multiple_tags():
    mem = FactualMemory()
    mem.add("A", tags=["x", "y"])
    mem.add("B", tags=["y", "z"])
    mem.add("C", tags=["z"])
    # any: 命中 x 或 z -> A, B, C
    assert {n.content for n in mem.search(["x", "z"], match="any")} == {"A", "B", "C"}
    # any: 只命中 z -> B, C
    assert {n.content for n in mem.search(["z"], match="any")} == {"B", "C"}


def test_factual_search_all_requires_every_tag():
    mem = FactualMemory()
    mem.add("A", tags=["x", "y"])
    mem.add("B", tags=["y", "z"])
    # all: 需同时含 x,y -> A
    assert {n.content for n in mem.search(["x", "y"], match="all")} == {"A"}


def test_factual_search_no_tags_returns_all():
    mem = FactualMemory()
    mem.add("A", tags=["x"])
    mem.add("B", tags=["y"])
    assert len(mem.search()) == 2


def test_factual_search_text_keyword():
    mem = FactualMemory()
    mem.add("帝许诺给袁崇焕升官", tags=["承诺"])
    mem.add("陕西旱灾", tags=["灾情"])
    res = mem.search_text("袁崇焕")
    assert len(res) == 1
    assert "袁崇焕" in res[0].content


def test_factual_get_by_id():
    mem = FactualMemory()
    nid = mem.add("A", tags=["x"])
    assert mem.get(nid).content == "A"
    assert mem.get(999) is None


# ---------- 全保留：不压缩、不丢失 ----------


def test_factual_never_compresses_or_loses():
    """计划核心需求：第5回合许诺升官，第10回合仍记得。"""
    mem = FactualMemory()
    mem.add("帝许诺给袁崇焕升官", tags=["承诺", "袁崇焕"], turn=5, importance=0.9)
    # 中间塞很多条目模拟时间流逝
    for i in range(100):
        mem.add(f"杂事{i}", tags=["杂"], turn=6 + i // 10)
    res = mem.search(["承诺"])
    assert len(res) == 1
    assert res[0].turn == 5
    assert res[0].importance == 0.9
    assert len(mem.all()) == 101  # 全保留


def test_factal_ids_increment():
    mem = FactualMemory()
    id1 = mem.add("A", tags=["x"])
    id2 = mem.add("B", tags=["y"])
    assert id2 == id1 + 1


# ---------- 序列化往返 ----------


def test_factual_serialize_roundtrip():
    mem = FactualMemory()
    mem.add("A", tags=["x", "y"], turn=1, importance=0.8)
    mem.add("B", tags=["z"], turn=2)
    data = mem.to_dict()
    restored = FactualMemory.from_dict(data)
    assert len(restored.all()) == 2
    assert restored.search(["x"])[0].content == "A"
    assert restored.get(2).content == "B"
    # 恢复后继续 add 不冲突
    nid = restored.add("C", tags=["w"])
    assert nid == 3


# ---------- 叙事记忆 ----------


def test_narrative_append_and_summary():
    mem = NarrativeMemory()
    mem.append(1, "开局铲除魏忠贤")
    mem.append(2, "陕西旱灾加重")
    s = mem.summary()
    assert "第1回合" in s
    assert "第2回合" in s
    assert "开局铲除魏忠贤" in s


def test_narrative_summary_recent_n():
    mem = NarrativeMemory()
    for t in range(1, 6):
        mem.append(t, f"叙事{t}")
    s = mem.summary(max_turns=2)
    assert "叙事4" in s
    assert "叙事5" in s
    assert "叙事3" not in s


def test_narrative_summary_empty():
    mem = NarrativeMemory()
    assert mem.summary() == ""


def test_narrative_persistence_load_save(tmp_path):
    save_path = tmp_path / "narrative.json"
    mem = NarrativeMemory()
    mem.append(1, "压缩叙事1")
    mem.append(2, "压缩叙事2")
    mem.save(str(save_path))
    # 新 session 加载
    loaded = NarrativeMemory.load(str(save_path))
    assert len(loaded.all()) == 2
    assert loaded.summary().count("回合") == 2


def test_narrative_load_missing_file_returns_empty(tmp_path):
    mem = NarrativeMemory.load(str(tmp_path / "nope.json"))
    assert mem.all() == []


def test_narrative_serialize_roundtrip():
    mem = NarrativeMemory()
    mem.append(1, "A")
    data = mem.to_dict()
    restored = NarrativeMemory.from_dict(data)
    assert restored.all()[0].text == "A"
    assert restored.all()[0].turn == 1
