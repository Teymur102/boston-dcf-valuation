"""Project-wide settings. Every modelling choice that is not derived from data lives here."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "outputs"

# SEC asks every automated client to identify itself and stay under 10 requests/second.
SEC_USER_AGENT = "Teymur Eyvazov teymur.eyvazov001@umb.edu"
SEC_MIN_SECONDS_BETWEEN_REQUESTS = 0.15

FRED_10Y_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10"
# Damodaran (NYU Stern) publishes the implied equity risk premium for the S&P 500 every month.
DAMODARAN_ERP_URL = "https://pages.stern.nyu.edu/~adamodar/pc/implprem/ERPbymonth.xlsx"
# Damodaran's interest-coverage -> synthetic rating -> default spread table (large non-financial firms).
DAMODARAN_RATINGS_URL = "https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/ratings.html"
MARKET_INDEX = "^GSPC"  # S&P 500 price index, used as the market proxy for beta

# Fallback only if the Damodaran download fails (his January 2025 implied ERP).
FALLBACK_ERP = 0.0433

# --- Forecast design -------------------------------------------------------------------------
PROJECTION_YEARS = 5
HISTORY_YEARS = 6            # fiscal years pulled from 10-K filings (gives 5 years of changes)
AVERAGING_YEARS = 3          # ratios (margin, capex %, ...) are averages of the last N fiscal years
TERMINAL_GROWTH = 0.025      # long-run nominal growth: roughly 2% inflation + modest real growth
YEAR1_GROWTH_BOUNDS = (-0.05, 0.15)  # guard rail on the historical CAGR used as year-1 growth
BETA_MONTHS = 60             # 5 years of monthly returns

# Sensitivity grid around the base case
SENS_WACC_STEPS = [-0.010, -0.005, 0.0, 0.005, 0.010]
SENS_GROWTH_STEPS = [-0.010, -0.005, 0.0, 0.005, 0.010]

# Default peer sets for trading comps (any ticker can be passed with --peers)
DEFAULT_PEERS = {
    "TJX": ["ROST", "BURL", "OLLI", "TGT", "DG"],  # off-price and value retail
    "BSX": ["MDT", "ABT", "SYK", "EW"],
}
