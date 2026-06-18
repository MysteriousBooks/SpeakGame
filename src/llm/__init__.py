"""LLM 接入层：多模型抽象（mock/deepseek/qwen/claude）。"""

from src.llm.provider import (
    LLMProvider,
    MockProvider,
    get_llm_for,
    get_provider,
    load_config,
)

__all__ = [
    "LLMProvider",
    "MockProvider",
    "get_provider",
    "get_llm_for",
    "load_config",
]
