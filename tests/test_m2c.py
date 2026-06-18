"""M2c: audience + court + tasks + historian + orchestrator 测试。"""


from src.agents.base_agent import BaseAgent, load_persona
from src.core.audience import (
    DECLINE_LOYALTY_PENALTY,
    AudienceQueue,
    AudienceRequest,
)
from src.core.court_session import CourtSession, CourtSpeech, format_history
from src.core.historian import Historian, TurnResult
from src.core.tasks import (
    COMPLETED,
    IN_PROGRESS,
    OVERDUE,
    PENDING,
    TaskSystem,
)
from src.core.turn_orchestrator import (
    ORCHESTRATOR_SCHEMA,
    OrchestratorPlan,
    TurnOrchestrator,
)
from src.llm.provider import MockProvider
from src.memory.factual_memory import FactualMemory
from src.memory.narrative_memory import NarrativeMemory

# ========== AudienceQueue ==========


def test_audience_add_and_items():
    q = AudienceQueue()
    q.add(AudienceRequest("a1", "户部尚书", "言财用", "high"))
    q.add(AudienceRequest("a2", "兵部尚书", "言边事", "normal"))
    items = q.items()
    assert len(items) == 2
    assert items[0].topic == "言财用"


def test_audience_no_duplicate():
    q = AudienceQueue()
    q.add(AudienceRequest("a1", "甲", "言边事"))
    q.add(AudienceRequest("a1", "甲", "言边事"))
    assert len(q.items()) == 1


def test_audience_grant_no_penalty():
    q = AudienceQueue()
    q.add(AudienceRequest("a1", "甲", "言边事"))
    out = q.grant("a1")
    assert out.granted is True
    assert out.loyalty_delta == 0
    assert out.missed_info is False
    assert q.items() == []  # 已处理，不再展示


def test_audience_decline_penalty():
    q = AudienceQueue()
    q.add(AudienceRequest("a1", "甲", "言边事", "high"))
    out = q.decline("a1")
    assert out.granted is False
    assert out.loyalty_delta == DECLINE_LOYALTY_PENALTY  # -3
    assert out.missed_info is True  # 错过情报
    assert q.items() == []


def test_audience_add_from_historian():
    q = AudienceQueue()
    historian_queue = [
        {"agent_id": "minister_war", "topic": "言边事", "urgency": "high"},
        {"agent_id": "minister_finance", "topic": "言财用"},
    ]
    q.add_from_historian(historian_queue)
    assert len(q.items()) == 2
    assert q.items()[0].urgency == "high"


def test_audience_serialize_roundtrip():
    q = AudienceQueue()
    q.add(AudienceRequest("a1", "甲", "言边事"))
    q.decline("a1")
    data = q.to_dict()
    restored = AudienceQueue.from_dict(data)
    assert restored.items() == []


# ========== CourtSession ==========


async def test_court_run_collects_speeches():
    persona = load_persona("minister_finance.yaml")
    llm = MockProvider(json_responses=[{
        "public": "臣以为当节用裁冗",
        "private": "实忧户部亏空",
        "want_audience": True,
        "audience_topic": "言财用",
    }])
    agent = BaseAgent(persona, FactualMemory(), NarrativeMemory(), llm)
    court = CourtSession(max_turns=1)
    speeches, requests = await court.run([agent], situation="陕西旱灾，国库空虚")
    assert len(speeches) == 1
    assert speeches[0].public == "臣以为当节用裁冗"
    assert speeches[0].want_audience is True
    assert len(requests) == 1
    assert requests[0].topic == "言财用"


async def test_court_run_multiple_turns_accumulates_history():
    persona = load_persona("minister_finance.yaml")
    # 2 轮，每轮 1 agent -> 2 次 chat_json
    llm = MockProvider(json_responses=[
        {"public": "第一轮请奏：当赈陕西", "private": "", "want_audience": False},
        {"public": "第二轮补充：须筹措军饷", "private": "", "want_audience": False},
    ])
    agent = BaseAgent(persona, FactualMemory(), NarrativeMemory(), llm)
    court = CourtSession(max_turns=2)
    speeches, _ = await court.run([agent], situation="议政")
    assert len(speeches) == 2
    assert speeches[0].public != speeches[1].public


async def test_court_run_empty_agents():
    court = CourtSession()
    speeches, requests = await court.run([], situation="x")
    assert speeches == []
    assert requests == []


def test_court_format_history():
    speeches = [
        CourtSpeech("a1", "户部尚书", "当节用"),
        CourtSpeech("a2", "兵部尚书", "当调兵"),
    ]
    h = format_history(speeches)
    assert "户部尚书：当节用" in h
    assert "兵部尚书：当调兵" in h


def test_court_format_history_empty():
    assert "尚未发言" in format_history([])


# ========== TaskSystem ==========


def test_task_create():
    ts = TaskSystem()
    t = ts.create("minister_finance", "清查各省欠赋", affects=["田赋", "国库"], deadline_month=6, success_condition="清册上报", turn=1)
    assert t.id == "task_1"
    assert t.target_agent == "minister_finance"
    assert t.status == PENDING


def test_task_update_progress():
    ts = TaskSystem()
    tid = ts.create("a", "任务", turn=1).id
    ts.update(tid, 0.5, turn=2)
    assert ts.tasks[tid].progress == 0.5
    assert ts.tasks[tid].status == IN_PROGRESS


def test_task_complete_on_full_progress():
    ts = TaskSystem()
    tid = ts.create("a", "任务", turn=1).id
    ts.update(tid, 1.0, turn=2)
    assert ts.tasks[tid].status == COMPLETED
    assert ts.tasks[tid].turn_completed == 2


def test_task_complete_and_fail():
    ts = TaskSystem()
    tid = ts.create("a", "任务", turn=1).id
    ts.complete(tid, turn=3)
    assert ts.tasks[tid].status == COMPLETED
    tid2 = ts.create("b", "任务2", turn=1).id
    ts.fail(tid2, turn=3)
    assert ts.tasks[tid2].status == "failed"


def test_task_check_overdue():
    ts = TaskSystem()
    t1 = ts.create("a", "紧急任务", deadline_month=3, turn=1)
    t2 = ts.create("b", "无期限任务", turn=1)
    overdue = ts.check_overdue(current_month=5)
    assert t1 in overdue
    assert t1.status == OVERDUE
    assert t2 not in overdue


def test_task_by_agent_and_active():
    ts = TaskSystem()
    ts.create("a", "任务1", turn=1)
    ts.create("a", "任务2", turn=1)
    ts.create("b", "任务3", turn=1)
    assert len(ts.by_agent("a")) == 2
    assert len(ts.active()) == 3


def test_task_serialize_roundtrip():
    ts = TaskSystem()
    ts.create("a", "任务", affects=["国库"], deadline_month=6, turn=1)
    ts.update("task_1", 0.5, turn=2)
    data = ts.to_dict()
    restored = TaskSystem.from_dict(data)
    assert restored.tasks["task_1"].progress == 0.5
    assert restored.tasks["task_1"].status == IN_PROGRESS


# ========== Historian ==========


async def test_historian_deduce_parses_result():
    llm = MockProvider(json_responses=[{
        "narrative": "帝拨银十万赈陕西，民心稍安",
        "delta": {"国库": -100000, "陕西_民心": 8},
        "finance_delta": {"tax_rates": {}},
        "new_events": [{"type": "民变", "trigger_condition": "陕西_民心<20"}],
        "factual_notes": ["崇祯元年春，帝拨银十万赈陕西"],
        "audience_queue": [{"agent_id": "minister_war", "topic": "言边事", "urgency": "high"}],
        "premonitions": [{"event_id": "ji_si", "level": "远期", "text": "辽东异动"}],
    }])
    h = Historian(llm, config={"game": {"era_name": "崇祯"}})
    result = await h.deduce(
        public_outputs="户部尚书：臣已拨银赈灾",
        world_snapshot={"国库": 1000000, "陕西_民心": 30},
        finance_params=None,
        edict_and_dispatch="帝诏：拨银十万赈陕西",
        upcoming_events="己巳之变（崇祯2年10月）",
        era="崇祯1年1月",
    )
    assert isinstance(result, TurnResult)
    assert result.narrative.startswith("帝拨银")
    assert result.delta["国库"] == -100000
    assert result.delta["陕西_民心"] == 8
    assert len(result.audience_queue) == 1
    assert len(result.premonitions) == 1


def test_historian_validate_delta_ok():
    ok, errors = Historian.validate_delta({"国库": -10, "民心": 5}, {"国库": {}, "民心": {}})
    assert ok is True
    assert errors == []


def test_historian_validate_delta_unknown_key():
    ok, errors = Historian.validate_delta({"不存在的": 5}, {"国库": {}})
    assert ok is False
    assert any("不存在的" in e for e in errors)


def test_historian_validate_delta_non_number():
    ok, errors = Historian.validate_delta({"国库": "大"}, {"国库": {}})
    assert ok is False


# ========== TurnOrchestrator ==========


async def test_orchestrator_parse_edict_execute():
    llm = MockProvider(json_responses=[{
        "action": "execute",
        "dispatch_targets": ["minister_finance"],
        "visits": [],
        "activation_order": ["minister_finance"],
        "task": {
            "target_agent": "minister_finance",
            "content": "清查各省欠赋",
            "affects": ["田赋", "国库"],
            "deadline": "崇祯1年6月",
            "success_condition": "各省欠赋清册上报",
        },
        "finance_action": None,
        "reason": "财政类诏书派户部",
    }])
    orch = TurnOrchestrator(llm, config={})
    plan = await orch.parse_edict(
        "清查各省欠赋",
        turn=1,
        available_agents=[{"id": "minister_finance", "name": "毕自严", "skills": ["理财"], "faction": "循吏系"}],
        situation="国库空虚",
        era="崇祯1年1月",
    )
    assert plan.action == "execute"
    assert plan.dispatch_targets == ["minister_finance"]
    assert plan.task is not None
    assert plan.task["target_agent"] == "minister_finance"
    assert plan.is_dismiss is False


async def test_orchestrator_parse_edict_execute_death():
    llm = MockProvider(json_responses=[{
        "action": "execute_death",
        "dispatch_targets": [],
        "target": "yuan_chonghuan",
        "reason": "赐死重臣",
    }])
    orch = TurnOrchestrator(llm)
    plan = await orch.parse_edict("赐死袁崇焕", turn=5, available_agents=[], situation="辽东", era="崇祯3年1月")
    assert plan.is_execute_death is True
    assert plan.target == "yuan_chonghuan"


async def test_orchestrator_parse_edict_finance_transfer():
    llm = MockProvider(json_responses=[{
        "action": "finance_transfer",
        "dispatch_targets": [],
        "finance_action": {"type": "inner_to_treasury", "amount": 1000000, "detail": "动用内帑充国库"},
        "reason": "财政划拨",
    }])
    orch = TurnOrchestrator(llm)
    plan = await orch.parse_edict("动用内帑一百万充国库", turn=2, available_agents=[], situation="国库空虚", era="崇祯1年2月")
    assert plan.is_finance_transfer is True
    assert plan.finance_action["type"] == "inner_to_treasury"
    assert plan.finance_action["amount"] == 1000000


def test_orchestrator_select_speaking_agents_subset():
    """事件驱动激活相关子集：只选 dispatch_targets 命中的在朝 agent。"""
    persona_f = load_persona("minister_finance.yaml")
    persona_w = load_persona("minister_war.yaml")
    a_f = BaseAgent(persona_f, FactualMemory(), NarrativeMemory(), MockProvider())
    a_w = BaseAgent(persona_w, FactualMemory(), NarrativeMemory(), MockProvider())
    plan = OrchestratorPlan(action="execute", dispatch_targets=["minister_war"])
    selected = TurnOrchestrator.select_speaking_agents(plan, [a_f, a_w])
    assert [a.id for a in selected] == ["minister_war"]


def test_orchestrator_select_speaking_agents_all_when_no_targets():
    persona_f = load_persona("minister_finance.yaml")
    a_f = BaseAgent(persona_f, FactualMemory(), NarrativeMemory(), MockProvider())
    plan = OrchestratorPlan(action="court_only", dispatch_targets=[])
    selected = TurnOrchestrator.select_speaking_agents(plan, [a_f])
    assert len(selected) == 1


def test_orchestrator_schema_has_actions():
    actions = ORCHESTRATOR_SCHEMA["properties"]["action"]["enum"]
    assert "execute" in actions
    assert "execute_death" in actions
    assert "dismiss" in actions
    assert "finance_transfer" in actions


def test_orchestrator_plan_properties():
    p = OrchestratorPlan(action="dismiss", target="a1")
    assert p.is_dismiss is True
    assert p.is_execute_death is False
    p2 = OrchestratorPlan(action="execute_death", target="a2")
    assert p2.is_execute_death is True
