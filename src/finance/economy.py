"""财政系统：太仓/内帑分库 + 支出多维度分类 + 宗禄改革 + 固定/临时支出 + 每回合结算。

开局按史实数据初始化，反映明末财政危机（月收支紧平衡）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path


@dataclass
class FinanceState:
    """财政状态。"""

    treasury: int = 1_000_000  # 太仓国库
    inner_purse: int = 5_000_000  # 内帑（皇帝私库）
    income_monthly: dict = field(
        default_factory=lambda: {
            "田赋": 220000,
            "商税": 40000,
            "辽饷加派": 90000,
            "其他": 10000,
        }
    )
    expense_monthly: dict = field(
        default_factory=lambda: {
            "辽东军饷": 150000,
            "边镇京营": 80000,
            "宗室岁禄": 90000,
            "官俸": 25000,
            "其他": 15000,
        }
    )
    tax_rates: dict = field(
        default_factory=lambda: {
            "田赋率": 0.05,
            "辽饷加派率": 0.03,
            "商税率": 0.02,
        }
    )
    zonglu_reform: dict = field(default_factory=dict)  # 宗禄改革参数
    temp_expense: list = field(default_factory=list)  # 本月额外临时支出

    def settle(
        self,
        year_景: str = "平",
        war_factor: float = 1.0,
        rebellion_factor: float = 1.0,
    ) -> dict:
        """每回合财政结算。

        返回 {收入, 支出, 净, delta: {国库: 净}}。
        年景调制田赋、战事调制军饷、民变中断地方税收。
        """
        # 年景系数
        year_景_coeff = {"丰": 1.2, "平": 1.0, "灾": 0.6}.get(year_景, 1.0)

        # 收入
        income = {
            k: int(v * year_景_coeff * rebellion_factor)
            for k, v in self.income_monthly.items()
        }
        total_income = sum(income.values())

        # 支出（宗禄受改革参数调制）
        expense = dict(self.expense_monthly)
        if "宗室岁禄" in expense and self.zonglu_reform:
            cut = self.zonglu_reform.get("cut_ratio", 0)
            expense["宗室岁禄"] = int(expense["宗室岁禄"] * (1 - cut))
        expense = {
            k: int(v * war_factor) if "军" in k else v
            for k, v in expense.items()
        }
        total_expense = sum(expense.values()) + sum(self.temp_expense)

        net = total_income - total_expense
        self.temp_expense.clear()
        return {
            "收入": total_income,
            "支出": total_expense,
            "净": net,
            "delta": {"国库": net},
        }

    def transfer_inner_to_treasury(self, amount: int) -> bool:
        """内帑→太仓（允许）。"""
        if amount <= 0 or amount > self.inner_purse:
            return False
        self.inner_purse -= amount
        self.treasury += amount
        return True

    def transfer_treasury_to_inner(self, amount: int) -> bool:
        """太仓→内帑（禁止）。"""
        return False

    def apply_zonglu_reform(self, reform: dict):
        """应用宗禄改革参数。"""
        self.zonglu_reform.update(reform)

    def add_temp_expense(self, item: str, amount: int):
        """添加临时支出项。"""
        self.temp_expense.append(amount)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "FinanceState":
        return cls(**d)

    def save(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: Path) -> "FinanceState":
        return cls.from_dict(
            json.loads(path.read_text(encoding="utf-8"))
        )
