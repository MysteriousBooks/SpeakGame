"""LLM provider 单元测试（mock 模式，无需 API Key）。"""
import pytest
from src.llm.provider import get_provider, MockProvider


@pytest.mark.asyncio
async def test_mock_provider_chat():
    """Mock provider 返回结构化 JSON 占位响应。"""
    provider = get_provider("mock", "mock")
    assert isinstance(provider, MockProvider)

    # 史官场景
    resp = await provider.chat([{"role": "user", "content": "史官推演"}])
    import json
    data = json.loads(resp)
    assert "narrative" in data
    assert "delta" in data
    assert "国库" in data["delta"]

    # 编排场景
    resp2 = await provider.chat([{"role": "user", "content": "编排分派"}])
    data2 = json.loads(resp2)
    assert "targets" in data2

    # 角色 agent 场景
    resp3 = await provider.chat([{"role": "user", "content": "臣有本奏"}])
    data3 = json.loads(resp3)
    assert "public" in data3
    assert "private" in data3
    assert "want_audience" in data3


@pytest.mark.asyncio
async def test_mock_provider_stream():
    """Mock provider 流式输出正常。"""
    provider = get_provider("mock", "mock")
    chunks = []
    async for chunk in provider.stream([{"role": "user", "content": "史官推演"}]):
        chunks.append(chunk)
    assert len(chunks) > 0
    # 合并后应为有效 JSON
    import json
    data = json.loads("".join(chunks))
    assert "narrative" in data


@pytest.mark.asyncio
async def test_get_provider_unknown():
    """未知 provider 应抛出 ValueError。"""
    with pytest.raises(ValueError, match="未知 provider"):
        get_provider("nonexistent", "x")
