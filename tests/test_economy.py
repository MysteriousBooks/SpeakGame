"""M1b: economy 财政系统 测试。"""

import pytest

from src.finance.economy import (
    FinanceParams,
    apply_finance_delta,
    settle,
    transfer_inner_to_treasury,
    transfer_treasury_to_inner,
)


def load_params():
    from src.llm.provider import load_config

    return FinanceParams.from_config(load_config("config.yaml"))


def state_with(treasury=1_000_000, inner=5_000_000):
    return {"国库": float(treasury), "内帑": float(inner)}


# ---------- 开局结算 ----------


def test_settle_initial_net_near_zero():
    params = load_params()
    res = settle(state_with(), params)
    income = sum(res.income_actual.values())
    expense = sum(res.expense_actual.values())
    # 开局：平年景、无战事、无民变 -> 收支持平
    assert income == pytest.approx(360_000)
    assert expense == pytest.approx(360_000)
    assert res.net == pytest.approx(0)
    assert res.treasury_delta == pytest.approx(0)
    assert res.inner_purse_delta == pytest.approx(0)


# ---------- 年景调制田赋 ----------


def test_harvest_disaster_reduces_land_tax():
    params = load_params()
    res = settle(state_with(), params, harvest="灾")
    # 田赋 220000 × 0.5 = 110000
    assert res.income_actual["田赋"] == pytest.approx(110_000)
    assert res.net < 0  # 灾年入不敷出


def test_harvest_bumper_increases_land_tax():
    params = load_params()
    res = settle(state_with(), params, harvest="丰收")
    assert res.income_actual["田赋"] == pytest.approx(220_000 * 1.2)


# ---------- 战事调制军饷 ----------


def test_wartime_increases_military_pay():
    params = load_params()
    res = settle(state_with(), params, wartime=True)
    assert res.expense_actual["辽东军饷"] == pytest.approx(150_000 * 1.3)
    assert res.expense_actual["边镇京营"] == pytest.approx(80_000 * 1.3)
    assert res.net < 0  # 战时支出↑


# ---------- 民变中断地方税收 ----------


def test_revolt_provinces_reduce_land_tax_capped():
    params = load_params()
    # 3 个民变省份 -> 扣减 0.75 封顶到 0.5
    res = settle(state_with(), params, revolt_provinces=["陕西", "山西", "河南"])
    assert res.income_actual["田赋"] == pytest.approx(220_000 * 0.5)


def test_revolt_single_province_partial_deduction():
    params = load_params()
    res = settle(state_with(), params, revolt_provinces=["陕西"])
    assert res.income_actual["田赋"] == pytest.approx(220_000 * 0.75)


# ---------- 宗禄改革 ----------


def test_zonglu_cut_reduces_expense_and_raises_dissatisfaction():
    params = load_params().replace(zonglu_reform={"cut_ratio": 0.3, "paper_ratio": 0.0})
    res = settle(state_with(), params)
    # 宗室岁禄 90000 × (1-0.3) = 63000
    assert res.expense_actual["宗室岁禄"] == pytest.approx(63_000)
    assert res.zonglu_dissatisfaction_delta == pytest.approx(0.3 * 30)  # 9


def test_zonglu_paper_money_reduces_expense():
    params = load_params().replace(zonglu_reform={"cut_ratio": 0.0, "paper_ratio": 1.0})
    res = settle(state_with(), params)
    # 宗室岁禄 90000 × (1-0.5) = 45000
    assert res.expense_actual["宗室岁禄"] == pytest.approx(45_000)
    assert res.zonglu_dissatisfaction_delta == pytest.approx(1.0 * 20)  # 20


def test_zonglu_combined_cut_and_paper():
    params = load_params().replace(zonglu_reform={"cut_ratio": 0.3, "paper_ratio": 1.0})
    res = settle(state_with(), params)
    # 90000 × (1-0.3) × (1-0.5) = 31500
    assert res.expense_actual["宗室岁禄"] == pytest.approx(31_500)
    assert res.zonglu_dissatisfaction_delta == pytest.approx(9 + 20)


# ---------- 临时支出 ----------


def test_extra_expense_from_treasury():
    params = load_params()
    res = settle(
        state_with(),
        params,
        extra_expenses=[{"name": "赈灾款", "amount": 100_000, "source": "国库"}],
    )
    assert res.extra_expense["赈灾款"] == 100_000
    assert res.treasury_delta == pytest.approx(-100_000)  # net=0 - 100000
    assert res.inner_purse_delta == 0


def test_extra_expense_from_inner_purse():
    params = load_params()
    res = settle(
        state_with(),
        params,
        extra_expenses=[{"name": "赏赐", "amount": 50_000, "source": "内帑"}],
    )
    assert res.treasury_delta == pytest.approx(0)  # net=0
    assert res.inner_purse_delta == pytest.approx(-50_000)


# ---------- 内帑→国库 单向划拨 ----------


def test_transfer_inner_to_treasury_success():
    s = state_with(treasury=1_000_000, inner=5_000_000)
    res = transfer_inner_to_treasury(s, 1_000_000)
    assert res.success
    assert s["内帑"] == 4_000_000
    assert s["国库"] == 2_000_000


def test_transfer_inner_to_treasury_insufficient():
    s = state_with(treasury=1_000_000, inner=500_000)
    res = transfer_inner_to_treasury(s, 1_000_000)
    assert not res.success
    assert "内帑不足" in res.message
    assert s["内帑"] == 500_000  # 未变动


def test_transfer_inner_to_treasury_non_positive_rejected():
    s = state_with()
    res = transfer_inner_to_treasury(s, -100)
    assert not res.success


# ---------- 国库→内帑 禁止 ----------


def test_transfer_treasury_to_inner_rejected_by_default():
    s = state_with(treasury=1_000_000, inner=5_000_000)
    res = transfer_treasury_to_inner(s, 500_000)
    assert not res.success
    assert "公帑不可入私库" in res.message
    assert s["国库"] == 1_000_000  # 未变动
    assert res.trigger_event is None


def test_transfer_treasury_to_inner_force_triggers_event():
    s = state_with(treasury=1_000_000, inner=5_000_000)
    res = transfer_treasury_to_inner(s, 500_000, force=True)
    assert res.success
    assert res.trigger_event == "挪用公款朝野哗然"
    assert s["国库"] == 500_000
    assert s["内帑"] == 5_500_000
    assert res.public_opinion_delta == -15
    assert res.loyalty_delta == -10


# ---------- 政令改变参数影响下回合结算 ----------


def test_apply_finance_delta_changes_income_next_turn():
    params = load_params()
    # 加征辽饷三成：辽饷加派 90000 -> 117000
    new_params = apply_finance_delta(
        params,
        {"income_monthly": {"辽饷加派": 117_000}, "tax_rates": {"辽饷加派率": 0.039}},
    )
    res1 = settle(state_with(), params)
    res2 = settle(state_with(), new_params)
    assert res2.income_actual["辽饷加派"] == pytest.approx(117_000)
    assert res1.income_actual["辽饷加派"] == pytest.approx(90_000)
    assert res2.net > res1.net  # 收入↑


def test_apply_finance_delta_cuts_military_expense():
    params = load_params()
    # 裁京营冗兵：边镇京营 80000 -> 60000
    new_params = apply_finance_delta(params, {"expense_monthly": {"边镇京营": 60_000}})
    res = settle(state_with(), new_params)
    assert res.expense_actual["边镇京营"] == pytest.approx(60_000)
    assert res.net == pytest.approx(20_000)  # 支出减 20000 -> 净 +20000


def test_finance_params_replace_immutable():
    params = load_params()
    new = params.replace(zonglu_reform={"cut_ratio": 0.5, "paper_ratio": 0.0})
    assert params.zonglu_reform["cut_ratio"] == 0.0  # 原对象不变
    assert new.zonglu_reform["cut_ratio"] == 0.5


def test_finance_params_from_config():
    params = load_params()
    assert params.income_monthly["田赋"] == 220_000
    assert params.tax_rates["田赋率"] == 0.05
    assert params.zonglu_reform == {"cut_ratio": 0.0, "paper_ratio": 0.0}
