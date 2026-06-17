"""M4 稳定性/缓存/benchmark 测试。"""
import pytest

from src.core.benchmark import Benchmark, CostTracker, LLMCache


def test_benchmark_consistency():
    b = Benchmark(target_consistency=0.8)
    result = b.run("拨银十万赈陕西", n=10)
    assert result["n"] == 10
    assert "consistency" in result
    assert "passed" in result


def test_benchmark_report():
    b = Benchmark()
    b.run("赈灾", n=5)
    b.run("加征辽饷", n=5)
    report = b.report()
    assert "Benchmark Report" in report
    assert "赈灾" in report
    assert "加征辽饷" in report


def test_cost_tracker():
    t = CostTracker()
    t.record("deepseek", 500, 200)
    t.record("deepseek", 300, 150)
    assert t.total_tokens == 1150
    assert t.turn_count == 2
    assert t.avg_cost_per_turn() > 0


def test_cost_tracker_claude():
    t = CostTracker()
    t.record("claude", 1000, 500)
    claude_cost = t.total_cost
    t.record("deepseek", 1000, 500)
    assert claude_cost > t.total_cost - claude_cost  # Claude 比 DeepSeek 贵


def test_llm_cache():
    c = LLMCache()
    msgs = [{"role": "user", "content": "史官推演"}]
    # 首次 miss
    result = c.get(msgs, "deepseek")
    assert result is None
    assert c.misses == 1
    # set 后 hit
    c.set(msgs, "deepseek", "mock response")
    result2 = c.get(msgs, "deepseek")
    assert result2 == "mock response"
    assert c.hits == 1


def test_llm_cache_different_model():
    c = LLMCache()
    msgs = [{"role": "user", "content": "史官推演"}]
    c.set(msgs, "deepseek", "deepseek response")
    # 不同 model 不同 key
    result = c.get(msgs, "claude")
    assert result is None


def test_llm_cache_hit_rate():
    c = LLMCache()
    msgs = [{"role": "user", "content": "test"}]
    c.get(msgs, "m")  # miss
    c.set(msgs, "m", "r")
    c.get(msgs, "m")  # hit
    assert c.hit_rate() == 0.5
