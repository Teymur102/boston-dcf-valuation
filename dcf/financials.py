"""Turn SEC XBRL company facts into a clean annual history and a latest balance sheet.

Rules:
* Annual (flow) items come from 10-K filings only, for periods of roughly one year.
* When a number was restated in a later 10-K, the most recently filed value wins.
* Every derived line records which XBRL tag(s) it came from, so the workbook can show it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd

# Ordered fallbacks: the first tag that has data for a given year is used.
REVENUE_TAGS = ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
                "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet",
                "SalesRevenueGoodsNet"]
FLOW_TAGS = {
    "cogs": ["CostOfGoodsAndServicesSold", "CostOfRevenue", "CostOfGoodsSold"],
    "sga": ["SellingGeneralAndAdministrativeExpense"],
    "operating_income": ["OperatingIncomeLoss"],
    "pretax_income": ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
                      "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"],
    "income_tax": ["IncomeTaxExpenseBenefit"],
    "interest_expense": ["InterestExpense", "InterestExpenseNonoperating", "InterestExpenseDebt"],
    "interest_income": ["InvestmentIncomeInterest", "InvestmentIncomeInterestAndDividend"],
    "da": ["DepreciationDepletionAndAmortization", "DepreciationAmortizationAndAccretionNet",
           "DepreciationAndAmortization"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
    "net_income": ["NetIncomeLoss"],
    "eps_diluted": ["EarningsPerShareDiluted"],
    "diluted_shares": ["WeightedAverageNumberOfDilutedSharesOutstanding"],
    "cfo": ["NetCashProvidedByUsedInOperatingActivities"],
}
INSTANT_TAGS = {
    "current_assets": ["AssetsCurrent"],
    "current_liabilities": ["LiabilitiesCurrent"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue",
             "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"],
    "st_investments": ["ShortTermInvestments", "MarketableSecuritiesCurrent",
                       "AvailableForSaleSecuritiesDebtSecuritiesCurrent"],
    "debt_current": ["LongTermDebtCurrent", "DebtCurrent",
                     "LongTermDebtAndCapitalLeaseObligationsCurrent"],
    "st_borrowings": ["ShortTermBorrowings", "CommercialPaper"],
    "debt_noncurrent": ["LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations"],
    "lease_liab_current": ["OperatingLeaseLiabilityCurrent"],
    "lease_liab_total": ["OperatingLeaseLiability"],
    "noncontrolling_interest": ["MinorityInterest"],
}


def _fiscal_label(end: date) -> int:
    """Fiscal year label: the calendar year the period ends in (52/53-week years that end in
    the first week of January belong to the prior year)."""
    return end.year - 1 if (end.month == 1 and end.day <= 7) else end.year


def _facts_for(facts: dict, tag: str, taxonomy: str = "us-gaap") -> list[dict]:
    node = facts.get("facts", {}).get(taxonomy, {}).get(tag)
    if not node:
        return []
    out = []
    for unit, rows in node["units"].items():
        for r in rows:
            out.append({**r, "unit": unit})
    return out


def annual_flow(facts: dict, tag: str) -> dict[date, float]:
    """{fiscal year end: value} for a duration tag, from 10-K filings, latest filing wins."""
    best: dict[date, tuple[str, float]] = {}
    for r in _facts_for(facts, tag):
        if r.get("form") not in ("10-K", "10-K/A") or "start" not in r:
            continue
        start, end = date.fromisoformat(r["start"]), date.fromisoformat(r["end"])
        if not 340 <= (end - start).days <= 380:
            continue
        if end not in best or r["filed"] > best[end][0]:
            best[end] = (r["filed"], float(r["val"]))
    return {k: v[1] for k, v in best.items()}


def instants(facts: dict, tag: str, forms=("10-K", "10-K/A", "10-Q", "10-Q/A"),
             taxonomy: str = "us-gaap") -> dict[date, float]:
    """{balance sheet date: value} for an instant tag, latest filing wins."""
    best: dict[date, tuple[str, float]] = {}
    for r in _facts_for(facts, tag, taxonomy):
        if r.get("form") not in forms or "start" in r:
            continue
        end = date.fromisoformat(r["end"])
        if end not in best or r["filed"] > best[end][0]:
            best[end] = (r["filed"], float(r["val"]))
    return {k: v[1] for k, v in best.items()}


def _first_available(series_by_tag: list[tuple[str, dict]], when: date):
    for tag, s in series_by_tag:
        if when in s:
            return s[when], tag
    return None, None


@dataclass
class History:
    company: str
    cik: str
    fiscal_year_ends: list[date]
    table: pd.DataFrame                     # rows = line items, columns = fiscal year labels
    sources: dict[str, str] = field(default_factory=dict)  # line item -> tag(s) used
    notes: list[str] = field(default_factory=list)


def build_history(facts: dict, years: int) -> History:
    rev_series = [(t, annual_flow(facts, t)) for t in REVENUE_TAGS]
    all_ends = sorted({d for _, s in rev_series for d in s})
    if not all_ends:
        raise RuntimeError("No annual revenue found in 10-K filings")
    ends = all_ends[-years:]

    data: dict[str, dict[int, float]] = {}
    sources: dict[str, set] = {}

    def put(item, end, value, tag):
        data.setdefault(item, {})[_fiscal_label(end)] = value
        if tag:
            sources.setdefault(item, set()).add(tag)

    for end in ends:
        v, t = _first_available(rev_series, end)
        put("revenue", end, v, t)

    flow_cache = {k: [(t, annual_flow(facts, t)) for t in tags] for k, tags in FLOW_TAGS.items()}
    for item, series in flow_cache.items():
        for end in ends:
            v, t = _first_available(series, end)
            put(item, end, v, t)

    inst_cache = {k: [(t, instants(facts, t, forms=("10-K", "10-K/A"))) for t in tags]
                  for k, tags in INSTANT_TAGS.items()}
    for item, series in inst_cache.items():
        for end in ends:
            v, t = _first_available(series, end)
            put(item, end, v, t)

    df = pd.DataFrame(data).T
    df = df[sorted(df.columns)]
    notes = []

    # D&A fallback: some filers tag depreciation and intangible amortization separately.
    dep = annual_flow(facts, "Depreciation")
    amort = annual_flow(facts, "AmortizationOfIntangibleAssets")
    for end in ends:
        col = _fiscal_label(end)
        if pd.isna(df.at["da", col]) and end in dep:
            df.at["da", col] = dep[end] + amort.get(end, 0.0)
            sources.setdefault("da", set()).add("Depreciation + AmortizationOfIntangibleAssets")

    # EBIT: reported operating income if the company tags it, otherwise rebuilt from pre-tax
    # income by adding back interest expense and removing interest income.
    ebit, ebit_src = {}, {}
    for col in df.columns:
        op = df.at["operating_income", col] if "operating_income" in df.index else None
        if pd.notna(op):
            ebit[col], ebit_src[col] = op, "OperatingIncomeLoss"
        else:
            pre = df.at["pretax_income", col]
            ie = df.at["interest_expense", col] if pd.notna(df.at["interest_expense", col]) else 0.0
            ii = df.at["interest_income", col] if ("interest_income" in df.index and
                                                   pd.notna(df.at["interest_income", col])) else 0.0
            ebit[col], ebit_src[col] = pre + ie - ii, "pre-tax income + interest expense - interest income"
    df.loc["ebit"] = pd.Series(ebit)
    srcs = sorted(set(ebit_src.values()))
    sources["ebit"] = set(srcs)
    if any("pre-tax" in s for s in srcs):
        notes.append("The company does not tag an operating-income line for some years; EBIT is "
                     "rebuilt as pre-tax income + interest expense - interest income.")

    for item in ["st_investments", "debt_current", "st_borrowings", "lease_liab_current",
                 "noncontrolling_interest", "interest_income", "cogs", "sga", "operating_income"]:
        if item in df.index:
            df.loc[item] = df.loc[item].fillna(0.0)
    return History(company=facts.get("entityName", ""), cik=f"{int(facts['cik']):010d}",
                   fiscal_year_ends=ends, table=df,
                   sources={k: ", ".join(sorted(v)) for k, v in sources.items()}, notes=notes)


@dataclass
class BalanceSheet:
    as_of: date
    cash: float
    st_investments: float
    debt: float
    noncontrolling_interest: float
    components: dict


def latest_balance_sheet(facts: dict) -> BalanceSheet:
    """Cash and debt from the most recent 10-K or 10-Q balance sheet."""
    cash_series = [s for s in (instants(facts, t) for t in INSTANT_TAGS["cash"]) if s]
    as_of = max(max(s) for s in cash_series)  # most recent balance sheet date

    def get(item):
        v, t = _first_available([(t, instants(facts, t)) for t in INSTANT_TAGS[item]], as_of)
        return (v or 0.0), t

    comps = {}
    for item in ["cash", "st_investments", "debt_current", "st_borrowings", "debt_noncurrent",
                 "noncontrolling_interest"]:
        v, t = get(item)
        comps[item] = {"value": v, "tag": t}
    debt = comps["debt_current"]["value"] + comps["st_borrowings"]["value"] + \
        comps["debt_noncurrent"]["value"]
    return BalanceSheet(as_of=as_of, cash=comps["cash"]["value"],
                        st_investments=comps["st_investments"]["value"], debt=debt,
                        noncontrolling_interest=comps["noncontrolling_interest"]["value"],
                        components=comps)


def shares_outstanding(facts: dict) -> tuple[float, date]:
    """Latest cover-page share count (dei:EntityCommonStockSharesOutstanding), summed over classes."""
    rows = [r for r in _facts_for(facts, "EntityCommonStockSharesOutstanding", "dei")]
    if not rows:
        raise RuntimeError("No dei:EntityCommonStockSharesOutstanding")
    latest_end = max(r["end"] for r in rows)
    latest = [r for r in rows if r["end"] == latest_end]
    latest_accn = max(latest, key=lambda r: r["filed"])["accn"]
    total = sum(float(r["val"]) for r in latest if r["accn"] == latest_accn)
    return total, date.fromisoformat(latest_end)
