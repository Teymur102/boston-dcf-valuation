"""Unit tests for the valuation math, checked against hand-computed numbers."""
from datetime import date

import numpy as np
import pytest

from dcf import core


# --- cost of capital -------------------------------------------------------------------------
def test_capm():
    assert core.capm_cost_of_equity(0.04, 1.2, 0.05) == pytest.approx(0.10)


def test_wacc_weights_and_tax_shield():
    # 80/20 equity/debt, Ke 10%, Kd 5% pre-tax, 25% tax -> 0.8*10% + 0.2*3.75% = 8.75%
    assert core.wacc(800, 200, 0.10, 0.05, 0.25) == pytest.approx(0.0875)


def test_wacc_all_equity_equals_cost_of_equity():
    assert core.wacc(1000, 0, 0.09, 0.06, 0.21) == pytest.approx(0.09)


def test_wacc_rejects_zero_capital():
    with pytest.raises(ValueError):
        core.wacc(0, 0, 0.1, 0.05, 0.2)


def test_regression_beta_recovers_known_slope():
    rng = np.random.default_rng(0)
    m = rng.normal(0.01, 0.04, 60)
    s = 0.002 + 1.3 * m  # no noise: slope must be exactly 1.3
    assert core.regression_beta(s, m) == pytest.approx(1.3)


def test_regression_beta_matches_excel_slope_definition():
    m = np.array([0.01, -0.02, 0.03, 0.00, 0.02, -0.01, 0.015, -0.005, 0.01, 0.02, -0.03, 0.04])
    s = np.array([0.02, -0.01, 0.02, 0.01, 0.03, -0.02, 0.01, 0.00, 0.02, 0.01, -0.02, 0.05])
    slope = np.polyfit(m, s, 1)[0]  # least-squares slope, same as Excel SLOPE()
    assert core.regression_beta(s, m) == pytest.approx(slope)


def test_synthetic_spread_lookup():
    table = [{"low": -1e5, "high": 0.2, "rating": "D", "spread": 0.19},
             {"low": 3.0, "high": 4.25, "rating": "A-", "spread": 0.0089},
             {"low": 8.5, "high": 1e5, "rating": "AAA", "spread": 0.004},
             {"low": 0.2, "high": 3.0, "rating": "B", "spread": 0.05}]
    assert core.synthetic_spread(90.9, table) == ("AAA", 0.004)
    assert core.synthetic_spread(3.5, table) == ("A-", 0.0089)
    assert core.synthetic_spread(8.5, table) == ("AAA", 0.004)  # boundary belongs to higher band
    assert core.synthetic_spread(0.1, table) == ("D", 0.19)


# --- discounting and terminal value ----------------------------------------------------------
def test_discount_factor():
    assert core.discount_factor(0.10, 1) == pytest.approx(1 / 1.1)
    assert core.discount_factor(0.10, 0) == 1.0
    assert core.discount_factor(0.08, 2.5) == pytest.approx(1.08 ** -2.5)


def test_gordon_terminal_value():
    # FCF 100 growing 3% at 8%: 103 / 0.05 = 2060
    assert core.gordon_terminal_value(100, 0.08, 0.03) == pytest.approx(2060)


def test_gordon_requires_rate_above_growth():
    with pytest.raises(ValueError):
        core.gordon_terminal_value(100, 0.03, 0.03)


def test_exit_multiple_terminal_value():
    assert core.exit_multiple_terminal_value(250, 12) == 3000


def test_implied_growth_inverts_gordon():
    tv = core.gordon_terminal_value(100, 0.08, 0.025)
    assert core.implied_perpetual_growth(tv, 100, 0.08) == pytest.approx(0.025)


def test_implied_exit_multiple():
    assert core.implied_exit_multiple(3000, 250) == 12


def test_equity_bridge():
    # EV 1,000 - debt 300 + cash 120 - NCI 20 = 800 equity; 40 shares -> $20
    eq, px = core.equity_bridge(1000, 300, 120, 20, 40)
    assert eq == 800 and px == 20


def test_equity_bridge_net_cash_adds_value():
    eq, _ = core.equity_bridge(1000, 0, 250, 0, 10)
    assert eq == 1250


# --- timing ----------------------------------------------------------------------------------
def test_stub_and_mid_year_periods():
    # valuation 2026-10-27, fiscal year ends 31 Jan: 96 days of FY2027 remain
    fr, per, tp, ends = core.stub_and_periods(date(2026, 10, 27), date(2026, 1, 31), 5)
    stub = 96 / 365
    assert fr == pytest.approx([stub, 1, 1, 1, 1])
    assert per == pytest.approx([stub / 2, stub + 0.5, stub + 1.5, stub + 2.5, stub + 3.5])
    assert tp == pytest.approx(stub + 4)
    assert ends[0] == date(2027, 1, 31) and ends[-1] == date(2031, 1, 31)


def test_stub_is_full_year_right_after_fiscal_year_end():
    fr, per, tp, _ = core.stub_and_periods(date(2026, 1, 31), date(2026, 1, 31), 3)
    assert fr == [1.0, 1.0, 1.0]
    assert per == pytest.approx([0.5, 1.5, 2.5])
    assert tp == pytest.approx(3.0)


def test_growth_path_fades_linearly_to_terminal():
    g = core.growth_path(0.10, 0.02, 4)
    assert g == pytest.approx([0.10, 0.08, 0.06, 0.04])


# --- full model ------------------------------------------------------------------------------
def _toy(**kw):
    base = dict(base_revenue=1000.0, growth_year1=0.05, terminal_growth=0.05, ebit_margin=0.20,
                tax_rate=0.25, da_pct=0.05, capex_pct=0.05, nwc_pct=0.0, wacc=0.10,
                exit_multiple=10.0, debt=100.0, cash=50.0, noncontrolling_interest=0.0,
                shares=10.0, valuation_date=date(2025, 12, 31),
                last_fiscal_year_end=date(2025, 12, 31), years=2)
    base.update(kw)
    return core.Assumptions(**base)


def test_run_dcf_matches_hand_calculation():
    a = _toy()
    r = core.run_dcf(a)
    # revenue 1050, 1102.5; FCF = EBIT*(1-t) = 0.15 x revenue (D&A = capex, no NWC)
    assert r.revenue == pytest.approx([1050, 1102.5])
    assert r.fcf == pytest.approx([157.5, 165.375])
    pv = 157.5 / 1.1 ** 0.5 + 165.375 / 1.1 ** 1.5
    tv = 165.375 * 1.05 / 0.05
    ev = pv + tv / 1.1 ** 2
    assert r.ev_gordon == pytest.approx(ev)
    assert r.price_gordon == pytest.approx((ev - 100 + 50) / 10)
    ebitda2 = 1102.5 * 0.25
    assert r.price_exit == pytest.approx((pv + ebitda2 * 10 / 1.1 ** 2 - 50) / 10)


def test_nwc_investment_reduces_fcf():
    r0 = core.run_dcf(_toy())
    r1 = core.run_dcf(_toy(nwc_pct=0.10))
    assert r1.delta_nwc[0] == pytest.approx(0.10 * 50)
    assert r1.fcf[0] == pytest.approx(r0.fcf[0] - 5)


def test_sensitivity_centre_equals_base_case():
    a = _toy(years=5, terminal_growth=0.025)
    grid = core.sensitivity_grid(a, [0.09, 0.10, 0.11], [0.02, 0.025, 0.03])
    assert grid[1, 1] == pytest.approx(core.run_dcf(a).price_gordon)
    assert grid[0, 2] > grid[1, 1] > grid[2, 0]  # lower WACC / higher growth -> higher value


def test_tornado_sorted_and_symmetric_inputs():
    a = _toy(years=5, terminal_growth=0.025)
    rows = core.tornado(a, {"wacc": ("wacc", 0.01), "margin": ("ebit_margin", 0.01)})
    assert rows[0]["swing"] >= rows[1]["swing"]
    w = next(r for r in rows if r["field"] == "wacc")
    assert w["low_input_price"] > w["base"] > w["high_input_price"]


def test_break_even_recovers_input():
    a = _toy(years=5, terminal_growth=0.025)
    target = core.run_dcf(a).price_gordon
    shifted = core.replace(a, wacc=0.12)
    assert core.break_even(shifted, "wacc", target, 0.05, 0.2) == pytest.approx(0.10, abs=1e-8)
    assert core.break_even(a, "wacc", 1e9, 0.05, 0.2) is None  # not bracketed
