"""XBRL extraction rules, tested on a small synthetic companyfacts document."""
from datetime import date

from dcf import financials as fin


def _fact(val, end, start=None, form="10-K", filed="2025-03-01", accn="a1"):
    f = {"val": val, "end": end, "form": form, "filed": filed, "accn": accn, "fp": "FY"}
    if start:
        f["start"] = start
    return f


FACTS = {
    "cik": 1,
    "entityName": "Toy Co",
    "facts": {
        "dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": [
            _fact(100, "2025-03-01", form="10-K", accn="k"),
            _fact(98, "2025-08-20", form="10-Q", accn="q", filed="2025-09-01")]}}},
        "us-gaap": {
            "Revenues": {"units": {"USD": [
                _fact(1000, "2024-01-31", "2023-02-01", filed="2024-03-01"),
                _fact(1010, "2024-01-31", "2023-02-01", filed="2025-03-01"),  # restated later
                _fact(1100, "2025-01-31", "2024-02-01"),
                _fact(300, "2024-10-31", "2024-08-01", form="10-Q"),           # quarter: ignored
            ]}},
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest":
                {"units": {"USD": [_fact(100, "2024-01-31", "2023-02-01"),
                                   _fact(120, "2025-01-31", "2024-02-01")]}},
            "InterestExpense": {"units": {"USD": [_fact(10, "2024-01-31", "2023-02-01"),
                                                  _fact(8, "2025-01-31", "2024-02-01")]}},
            "InvestmentIncomeInterest": {"units": {"USD": [_fact(2, "2025-01-31", "2024-02-01")]}},
            "CashAndCashEquivalentsAtCarryingValue": {"units": {"USD": [
                _fact(50, "2025-01-31"), _fact(40, "2025-08-02", form="10-Q", filed="2025-09-01")]}},
            "LongTermDebtNoncurrent": {"units": {"USD": [
                _fact(200, "2025-01-31"), _fact(190, "2025-08-02", form="10-Q", filed="2025-09-01")]}},
            "LongTermDebtCurrent": {"units": {"USD": [
                _fact(15, "2025-08-02", form="10-Q", filed="2025-09-01")]}},
        },
    },
}


def test_latest_filing_wins_and_quarters_ignored():
    s = fin.annual_flow(FACTS, "Revenues")
    assert s == {date(2024, 1, 31): 1010.0, date(2025, 1, 31): 1100.0}


def test_ebit_rebuilt_from_pretax_when_operating_income_missing():
    h = fin.build_history(FACTS, 2)
    assert list(h.table.columns) == [2024, 2025]
    assert h.table.at["ebit", 2024] == 110      # 100 + 10 - 0
    assert h.table.at["ebit", 2025] == 126      # 120 + 8 - 2
    assert h.notes


def test_latest_balance_sheet_uses_most_recent_quarter():
    bs = fin.latest_balance_sheet(FACTS)
    assert bs.as_of == date(2025, 8, 2)
    assert bs.cash == 40 and bs.debt == 205


def test_shares_from_latest_cover_page():
    assert fin.shares_outstanding(FACTS) == (98.0, date(2025, 8, 20))


def test_fiscal_label_for_early_january_year_end():
    assert fin._fiscal_label(date(2026, 1, 3)) == 2025
    assert fin._fiscal_label(date(2026, 1, 31)) == 2026
