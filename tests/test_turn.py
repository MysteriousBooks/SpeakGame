"""M3: 端到端回合测试（mock LLM，打通下诏→分派→执行→史官→落库→事件→时间推进）。"""

from src.core.game_engine import GameEngine, TurnSummary
from src.llm.provider import MockProvider, load_config


def make_engine(orch_resp=None, hist_resp=None, role_resp=None):
    """构造 mock LLM 的 GameEngine。每个 LLM 注入预设 json。"""
    cfg = load_config("config.yaml")
    orch_llm = MockProvider(json_responses=orch_resp or [{}])
    hist_llm = MockProvider(json_responses=hist_resp or [{}])
    role_llm = MockProvider(json_responses=role_resp or [{}])
    return GameEngine(
        cfg,
        orchestrator_llm=orch_llm,
        historian_llm=hist_llm,
        role_llm=role_llm,
    ), cfg


# ---------- 开局初始化 ----------


def test_engine_initial_state():
    eng, _ = make_engine()
    # 开局内阁在朝：户部尚书、兵部尚书、百姓
    ids = {a.id for a in eng.roster.active_agents()}
    assert {"minister_finance", "minister_war", "common_people"} <= ids
    # 开局事件挂起：铲除魏忠贤、陕西旱灾
    active_ids = {ae.event.id for ae in eng.events.active}
    assert "chu_chu_wei_zhong_xian" in active_ids
    assert "shan_xi_han_zai" in active_ids
    # 开局数值
    assert eng.state.values["国库"] == 1_000_000
    assert eng.state.era_label() == "崇祯1年1月"


# ---------- 端到端：赈灾诏书 ----------


async def test_turn_edict_relieve_shaanxi():
    orch_resp = [{
        "action": "execute",
        "dispatch_targets": ["minister_finance"],
        "visits": [],
        "activation_order": ["minister_finance"],
        "task": {
            "target_agent": "minister_finance",
            "content": "拨银十万赈陕西",
            "affects": ["国库", "陕西_民心"],
            "deadline": "崇祯1年6月",
            "success_condition": "赈灾款到位",
        },
        "finance_action": None,
        "reason": "赈灾派户部",
    }]
    hist_resp = [{
        "narrative": "帝拨银十万赈陕西，民心稍安",
        "delta": {"国库": -100000, "陕西_民心": 8},
        "finance_delta": {},
        "new_events": [],
        "factual_notes": ["崇祯元年正月，帝拨银十万赈陕西"],
        "audience_queue": [{"agent_id": "minister_war", "topic": "言边事", "urgency": "high"}],
        "premonitions": [],
    }]
    role_resp = [{
        "public": "臣已拨银十万赈陕西，灾区民心稍安",
        "private": "实忧国库更虚",
        "want_audience": False,
    }]
    eng, _ = make_engine(orch_resp, hist_resp, role_resp)

    shanxi_before = eng.state.values["陕西_民心"]
    treasury_before = eng.state.values["国库"]
    summary = await eng.run_turn("陕西旱灾，拨银十万两赈灾")

    assert isinstance(summary, TurnSummary)
    # 陕西_民心 +8
    assert eng.state.values["陕西_民心"] == shanxi_before + 8
    # 国库：自然收支(0) + 史官(-100000)
    assert eng.state.values["国库"] == treasury_before - 100000
    # 任务已创建
    assert summary.task is not None
    assert summary.task["target_agent"] == "minister_finance"
    # agent 执行输出已记录
    assert len(summary.execution_public) == 1
    assert summary.execution_public[0]["agent_id"] == "minister_finance"
    # 求见队列汇总（兵部尚书求见言边事）
    assert any(q["agent_id"] == "minister_war" for q in summary.audience_queue)
    # 事实记忆已写入户部尚书
    fin = eng.roster.get("minister_finance")
    assert fin.factual.search(["回合事件"])
    # 时间推进（month 模式 1 回合=1月）→ 崇祯1年2月
    assert eng.state.era_label() == "崇祯1年2月"


# ---------- 端到端：财政划拨（内帑→国库） ----------


async def test_turn_finance_transfer_inner_to_treasury():
    orch_resp = [{
        "action": "finance_transfer",
        "dispatch_targets": [],
        "finance_action": {"type": "inner_to_treasury", "amount": 1000000, "detail": "动用内帑充国库"},
        "reason": "财政划拨",
    }]
    hist_resp = [{
        "narrative": "帝动用内帑百万充国库",
        "delta": {},
        "finance_delta": {},
        "new_events": [],
        "factual_notes": [],
        "audience_queue": [],
        "premonitions": [],
    }]
    eng, _ = make_engine(orch_resp, hist_resp, [])
    treasury_before = eng.state.values["国库"]
    inner_before = eng.state.values["内帑"]
    await eng.run_turn("动用内帑一百万充国库")
    assert eng.state.values["内帑"] == inner_before - 1_000_000
    assert eng.state.values["国库"] == treasury_before + 1_000_000


# ---------- 端到端：财政划拨（国库→内帑 拒绝） ----------


async def test_turn_finance_transfer_treasury_to_inner_rejected():
    orch_resp = [{
        "action": "finance_transfer",
        "dispatch_targets": [],
        "finance_action": {"type": "treasury_to_inner", "amount": 500000, "detail": "挪国库入内帑"},
        "reason": "违规",
    }]
    hist_resp = [{
        "narrative": "帝欲挪国库入内帑，群臣阻之",
        "delta": {},
        "finance_delta": {},
        "new_events": [],
        "factual_notes": [],
        "audience_queue": [],
        "premonitions": [],
    }]
    eng, _ = make_engine(orch_resp, hist_resp, [])
    treasury_before = eng.state.values["国库"]
    inner_before = eng.state.values["内帑"]
    await eng.run_turn("挪国库五十万入内帑")
    # 默认拒绝，数值不变
    assert eng.state.values["国库"] == treasury_before
    assert eng.state.values["内帑"] == inner_before


# ---------- 端到端：赐死处置 ----------


async def test_turn_execute_death():
    # 先招募袁崇焕到 active（从历史角色库）
    eng, _ = make_engine(
        orch_resp=[{
            "action": "execute_death",
            "dispatch_targets": [],
            "target": "yuan_chonghuan",
            "reason": "赐死袁崇焕",
        }],
        hist_resp=[{
            "narrative": "帝赐死袁崇焕，辽东军心震动",
            "delta": {"民心": -10, "军心": -10},
            "finance_delta": {},
            "new_events": [{"type": "辽东军心震动", "trigger_condition": "true"}],
            "factual_notes": ["帝赐死袁崇焕"],
            "audience_queue": [],
            "premonitions": [],
        }],
        role_resp=[],
    )
    # 招募袁崇焕为 active（袁崇焕在历史角色库，status=available）
    eng.roster.recruit("yuan_chonghuan", MockProvider(), eng.state.era_label())
    assert eng.roster.status_of("yuan_chonghuan") == "active"

    await eng.run_turn("赐死袁崇焕")
    # 袁崇焕转为 dead
    assert eng.roster.status_of("yuan_chonghuan") == "dead"
    assert eng.roster.get("yuan_chonghuan").agent is None


# ---------- 端到端：财政政令改变下回合收支 ----------


async def test_turn_tax_adjust_changes_next_settlement():
    orch_resp = [{
        "action": "execute",
        "dispatch_targets": ["minister_finance"],
        "task": None,
        "finance_action": {"type": "tax_adjust", "amount": 0, "detail": "加征辽饷三成"},
        "reason": "财政",
    }]
    hist_resp = [{
        "narrative": "加征辽饷三成",
        "delta": {"民心": -5},
        "finance_delta": {
            "income_monthly": {"辽饷加派": 117000},
            "tax_rates": {"辽饷加派率": 0.039},
        },
        "new_events": [],
        "factual_notes": [],
        "audience_queue": [],
        "premonitions": [],
    }]
    role_resp = [{"public": "臣遵旨加征", "private": "", "want_audience": False}]
    eng, _ = make_engine(orch_resp, hist_resp, role_resp)
    assert eng.finance.income_monthly["辽饷加派"] == 90000
    await eng.run_turn("加征辽饷三成")
    # 财政参数已更新，下回合结算用新值
    assert eng.finance.income_monthly["辽饷加派"] == 117000
    assert eng.finance.tax_rates["辽饷加派率"] == 0.039


# ---------- 事件解决判定（纯代码） ----------


async def test_turn_event_resolved_when_conditions_met():
    """玩家持续赈灾使陕西_民心>=60 且 国库>=200000，代码自动标记陕西旱灾已解决。"""
    orch_resp = [{
        "action": "execute", "dispatch_targets": ["minister_finance"],
        "task": None, "finance_action": None, "reason": "赈灾",
    }]
    hist_resp = [{
        "narrative": "赈灾得力，陕西民心大振",
        "delta": {"陕西_民心": 35, "国库": 100000},  # 30+35=65>=60
        "finance_delta": {},
        "new_events": [], "factual_notes": [], "audience_queue": [], "premonitions": [],
    }]
    role_resp = [{"public": "赈灾得力", "private": "", "want_audience": False}]
    eng, _ = make_engine(orch_resp, hist_resp, role_resp)
    # 先充国库到足够（陕西_民心需>=60 且 国库>=200000）
    eng.state.values["国库"] = 200000
    await eng.run_turn("大力赈灾陕西")
    resolved = [ae for ae in eng.events.active if ae.event.id == "shan_xi_han_zai" and ae.resolved]
    assert len(resolved) == 1


# ---------- 求见处理（decline 扣忠诚） ----------


def test_apply_audience_decisions_decline_reduces_loyalty():
    eng, _ = make_engine()
    from src.core.audience import AudienceRequest

    eng.audience.add(AudienceRequest("minister_war", "王在晋", "言边事", "high"))
    loyalty_before = eng.roster.get("minister_war").loyalty
    eng.apply_audience_decisions({"minister_war": "decline"})
    assert eng.roster.get("minister_war").loyalty == loyalty_before - 3
    # grant 不扣
    eng.audience.add(AudienceRequest("minister_finance", "毕自严", "言财用"))
    fin_before = eng.roster.get("minister_finance").loyalty
    eng.apply_audience_decisions({"minister_finance": "grant"})
    assert eng.roster.get("minister_finance").loyalty == fin_before


# ---------- 存档/读档 ----------


def test_engine_save_load_roundtrip(tmp_path):
    eng, cfg = make_engine()
    eng.state.values["民心"] = 55
    eng.events.trigger_initial()
    save_path = tmp_path / "save.json"
    eng.save(save_path)
    loaded = GameEngine.load(
        save_path,
        cfg,
        orchestrator_llm=MockProvider(),
        historian_llm=MockProvider(),
        role_llm=MockProvider(),
    )
    assert loaded.state.values["民心"] == 55
    assert len(loaded.events.active) == len(eng.events.active)
    # active agent 重建
    assert any(a.id == "minister_finance" for a in loaded.roster.active_agents())


# ---------- 早朝 ----------


async def test_run_court_produces_speeches():
    def responder(messages, system):
        return '{"public":"臣请奏边事","private":"","want_audience":false}'

    eng, _ = make_engine(role_resp=None)
    for agent in eng.roster.active_agents():
        agent.llm = MockProvider(responder=responder, passthrough_json=True)
    speeches, requests = await eng.run_court("陕西旱灾")
    assert len(speeches) > 0
    assert all(s.public for s in speeches)
