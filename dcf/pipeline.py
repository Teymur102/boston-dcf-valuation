"""Glue: download/cache data, derive assumptions, run the valuation, collect everything the
workbook, chart and README need."""
from __future__ import annotations

import statistics
from dataclasses import asdict, dataclass, field, replace
from datetime import date

import numpy as np
import pandas as pd

from . import config, core, data
from . import financials as fin


@dataclass
class Peer:
    ticker: str
    name: str
    price: float
    price_date: str
    shares: float
    debt: float
    cash: float
    noncontrolling_interest: float
    ebitda: float
    eps: float
    fiscal_year: int
    bs_date: str

    @property
    def market_cap(self):
        return self.price * self.shares

    @property
    def ev(self):
        return self.market_cap + self.debt - self.cash + self.noncontrolling_interest

    @property
    def ev_ebitda(self):
        return self.ev / self.ebitda if self.ebitda > 0 else float("nan")

    @property
    def pe(self):
        return self.price / self.eps if self.eps > 0 else float("nan")


@dataclass
class Model:
    ticker: str
    company: str
    cik: str
    history: fin.History
    ratios: pd.DataFrame
    averages: dict
    year1_growth_raw: float
    bs: fin.BalanceSheet
    shares: float
    shares_date: date
    quote: dict
    rf: dict
    erp: dict
    ratings: list
    beta: float
    beta_table: pd.DataFrame
    coverage: float
    rating: str
    spread: float
    cost_of_equity: float
    pre_tax_cost_of_debt: float
    wacc: float
    weights: dict
    peers: list
    target_comp: Peer
    exit_multiple: float
    assumptions: core.Assumptions
    result: core.Result
    sens_waccs: list
    sens_growths: list
    sens_grid: np.ndarray
    sens_multiples: list
    sens_exit_grid: np.ndarray
    tornado: list
    week52: tuple
    breakeven: dict
    notes: list = field(default_factory=list)


def compute_ratios(t: pd.DataFrame) -> pd.DataFrame:
    """Historical ratios. Same definitions as the formulas in the workbook's Historicals sheet."""
    r = pd.DataFrame(index=t.columns, dtype=float)
    r["revenue_growth"] = t.loc["revenue"].pct_change()
    r["ebit_margin"] = t.loc["ebit"] / t.loc["revenue"]
    r["tax_rate"] = t.loc["income_tax"] / t.loc["pretax_income"]
    r["da_pct"] = t.loc["da"] / t.loc["revenue"]
    r["capex_pct"] = t.loc["capex"] / t.loc["revenue"]
    nwc = (t.loc["current_assets"] - t.loc["cash"] - t.loc["st_investments"]) - \
          (t.loc["current_liabilities"] - t.loc["debt_current"] - t.loc["st_borrowings"]
           - t.loc["lease_liab_current"])
    r["nwc"] = nwc
    r["nwc_pct"] = nwc / t.loc["revenue"]
    return r.T


def estimate_beta(ticker: str, refresh: bool, as_of: date) -> tuple[float, pd.DataFrame]:
    stock = data.monthly_prices(ticker, refresh)
    market = data.monthly_prices(config.MARKET_INDEX, refresh)
    df = pd.concat([stock.rename("stock"), market.rename("market")], axis=1).dropna()
    # drop the month we are in: its "close" is only month-to-date
    df = df[df.index < pd.Timestamp(as_of.year, as_of.month, 1)]
    df = df.iloc[-(config.BETA_MONTHS + 1):]
    rets = df.pct_change().dropna()
    beta = core.regression_beta(rets["stock"], rets["market"])
    table = df.copy()
    table["stock_ret"] = df["stock"].pct_change()
    table["market_ret"] = df["market"].pct_change()
    return beta, table


def load_peer(ticker: str, refresh: bool) -> Peer:
    cik, title = data.ticker_to_cik(ticker, refresh=False)
    facts = data.company_facts(cik, refresh)
    h = fin.build_history(facts, 2)
    last = h.table.columns[-1]
    t = h.table[last]
    bs = fin.latest_balance_sheet(facts)
    shares, _ = fin.shares_outstanding(facts)
    q = data.last_price(ticker, refresh)
    return Peer(ticker=ticker, name=title, price=q["price"], price_date=q["date"],
                shares=shares, debt=bs.debt, cash=bs.cash + bs.st_investments,
                noncontrolling_interest=bs.noncontrolling_interest,
                ebitda=float(t["ebit"] + t["da"]), eps=float(t["eps_diluted"]),
                fiscal_year=int(last), bs_date=str(bs.as_of))


def build(ticker: str, peers: list[str], refresh: bool = False,
          terminal_growth: float = config.TERMINAL_GROWTH) -> Model:
    ticker = ticker.upper()
    cik, _ = data.ticker_to_cik(ticker, refresh)
    facts = data.company_facts(cik, refresh)
    hist = fin.build_history(facts, config.HISTORY_YEARS)
    t = hist.table
    ratios = compute_ratios(t)
    n = config.AVERAGING_YEARS
    last_cols = list(t.columns[-n:])
    averages = {k: float(ratios.loc[k, last_cols].mean())
                for k in ["ebit_margin", "tax_rate", "da_pct", "capex_pct", "nwc_pct"]}
    rev = t.loc["revenue"]
    g_raw = float((rev.iloc[-1] / rev.iloc[-1 - n]) ** (1 / n) - 1)
    lo, hi = config.YEAR1_GROWTH_BOUNDS
    g1 = min(hi, max(lo, g_raw))

    bs = fin.latest_balance_sheet(facts)
    shares, shares_date = fin.shares_outstanding(facts)
    quote = data.last_price(ticker, refresh)
    valuation_date = date.fromisoformat(quote["date"])
    rf = data.risk_free_rate(refresh)
    erp = data.equity_risk_premium(refresh)
    ratings = data.rating_spreads(refresh)
    beta, beta_table = estimate_beta(ticker, refresh, valuation_date)

    last = t.columns[-1]
    ie_last = t.at["interest_expense", last]
    # no reported interest expense -> treat as debt-free (top of the rating table)
    coverage = float(t.at["ebit", last] / ie_last) if (pd.notna(ie_last) and ie_last > 0) \
        else 100000.0
    rating, spread = core.synthetic_spread(coverage, ratings)
    ke = core.capm_cost_of_equity(rf["rate"], beta, erp["erp"])
    kd = rf["rate"] + spread
    equity_mv = quote["price"] * shares
    w = core.wacc(equity_mv, bs.debt, ke, kd, averages["tax_rate"])
    weights = {"equity": equity_mv / (equity_mv + bs.debt), "debt": bs.debt / (equity_mv + bs.debt),
               "equity_value": equity_mv, "debt_value": bs.debt}

    peer_objs = [load_peer(p, refresh) for p in peers]
    target_comp = Peer(ticker=ticker, name=hist.company, price=quote["price"],
                       price_date=quote["date"], shares=shares, debt=bs.debt,
                       cash=bs.cash + bs.st_investments,
                       noncontrolling_interest=bs.noncontrolling_interest,
                       ebitda=float(t.at["ebit", last] + t.at["da", last]),
                       eps=float(t.at["eps_diluted", last]), fiscal_year=int(last),
                       bs_date=str(bs.as_of))
    multiples = [p.ev_ebitda for p in peer_objs if not np.isnan(p.ev_ebitda)]
    exit_multiple = float(statistics.median(multiples))

    a = core.Assumptions(
        base_revenue=float(rev.iloc[-1]), growth_year1=g1, terminal_growth=terminal_growth,
        ebit_margin=averages["ebit_margin"], tax_rate=averages["tax_rate"],
        da_pct=averages["da_pct"], capex_pct=averages["capex_pct"], nwc_pct=averages["nwc_pct"],
        wacc=w, exit_multiple=exit_multiple, debt=bs.debt, cash=bs.cash + bs.st_investments,
        noncontrolling_interest=bs.noncontrolling_interest, shares=shares,
        valuation_date=valuation_date, last_fiscal_year_end=hist.fiscal_year_ends[-1],
        years=config.PROJECTION_YEARS)
    result = core.run_dcf(a)

    sens_w = [w + s for s in config.SENS_WACC_STEPS]
    sens_g = [terminal_growth + s for s in config.SENS_GROWTH_STEPS]
    grid = core.sensitivity_grid(a, sens_w, sens_g)
    sens_m = [exit_multiple + s for s in (-2.0, -1.0, 0.0, 1.0, 2.0)]
    exit_grid = np.array([[core.equity_bridge(
        sum(f * fr * core.discount_factor(ww, p) for f, fr, p in
            zip(result.fcf, result.fractions, result.periods))
        + result.ebitda[-1] * m * core.discount_factor(ww, result.terminal_period),
        a.debt, a.cash, a.noncontrolling_interest, a.shares)[1] for m in sens_m] for ww in sens_w])

    shocks = {
        "WACC +/- 1.0 pt": ("wacc", 0.01),
        "Terminal growth +/- 0.5 pt": ("terminal_growth", 0.005),
        "EBIT margin +/- 1.0 pt": ("ebit_margin", 0.01),
        "Year-1 revenue growth +/- 2.0 pts": ("growth_year1", 0.02),
        "Capex % of revenue +/- 0.5 pt": ("capex_pct", 0.005),
        "Tax rate +/- 2.0 pts": ("tax_rate", 0.02),
    }
    torn = core.tornado(a, shocks)
    # beta and ERP act through WACC; report them too by translating to a WACC change
    for label, dk in [("Beta +/- 0.2", 0.2 * erp["erp"]), ("Equity risk premium +/- 0.5 pt", 0.005 * beta)]:
        dw = dk * weights["equity"]
        lo_p = core.run_dcf(replace(a, wacc=w - dw)).price_gordon
        hi_p = core.run_dcf(replace(a, wacc=w + dw)).price_gordon
        torn.append({"driver": label, "field": "wacc", "step": dw, "low_input_price": lo_p,
                     "high_input_price": hi_p, "swing": abs(hi_p - lo_p),
                     "base": result.price_gordon})
    torn.sort(key=lambda r: -r["swing"])

    price = quote["price"]
    breakeven = {
        "wacc": core.break_even(a, "wacc", price, terminal_growth + 0.001, 0.30),
        "ebit_margin": core.break_even(a, "ebit_margin", price, 0.0, 0.60),
        "terminal_growth": core.break_even(a, "terminal_growth", price, -0.05, w - 0.001),
        "growth_year1": core.break_even(a, "growth_year1", price, -0.20, 0.60),
    }

    daily = data.daily_prices_1y(ticker, refresh)
    week52 = (float(daily.min()), float(daily.max()))

    notes = list(hist.notes)
    if g1 != g_raw:
        notes.append(f"Historical CAGR {g_raw:.2%} was capped to {g1:.2%} for year-1 growth.")
    return Model(ticker, hist.company, cik, hist, ratios, averages, g_raw, bs, shares,
                 shares_date, quote, rf, erp, ratings, beta, beta_table, coverage, rating, spread,
                 ke, kd, w, weights, peer_objs, target_comp, exit_multiple, a, result, sens_w,
                 sens_g, grid, sens_m, exit_grid, torn, week52, breakeven, notes)


def comps_implied_prices(m: Model) -> dict:
    """Implied per-share value of the target from peer EV/EBITDA and P/E (min, median, max)."""
    t = m.target_comp
    evx = [p.ev_ebitda for p in m.peers if not np.isnan(p.ev_ebitda)]
    pes = [p.pe for p in m.peers if not np.isnan(p.pe)]

    def from_ev(mult):
        return (mult * t.ebitda - t.debt + t.cash - t.noncontrolling_interest) / t.shares

    return {
        "ev_ebitda": {"min": from_ev(min(evx)), "median": from_ev(statistics.median(evx)),
                      "max": from_ev(max(evx))},
        "pe": {"min": min(pes) * t.eps, "median": statistics.median(pes) * t.eps,
               "max": max(pes) * t.eps},
    }


def to_json(m: Model) -> dict:
    """Machine-readable results: the README and notes are generated from this."""
    r = m.result
    comps = comps_implied_prices(m)
    return {
        "ticker": m.ticker, "company": m.company, "cik": m.cik,
        "valuation_date": m.quote["date"], "price": m.quote["price"],
        "price_source": m.quote["source"],
        "implied_price_gordon": r.price_gordon, "implied_price_exit": r.price_exit,
        "upside_gordon": r.price_gordon / m.quote["price"] - 1,
        "upside_exit": r.price_exit / m.quote["price"] - 1,
        "wacc": m.wacc, "cost_of_equity": m.cost_of_equity, "beta": m.beta,
        "beta_observations": int(m.beta_table["stock_ret"].notna().sum()),
        "beta_first_month": str(m.beta_table.index[1].date()),
        "beta_last_month": str(m.beta_table.index[-1].date()),
        "risk_free": m.rf, "erp": m.erp, "coverage": m.coverage, "rating": m.rating,
        "spread": m.spread, "ratings_as_of": m.ratings[0]["as_of"],
        "pre_tax_cost_of_debt": m.pre_tax_cost_of_debt,
        "after_tax_cost_of_debt": m.pre_tax_cost_of_debt * (1 - m.assumptions.tax_rate),
        "weights": m.weights,
        "assumptions": {k: (str(v) if isinstance(v, date) else v)
                        for k, v in asdict(m.assumptions).items()},
        "year1_growth_raw": m.year1_growth_raw, "averages": m.averages,
        "averaging_years": [int(c) for c in m.history.table.columns[-config.AVERAGING_YEARS:]],
        "history": {int(c): {k: (None if pd.isna(v) else float(v))
                             for k, v in m.history.table[c].items()}
                    for c in m.history.table.columns},
        "ratios": {int(c): {k: (None if pd.isna(v) else float(v)) for k, v in m.ratios[c].items()}
                   for c in m.ratios.columns},
        "sources": m.history.sources,
        "balance_sheet": {"as_of": str(m.bs.as_of), "cash": m.bs.cash,
                          "st_investments": m.bs.st_investments, "debt": m.bs.debt,
                          "noncontrolling_interest": m.bs.noncontrolling_interest,
                          "components": m.bs.components},
        "shares": m.shares, "shares_date": str(m.shares_date),
        "projection": {
            "fiscal_year_ends": [str(d) for d in r.fiscal_year_ends], "growth": r.growth,
            "revenue": r.revenue, "ebit": r.ebit, "nopat": r.nopat, "da": r.da,
            "capex": r.capex, "delta_nwc": r.delta_nwc, "ebitda": r.ebitda, "fcf": r.fcf,
            "fractions": r.fractions, "periods": r.periods, "terminal_period": r.terminal_period,
            "discount_factors": r.discount_factors, "pv_fcf": r.pv_fcf},
        "valuation": {"sum_pv_fcf": r.sum_pv_fcf, "tv_gordon": r.tv_gordon, "tv_exit": r.tv_exit,
                      "pv_tv_gordon": r.pv_tv_gordon, "pv_tv_exit": r.pv_tv_exit,
                      "ev_gordon": r.ev_gordon, "ev_exit": r.ev_exit,
                      "equity_gordon": r.equity_gordon, "equity_exit": r.equity_exit,
                      "tv_share_of_ev_gordon": r.pv_tv_gordon / r.ev_gordon,
                      "implied_exit_multiple": r.implied_exit_multiple,
                      "implied_growth_from_exit": r.implied_growth_from_exit},
        "exit_multiple": m.exit_multiple,
        "sensitivity": {"waccs": m.sens_waccs, "growths": m.sens_growths,
                        "grid": [[None if np.isnan(x) else float(x) for x in row]
                                 for row in m.sens_grid],
                        "multiples": m.sens_multiples,
                        "exit_grid": [[float(x) for x in row] for row in m.sens_exit_grid]},
        "tornado": m.tornado,
        "peers": [{**asdict(p), "market_cap": p.market_cap, "ev": p.ev,
                   "ev_ebitda": p.ev_ebitda, "pe": p.pe} for p in m.peers],
        "target_multiples": {"ev_ebitda": m.target_comp.ev_ebitda, "pe": m.target_comp.pe,
                             "ebitda": m.target_comp.ebitda, "eps": m.target_comp.eps},
        "comps_implied": comps,
        "week52": {"low": m.week52[0], "high": m.week52[1]},
        "break_even_to_market_price": m.breakeven,
        "notes": m.notes,
    }
