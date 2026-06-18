"""M2a: base_agent + 角色卡 测试。"""


from src.agents.base_agent import (
    AGENT_OUTPUT_SCHEMA,
    AgentOutput,
    BaseAgent,
    PersonaCard,
    load_agent_base_prompt,
    load_historical_figures,
    load_persona,
)
from src.llm.provider import MockProvider
from src.memory.factual_memory import FactualMemory
from src.memory.narrative_memory import NarrativeMemory

# ---------- PersonaCard ----------


def test_persona_from_dict():
    d = {
        "id": "yuan_chonghuan",
        "name": "袁崇焕",
        "courtesy": "元素",
        "faction": "辽东系",
        "skills": ["军事", "辽防"],
        "personality": "刚烈敢言",
        "relations": {"政敌": "阉党余孽"},
        "historical_alignment": "争议",
        "born_year": 1584,
        "historical_death_year": 1630,
        "death_cause": {"type": "execution", "desc": "崇祯三年被凌迟"},
    }
    card = PersonaCard.from_dict(d)
    assert card.name == "袁崇焕"
    assert card.historical_alignment == "争议"
    assert card.death_cause["type"] == "execution"


def test_persona_prompt_card_excludes_meta_info():
    """元信息隔离：to_prompt_card 不输出死因/正反派。"""
    card = PersonaCard.from_dict(
        {
            "id": "x",
            "name": "袁崇焕",
            "courtesy": "元素",
            "faction": "辽东系",
            "skills": ["军事"],
            "personality": "刚烈敢言",
            "relations": {"政敌": "阉党余孽"},
            "historical_alignment": "争议",
            "death_cause": {"desc": "崇祯三年被凌迟"},
        }
    )
    text = card.to_prompt_card()
    assert "袁崇焕" in text
    assert "辽东系" in text
    assert "刚烈敢言" in text
    # 元信息不应出现
    assert "凌迟" not in text
    assert "争议" not in text


def test_persona_is_alive_in_year():
    card = PersonaCard(born_year=1584, historical_death_year=1630)
    assert card.is_alive_in(1627)  # 崇祯元年
    assert card.is_alive_in(1629)
    assert not card.is_alive_in(1583)  # 未出生
    assert not card.is_alive_in(1630)  # 已死（区间右开）


# ---------- YAML 加载 ----------


def test_load_minister_finance_persona():
    card = load_persona("minister_finance.yaml")
    assert card.id == "minister_finance"
    assert card.name == "毕自严"
    assert "理财" in card.skills


def test_load_minister_war_persona():
    card = load_persona("minister_war.yaml")
    assert card.id == "minister_war"
    assert card.name == "王在晋"


def test_load_common_people_persona():
    card = load_persona("common_people.yaml")
    assert card.id == "common_people"


def test_load_historical_figures():
    figures = load_historical_figures()
    ids = {f.id for f in figures}
    assert "yuan_chonghuan" in ids
    assert "sun_chuanting" in ids
    assert "lu_xiangsheng" in ids
    assert len(figures) >= 7
    # 元数据完整
    yuan = next(f for f in figures if f.id == "yuan_chonghuan")
    assert yuan.born_year == 1584
    assert yuan.death_cause["type"] == "execution"


def test_load_agent_base_prompt_has_isolation():
    prompt = load_agent_base_prompt()
    assert "信息隔离" in prompt
    assert "私密层" in prompt
    assert "{{persona_card}}" in prompt


# ---------- BaseAgent.respond ----------


async def test_respond_parses_agent_output():
    persona = load_persona("minister_finance.yaml")
    llm = MockProvider(json_responses=[{
        "public": "臣以为当节用裁冗",
        "private": "其实我担心户部亏空难补",
        "want_audience": True,
        "audience_topic": "言财用",
    }])
    agent = BaseAgent(persona, FactualMemory(), NarrativeMemory(), llm)
    out = await agent.respond("早朝议政", "户部尚书有何高见？")
    assert isinstance(out, AgentOutput)
    assert out.public == "臣以为当节用裁冗"
    assert out.private == "其实我担心户部亏空难补"
    assert out.want_audience is True
    assert out.audience_topic == "言财用"


async def test_respond_injects_isolation_and_excludes_meta():
    """验证 system prompt 含信息隔离约束、含人格卡、不含死因元信息。"""
    captured: dict = {}

    def responder(messages, system):
        captured["system"] = system
        return '{"public":"p","private":"pv","want_audience":false,"audience_topic":""}'

    persona = next(f for f in load_historical_figures() if f.id == "yuan_chonghuan")
    yuan = persona
    llm = MockProvider(responder=responder, passthrough_json=True)
    agent = BaseAgent(yuan, FactualMemory(), NarrativeMemory(), llm, era="崇祯1年1月")
    await agent.respond("早朝", "请奏")
    sys_text = captured["system"]
    assert "信息隔离" in sys_text  # 约束注入
    assert "袁崇焕" in sys_text  # 人格卡注入
    assert "崇祯1年1月" in sys_text  # 时间锚点注入
    assert "凌迟" not in sys_text  # 死因元信息隔离


async def test_respond_loads_factual_memory_by_tags():
    """按 tag 检索加载相关事实记忆到 prompt。"""
    captured: dict = {}

    def responder(messages, system):
        captured["system"] = system
        return '{"public":"p","private":"pv","want_audience":false}'

    persona = load_persona("minister_finance.yaml")
    factual = FactualMemory()
    factual.add("帝曾许诺拨银赈陕西", tags=["财政", "陕西"], turn=3)
    factual.add("无关条目", tags=["杂"], turn=4)
    llm = MockProvider(responder=responder, passthrough_json=True)
    agent = BaseAgent(persona, factual, NarrativeMemory(), llm)
    await agent.respond("议陕西赈灾", "陕西旱灾如何处置？", tags=["陕西"])
    # 陕西相关条目应注入，无关条目不注入
    assert "赈陕西" in captured["system"]
    assert "无关条目" not in captured["system"]


async def test_respond_loads_narrative_memory():
    captured: dict = {}

    def responder(messages, system):
        captured["system"] = system
        return '{"public":"p","private":"pv","want_audience":false}'

    persona = load_persona("minister_finance.yaml")
    narrative = NarrativeMemory()
    narrative.append(1, "开局铲除魏忠贤")
    llm = MockProvider(responder=responder, passthrough_json=True)
    agent = BaseAgent(persona, FactualMemory(), narrative, llm)
    await agent.respond("早朝", "请奏")
    assert "铲除魏忠贤" in captured["system"]


# ---------- 拜访 ----------


async def test_visit_receives_other_public():
    captured: dict = {}

    def responder(messages, system):
        captured["system"] = system
        return '{"public":"附和","private":"实不同意","want_audience":false}'

    persona = load_persona("minister_finance.yaml")
    llm = MockProvider(responder=responder, passthrough_json=True)
    agent = BaseAgent(persona, FactualMemory(), NarrativeMemory(), llm)
    out = await agent.visit("兵部尚书请奏调兵勤王")
    assert out.public == "附和"
    # 拜访场景注入了对方的公开层（在 system 而非 user message）
    assert "调兵勤王" in captured["system"]


# ---------- 事实记忆写入 ----------


def test_add_factual_records():
    persona = load_persona("minister_finance.yaml")
    agent = BaseAgent(persona, FactualMemory(), NarrativeMemory(), MockProvider())
    nid = agent.add_factual("帝下诏清查各省欠赋", ["财政", "任务"], turn=2)
    assert agent.factual.get(nid).content == "帝下诏清查各省欠赋"
    assert len(agent.factual.search(["财政"])) == 1


def test_agent_output_from_dict_defaults():
    out = AgentOutput.from_dict({"public": "p", "private": "", "want_audience": False})
    assert out.audience_topic == ""


def test_agent_output_schema_required_fields():
    assert "public" in AGENT_OUTPUT_SCHEMA["required"]
    assert "private" in AGENT_OUTPUT_SCHEMA["required"]
    assert "want_audience" in AGENT_OUTPUT_SCHEMA["required"]
