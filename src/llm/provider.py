"""LLM 接入层：多模型抽象（mock/deepseek/qwen/claude）。

设计要点（见计划第4节架构、第7节技术选型）：
- httpx 直连各家 API，最可控，避免抽象与信息隔离需求错配。
- Key 从环境变量读取（.env / 进程环境）。
- 双模型策略：编排/史官用强模型，角色 agent 用低成本模型——通过 get_llm_for(role) 路由。
- chat_json 强约束：把 schema 描述注入提示，解析失败重试（≤ max_retries），仍失败抛错或兜底。
- asyncio 并行多 agent 调用（gather_calls）。
"""

from __future__ import annotations

import asyncio
import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Sequence

import httpx
import yaml

# 各 provider 默认 base_url 与所需环境变量
DEFAULT_BASE_URLS: dict[str, str] = {
    "deepseek": "https://api.deepseek.com",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "claude": "https://api.anthropic.com",
    "ollama": "http://localhost:11434/v1",
}
ENV_KEY: dict[str, str] = {
    "deepseek": "DEEPSEEK_API_KEY",
    "qwen": "DASHSCOPE_API_KEY",
    "claude": "ANTHROPIC_API_KEY",
}

# JSON 提取辅助正则不需要——优先用 json.loads 兜底解析
_JSON_TIMEOUT = 60.0


@dataclass
class Message:
    """对话消息。role: system/user/assistant。"""

    role: str
    content: str

    def to_dict(self) -> dict:
        return {"role": self.role, "content": self.content}


def _strip_json(text: str) -> str:
    """从模型输出中抠出 JSON 对象（容忍 ```json 围栏与前后缀文字）。"""
    s = text.strip()
    if s.startswith("```"):
        # 去掉围栏
        s = s.strip("`")
        if s.lower().startswith("json"):
            s = s[4:]
        s = s.strip()
    # 取最外层花括号
    start = s.find("{")
    end = s.rfind("}")
    if start != -1 and end != -1 and end > start:
        s = s[start : end + 1]
    return s


def parse_json(text: str) -> dict:
    """宽松解析模型输出的 JSON，失败抛 ValueError。"""
    return json.loads(_strip_json(text))


class LLMError(RuntimeError):
    """LLM 调用或解析错误。"""


class LLMProvider(ABC):
    """LLM provider 抽象基类。"""

    name: str = "base"

    @abstractmethod
    async def chat(
        self,
        messages: Sequence[Message],
        *,
        system: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.7,
    ) -> str:
        """同步返回完整回复文本。"""

    async def chat_json(
        self,
        messages: Sequence[Message],
        *,
        schema: dict,
        system: str | None = None,
        max_retries: int = 2,
        max_tokens: int = 2048,
        temperature: float = 0.3,
    ) -> dict:
        """强约束输出 JSON。把 schema 描述注入 system，解析失败重试。

        失败 max_retries 次后抛 LLMError（上层可兜底默认值）。
        """
        schema_hint = (
            "你必须只输出一个合法 JSON 对象，不要任何解释文字或 Markdown 围栏。"
            f"结构需符合以下 JSON Schema：\n{json.dumps(schema, ensure_ascii=False, indent=2)}\n"
        )
        sys_prompt = (system + "\n\n" if system else "") + schema_hint
        last_err: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                text = await self.chat(
                    messages, system=sys_prompt, max_tokens=max_tokens, temperature=temperature
                )
                return parse_json(text)
            except (ValueError, LLMError) as exc:
                last_err = exc
                # 重试时追加纠正提示
                messages = list(messages) + [
                    Message("assistant", text if "text" in locals() else ""),
                    Message(
                        "user",
                        f"你的上一次输出无法解析为 JSON（错误：{exc}）。请只输出符合 schema 的合法 JSON 对象。",
                    ),
                ]
        raise LLMError(f"chat_json 解析失败 {max_retries + 1} 次：{last_err}")

    async def stream(
        self,
        messages: Sequence[Message],
        *,
        system: str | None = None,
        max_tokens: int = 2048,
    ) -> AsyncIterator[str]:
        """流式输出 token 增量。默认实现退化为一次性 yield 完整文本。"""
        yield await self.chat(messages, system=system, max_tokens=max_tokens)
        if False:  # pragma: no cover - 保持生成器语义
            yield ""

    async def close(self) -> None:
        """释放底层资源（http 连接池等）。"""


class MockProvider(LLMProvider):
    """确定性 mock provider，用于测试与离线开发。

    - responses: chat() 按序消费的预设文本（耗尽后循环末项）。
    - json_responses: chat_json() 按序消费的预设 dict（耗尽后循环末项）。
    - responder: 可选回调 (messages, system) -> str，覆盖 responses。
    - json_responder: 可选回调 (messages, schema) -> dict，覆盖 json_responses。
    记录所有调用到 .calls 便于断言。
    """

    name = "mock"

    def __init__(
        self,
        responses: Sequence[str] | None = None,
        json_responses: Sequence[dict] | None = None,
        responder: Callable[[Sequence[Message], str | None], str] | None = None,
        json_responder: Callable[[Sequence[Message], dict], dict] | None = None,
        passthrough_json: bool = False,
    ) -> None:
        self._responses: list[str] = list(responses or [])
        self._json: list[dict] = list(json_responses or [])
        self._idx = 0
        self._jidx = 0
        self._responder = responder
        self._json_responder = json_responder
        self.passthrough_json = passthrough_json
        self.calls: list[dict] = []

    async def chat(
        self,
        messages: Sequence[Message],
        *,
        system: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.7,
    ) -> str:
        self.calls.append(
            {"kind": "chat", "messages": [m.to_dict() for m in messages], "system": system}
        )
        if self._responder is not None:
            return self._responder(messages, system)
        if self._responses:
            text = self._responses[min(self._idx, len(self._responses) - 1)]
            self._idx += 1
            return text
        return "（mock 回复）"

    async def chat_json(
        self,
        messages: Sequence[Message],
        *,
        schema: dict,
        system: str | None = None,
        max_retries: int = 2,
        max_tokens: int = 2048,
        temperature: float = 0.3,
    ) -> dict:
        # passthrough_json=True 时不短路，走基类重试逻辑（用于测试基类的解析重试）
        if not self.passthrough_json:
            self.calls.append(
                {"kind": "chat_json", "messages": [m.to_dict() for m in messages], "schema": schema}
            )
            if self._json_responder is not None:
                return self._json_responder(messages, schema)
            if self._json:
                obj = self._json[min(self._jidx, len(self._json) - 1)]
                self._jidx += 1
                return obj
            return {}
        return await super().chat_json(
            messages,
            schema=schema,
            system=system,
            max_retries=max_retries,
            max_tokens=max_tokens,
            temperature=temperature,
        )

    async def stream(
        self,
        messages: Sequence[Message],
        *,
        system: str | None = None,
        max_tokens: int = 2048,
    ) -> AsyncIterator[str]:
        text = await self.chat(messages, system=system, max_tokens=max_tokens)
        for ch in text:
            yield ch

    async def close(self) -> None:
        pass


class _OpenAICompatibleProvider(LLMProvider):
    """DeepSeek / Qwen 等 OpenAI Chat Completions 兼容 provider。"""

    def __init__(
        self,
        name: str,
        model: str,
        api_key: str,
        base_url: str | None = None,
        *,
        timeout: float = 60.0,
    ) -> None:
        self.name = name
        self.model = model
        self.api_key = api_key
        self.base_url = (base_url or DEFAULT_BASE_URLS.get(name, "")).rstrip("/")
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=self.timeout,
            )
        return self._client

    async def chat(
        self,
        messages: Sequence[Message],
        *,
        system: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.7,
    ) -> str:
        client = await self._ensure_client()
        payload_msgs = ([{"role": "system", "content": system}] if system else []) + [
            m.to_dict() for m in messages
        ]
        resp = await client.post(
            "/chat/completions",
            json={
                "model": self.model,
                "messages": payload_msgs,
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    async def stream(
        self,
        messages: Sequence[Message],
        *,
        system: str | None = None,
        max_tokens: int = 2048,
    ) -> AsyncIterator[str]:
        client = await self._ensure_client()
        payload_msgs = ([{"role": "system", "content": system}] if system else []) + [
            m.to_dict() for m in messages
        ]
        async with client.stream(
            "POST",
            "/chat/completions",
            json={
                "model": self.model,
                "messages": payload_msgs,
                "max_tokens": max_tokens,
                "stream": True,
            },
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line.startswith("data: ") and line.strip() != "data: [DONE]":
                    try:
                        chunk = json.loads(line[6:])
                        delta = chunk["choices"][0]["delta"].get("content")
                        if delta:
                            yield delta
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


class ClaudeProvider(LLMProvider):
    """Anthropic Messages API provider。"""

    name = "claude"

    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: str | None = None,
        *,
        timeout: float = 60.0,
    ) -> None:
        self.model = model
        self.api_key = api_key
        self.base_url = (base_url or DEFAULT_BASE_URLS["claude"]).rstrip("/")
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                timeout=self.timeout,
            )
        return self._client

    async def chat(
        self,
        messages: Sequence[Message],
        *,
        system: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.7,
    ) -> str:
        client = await self._ensure_client()
        # Claude 要求 user/assistant 交替，过滤 system
        payload_msgs = [m.to_dict() for m in messages if m.role != "system"]
        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": payload_msgs,
            "temperature": temperature,
        }
        if system:
            body["system"] = system
        resp = await client.post("/v1/messages", json=body)
        resp.raise_for_status()
        data = resp.json()
        # content 是 list of blocks
        return "".join(block.get("text", "") for block in data.get("content", []))

    async def stream(
        self,
        messages: Sequence[Message],
        *,
        system: str | None = None,
        max_tokens: int = 2048,
    ) -> AsyncIterator[str]:
        client = await self._ensure_client()
        payload_msgs = [m.to_dict() for m in messages if m.role != "system"]
        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": payload_msgs,
            "stream": True,
        }
        if system:
            body["system"] = system
        async with client.stream("POST", "/v1/messages", json=body) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    try:
                        evt = json.loads(line[6:])
                        if evt.get("type") == "content_block_delta":
                            delta = evt.get("delta", {})
                            if delta.get("type") == "text_delta":
                                yield delta.get("text", "")
                    except json.JSONDecodeError:
                        continue

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


def _default_mock_json(messages: Sequence[Message], schema: dict) -> dict:
    """根据 schema 自动生成有意义的 mock 响应（而非空 {}）。"""
    props = schema.get("properties", {})
    result: dict = {}

    # --- 编排 schema（action + dispatch_targets） ---
    if "action" in props and "dispatch_targets" in props:
        result["action"] = "execute"
        result["dispatch_targets"] = []
        result["visits"] = []
        result["activation_order"] = []
        result["reason"] = "（mock 编排：默认执行）"
        return result

    # --- 史官 schema（narrative + delta + audience_queue） ---
    if "narrative" in props and "delta" in props:
        result["narrative"] = "（mock 叙事）帝下诏，群臣奉行，朝局如常。"
        result["delta"] = {"民心": 1, "军力": 0}
        result["finance_delta"] = {}
        result["new_events"] = []
        result["factual_notes"] = ["mock 回合执行完毕"]
        result["audience_queue"] = []
        result["premonitions"] = []
        return result

    # --- agent schema（public + private + want_audience） ---
    if "public" in props and "private" in props:
        # 从用户消息中提取问题内容，融入回复
        user_msg = ""
        if messages:
            user_msg = messages[-1].content[:80]
        result["public"] = f"臣已听明陛下所言：「{user_msg}」。臣当即刻着手办理，容臣细细筹划后上奏。"
        result["private"] = f"（内心）陛下问及「{user_msg}」，此事涉及甚广，须谨慎应对，不可轻易承诺。"
        result["want_audience"] = False
        result["audience_topic"] = ""
        return result

    # --- 兜底：按 schema 类型填默认值 ---
    for key, val in props.items():
        t = val.get("type", "string")
        if t == "string":
            result[key] = f"（mock {key}）"
        elif t == "number" or t == "integer":
            result[key] = 0
        elif t == "boolean":
            result[key] = False
        elif t == "array":
            result[key] = []
        elif t == "object":
            result[key] = {}
    return result


def get_provider(
    name: str,
    *,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
) -> LLMProvider:
    """工厂：按 name 创建 provider。mock 无需 Key，ollama 无需 Key。"""
    name = name.lower()
    if name == "mock":
        return MockProvider(json_responder=_default_mock_json)
    # Ollama：本地运行，无需 API Key，OpenAI 兼容格式
    if name == "ollama":
        ollama_url = base_url or os.environ.get("OLLAMA_BASE_URL", DEFAULT_BASE_URLS["ollama"])
        return _OpenAICompatibleProvider(
            "ollama", model or "qwen2.5", "ollama", ollama_url
        )
    key = api_key or os.environ.get(ENV_KEY.get(name, ""), "")
    if not key:
        raise LLMError(f"provider {name} 缺少 API Key（环境变量 {ENV_KEY.get(name)} 未设置）")
    if name == "claude":
        return ClaudeProvider(model or "claude-sonnet-4-6", key, base_url)
    if name in ("deepseek", "qwen"):
        return _OpenAICompatibleProvider(
            name, model or "deepseek-chat", key, base_url
        )
    raise LLMError(f"未知 provider: {name}")


def load_config(path: str | Path = "config.yaml") -> dict:
    """加载 config.yaml（UTF-8，含中文 key）。"""
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_llm_for(role_key: str, config: dict, **overrides) -> LLMProvider:
    """按角色（orchestrator/historian/role_agent）从 config.llm 路由对应 provider。

    role_key 不在 config.llm 时回退到 default_provider。
    指定 provider 缺 API Key 时回退到 default_provider（mock），保证离线可跑。
    """
    llm_cfg = config.get("llm", {})
    role_cfg = llm_cfg.get(role_key)
    if role_cfg is None:
        name = llm_cfg.get("default_provider", "mock")
        model = None
    else:
        name = role_cfg.get("provider", llm_cfg.get("default_provider", "mock"))
        model = role_cfg.get("model")
    try:
        return get_provider(name, model=model, **overrides)
    except LLMError:
        # 缺 Key 等情况回退到 default_provider（通常是 mock），保证离线/测试可跑
        fallback = llm_cfg.get("default_provider", "mock")
        if name == fallback:
            raise
        return get_provider(fallback)


async def gather_calls(
    providers_calls: Sequence[Any],
) -> list[Any]:
    """并行执行多个 (provider, method, args) 调用，返回结果列表。

    每个元素为 (coroutine) —— 直接传入协程即可，本函数等价于 asyncio.gather 的安全版本：
    任一失败返回该位置的异常对象而非整体抛出，便于上层按位处理。
    """
    async def _safe(coro):
        try:
            return await coro
        except Exception as exc:  # noqa: BLE001
            return exc

    return await asyncio.gather(*[_safe(c) for c in providers_calls])
