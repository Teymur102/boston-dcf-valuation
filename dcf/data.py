"""Downloaders with an on-disk cache under data/.

The first run downloads everything; later runs read the cached files, so the numbers reproduce
exactly. Pass refresh=True (``--refresh`` on the CLI) to pull fresh data.
"""
from __future__ import annotations

import gzip
import io
import json
import re
import time
import warnings
from html import unescape

import pandas as pd
import requests

from . import config

_last_sec_call = 0.0


def _sec_get(url: str) -> bytes:
    """GET from sec.gov with the declared User-Agent, throttled well under 10 requests/second."""
    global _last_sec_call
    wait = config.SEC_MIN_SECONDS_BETWEEN_REQUESTS - (time.time() - _last_sec_call)
    if wait > 0:
        time.sleep(wait)
    for attempt in range(4):
        r = requests.get(url, headers={"User-Agent": config.SEC_USER_AGENT,
                                       "Accept-Encoding": "gzip, deflate"}, timeout=60)
        _last_sec_call = time.time()
        if r.status_code == 429:  # rate limited: back off and retry
            time.sleep(2 ** attempt)
            continue
        r.raise_for_status()
        return r.content
    raise RuntimeError(f"SEC kept rate-limiting {url}")


def _write_gz_json(path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(obj, f)


def _read_gz_json(path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


# --- SEC EDGAR -------------------------------------------------------------------------------
def ticker_to_cik(ticker: str, refresh: bool = False) -> tuple[str, str]:
    """Return (10-digit CIK, company title) for a ticker using SEC's company_tickers.json."""
    path = config.DATA_DIR / "sec" / "company_tickers.json.gz"
    if refresh or not path.exists():
        _write_gz_json(path, json.loads(_sec_get("https://www.sec.gov/files/company_tickers.json")))
    table = _read_gz_json(path)
    for row in table.values():
        if row["ticker"].upper() == ticker.upper():
            return f"{int(row['cik_str']):010d}", row["title"]
    raise KeyError(f"Ticker {ticker} not found in SEC company_tickers.json")


def company_facts(cik: str, refresh: bool = False) -> dict:
    """XBRL company facts (every number the company has tagged in its filings)."""
    path = config.DATA_DIR / "sec" / f"CIK{cik}.json.gz"
    if refresh or not path.exists():
        url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
        _write_gz_json(path, json.loads(_sec_get(url)))
    return _read_gz_json(path)


# --- FRED ------------------------------------------------------------------------------------
def risk_free_rate(refresh: bool = False) -> dict:
    """Latest 10-year Treasury constant-maturity yield (FRED DGS10), as a decimal."""
    path = config.DATA_DIR / "fred" / "DGS10.csv"
    if refresh or not path.exists():
        r = requests.get(config.FRED_10Y_URL, timeout=60, headers={"User-Agent": config.SEC_USER_AGENT})
        r.raise_for_status()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(r.content)
    df = pd.read_csv(path)
    df.columns = ["date", "value"]
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna()
    last = df.iloc[-1]
    return {"rate": float(last["value"]) / 100.0, "date": str(last["date"]),
            "source": "FRED series DGS10 (10-Year Treasury Constant Maturity)"}


# --- Damodaran -------------------------------------------------------------------------------
def equity_risk_premium(refresh: bool = False) -> dict:
    """Latest monthly implied ERP for the S&P 500 published by Aswath Damodaran."""
    path = config.DATA_DIR / "damodaran" / "ERPbymonth.xlsx"
    try:
        if refresh or not path.exists():
            r = requests.get(config.DAMODARAN_ERP_URL, timeout=60,
                             headers={"User-Agent": config.SEC_USER_AGENT})
            r.raise_for_status()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(r.content)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            df = pd.read_excel(path, sheet_name="Last 12 months data")
        df = df.iloc[:, :4]
        df.columns = ["date", "sp500", "t10", "erp"]
        df = df[pd.to_datetime(df["date"], errors="coerce").notna()]
        df["erp"] = pd.to_numeric(df["erp"], errors="coerce")
        df = df.dropna(subset=["erp"])
        last = df.iloc[-1]
        return {"erp": float(last["erp"]), "date": str(pd.Timestamp(last["date"]).date()),
                "source": "Damodaran (NYU Stern), implied ERP for the S&P 500, monthly update "
                          "(ERPbymonth.xlsx, 'Last 12 months data')"}
    except Exception as exc:  # network or format change: fall back to a stated constant
        return {"erp": config.FALLBACK_ERP, "date": "2025-01-01",
                "source": f"Fallback: Damodaran January 2025 implied ERP (download failed: {exc})"}


def rating_spreads(refresh: bool = False) -> list[dict]:
    """Damodaran's coverage-ratio -> rating -> default-spread table for large non-financial firms."""
    path = config.DATA_DIR / "damodaran" / "ratings.html"
    if refresh or not path.exists():
        r = requests.get(config.DAMODARAN_RATINGS_URL, timeout=60,
                         headers={"User-Agent": config.SEC_USER_AGENT})
        r.raise_for_status()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(r.content)
    text = path.read_bytes().decode("latin-1")
    text = unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)))
    date = re.search(r"Data used is as of ([A-Za-z]+ \d{4})", text)
    # Each row of the page reads: low  high  rating  spread% (two side-by-side tables; the first
    # 15 rows belong to the large non-financial firm table, the next 15 to financial firms
    # because the HTML interleaves them row by row).
    rows = re.findall(r"(-?[\d.]+) (-?[\d.]+) ([A-Za-z0-9]+/[A-Z+\-]+) ([\d.]+)%", text)
    nonfin = rows[0::2]
    table = [{"low": float(lo), "high": float(hi), "rating": rt, "spread": float(sp) / 100}
             for lo, hi, rt, sp in nonfin]
    table.sort(key=lambda r: r["low"])
    if len(table) < 10:
        raise RuntimeError("Could not parse Damodaran ratings table")
    for row in table:
        row["as_of"] = date.group(1) if date else "unknown"
    return table


# --- Prices ----------------------------------------------------------------------------------
def _yf():
    warnings.filterwarnings("ignore")
    import yfinance as yf  # imported lazily: slow import, and only needed on refresh
    return yf


def monthly_prices(ticker: str, refresh: bool = False) -> pd.Series:
    """~6 years of month-end adjusted closes (dividend-adjusted) from Yahoo Finance via yfinance."""
    safe = ticker.replace("^", "IDX_")
    path = config.DATA_DIR / "market" / f"{safe}_monthly.csv"
    if refresh or not path.exists():
        df = _yf().download(ticker, period="6y", interval="1mo", auto_adjust=True,
                            progress=False)
        if df.empty:
            raise RuntimeError(f"No monthly prices for {ticker}")
        close = df["Close"]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        path.parent.mkdir(parents=True, exist_ok=True)
        close.rename("close").to_csv(path, index_label="date")
    s = pd.read_csv(path, index_col="date", parse_dates=True)["close"]
    return s.dropna()


def last_price(ticker: str, refresh: bool = False) -> dict:
    """Latest daily close. Cached in data/market/quotes.json so a rerun uses the same price."""
    path = config.DATA_DIR / "market" / "quotes.json"
    quotes = json.loads(path.read_text()) if path.exists() else {}
    if refresh or ticker not in quotes:
        df = _yf().download(ticker, period="10d", interval="1d", auto_adjust=False,
                            progress=False)
        close = df["Close"]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        close = close.dropna()
        quotes[ticker] = {"price": round(float(close.iloc[-1]), 4),
                          "date": str(close.index[-1].date()),
                          "source": "Yahoo Finance daily close via yfinance"}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(quotes, indent=2, sort_keys=True))
    return quotes[ticker]



def daily_prices_1y(ticker: str, refresh: bool = False) -> pd.Series:
    """One year of daily closes (unadjusted), used only for the 52-week range on the chart."""
    path = config.DATA_DIR / "market" / f"{ticker}_daily_1y.csv"
    if refresh or not path.exists():
        df = _yf().download(ticker, period="1y", interval="1d", auto_adjust=False,
                            progress=False)
        close = df["Close"]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        path.parent.mkdir(parents=True, exist_ok=True)
        close.rename("close").to_csv(path, index_label="date")
    return pd.read_csv(path, index_col="date", parse_dates=True)["close"].dropna()
