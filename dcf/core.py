"""Valuation math. Pure functions, no I/O, so every piece is unit-tested.

The Excel workbook rebuilds exactly the same calculations with live formulas; tests check that
both give the same answer.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date

import numpy as np
from dateutil.relativedelta import relativedelta


# --- Cost of capital -------------------------------------------------------------------------
def regression_beta(stock_returns, market_returns) -> float:
    """OLS slope of stock returns on market returns: cov(r_s, r_m) / var(r_m)."""
    s = np.asarray(stock_returns, dtype=float)
    m = np.asarray(market_returns, dtype=float)
    if s.shape != m.shape or len(s) < 12:
        raise ValueError("need matching return series with at least 12 observations")
    return float(np.cov(s, m, ddof=1)[0, 1] / np.var(m, ddof=1))


def capm_cost_of_equity(risk_free: float, beta: float, erp: float) -> float:
    return risk_free + beta * erp


def synthetic_spread(coverage: float, table: list[dict]) -> tuple[str, float]:
    """Default spread for an interest-coverage ratio (Damodaran's rating table)."""
    rows = sorted(table, key=lambda r: r["low"])
    pick = rows[0]
    for r in rows:
        if coverage >= r["low"]:
            pick = r
    return pick["rating"], pick["spread"]


def wacc(equity_value: float, debt_value: float, cost_of_equity: float,
         pre_tax_cost_of_debt: float, tax_rate: float) -> float:
    total = equity_value + debt_value
    if total <= 0:
        raise ValueError("capital must be positive")
    return (equity_value / total) * cost_of_equity + \
        (debt_value / total) * pre_tax_cost_of_debt * (1 - tax_rate)


# --- Discounting and terminal value ----------------------------------------------------------
def discount_factor(rate: float, period: float) -> float:
    return 1.0 / (1.0 + rate) ** period


def gordon_terminal_value(final_fcf: float, rate: float, growth: float) -> float:
    """Value at the end of the forecast of cash flows growing at `growth` forever."""
    if rate <= growth:
        raise ValueError("discount rate must exceed terminal growth")
    return final_fcf * (1 + growth) / (rate - growth)


def exit_multiple_terminal_value(final_ebitda: float, multiple: float) -> float:
    return final_ebitda * multiple


def implied_exit_multiple(terminal_value: float, final_ebitda: float) -> float:
    return terminal_value / final_ebitda


def implied_perpetual_growth(terminal_value: float, final_fcf: float, rate: float) -> float:
    """Growth rate g that makes FCF*(1+g)/(r-g) equal the given terminal value."""
    return (terminal_value * rate - final_fcf) / (terminal_value + final_fcf)


def equity_bridge(enterprise_value: float, debt: float, cash: float,
                  noncontrolling_interest: float, shares: float) -> tuple[float, float]:
    """Enterprise value -> equity value -> value per share."""
    equity = enterprise_value - debt + cash - noncontrolling_interest
    return equity, equity / shares


def stub_and_periods(valuation_date: date, last_fiscal_year_end: date, years: int):
    """Year fractions and mid-year discount periods measured from the valuation date.

    Year 1 is only partly ahead of us: we count the fraction of its cash flow that is still to
    come, and discount it at the middle of that remaining stub. Later years are discounted at
    their mid-points. The terminal value is discounted from the end of the final year.
    """
    first_end = last_fiscal_year_end + relativedelta(months=12)
    stub = (first_end - valuation_date).days / 365.0
    stub = min(1.0, max(0.0, stub))
    fractions = [stub] + [1.0] * (years - 1)
    # year i>=2 ends at stub + (i-1) years, so its mid-point is stub + (i-1) - 0.5
    periods = [stub / 2] + [stub + (i - 1) - 0.5 for i in range(2, years + 1)]
    terminal_period = stub + (years - 1)
    ends = [last_fiscal_year_end + relativedelta(months=12 * i) for i in range(1, years + 1)]
    return fractions, periods, terminal_period, ends


# --- Full model ------------------------------------------------------------------------------
@dataclass(frozen=True)
class Assumptions:
    base_revenue: float           # last fiscal year revenue
    growth_year1: float
    terminal_growth: float
    ebit_margin: float
    tax_rate: float
    da_pct: float                 # D&A as % of revenue
    capex_pct: float              # capex as % of revenue
    nwc_pct: float                # net working capital as % of revenue
    wacc: float
    exit_multiple: float          # EV / EBITDA applied to final-year EBITDA
    debt: float
    cash: float
    noncontrolling_interest: float
    shares: float
    valuation_date: date
    last_fiscal_year_end: date
    years: int = 5


def growth_path(g1: float, g_terminal: float, years: int) -> list[float]:
    """Straight-line fade from year-1 growth toward terminal growth (reached the year after)."""
    return [g1 + (g_terminal - g1) * i / years for i in range(years)]


@dataclass
class Result:
    revenue: list
    growth: list
    ebit: list
    nopat: list
    da: list
    capex: list
    delta_nwc: list
    ebitda: list
    fcf: list
    fractions: list
    periods: list
    terminal_period: float
    discount_factors: list
    pv_fcf: list
    sum_pv_fcf: float
    tv_gordon: float
    tv_exit: float
    pv_tv_gordon: float
    pv_tv_exit: float
    ev_gordon: float
    ev_exit: float
    equity_gordon: float
    equity_exit: float
    price_gordon: float
    price_exit: float
    implied_exit_multiple: float
    implied_growth_from_exit: float
    fiscal_year_ends: list


def run_dcf(a: Assumptions) -> Result:
    growth = growth_path(a.growth_year1, a.terminal_growth, a.years)
    revenue, prev = [], a.base_revenue
    for g in growth:
        prev = prev * (1 + g)
        revenue.append(prev)
    ebit = [r * a.ebit_margin for r in revenue]
    nopat = [e * (1 - a.tax_rate) for e in ebit]
    da = [r * a.da_pct for r in revenue]
    capex = [r * a.capex_pct for r in revenue]
    prev_rev = [a.base_revenue] + revenue[:-1]
    delta_nwc = [a.nwc_pct * (r - p) for r, p in zip(revenue, prev_rev)]
    ebitda = [e + d for e, d in zip(ebit, da)]
    fcf = [n + d - c - w for n, d, c, w in zip(nopat, da, capex, delta_nwc)]

    fractions, periods, tp, ends = stub_and_periods(a.valuation_date, a.last_fiscal_year_end,
                                                    a.years)
    dfs = [discount_factor(a.wacc, p) for p in periods]
    pv = [f * fr * d for f, fr, d in zip(fcf, fractions, dfs)]
    sum_pv = sum(pv)

    tv_g = gordon_terminal_value(fcf[-1], a.wacc, a.terminal_growth)
    tv_x = exit_multiple_terminal_value(ebitda[-1], a.exit_multiple)
    df_tv = discount_factor(a.wacc, tp)
    ev_g, ev_x = sum_pv + tv_g * df_tv, sum_pv + tv_x * df_tv
    eq_g, px_g = equity_bridge(ev_g, a.debt, a.cash, a.noncontrolling_interest, a.shares)
    eq_x, px_x = equity_bridge(ev_x, a.debt, a.cash, a.noncontrolling_interest, a.shares)
    return Result(revenue, growth, ebit, nopat, da, capex, delta_nwc, ebitda, fcf, fractions,
                  periods, tp, dfs, pv, sum_pv, tv_g, tv_x, tv_g * df_tv, tv_x * df_tv, ev_g,
                  ev_x, eq_g, eq_x, px_g, px_x, implied_exit_multiple(tv_g, ebitda[-1]),
                  implied_perpetual_growth(tv_x, fcf[-1], a.wacc), ends)


def sensitivity_grid(a: Assumptions, waccs, growths) -> np.ndarray:
    """Per-share value (Gordon growth) for each WACC x terminal-growth pair.

    The projected cash flows are held fixed (as in the workbook); only the discount rate and the
    terminal growth rate change.
    """
    base = run_dcf(a)
    fractions, periods, tp = base.fractions, base.periods, base.terminal_period
    out = np.full((len(waccs), len(growths)), np.nan)
    for i, w in enumerate(waccs):
        pv = sum(f * fr * discount_factor(w, p) for f, fr, p in zip(base.fcf, fractions, periods))
        for j, g in enumerate(growths):
            if w <= g:
                continue
            ev = pv + gordon_terminal_value(base.fcf[-1], w, g) * discount_factor(w, tp)
            out[i, j] = equity_bridge(ev, a.debt, a.cash, a.noncontrolling_interest, a.shares)[1]
    return out


def tornado(a: Assumptions, shocks: dict[str, tuple[str, float]]) -> list[dict]:
    """Re-run the full model with one input moved down/up at a time.

    shocks: label -> (Assumptions field, step). Returns rows sorted by total swing.
    """
    base = run_dcf(a).price_gordon
    rows = []
    for label, (fld, step) in shocks.items():
        lo = run_dcf(replace(a, **{fld: getattr(a, fld) - step})).price_gordon
        hi = run_dcf(replace(a, **{fld: getattr(a, fld) + step})).price_gordon
        rows.append({"driver": label, "field": fld, "step": step, "low_input_price": lo,
                     "high_input_price": hi, "swing": abs(hi - lo), "base": base})
    return sorted(rows, key=lambda r: -r["swing"])


def break_even(a: Assumptions, fld: str, target_price: float, lo: float, hi: float,
               tol: float = 1e-10) -> float | None:
    """Value of one input (others fixed) at which the Gordon-growth value equals target_price.

    Bisection; returns None if the target is not bracketed by [lo, hi].
    """
    def f(x):
        return run_dcf(replace(a, **{fld: x})).price_gordon - target_price

    f_lo, f_hi = f(lo), f(hi)
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        f_mid = f(mid)
        if abs(f_mid) < tol:
            return mid
        if f_lo * f_mid <= 0:
            hi = mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2
