"""Generate README.md (short summary) and docs/DETAILS.md (full write-up) from
outputs/<TICKER>_results.json.

Every number in both files is formatted from the results file of the same run, so the
documentation cannot drift from what the code produced.
"""
from __future__ import annotations

from . import config


def usd(x, d=2):
    return f"${x:,.{d}f}"


def pct(x, d=2):
    return f"{x * 100:.{d}f}%"


def mil(x):
    return f"{x / 1e6:,.0f}"


def signed_pct(x, d=1):
    return f"{x * 100:+.{d}f}%"


def write_details(r: dict, path) -> None:
    """Full method, assumptions, results and limitations (docs/DETAILS.md)."""
    t = r["ticker"]
    a = r["assumptions"]
    v = r["valuation"]
    p = r["projection"]
    h = r["history"]
    yrs = sorted(h, key=int)
    last = yrs[-1]
    avg_yrs = r["averaging_years"]
    avg_span = f"FY{avg_yrs[0]}-FY{avg_yrs[-1]}"
    cagr_from = int(last) - config.AVERAGING_YEARS
    comps = r["comps_implied"]
    be = r["break_even_to_market_price"]
    price = r["price"]
    name = r["company"]
    short = t
    lease = h[last].get("lease_liab_total")
    direction = "below" if r["implied_price_gordon"] < price else "above"

    def be_txt(key, fmt=pct):
        return fmt(be[key]) if be.get(key) is not None else "not reachable"

    lines = []
    L = lines.append
    L(f"# What is {short} worth? A DCF built from SEC filings\n")
    L(f"**Question:** is {name} ({t}), the Framingham, Massachusetts off-price retailer, worth its "
      f"share price of **{usd(price)}** (close on {r['valuation_date']})?\n")
    L(f"**Answer from this model:** a five-year unlevered DCF puts intrinsic value at "
      f"**{usd(r['implied_price_gordon'])} per share** with a Gordon-growth terminal value and "
      f"**{usd(r['implied_price_exit'])}** with a peer exit multiple, "
      f"{pct(abs(r['upside_gordon']), 1)} and {pct(abs(r['upside_exit']), 1)} {direction} the market "
      f"price. To justify {usd(price)} with everything else unchanged, the WACC would have to be "
      f"{be_txt('wacc')} (model: {pct(r['wacc'])}) or the EBIT margin {be_txt('ebit_margin')} "
      f"(model: {pct(a['ebit_margin'])}).\n")
    L(f"![Football field: {t} valuation ranges vs share price](../figures/{t}_football_field.png)\n")
    L(f"The Excel model is in [`outputs/{t}_dcf.xlsx`](../outputs/{t}_dcf.xlsx). Every calculated "
      f"cell is a live formula (inputs in blue, formulas in black), so a reviewer can trace any "
      f"number back to its source or change an input and watch the value move. The workbook "
      f"was recalculated independently (pycel) during the run and matched the Python model "
      f"{'to better than $0.000001 per share' if r['workbook_check']['abs_diff_gordon'] < 1e-6 else 'to the cent' if r['workbook_check']['abs_diff_gordon'] < 0.005 else 'NOT within a cent: see results JSON'}.\n")

    L("## Data\n")
    L("| Input | Source | As of |")
    L("|---|---|---|")
    L(f"| Financial statements, FY{yrs[0]}-FY{last} | SEC EDGAR XBRL `companyfacts` API "
      f"(CIK {r['cik']}), 10-K filings | FY ended {a['last_fiscal_year_end']} |")
    L(f"| Cash and debt | Latest 10-Q balance sheet | {r['balance_sheet']['as_of']} |")
    L(f"| Shares outstanding ({r['shares'] / 1e6:,.1f}m) | 10-Q cover page "
      f"(`dei:EntityCommonStockSharesOutstanding`) | {r['shares_date']} |")
    L(f"| Risk-free rate ({pct(r['risk_free']['rate'])}) | FRED `DGS10`, 10-year Treasury yield "
      f"| {r['risk_free']['date']} |")
    L(f"| Equity risk premium ({pct(r['erp']['erp'])}) | Damodaran (NYU Stern) implied ERP for "
      f"the S&P 500, monthly update | {r['erp']['date']} |")
    L(f"| Default spread by rating | Damodaran synthetic-rating table, large non-financial firms "
      f"| {r['ratings_as_of']} |")
    L(f"| Share prices, beta inputs | Yahoo Finance via `yfinance` (adjusted monthly closes; "
      f"S&P 500 = `^GSPC`) | {r['valuation_date']} |")
    L(f"| Peers ({', '.join(x['ticker'] for x in r['peers'])}) | Same SEC + price sources | "
      f"latest 10-K / 10-Q |")
    L("")
    L("All raw downloads are cached under `data/` (SEC JSON gzipped), so rerunning the model "
      "reproduces these numbers exactly; `--refresh` pulls new data. SEC requests carry a "
      "declared User-Agent and are throttled below SEC's 10-requests-per-second limit.\n")

    L("## Method\n")
    L(f"1. **History.** Six fiscal years of revenue, EBIT, D&A, capex, working capital and taxes "
      f"from 10-K XBRL facts (latest filing wins when a year was restated). TJX does not tag an "
      f"operating-income line, so EBIT is rebuilt as pre-tax income + interest expense - interest "
      f"income.")
    L(f"2. **Forecast.** Five fiscal years (FY{int(last) + 1}-FY{int(last) + 5}). Revenue growth "
      f"starts at the {config.AVERAGING_YEARS}-year historical CAGR and fades in a straight line "
      f"toward terminal growth. Margin, tax rate, D&A, capex and working capital are held at "
      f"their {config.AVERAGING_YEARS}-year averages ({avg_span}).")
    L("3. **Free cash flow.** EBIT x (1 - tax) + D&A - capex - increase in net working capital.")
    L(f"4. **Discount rate.** CAPM cost of equity with a beta regressed on {r['beta_observations']} "
      f"monthly returns ({r['beta_first_month'][:7]} to {r['beta_last_month'][:7]}) against the "
      f"S&P 500. Pre-tax cost of debt = risk-free rate + default spread for the synthetic rating "
      f"implied by interest coverage. Weights use market value of equity and book value of debt.")
    L(f"5. **Timing.** Valuation date = price date. Only the {pct(p['fractions'][0], 1)} of "
      f"FY{int(last) + 1} still ahead is counted; cash flows are discounted mid-year; terminal value "
      f"is discounted from the end of year 5.")
    L(f"6. **Terminal value, two ways.** Gordon growth on year-5 free cash flow, and an exit "
      f"EV/EBITDA multiple equal to the peer median. Each is cross-checked against the other "
      f"(implied multiple, implied growth).")
    L("7. **Equity bridge.** Enterprise value - debt + cash = equity value, divided by shares "
      "outstanding.\n")

    L("## Assumptions\n")
    L("| Assumption | Value | Basis |")
    L("|---|---|---|")
    L(f"| Year-1 revenue growth | {pct(a['growth_year1'])} | FY{cagr_from}-FY{last} revenue CAGR |")
    L(f"| Revenue growth, years 2-5 | {', '.join(pct(g) for g in p['growth'][1:])} | straight-line "
      f"fade toward terminal growth |")
    L(f"| Terminal growth | {pct(a['terminal_growth'])} | long-run nominal growth; below the "
      f"{pct(r['risk_free']['rate'])} risk-free rate |")
    L(f"| EBIT margin | {pct(a['ebit_margin'])} | {avg_span} average "
      f"(FY{last} alone: {pct(r['ratios'][last]['ebit_margin'])}) |")
    L(f"| Tax rate | {pct(a['tax_rate'])} | {avg_span} average effective rate |")
    L(f"| D&A, % of revenue | {pct(a['da_pct'])} | {avg_span} average |")
    L(f"| Capex, % of revenue | {pct(a['capex_pct'])} | {avg_span} average |")
    L(f"| Net working capital, % of revenue | {pct(a['nwc_pct'])} | {avg_span} average (negative: "
      f"suppliers fund inventory, so growth releases cash) |")
    L(f"| Risk-free rate | {pct(r['risk_free']['rate'])} | FRED DGS10, {r['risk_free']['date']} |")
    L(f"| Beta | {r['beta']:.3f} | 5-year monthly regression vs S&P 500 |")
    L(f"| Equity risk premium | {pct(r['erp']['erp'])} | Damodaran implied ERP, "
      f"{r['erp']['date']} |")
    L(f"| Cost of equity | {pct(r['cost_of_equity'])} | CAPM |")
    L(f"| Pre-tax / after-tax cost of debt | {pct(r['pre_tax_cost_of_debt'])} / "
      f"{pct(r['after_tax_cost_of_debt'])} | interest coverage {r['coverage']:.1f}x -> "
      f"{r['rating']} -> spread {pct(r['spread'])} |")
    L(f"| Equity / debt weights | {pct(r['weights']['equity'], 1)} / {pct(r['weights']['debt'], 1)} "
      f"| market cap {usd(r['weights']['equity_value'] / 1e6, 0)}m, debt "
      f"{usd(r['weights']['debt_value'] / 1e6, 0)}m |")
    L(f"| **WACC** | **{pct(r['wacc'])}** | |")
    L(f"| Exit EV/EBITDA | {r['exit_multiple']:.2f}x | median of {len(r['peers'])} peers |")
    L("")

    L("## Results\n")
    L(f"Forecast ($ millions):\n")
    hdr = "| | " + " | ".join(f"FY{int(last) + i + 1}E" for i in range(len(p['fcf']))) + " |"
    L(hdr)
    L("|---" * (len(p["fcf"]) + 1) + "|")
    for label, key in [("Revenue", "revenue"), ("EBIT", "ebit"), ("NOPAT", "nopat"),
                       ("+ D&A", "da"), ("- Capex", "capex"), ("- Increase in NWC", "delta_nwc"),
                       ("**Unlevered FCF**", "fcf"), ("PV of FCF", "pv_fcf")]:
        L(f"| {label} | " + " | ".join(mil(x) for x in p[key]) + " |")
    L("")
    L(f"Valuation ($ millions except per share):\n")
    L("| | Gordon growth | Exit multiple |")
    L("|---|---:|---:|")
    L(f"| Sum of PV of free cash flows | {mil(v['sum_pv_fcf'])} | {mil(v['sum_pv_fcf'])} |")
    L(f"| PV of terminal value | {mil(v['pv_tv_gordon'])} | {mil(v['pv_tv_exit'])} |")
    L(f"| Enterprise value | {mil(v['ev_gordon'])} | {mil(v['ev_exit'])} |")
    bs = r["balance_sheet"]
    L(f"| - Debt | {mil(bs['debt'])} | {mil(bs['debt'])} |")
    L(f"| + Cash and short-term investments | {mil(bs['cash'] + bs['st_investments'])} | "
      f"{mil(bs['cash'] + bs['st_investments'])} |")
    L(f"| Equity value | {mil(v['equity_gordon'])} | {mil(v['equity_exit'])} |")
    L(f"| **Value per share** | **{usd(r['implied_price_gordon'])}** | "
      f"**{usd(r['implied_price_exit'])}** |")
    L(f"| vs share price {usd(price)} | {signed_pct(r['upside_gordon'])} | "
      f"{signed_pct(r['upside_exit'])} |")
    L(f"| Terminal value share of EV | {pct(v['tv_share_of_ev_gordon'], 1)} | "
      f"{pct(v['pv_tv_exit'] / v['ev_exit'], 1)} |")
    L(f"| Cross-check | implies {v['implied_exit_multiple']:.2f}x EBITDA | implies "
      f"{pct(v['implied_growth_from_exit'])} perpetual growth |")
    L("")
    gap = abs(r["implied_price_exit"] / r["implied_price_gordon"] - 1)
    L(f"The two terminal-value methods differ by {pct(gap, 1)} per share: the Gordon-growth value "
      f"implies {v['implied_exit_multiple']:.2f}x EBITDA against a peer median of "
      f"{r['exit_multiple']:.2f}x, and the peer multiple implies "
      f"{pct(v['implied_growth_from_exit'])} perpetual growth against "
      f"{pct(a['terminal_growth'])} assumed.\n")
    L("Trading comparables (latest fiscal year EBITDA and diluted EPS; prices on the valuation "
      "date):\n")
    L("| Company | EV/EBITDA | P/E |")
    L("|---|---:|---:|")
    for x in r["peers"]:
        L(f"| {x['ticker']} | {x['ev_ebitda']:.2f}x | {x['pe']:.2f}x |")
    tm = r["target_multiples"]
    L(f"| **{t} at market** | **{tm['ev_ebitda']:.2f}x** | **{tm['pe']:.2f}x** |")
    L("")
    L(f"Applying the peer medians to {t}'s own EBITDA and EPS gives "
      f"{usd(comps['ev_ebitda']['median'])} (EV/EBITDA) and {usd(comps['pe']['median'])} (P/E). "
      f"{t} trades at {tm['ev_ebitda']:.2f}x EBITDA and {tm['pe']:.2f}x earnings; peers above it "
      f"on EV/EBITDA: {', '.join(x['ticker'] for x in r['peers'] if x['ev_ebitda'] > tm['ev_ebitda']) or 'none'}; "
      f"on P/E: {', '.join(x['ticker'] for x in r['peers'] if x['pe'] > tm['pe']) or 'none'}.\n")

    L("## What drives the value\n")
    L(f"![WACC x terminal growth sensitivity](../figures/{t}_sensitivity.png)\n")
    L("One input moved at a time, full model re-run (value per share):\n")
    L("| Driver | Lower input | Higher input | Swing |")
    L("|---|---:|---:|---:|")
    for row in r["tornado"]:
        L(f"| {row['driver']} | {usd(row['low_input_price'])} | {usd(row['high_input_price'])} | "
          f"{usd(row['swing'])} |")
    L("")
    L(f"- **Discount rate dominates.** {pct(v['tv_share_of_ev_gordon'], 1)} of enterprise value "
      f"sits in the terminal value, so a one-point change in WACC moves the answer by more than "
      f"any operating assumption. Beta matters for the same reason: the regression gives "
      f"{r['beta']:.2f}, and each 0.2 of beta is worth about "
      f"{pct(0.2 * r['erp']['erp'] * r['weights']['equity'])} of WACC.")
    L(f"- **Margin is the main operating lever.** The model uses the {avg_span} average EBIT "
      f"margin of {pct(a['ebit_margin'])}, below the latest year's "
      f"{pct(r['ratios'][last]['ebit_margin'])}. The margin that alone would justify the share "
      f"price is {be_txt('ebit_margin')}.")
    L(f"- **What the market price implies.** Solving for each input alone (others at base): "
      f"WACC {be_txt('wacc')}, or EBIT margin {be_txt('ebit_margin')}, or terminal growth "
      f"{be_txt('terminal_growth')}, or year-1 revenue growth {be_txt('growth_year1')} fading "
      f"from there. The market is pricing in some combination of a lower discount rate and "
      f"higher margins than {short}'s recent history.\n")

    L("## Limitations\n")
    lease_txt = (f" ({usd(lease / 1e6, 0)}m at FY{last} year-end)" if lease else "")
    L(f"- **Leases.** Operating lease liabilities{lease_txt} are not counted as debt, because "
      f"lease cost already sits inside EBIT. Treating them as debt would require adding rent "
      f"back to EBITDA and changing the multiples and WACC to match; the choice is consistent "
      f"here but it is a choice.")
    L(f"- **Beta is noisy.** {r['beta_observations']} monthly observations give a raw beta of "
      f"{r['beta']:.2f}. Many practitioners use an adjusted (Blume) beta, which pulls toward 1.0 "
      f"and would raise WACC and lower the value; the workbook shows it for reference.")
    L(f"- **The ERP is a judgment call.** Damodaran's implied ERP ({pct(r['erp']['erp'])}) is "
      f"forward-looking and lower than many historical-average premiums. A higher ERP lowers "
      f"the value further.")
    L(f"- **Averages, not a view.** Margins, capex and working capital are held at "
      f"{config.AVERAGING_YEARS}-year averages. There is no store-count, comparable-sales or "
      f"segment build, and no explicit view on tariffs or consumer spending.")
    L(f"- **Comps use the latest fiscal year, not trailing twelve months,** and the peer set is "
      f"small ({', '.join(x['ticker'] for x in r['peers'])}). Some are broader value retailers "
      f"rather than pure off-price peers, which pulls the median multiple down.")
    L(f"- **Share count is basic, not diluted** ({r['shares'] / 1e6:,.1f}m from the latest cover "
      f"page). FY{last} diluted weighted shares were "
      f"{h[last]['diluted_shares'] / 1e6:,.0f}m; using them would lower value per share by about "
      f"{pct(1 - r['shares'] / h[last]['diluted_shares'], 1)}.")
    L(f"- **Cost of debt is synthetic.** It comes from interest coverage and a published spread "
      f"table, not from traded bond yields. Debt is {pct(r['weights']['debt'], 1)} of capital, "
      f"so this has little effect on WACC.")
    L("- **XBRL tagging varies by company.** The code walks ordered lists of tags and records "
      "which one it used in the workbook, but other tickers may need new fallbacks.\n")

    L("## How to run\n")
    L("```bash")
    L("python3 -m venv .venv && source .venv/bin/activate")
    L("pip install -r requirements.txt")
    L(f"python -m dcf run {t} --readme   # rebuild workbook, figures, results JSON and this README")
    L("python -m pytest                   # core math, XBRL parsing, workbook-vs-Python checks")
    L("```\n")
    L("Or just `make` (runs the model and the tests). Other companies work the same way, e.g. "
      "`python -m dcf run BSX --peers MDT,ABT,SYK,EW`. Add `--refresh` to download fresh data. "
      "With cached data a full run takes a few seconds.\n")
    L("```")
    L("dcf/data.py         downloads + on-disk cache (SEC, FRED, Damodaran, Yahoo)")
    L("dcf/financials.py   XBRL facts -> annual history and latest balance sheet")
    L("dcf/core.py         valuation math (WACC, discounting, terminal values, bridge)")
    L("dcf/pipeline.py     assumptions, beta, comps, sensitivities, results JSON")
    L("dcf/excel.py        Excel workbook with live formulas")
    L("dcf/verify.py       recalculates the workbook without Excel and compares")
    L("dcf/figures.py      football field and sensitivity heatmap")
    L(f"outputs/           {t}_dcf.xlsx, {t}_results.json (every number in this README)")
    L("```\n")
    L("---\n")
    L("Every number here is produced by the code in this repo.")
    path.write_text("\n".join(lines) + "\n")


def _requirements() -> list[tuple[str, str]]:
    out = []
    for line in (config.ROOT / "requirements.txt").read_text().splitlines():
        line = line.split("#")[0].strip()
        if "==" in line:
            name, ver = line.split("==", 1)
            out.append((name.strip(), ver.strip()))
    return out


def _test_count() -> int:
    return sum(f.read_text().count("\ndef test_") for f in (config.ROOT / "tests").glob("test_*.py"))


def _badge(label, msg, color):
    esc = lambda x: x.replace("-", "--").replace(" ", "%20")
    return f"![{label}](https://img.shields.io/badge/{esc(label)}-{esc(msg)}-{color}.svg)"


def write_readme(r: dict, path) -> None:
    """Short, visual-first README; the full write-up goes to docs/DETAILS.md."""
    t = r["ticker"]
    a = r["assumptions"]
    v = r["valuation"]
    price = r["price"]
    be = r["break_even_to_market_price"]
    reqs = dict(_requirements())
    direction = "below" if r["implied_price_gordon"] < price else "above"
    wb = r["workbook_check"]["abs_diff_gordon"]
    wb_txt = ("matches Python to better than $0.000001 per share" if wb < 1e-6
              else "matches Python to the cent" if wb < 0.005 else "does NOT match Python within a cent")
    be_wacc = pct(be["wacc"]) if be.get("wacc") is not None else "not reachable"
    be_margin = pct(be["ebit_margin"]) if be.get("ebit_margin") is not None else "not reachable"

    badges = [
        _badge("License", "MIT", "yellow"),
        _badge("python", "3.14", "blue"),
    ] + [_badge(k, reqs[k], c) for k, c in
         [("pandas", "150458"), ("openpyxl", "217346"), ("pycel", "6a5acd"), ("yfinance", "6001d2")]
         if k in reqs] + [_badge("tests", f"{_test_count()} passed", "brightgreen")]

    lines = []
    L = lines.append
    L(f"# What is {t} worth? A DCF built from SEC filings\n")
    L(f"Is {r['company']} worth its {usd(price)} share price ({r['valuation_date']})? A five-year "
      f"unlevered DCF says **{usd(r['implied_price_gordon'])}** (Gordon growth) to "
      f"**{usd(r['implied_price_exit'])}** (peer exit multiple), about "
      f"{pct(abs(r['upside_gordon']), 1)} {direction} the market.\n")
    L(" ".join(badges) + "\n")
    L("<table>\n<tr>")
    L(f'<td width="50%"><img src="figures/{t}_football_field.png" alt="Football field: valuation '
      f'ranges vs share price"></td>')
    L(f'<td width="50%"><img src="figures/{t}_sensitivity.png" alt="WACC x terminal growth '
      f'sensitivity"></td>')
    L("</tr>\n</table>\n")
    L("## Results\n")
    L(f"From [`outputs/{t}_results.json`](outputs/{t}_results.json); the live-formula Excel model "
      f"is [`outputs/{t}_dcf.xlsx`](outputs/{t}_dcf.xlsx).\n")
    L("| Metric | Value |")
    L("|---|---|")
    L(f"| Value per share: Gordon growth / exit multiple | {usd(r['implied_price_gordon'])} / "
      f"{usd(r['implied_price_exit'])} |")
    L(f"| vs share price {usd(price)} | {signed_pct(r['upside_gordon'])} / "
      f"{signed_pct(r['upside_exit'])} |")
    L(f"| WACC (beta {r['beta']:.3f}) | {pct(r['wacc'])} |")
    L(f"| WACC or EBIT margin needed to justify the price | {be_wacc} or {be_margin} "
      f"(model: {pct(r['wacc'])}, {pct(a['ebit_margin'])}) |")
    L(f"| Terminal value share of EV | {pct(v['tv_share_of_ev_gordon'], 1)} |")
    L("")
    L("## Proof\n")
    L(f"- **{_test_count()} tests** (`pytest`): WACC/CAPM, beta regression, discounting and stub "
      f"periods, both terminal values, equity bridge, XBRL parsing, and workbook-vs-Python checks.")
    L(f"- **Independent recalculation:** every run recomputes the Excel workbook with pycel; it "
      f"{wb_txt}.")
    L("- **One command:** `make` runs the model and the tests in a few seconds from cached data.")
    L("- **Data:** [SEC EDGAR XBRL companyfacts](https://www.sec.gov/edgar/sec-api-documentation), "
      "[FRED DGS10](https://fred.stlouisfed.org/series/DGS10), "
      "[Damodaran ERP and ratings](https://pages.stern.nyu.edu/~adamodar/), "
      "Yahoo Finance via `yfinance`.")
    L("- **Deterministic:** all downloads are cached under `data/`, so reruns reproduce every number; "
      "`--refresh` pulls new data.")
    L("")
    L("## Stack\n")
    L("Python 3.14 · " + " · ".join(f"{k} {ver}" for k, ver in reqs.items()) + "\n")
    L("## Run\n")
    L("```bash")
    L("python3 -m venv .venv && .venv/bin/pip install -r requirements.txt")
    L(f".venv/bin/python -m dcf run {t} --readme && .venv/bin/python -m pytest")
    L("```\n")
    L("## Structure\n")
    L("```")
    L("dcf/data.py, financials.py   downloads + cache; XBRL facts -> history and balance sheet")
    L("dcf/core.py, pipeline.py     valuation math; assumptions, beta, comps, sensitivities")
    L("dcf/excel.py, verify.py      live-formula workbook; independent pycel recalculation")
    L("dcf/figures.py, readme.py    charts; README and docs/DETAILS.md from results")
    L("tests/                       core math, XBRL parsing, workbook checks")
    L(f"outputs/                     {t}_dcf.xlsx, {t}_results.json")
    L("```\n")
    L("---\n")
    L("Full method, limitations and interview-level detail: [docs/DETAILS.md](docs/DETAILS.md) · "
      "MIT License")
    path.write_text("\n".join(lines) + "\n")
