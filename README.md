# What is TJX worth? A DCF built from SEC filings

Is The TJX Companies, Inc. worth its $140.20 share price (2026-10-27)? A five-year unlevered DCF says **$105.54** (Gordon growth) to **$106.09** (peer exit multiple), about 24.7% below the market.

![License](https://img.shields.io/badge/License-MIT-yellow.svg) ![python](https://img.shields.io/badge/python-3.14-blue.svg) ![pandas](https://img.shields.io/badge/pandas-3.1.0-150458.svg) ![openpyxl](https://img.shields.io/badge/openpyxl-3.1.5-217346.svg) ![pycel](https://img.shields.io/badge/pycel-1.0b30-6a5acd.svg) ![yfinance](https://img.shields.io/badge/yfinance-1.7.0-6001d2.svg) ![tests](https://img.shields.io/badge/tests-32%20passed-brightgreen.svg)

<table>
<tr>
<td width="50%"><img src="figures/TJX_football_field.png" alt="Football field: valuation ranges vs share price"></td>
<td width="50%"><img src="figures/TJX_sensitivity.png" alt="WACC x terminal growth sensitivity"></td>
</tr>
</table>

## Results

From [`outputs/TJX_results.json`](outputs/TJX_results.json); the live-formula Excel model is [`outputs/TJX_dcf.xlsx`](outputs/TJX_dcf.xlsx).

| Metric | Value |
|---|---|
| Value per share: Gordon growth / exit multiple | $105.54 / $106.09 |
| vs share price $140.20 | -24.7% / -24.3% |
| WACC (beta 0.564) | 7.03% |
| WACC or EBIT margin needed to justify the price | 5.88% or 14.51% (model: 7.03%, 11.26%) |
| Terminal value share of EV | 83.0% |

## Proof

- **32 tests** (`pytest`): WACC/CAPM, beta regression, discounting and stub periods, both terminal values, equity bridge, XBRL parsing, and workbook-vs-Python checks.
- **Independent recalculation:** every run recomputes the Excel workbook with pycel; it matches Python to better than $0.000001 per share.
- **One command:** `make` runs the model and the tests in a few seconds from cached data.
- **Data:** [SEC EDGAR XBRL companyfacts](https://www.sec.gov/edgar/sec-api-documentation), [FRED DGS10](https://fred.stlouisfed.org/series/DGS10), [Damodaran ERP and ratings](https://pages.stern.nyu.edu/~adamodar/), Yahoo Finance via `yfinance`.
- **Deterministic:** all downloads are cached under `data/`, so reruns reproduce every number; `--refresh` pulls new data.

## Stack

Python 3.14 · pandas 3.1.0 · numpy 2.5.4 · openpyxl 3.1.5 · matplotlib 3.11.2 · requests 2.34.2 · python-dateutil 3.0.0 · yfinance 1.7.0 · pycel 1.0b30 · pytest 9.2.0

## Run

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m dcf run TJX --readme && .venv/bin/python -m pytest
```

## Structure

```
dcf/data.py, financials.py   downloads + cache; XBRL facts -> history and balance sheet
dcf/core.py, pipeline.py     valuation math; assumptions, beta, comps, sensitivities
dcf/excel.py, verify.py      live-formula workbook; independent pycel recalculation
dcf/figures.py, readme.py    charts; README and docs/DETAILS.md from results
tests/                       core math, XBRL parsing, workbook checks
outputs/                     TJX_dcf.xlsx, TJX_results.json
```

---

Full method, limitations and interview-level detail: [docs/DETAILS.md](docs/DETAILS.md) · MIT License
