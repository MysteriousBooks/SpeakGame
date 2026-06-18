"""M0: LLM provider 多模型抽象 测试。"""


import pytest

from src.llm.provider import (
    LLMError,
    LLMProvider,
    Message,
    MockProvider,
    gather_calls,
    get_llm_for,
    get_provider,
    load_config,
    parse_json,
)

# ---------- parse_json 宽松解析 ----------


def test_parse_json_plain():
    assert parse_json('{"a": 1}') == {"a": 1}


def test_parse_json_fence():
    assert parse_json('```json\n{"a": 2}\n```') == {"a": 2}


def test_parse_json_with_prefix_text():
    assert parse_json('好的，这是结果：{"a": 3} 收工') == {"a": 3}


def test_parse_json_invalid_raises():
    with pytest.raises(ValueError):
        parse_json("这不是 json")


# ---------- MockProvider ----------


async def test_mock_chat_returns_preset():
    p = MockProvider(responses=["你好", "再见"])
    assert await p.chat([Message("user", "hi")]) == "你好"
    assert await p.chat([Message("user", "hi")]) == "再见"
    # 耗尽后循环末项
    assert await p.chat([Message("user", "hi")]) == "再见"
    await p.close()


async def test_mock_chat_default_text():
    p = MockProvider()
    assert await p.chat([Message("user", "hi")]) == "（mock 回复）"


async def test_mock_chat_json_preset():
    p = MockProvider(json_responses=[{"delta": {"国库": -10}}])
    out = await p.chat_json([Message("user", "推演")], schema={})
    assert out == {"delta": {"国库": -10}}


async def test_mock_chat_json_default_empty():
    p = MockProvider()
    assert await p.chat_json([Message("user", "推演")], schema={}) == {}


async def test_mock_responder_callback():
    def resp(messages, system):
        return f"echo:{messages[-1].content}"

    p = MockProvider(responder=resp)
    assert await p.chat([Message("user", "下诏")]) == "echo:下诏"


async def test_mock_stream_yields_chars():
    p = MockProvider(responses=["abc"])
    chunks = [c async for c in p.stream([Message("user", "x")])]
    assert "".join(chunks) == "abc"


async def test_mock_records_calls():
    p = MockProvider(responses=["ok"])
    await p.chat([Message("user", "hi")], system="sys")
    assert len(p.calls) == 1
    assert p.calls[0]["kind"] == "chat"
    assert p.calls[0]["system"] == "sys"


# ---------- chat_json 重试（模拟解析失败后成功） ----------


async def test_chat_json_retries_on_bad_json():
    # 前两次返回非法文本，第三次返回合法 JSON（走基类重试）
    p = MockProvider(responses=["不是json", "{坏", '{"ok": true}'], passthrough_json=True)
    out = await p.chat_json([Message("user", "推演")], schema={}, max_retries=2)
    assert out == {"ok": True}


async def test_chat_json_raises_after_retries_exhausted():
    p = MockProvider(responses=["bad", "still bad", "nope"], passthrough_json=True)
    with pytest.raises(LLMError):
        await p.chat_json([Message("user", "推演")], schema={}, max_retries=2)


# ---------- 工厂与路由 ----------


def test_get_provider_mock():
    p = get_provider("mock")
    assert isinstance(p, MockProvider)
    assert isinstance(p, LLMProvider)


def test_get_provider_real_missing_key_raises():
    with pytest.raises(LLMError):
        # 确保未设置环境变量
        import os

        os.environ.pop("DEEPSEEK_API_KEY", None)
        get_provider("deepseek", model="deepseek-chat")


def test_get_llm_for_orchestrator_uses_config():
    cfg = {
        "llm": {
            "default_provider": "mock",
            "orchestrator": {"provider": "mock", "model": "x"},
        }
    }
    p = get_llm_for("orchestrator", cfg)
    assert isinstance(p, MockProvider)


def test_get_llm_for_fallback_default():
    cfg = {"llm": {"default_provider": "mock"}}
    # 未知 role 回退到 default_provider
    p = get_llm_for("unknown_role", cfg)
    assert isinstance(p, MockProvider)


# ---------- 并行调用 ----------


async def test_gather_calls_parallel_and_isolates_errors():
    p1 = MockProvider(responses=["a"])
    p2 = MockProvider(responses=["b"])

    async def call_a():
        return await p1.chat([Message("user", "1")])

    async def call_b():
        return await p2.chat([Message("user", "2")])

    async def call_fail():
        raise RuntimeError("boom")

    results = await gather_calls([call_a(), call_b(), call_fail()])
    assert results[0] == "a"
    assert results[1] == "b"
    assert isinstance(results[2], RuntimeError)


# ---------- config.yaml 加载 ----------


def test_load_config_reads_chinese_keys():
    cfg = load_config("config.yaml")
    assert cfg["game"]["era_name"] == "崇祯"
    assert "国库" in cfg["bounds"]
    assert cfg["bounds"]["国库"]["max_delta"] == 500000
    assert cfg["finance_initial"]["treasury"] == 1000000
    assert cfg["game"]["turn_length"] == "month"


def test_config_bounds_complete():
    """计划要求的全部数值项都有边界配置。"""
    cfg = load_config("config.yaml")
    required = {
        "国库",
        "内帑",
        "民心",
        "军力",
        "军心",
        "朝堂清洗度",
        "宗室不满",
        "陕西_民心",
        "京畿_民心",
        "陕西_人口",
    }
    assert required <= set(cfg["bounds"].keys())
    for k, v in cfg["bounds"].items():
        assert {"min", "max", "max_delta"} <= set(v.keys()), k
