"""M3-web: FastAPI 路由与界面可用性测试（TestClient，mock LLM）。"""

import pytest
from fastapi.testclient import TestClient

from src.web.app import app


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_index_page(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "崇祯" in r.text
    assert "国库" in r.text
    assert "下诏" in r.text


def test_state_snapshot(client):
    r = client.get("/state")
    assert r.status_code == 200
    s = r.json()
    assert "era" in s
    assert "values" in s
    assert "国库" in s["values"]
    assert "内帑" in s["values"]
    assert "active_events" in s
    assert "premonitions" in s
    assert "active_agents" in s


def test_state_has_initial_court(client):
    """开局应有 8 位在朝官员（六部 + 魏忠贤 + 百姓）。"""
    s = client.get("/state").json()
    ids = {a["id"] for a in s["active_agents"]}
    expected = {
        "minister_finance", "minister_war", "common_people",
        "wang_yongguang", "qiao_yunsheng", "liu_zunxian",
        "wei_zhongxian", "wen_tiren",
    }
    missing = expected - ids
    assert not missing, f"缺少开局官员: {missing}"


def test_agents_have_position(client):
    """每个 active agent 应有 position 字段。"""
    s = client.get("/state").json()
    for a in s["active_agents"]:
        assert "position" in a, f"{a['name']} 缺少 position"
        assert a["position"], f"{a['name']} position 为空"


def test_wei_zhongxian_in_court(client):
    """魏忠贤应在朝且显示正确职务。"""
    s = client.get("/state").json()
    wei = next((a for a in s["active_agents"] if a["id"] == "wei_zhongxian"), None)
    assert wei is not None, "魏忠贤不在朝"
    assert wei["position"] == "司礼监掌印太监"


def test_state_has_opening_events(client):
    s = client.get("/state").json()
    event_ids = {ae["id"] for ae in s["active_events"]}
    assert "chu_chu_wei_zhong_xian" in event_ids
    assert "shan_xi_han_zai" in event_ids


def test_edict_json_returns_turn_result(client):
    """下诏（mock 默认空回合）应返回结构化回合结果。"""
    r = client.post("/edict/json", data={"edict": "陕西旱灾，拨银十万两赈灾"})
    assert r.status_code == 200
    body = r.json()
    assert "era" in body
    assert "narrative" in body
    assert "delta_applied" in body
    assert "audience_queue" in body
    # mock 下推进一回合（month 模式）-> 崇祯1年2月
    assert body["era"] == "崇祯1年2月"


def test_edict_sse_stream(client):
    """SSE 流式下诏应返回 event-stream。"""
    with client.stream("POST", "/edict", data={"edict": "测试下诏"}) as resp:
        assert resp.status_code == 200
        chunks = list(resp.iter_text())
        full = "".join(chunks)
        assert "data:" in full
        assert "[DONE]" in full


def test_recruit_pool(client):
    r = client.get("/recruit")
    assert r.status_code == 200
    body = r.json()
    assert "difficulty" in body
    assert "candidates" in body
    # 崇祯元年(1628)：袁崇焕(1584-1630)在世，应在招募池
    ids = {c["id"] for c in body["candidates"]}
    assert "yuan_chonghuan" in ids


def test_recruit_normal_hides_meta(client):
    """normal 难度招募池不显示死因/正反派（信息隔离）。"""
    body = client.get("/recruit").json()
    yuan = next(c for c in body["candidates"] if c["id"] == "yuan_chonghuan")
    assert "death_cause" not in yuan  # normal 不剧透死因
    assert "historical_alignment" not in yuan
    assert "skills" in yuan  # normal 显示擅长


def test_audience_decline(client):
    # 先制造一条求见（通过下诏可能产生），此处直接 POST decline 验证路由
    r = client.post("/audience/minister_war", data={"action": "decline"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["granted"] is False


def test_save_endpoint(client):
    """存档到槽位1。"""
    r = client.post("/save", data={"slot": 1})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    from pathlib import Path
    assert Path("saves/slot_1/state.json").exists()


def test_new_game_endpoint(client):
    """新游戏重置状态。"""
    r = client.post("/new_game")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert "崇祯" in data["era"]


def test_list_saves(client):
    """列出存档槽位。"""
    # 先存一个档
    client.post("/save", data={"slot": 2})
    r = client.get("/saves")
    assert r.status_code == 200
    slots = r.json()["slots"]
    assert len(slots) == 3
    slot2 = [s for s in slots if s["slot"] == 2]
    assert len(slot2) == 1
    assert slot2[0]["exists"] is True


def test_load_from_slot(client):
    """从槽位读档。"""
    client.post("/save", data={"slot": 3})
    r = client.post("/load", data={"slot": 3})
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_load_empty_slot(client):
    """读空槽位返回 404。"""
    r = client.post("/load", data={"slot": 99})
    assert r.status_code == 404


def test_dialogue_records_exchanges(client):
    """对话后 agent 应有对话记录。"""
    # 先推进一回合确保有 active agent
    r = client.post("/next_turn", data={"edict": "test", "action": "execute"})
    assert r.status_code == 200

    # 找一个 active agent 对话
    state = client.get("/state").json()
    agents = state.get("active_agents", [])
    if not agents:
        return  # 无 agent 则跳过
    agent_id = agents[0]["id"]

    r = client.post(f"/dialogue/{agent_id}", data={"message": "你好"})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["public"] != ""

    # 存档后验证对话记录存在
    client.post("/save", data={"slot": 1})
    import json
    from pathlib import Path
    saved = json.loads(Path("saves/slot_1/state.json").read_text(encoding="utf-8"))
    roster = saved.get("roster", {}).get("instances", {})
    if agent_id in roster:
        dm = roster[agent_id].get("dialogue_memory", {})
        assert len(dm.get("exchanges", [])) >= 2  # player + agent


# ---- 吏部管理 ----

def test_positions_endpoint(client):
    r = client.get("/positions")
    assert r.status_code == 200
    data = r.json()
    assert "all_positions" in data
    assert "vacant_positions" in data
    assert len(data["all_positions"]) > 0


def test_talent_pool_endpoint(client):
    r = client.get("/talent_pool")
    assert r.status_code == 200
    data = r.json()
    assert "talent_pool" in data
    assert len(data["talent_pool"]) > 0


def test_appoint_endpoint(client):
    """任命 available 角色到空缺职务。"""
    pool = client.get("/talent_pool").json()["talent_pool"]
    available = [p for p in pool if p["status"] == "available"]
    assert len(available) > 0
    vacant = client.get("/positions").json()["vacant_positions"]
    assert len(vacant) > 0
    r = client.post("/appoint", data={
        "persona_id": available[0]["id"],
        "position_id": vacant[0]["id"],
    })
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_dismiss_endpoint(client):
    """卸任在朝官员。"""
    pool = client.get("/talent_pool").json()["talent_pool"]
    available = [p for p in pool if p["status"] == "available"]
    vacant = client.get("/positions").json()["vacant_positions"]
    client.post("/appoint", data={"persona_id": available[0]["id"], "position_id": vacant[0]["id"]})
    r = client.post(f"/dismiss/{available[0]['id']}")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_create_position_endpoint(client):
    r = client.post("/positions/create", data={
        "name": "东厂提督", "rank": "正四品", "scope": "掌东厂刑狱侦缉",
    })
    assert r.status_code == 200
    assert r.json()["ok"] is True
    vacant = client.get("/positions").json()["vacant_positions"]
    assert any(p["name"] == "东厂提督" for p in vacant)
