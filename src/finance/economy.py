"""财政系统：太仓国库 / 内帑分库 + 支出多维度分类 + 宗禄改革 + 固定/临时支出 + 每回合结算。

设计要点（见计划第3节"金钱/财政系统"）：
- 太仓国库（公共财政，紧张）与内帑（皇帝私库，相对充裕）分开记账。
- 每回合结算：国库 += 实际收入 - 实际支出 - 临时支出（国库项）；内帑 -= 临时支出（内帑项）。
- 实际收支由名义项 × 动态系数计算（年景调制田赋、战事调制军饷、民变中断地方税）。
- 内帑→国库 允许；太仓→内帑 禁止（公帑不可入私库），强行触发"朝野哗然"事件。
- 政令改变税率/支出规模/宗禄改革参数 → 下回合结算用新参数 → 收支变化值随之变动。
- 国库/内帑 数值的 ground truth 在 WorldState.values；FinanceParams 只存收支项/税率/改革参数。
"""

from __future__ import annotations

from dataclasses import dataclass, field

# 年景 → 田赋系数
HARVEST_FACTOR = {"丰收": 1.2, "平": 1.0, "灾": 0.5}
# 战时军饷系数
WARTIME_FACTOR = 1.3
# 每个民变省份对田赋的扣减比例（最多扣 50%）
REVOLT_DEDUCT_PER_PROVINCE = 0.25
REVOLT_DEDUCT_CAP = 0.5
# 折钞的隐性赖账比例（宝钞贬值，实际支出折减）
PAPER_MONEY_DISCOUNT = 0.5


@dataclass
class FinanceParams:
    """财政参数（收支项、税率、宗禄改革）。国库/内帑 数值在 WorldState.values。"""

    income_monthly: dict[str, float]
    expense_monthly: dict[str, float]
    tax_rates: dict[str, float]
    # 宗禄改革：cut_ratio 削减比例、paper_ratio 折钞比例（0~1）
    zonglu_reform: dict[str, float] = field(default_factory=lambda: {"cut_ratio": 0.0, "paper_ratio": 0.0})

    @classmethod
    def from_config(cls, config: dict) -> "FinanceParams":
        fin = config.get("finance_initial", {})
        return cls(
            income_monthly=dict(fin.get("income_monthly", {})),
            expense_monthly=dict(fin.get("expense_monthly", {})),
            tax_rates=dict(fin.get("tax_rates", {})),
        )

    def replace(self, **changes) -> "FinanceParams":
        """不可变更新：返回修改后的新 FinanceParams（保留未改字段）。"""
        from dataclasses import replace as _replace

        return _replace(self, **changes)


@dataclass
class SettlementResult:
    """每回合财政结算结果。"""

    income_actual: dict[str, float] = field(default_factory=dict)
    expense_actual: dict[str, float] = field(default_factory=dict)
    extra_expense: dict[str, float] = field(default_factory=dict)  # 临时支出明细
    treasury_delta: float = 0.0  # 国库净变化（自然收支 + 临时）
    inner_purse_delta: float = 0.0  # 内帑净变化（临时支出扣减）
    net: float = 0.0  # 自然收支（不含临时）
    zonglu_dissatisfaction_delta: float = 0.0  # 宗禄改革新增的宗室不满


@dataclass
class TransferResult:
    """内帑/国库划拨结果。"""

    success: bool
    message: str
    treasury_delta: float = 0.0
    inner_purse_delta: float = 0.0
    trigger_event: str | None = None  # 触发的支线事件（如"朝野哗然"）
    public_opinion_delta: float = 0.0  # 民心/忠诚连锁
    loyalty_delta: float = 0.0


def settle(
    state_values: dict[str, float],
    params: FinanceParams,
    *,
    harvest: str = "平",
    wartime: bool = False,
    revolt_provinces: list[str] | None = None,
    extra_expenses: list[dict] | None = None,
) -> SettlementResult:
    """执行一回合财政结算。返回 SettlementResult（delta 由上层 apply_delta 落库）。

    extra_expenses: [{"name":"赈灾款","amount":100000,"source":"国库"|"内帑"}]
    """
    result = SettlementResult()

    # ---- 实际收入 ----
    harvest_factor = HARVEST_FACTOR.get(harvest, 1.0)
    revolt = revolt_provinces or []
    revolt_deduction = min(len(revolt) * REVOLT_DEDUCT_PER_PROVINCE, REVOLT_DEDUCT_CAP)

    for key, nominal in params.income_monthly.items():
        if key == "田赋":
            actual = nominal * harvest_factor * (1 - revolt_deduction)
        elif key == "商税":
            actual = nominal  # 商税稳定
        elif key == "辽饷加派":
            # 受 tax_rates.辽饷加派率 调制（玩家政令可调）
            actual = nominal
        else:
            actual = nominal
        result.income_actual[key] = actual

    # ---- 实际支出 ----
    cut = params.zonglu_reform.get("cut_ratio", 0.0)
    paper = params.zonglu_reform.get("paper_ratio", 0.0)
    for key, nominal in params.expense_monthly.items():
        if key == "宗室岁禄":
            actual = nominal * (1 - cut) * (1 - paper * PAPER_MONEY_DISCOUNT)
        elif key in ("辽东军饷", "边镇京营"):
            actual = nominal * (WARTIME_FACTOR if wartime else 1.0)
        else:
            actual = nominal
        result.expense_actual[key] = actual

    # ---- 宗禄改革新增宗室不满（delta，由上层落库到 宗室不满 数值）----
    # 削减与折钞都推高不满
    result.zonglu_dissatisfaction_delta = cut * 30 + paper * 20

    # ---- 自然收支 ----
    total_income = sum(result.income_actual.values())
    total_expense = sum(result.expense_actual.values())
    result.net = total_income - total_expense

    # ---- 临时支出 ----
    treasury_extra = 0.0
    inner_extra = 0.0
    for item in extra_expenses or []:
        name = item["name"]
        amount = float(item["amount"])
        source = item.get("source", "国库")
        result.extra_expense[name] = amount
        if source == "内帑":
            inner_extra += amount
        else:
            treasury_extra += amount

    result.treasury_delta = result.net - treasury_extra
    result.inner_purse_delta = -inner_extra
    return result


def transfer_inner_to_treasury(
    state_values: dict[str, float],
    amount: float,
) -> TransferResult:
    """内帑 → 太仓国库（允许）。皇帝动用私房钱补贴公帑。

    直接改 state_values（绕过 max_delta 裁剪，因属玩家明确政令，但仍受 min=0 clamp）。
    """
    amount = float(amount)
    inner = state_values.get("内帑", 0)
    if amount <= 0:
        return TransferResult(False, "划拨金额须为正数")
    if amount > inner:
        return TransferResult(False, f"内帑不足（现有 {inner}，需 {amount}）")
    clamped = min(amount, inner)
    state_values["内帑"] = inner - clamped
    state_values["国库"] = state_values.get("国库", 0) + clamped
    return TransferResult(
        True,
        f"动用内帑 {clamped} 充国库",
        treasury_delta=clamped,
        inner_purse_delta=-clamped,
    )


def transfer_treasury_to_inner(
    state_values: dict[str, float],
    amount: float,
    *,
    force: bool = False,
) -> TransferResult:
    """太仓国库 → 内帑（禁止）。公帑不可入私库。

    默认拒绝并提示；force=True 时强行执行，触发"朝野哗然"事件（民心-、官员忠诚-）。
    """
    amount = float(amount)
    if amount <= 0:
        return TransferResult(False, "划拨金额须为正数")
    if not force:
        return TransferResult(
            False,
            "公帑不可入私库。国库乃军国公帑，不可挪入皇帝私库。",
            trigger_event=None,
        )
    # 强行挪用 → 触发哗然事件
    treasury = state_values.get("国库", 0)
    clamped = min(amount, max(treasury, 0))
    state_values["国库"] = treasury - clamped
    state_values["内帑"] = state_values.get("内帑", 0) + clamped
    return TransferResult(
        True,
        f"强行挪用国库 {clamped} 入内帑，朝野哗然",
        treasury_delta=-clamped,
        inner_purse_delta=clamped,
        trigger_event="挪用公款朝野哗然",
        public_opinion_delta=-15,
        loyalty_delta=-10,
    )


def apply_finance_delta(params: FinanceParams, delta: dict) -> FinanceParams:
    """应用史官推演的财政参数变更（税率/收支项/宗禄改革），返回新 FinanceParams。

    delta 形如：
      {"tax_rates": {"辽饷加派率": 0.039}, "income_monthly": {"辽饷加派": 117000},
       "expense_monthly": {"边镇京营": 60000}, "zonglu_reform": {"cut_ratio": 0.3}}
    用于实现"下政令则每回合收支变化值可变动"。
    """
    new_income = dict(params.income_monthly)
    new_expense = dict(params.expense_monthly)
    new_tax = dict(params.tax_rates)
    new_zonglu = dict(params.zonglu_reform)
    if "income_monthly" in delta:
        new_income.update(delta["income_monthly"])
    if "expense_monthly" in delta:
        new_expense.update(delta["expense_monthly"])
    if "tax_rates" in delta:
        new_tax.update(delta["tax_rates"])
    if "zonglu_reform" in delta:
        new_zonglu.update(delta["zonglu_reform"])
    return FinanceParams(
        income_monthly=new_income,
        expense_monthly=new_expense,
        tax_rates=new_tax,
        zonglu_reform=new_zonglu,
    )
