"""世界状态层：全局数值 ground truth + delta 代码校验/落库 + 时间推进。

agent 间信息隔离不变，但全局数值由代码持有为 ground truth，
史官 agent 输出结构化 delta，代码校验后落库。这是"轻状态层兜底"。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path

# 数值边界（与 config.yaml 对应，此处内嵌默认，可被 config 覆盖）
DEFAULT_BOUNDS: dict[str, dict] = {
    "国库": {"min": 0, "max": 10_000_000, "max_delta": 500_000},
    "内帑": {"min": 0, "max": 10_000_000, "max_delta": 1_000_000},
    "民心": {"min": 0, "max": 100, "max_delta": 30},
    "军力": {"min": 0, "max": 100, "max_delta": 20},
    "军心": {"min": 0, "max": 100, "max_delta": 25},
    "朝堂清洗度": {"min": 0, "max": 100, "max_delta": 40},
    "宗室不满": {"min": 0, "max": 100, "max_delta": 30},
    "陕西_民心": {"min": 0, "max": 100, "max_delta": 30},
    "京畿_民心": {"min": 0, "max": 100, "max_delta": 30},
    "陕西_人口": {"min": 0, "max": 10_000_000, "max_delta": 500_000},
}

TURN_DAYS = {"week": 7, "half_month": 15, "month": 30}


@dataclass
class WorldState:
    """世界状态 ground truth。"""

    era: str = "崇祯"
    year: int = 1  # 崇祯元年
    month: int = 1
    day: int = 1
    # 崇祯登基开局数值（反映登基局势：国库枯竭、陕西民心低迷、军力受辽饷拖累）
    values: dict = field(
        default_factory=lambda: {
            "国库": 1_000_000,
            "内帑": 5_000_000,
            "民心": 55,
            "军力": 60,
            "军心": 55,
            "朝堂清洗度": 10,  # 阉党未除，清洗度低
            "宗室不满": 20,
            "陕西_民心": 30,
            "京畿_民心": 50,
            "陕西_人口": 5_000_000,
        }
    )
    active_events: list = field(default_factory=list)
    resolved_events: list = field(default_factory=list)
    active_tasks: list = field(default_factory=list)

    def snapshot(self) -> dict:
        """供史官 agent 读取的数值快照（只读副本）。"""
        return dict(self.values)

    def get(self, key: str) -> float:
        return self.values.get(key, 0)

    def advance(self, turn_length: str = "month"):
        """按 turn_length 推进时间。"""
        days = TURN_DAYS.get(turn_length, 30)
        self.day += days
        while self.day > 30:
            self.day -= 30
            self.month += 1
            if self.month > 12:
                self.month = 1
                self.year += 1

    def era_label(self) -> str:
        return f"{self.era}{self.year}年{self.month}月"

    def validate_delta(
        self, delta: dict, bounds: dict | None = None
    ) -> tuple[dict, list[str]]:
        """校验史官输出的 delta，返回 (裁剪后实际delta, 错误信息列表)。

        - 数值不得越界（min/max），超界裁剪到边界
        - 单回合变更幅度上限 max_delta，超幅度裁剪
        - 未知数值键报错（防 LLM 凭空捏造新数值）
        """
        b = bounds or DEFAULT_BOUNDS
        applied: dict = {}
        errors: list[str] = []
        for key, change in delta.items():
            if key not in b:
                errors.append(f"未知数值键 '{key}'，已忽略")
                continue
            bound = b[key]
            cur = self.values.get(key, 0)
            # 幅度裁剪
            md = bound.get("max_delta")
            if md is not None and abs(change) > md:
                errors.append(
                    f"'{key}' 变更 {change} 超幅度上限 {md}，裁剪"
                )
                change = -md if change < 0 else md
            new_val = cur + change
            # 边界裁剪
            lo, hi = bound["min"], bound["max"]
            if new_val < lo:
                errors.append(f"'{key}' 新值 {new_val} 低于下限 {lo}，裁剪")
                new_val = lo
            elif new_val > hi:
                errors.append(
                    f"'{key}' 新值 {new_val} 高于上限 {hi}，裁剪"
                )
                new_val = hi
            applied[key] = new_val - cur  # 实际应用的变化量
        return applied, errors

    def apply(self, applied_delta: dict):
        """落库已校验的 delta。"""
        for k, v in applied_delta.items():
            self.values[k] = self.values.get(k, 0) + v

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "WorldState":
        return cls(**d)

    def save(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: Path) -> "WorldState":
        return cls.from_dict(
            json.loads(path.read_text(encoding="utf-8"))
        )
