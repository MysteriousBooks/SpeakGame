"""LLM 多模型接入抽象层。

支持 DeepSeek / Qwen（OpenAI 兼容）/ Claude（Anthropic）/ Mock。
开发期可用 mock 模式在无 API Key 下跑通逻辑。
"""
from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from typing import AsyncIterator

import httpx
from dotenv import load_dotenv

load_dotenv()


class LLMProvider(ABC):
    """LLM 提供方抽象。"""

    def __init__(self, model: str):
        self.model = model

    @abstractmethod
    async def chat(
        self,
        messages: list[dict],
        *,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        response_format: dict | None = None,
    ) -> str:
        """同步（非流式）对话，返回完整文本。"""

    @abstractmethod
    async def stream(
        self,
        messages: list[dict],
        *,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> AsyncIterator[str]:
        """流式对话，逐 token 产出文本片段。"""


class OpenAICompatProvider(LLMProvider):
    """DeepSeek / Qwen 等 OpenAI 兼容接口。"""

    def __init__(self, model: str, api_key: str, base_url: str):
        super().__init__(model)
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    async def chat(
        self,
        messages,
        *,
        temperature=0.7,
        max_tokens=1024,
        response_format=None,
    ):
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            payload["response_format"] = response_format
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]

    async def stream(self, messages, *, temperature=0.7, max_tokens=1024):
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        chunk = line[6:]
                        if chunk == "[DONE]":
                            break
                        data = json.loads(chunk)
                        delta = data["choices"][0]["delta"].get("content")
                        if delta:
                            yield delta


class ClaudeProvider(LLMProvider):
    """Anthropic Claude 接口。"""

    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: str = "https://api.anthropic.com",
    ):
        super().__init__(model)
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def _split(self, messages):
        """Claude 要求 system 单独传；messages 只含 user/assistant。"""
        system = ""
        conv = []
        for m in messages:
            if m["role"] == "system":
                system += m["content"] + "\n"
            else:
                conv.append(m)
        return system.strip(), conv

    async def chat(
        self,
        messages,
        *,
        temperature=0.7,
        max_tokens=1024,
        response_format=None,
    ):
        system, conv = self._split(messages)
        payload = {
            "model": self.model,
            "messages": conv,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system:
            payload["system"] = system
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{self.base_url}/v1/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()["content"][0]["text"]

    async def stream(self, messages, *, temperature=0.7, max_tokens=1024):
        text = await self.chat(
            messages, temperature=temperature, max_tokens=max_tokens
        )
        for i in range(0, len(text), 4):
            yield text[i : i + 4]


class MockProvider(LLMProvider):
    """无 API Key 下的确定性 mock，用于跑通逻辑与测试。

    根据输入关键词产生结构化占位响应。仅用于开发/测试，不用于真实推演。
    """

    async def chat(
        self,
        messages,
        *,
        temperature=0.7,
        max_tokens=1024,
        response_format=None,
    ):
        last = messages[-1]["content"] if messages else ""
        # 识别调用场景，返回对应结构化 JSON 占位
        if "史官" in last or "delta" in last.lower() or "narrative" in last.lower():
            return json.dumps(
                {
                    "narrative": "[mock] 诏书已下，户部执行，国库支出，陕西民心略升。",
                    "delta": {"国库": -100000, "陕西_民心": 8},
                    "new_events": [],
                    "factual_notes": ["崇祯元年春，帝拨银赈陕西(mock)"],
                    "audience_queue": [],
                },
                ensure_ascii=False,
            )
        if "编排" in last or "分派" in last:
            return json.dumps(
                {
                    "targets": ["minister_finance"],
                    "visits": [],
                    "order": ["minister_finance"],
                },
                ensure_ascii=False,
            )
        # 角色 agent
        return json.dumps(
            {
                "public": "[mock] 臣以为当从国库拨银赈灾，以安民心。",
                "private": "[mock] 然国库空虚，此议或招怨言。",
                "want_audience": False,
                "audience_topic": "",
            },
            ensure_ascii=False,
        )

    async def stream(self, messages, *, temperature=0.7, max_tokens=1024):
        text = await self.chat(
            messages, temperature=temperature, max_tokens=max_tokens
        )
        for i in range(0, len(text), 4):
            yield text[i : i + 4]


def get_provider(provider: str, model: str) -> LLMProvider:
    """工厂：按 provider 名构建实例。"""
    p = (provider or "").lower()
    if p == "mock":
        return MockProvider(model or "mock")
    if p == "deepseek":
        return OpenAICompatProvider(
            model or "deepseek-chat",
            os.getenv("DEEPSEEK_API_KEY", ""),
            os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        )
    if p == "qwen":
        return OpenAICompatProvider(
            model or "qwen-plus",
            os.getenv("DASHSCOPE_API_KEY", ""),
            os.getenv(
                "QWEN_BASE_URL",
                "https://dashscope.aliyuncs.com/compatible-mode/v1",
            ),
        )
    if p == "claude":
        return ClaudeProvider(
            model or "claude-opus-4-8",
            os.getenv("ANTHROPIC_API_KEY", ""),
            os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com"),
        )
    raise ValueError(f"未知 provider: {provider}")
