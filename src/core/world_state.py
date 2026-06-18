"""世界状态层：全局数值 ground truth + delta 校验/落库 + 时间推进。

设计要点（见计划第4节架构、第6节防数值崩约束）：
- 全局数值由代码持有为 ground truth，史官输出结构化 delta，代码校验+落库。
- apply_delta 走 max_delta 裁剪（防"一刀民心+50"骤变）+ min/max 边界 clamp。
- 时间按 day 推进；turn_length（week/half_month/month）决定每回合天数。
- 历史事件按月触发，advance_time 返回本回合新跨越的月份序号供事件引擎使用。
"""

from __future__ import annotations

from dataclasses import dataclass, field

DAYS_PER_TURN: dict[str, int] = {
    "week": 7,
    "half_month": 15,
    "month": 30,
}
DAYS_PER_MONTH = 30  # MVP 简化：每月按 30 天计，便于月序计算
# 崇祯纪年 → 真实公元年：崇祯元年 = 1628 = 1627 + 1
ERA_BASE_REAL_YEAR = 1627


@dataclass
class Bounds:
    """单个数值项的边界与单回合最大变化幅度。"""

    min: float
    max: float
    max_delta: float


@dataclass
class DeltaResult:
    """apply_delta 的返回：实际生效 delta + 被裁剪/拒绝记录。"""

    applied: dict[str, float] = field(default_factory=dict)
    clipped: dict[str, str] = field(default_factory=dict)  # key -> 裁剪原因


@dataclass
class WorldState:
    """世界数值 ground truth + 时间。"""

    values: dict[str, float]
    bounds: dict[str, Bounds]
    day: int = 0  # 从开局累计天数
    last_month_index: int = 0  # 上次结算时的月份序号（用于判断跨月）
    era: str = "崇祯"
    start_year: int = 1
    start_month: int = 1

    # ---------- 构造 ----------
    @classmethod
    def initial(cls, config: dict) -> "WorldState":
        game = config.get("game", {})
        bounds_cfg = config.get("bounds", {})
        world_init = config.get("world_initial", {})
        bounds = {k: Bounds(**v) for k, v in bounds_cfg.items()}
        # 数值初始化：取 world_initial，缺项回退到 bounds.min
        values: dict[str, float] = {}
        for key, b in bounds.items():
            if key in world_init:
                values[key] = float(world_init[key])
            else:
                values[key] = float(b.min)
        # world_initial 中可能有 bounds 之外的项（一般不会，但保留）
        for key, val in world_init.items():
            values.setdefault(key, float(val))
        return cls(
            values=values,
            bounds=bounds,
            day=0,
            last_month_index=0,
            era=game.get("era_name", "崇祯"),
            start_year=int(game.get("start_year", 1)),
            start_month=int(game.get("start_month", 1)),
        )

    # ---------- delta 校验与落库 ----------
    def apply_delta(self, delta: dict[str, float]) -> DeltaResult:
        """应用史官输出的 delta：裁剪 max_delta + clamp 到 [min,max]，返回生效结果。

        未知 key 记录为 clipped（reason="unknown_key"）但不抛错，便于史官重推时拿到反馈。
        """
        result = DeltaResult()
        for key, change in delta.items():
            if key not in self.bounds:
                result.clipped[key] = "unknown_key"
                continue
            b = self.bounds[key]
            change = float(change)
            # max_delta 裁剪：单回合变化幅度上限
            if abs(change) > b.max_delta:
                sign = 1 if change > 0 else -1
                original = change
                change = sign * b.max_delta
                result.clipped[key] = f"max_delta:{original}->{change}"
            new_val = self.values[key] + change
            # min/max 边界 clamp
            clamped = max(b.min, min(b.max, new_val))
            if clamped != new_val:
                result.clipped.setdefault(key, f"bound:{new_val}->{clamped}")
            actual = clamped - self.values[key]
            self.values[key] = clamped
            result.applied[key] = actual
        return result

    # ---------- 时间 ----------
    def current_month_index(self) -> int:
        """从开局累计的月份序号（0=开局月）。"""
        return self.day // DAYS_PER_MONTH

    def current_year_month(self) -> tuple[int, int]:
        """返回 (崇祯纪年, 月份)。崇祯元年正月为起点。"""
        m = self.current_month_index()
        total = (self.start_month - 1) + m
        year = self.start_year + total // 12
        month = total % 12 + 1
        return year, month

    def era_label(self) -> str:
        """如 '崇祯1年1月'。"""
        y, m = self.current_year_month()
        return f"{self.era}{y}年{m}月"

    def real_year(self) -> int:
        """当前崇祯纪年对应的真实公元年（历史角色卡用真实公元年，需转换）。"""
        y, _ = self.current_year_month()
        return ERA_BASE_REAL_YEAR + y

    def advance_time(self, turn_length: str) -> list[int]:
        """推进一个回合，返回本回合新跨越的月份序号列表（用于按月触发历史事件）。

        例如 week 模式 7 天通常不跨月（除非靠近月末），month 模式 30 天跨 1 月。
        """
        if turn_length not in DAYS_PER_TURN:
            raise ValueError(f"未知 turn_length: {turn_length}")
        old = self.last_month_index
        self.day += DAYS_PER_TURN[turn_length]
        new = self.current_month_index()
        crossed = list(range(old + 1, new + 1))
        self.last_month_index = new
        return crossed

    # ---------- 序列化 ----------
    def to_dict(self) -> dict:
        return {
            "values": dict(self.values),
            "day": self.day,
            "last_month_index": self.last_month_index,
            "era": self.era,
            "start_year": self.start_year,
            "start_month": self.start_month,
        }

    @classmethod
    def from_dict(cls, data: dict, bounds: dict[str, Bounds]) -> "WorldState":
        return cls(
            values={k: float(v) for k, v in data["values"].items()},
            bounds=bounds,
            day=int(data["day"]),
            last_month_index=int(data["last_month_index"]),
            era=data.get("era", "崇祯"),
            start_year=int(data["start_year"]),
            start_month=int(data["start_month"]),
        )
