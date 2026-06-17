"""Benchmark 系统：同诏书跑多次验证 delta 一致性 + 成本统计。"""
from __future__ import annotations

import json
import time
from collections import Counter
from pathlib import Path
from typing import Optional

from src.core.world_state import WorldState, DEFAULT_BOUNDS
from src.finance.economy import FinanceState


class Benchmark:
    """基准测试：同诏书跑 N 次，检查 delta 一致性。"""

    def __init__(self, target_consistency: float = 0.8):
        self.target = target_consistency
        self.results: list[dict] = []

    def run(
        self,
        edict: str,
        n: int = 10,
        state: Optional[WorldState] = None,
        finance: Optional[FinanceState] = None,
    ) -> dict:
        """运行 N 次推演，返回一致性报告。"""
        deltas: list[dict] = []
        for _ in range(n):
            s = WorldState() if state is None else WorldState.from_dict(
                state.to_dict()
            )
            # mock 推演（实际应调 LLM）
            delta = {"国库": -100_000, "陕西_民心": 5}
            applied, _ = s.validate_delta(delta, DEFAULT_BOUNDS)
            s.apply(applied)
            deltas.append(applied)

        # 分析一致性
        delta_strs = [json.dumps(d, sort_keys=True) for d in deltas]
        counts = Counter(delta_strs)
        most_common = counts.most_common(1)[0]
        consistency = most_common[1] / n

        result = {
            "edict": edict,
            "n": n,
            "consistency": consistency,
            "passed": consistency >= self.target,
            "unique_outcomes": len(counts),
            "most_common_delta": json.loads(most_common[0]),
        }
        self.results.append(result)
        return result

    def report(self) -> str:
        """生成可读报告。"""
        lines = ["=== Benchmark Report ==="]
        for r in self.results:
            status = "✅" if r["passed"] else "❌"
            lines.append(
                f"{status} {r['edict'][:20]} x{r['n']}: "
                f"一致性 {r['consistency']:.0%} "
                f"(目标 {self.target:.0%}), "
                f"唯一结果 {r['unique_outcomes']} 种"
            )
        return "\n".join(lines)


class CostTracker:
    """Token 成本统计。"""

    def __init__(self):
        self.total_tokens: int = 0
        self.total_cost: float = 0.0
        self.turn_count: int = 0
        self._prices = {
            "deepseek": {"input": 0.00014, "output": 0.00028},  # per 1K tokens
            "claude": {"input": 0.003, "output": 0.015},
            "qwen": {"input": 0.0005, "output": 0.002},
        }

    def record(self, provider: str, input_tokens: int, output_tokens: int):
        """记录一次 LLM 调用。"""
        prices = self._prices.get(provider, self._prices["deepseek"])
        cost = (input_tokens * prices["input"] + output_tokens * prices["output"]) / 1000
        self.total_tokens += input_tokens + output_tokens
        self.total_cost += cost
        self.turn_count += 1

    def avg_cost_per_turn(self) -> float:
        return self.total_cost / self.turn_count if self.turn_count else 0.0

    def report(self) -> str:
        return (
            f"总 Token: {self.total_tokens:,} | "
            f"总成本: ${self.total_cost:.4f} | "
            f"回合数: {self.turn_count} | "
            f"均成本/回合: ${self.avg_cost_per_turn():.4f}"
        )


class LLMCache:
    """LLM 调用缓存（相同输入命中缓存，减少重复调用）。"""

    def __init__(self):
        self._cache: dict[str, str] = {}
        self.hits: int = 0
        self.misses: int = 0

    def _key(self, messages: list[dict], model: str) -> str:
        return f"{model}:{json.dumps(messages, sort_keys=True, ensure_ascii=False)}"

    def get(self, messages: list[dict], model: str) -> Optional[str]:
        key = self._key(messages, model)
        if key in self._cache:
            self.hits += 1
            return self._cache[key]
        self.misses += 1
        return None

    def set(self, messages: list[dict], model: str, response: str):
        key = self._key(messages, model)
        self._cache[key] = response

    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total else 0.0
