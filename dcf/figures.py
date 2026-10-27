"""Charts: a valuation football field and a WACC x terminal-growth heatmap."""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

plt.rcParams["text.parse_math"] = False  # "$" is a currency sign here, not math mode
import numpy as np  # noqa: E402

from .pipeline import Model, comps_implied_prices  # noqa: E402

INK = "#1f2933"
MUTED = "#6b7280"
BAR = "#3b6ea5"
BAR_LIGHT = "#a9c1dd"
PRICE = "#c2410c"


def football_field(m: Model, path) -> list[dict]:
    grid = m.sens_grid
    xg = m.sens_exit_grid
    comps = comps_implied_prices(m)
    rows = [
        {"label": "DCF, Gordon growth\nWACC ±1 pt, g ±1 pt", "low": np.nanmin(grid),
         "high": np.nanmax(grid), "mid": m.result.price_gordon},
        {"label": "DCF, exit multiple\nWACC ±1 pt, multiple ±2x", "low": xg.min(),
         "high": xg.max(), "mid": m.result.price_exit},
        {"label": "Trading comps, EV/EBITDA\npeer min to max", "low": comps["ev_ebitda"]["min"],
         "high": comps["ev_ebitda"]["max"], "mid": comps["ev_ebitda"]["median"]},
        {"label": "Trading comps, P/E\npeer min to max", "low": comps["pe"]["min"],
         "high": comps["pe"]["max"], "mid": comps["pe"]["median"]},
        {"label": "52-week trading range", "low": m.week52[0], "high": m.week52[1], "mid": None},
    ]
    fig, ax = plt.subplots(figsize=(10, 5.2), dpi=150)
    for i, r in enumerate(rows):
        y = len(rows) - 1 - i
        ax.barh(y, r["high"] - r["low"], left=r["low"], height=0.5,
                color=BAR if i < 2 else BAR_LIGHT, edgecolor="none")
        ax.text(r["low"] - 2, y, f"${r['low']:.0f}", va="center", ha="right", fontsize=9,
                color=INK)
        ax.text(r["high"] + 2, y, f"${r['high']:.0f}", va="center", ha="left", fontsize=9,
                color=INK)
        if r["mid"] is not None:
            ax.plot([r["mid"]] * 2, [y - 0.25, y + 0.25], color="white", lw=2.2)
    price = m.quote["price"]
    ax.axvline(price, color=PRICE, lw=1.6, ls="--")
    ax.text(price, len(rows) - 0.45, f"Share price ${price:.2f}\n({m.quote['date']})",
            color=PRICE, ha="center", va="bottom", fontsize=9,
            bbox=dict(facecolor="white", edgecolor="none", pad=1.5))
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([r["label"] for r in reversed(rows)], fontsize=9, color=INK)
    ax.set_xlabel("Value per share ($)", color=MUTED)
    lo = min(r["low"] for r in rows)
    hi = max(r["high"] for r in rows)
    ax.set_xlim(lo - 25, hi + 25)
    ax.set_ylim(-0.6, len(rows) + 0.2)
    for sp in ("top", "right", "left"):
        ax.spines[sp].set_visible(False)
    ax.tick_params(axis="y", length=0)
    ax.grid(axis="x", color="#e5e7eb", lw=0.8)
    ax.set_axisbelow(True)
    name = m.company.replace(", Inc.", "").replace(" Inc.", "")
    ax.set_title(f"{name} ({m.ticker}): DCF base case "
                 f"${m.result.price_gordon:.2f} vs share price ${price:.2f}",
                 loc="left", fontsize=12, color=INK, pad=28)
    fig.text(0.01, 0.01, "White tick = base case / peer median. Sources: SEC EDGAR XBRL, FRED "
             "DGS10, Damodaran ERP, Yahoo Finance.", fontsize=7.5, color=MUTED)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(path)
    plt.close(fig)
    return rows


def sensitivity_heatmap(m: Model, path) -> None:
    grid = m.sens_grid
    price = m.quote["price"]
    fig, ax = plt.subplots(figsize=(7.5, 5), dpi=150)
    rel = grid / price - 1
    lim = np.nanmax(np.abs(rel))
    ax.imshow(rel, cmap="RdBu", vmin=-lim, vmax=lim, aspect="auto")
    for i in range(grid.shape[0]):
        for j in range(grid.shape[1]):
            v = grid[i, j]
            if np.isnan(v):
                continue
            strong = abs(rel[i, j]) > lim * 0.55
            ax.text(j, i, f"${v:.0f}", ha="center", va="center", fontsize=10,
                    color="white" if strong else INK,
                    fontweight="bold" if (i == grid.shape[0] // 2 and j == grid.shape[1] // 2)
                    else "normal")
    ax.set_xticks(range(len(m.sens_growths)))
    ax.set_xticklabels([f"{g:.1%}" for g in m.sens_growths])
    ax.set_yticks(range(len(m.sens_waccs)))
    ax.set_yticklabels([f"{w:.2%}" for w in m.sens_waccs])
    ax.set_xlabel("Terminal growth rate")
    ax.set_ylabel("WACC")
    ax.set_title(f"{m.ticker} value per share: WACC x terminal growth\n"
                 f"blue = above the ${price:.2f} share price, red = below", fontsize=11,
                 loc="left", color=INK)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
