"""
Quantitative backtest visualizations — generates 10 PNG charts.
Output folder: backtest_charts/
"""
from __future__ import annotations
import os
from collections import defaultdict
from datetime import date

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import matplotlib.patches as mpatches
import seaborn as sns

from backtest.quant_engine import QuantTrade

OUT_DIR = "backtest_charts"

# ── Style ─────────────────────────────────────────────────────────────────────
BG      = "#0d1117"
PANEL   = "#161b22"
GRID    = "#21262d"
GREEN   = "#39d353"
RED     = "#f85149"
BLUE    = "#58a6ff"
PURPLE  = "#bc8cff"
ORANGE  = "#ffa657"
YELLOW  = "#e3b341"
TEXT    = "#e6edf3"
SUBTEXT = "#8b949e"

STRAT_COLORS = {
    "gap_fill":       BLUE,
    "fvg":            PURPLE,
    "orb":            ORANGE,
    "ib_breakout":    YELLOW,
    "vwap_rev":       GREEN,
    "vwap_pm":        "#3fb950",
    "vwap_bounce":    "#79c0ff",
    "vwap_bounce_pm": "#a5d6ff",
}

STRAT_LABELS = {
    "gap_fill":       "Gap Fill",
    "fvg":            "FVG",
    "orb":            "ORB",
    "ib_breakout":    "IB Breakout",
    "vwap_rev":       "VWAP Rev AM",
    "vwap_pm":        "VWAP Rev PM",
    "vwap_bounce":    "VWAP Bounce AM",
    "vwap_bounce_pm": "VWAP Bounce PM",
}


def _fig(w=14, h=7):
    fig, ax = plt.subplots(figsize=(w, h), facecolor=BG)
    ax.set_facecolor(PANEL)
    ax.tick_params(colors=SUBTEXT, labelsize=9)
    ax.xaxis.label.set_color(SUBTEXT)
    ax.yaxis.label.set_color(SUBTEXT)
    for spine in ax.spines.values():
        spine.set_edgecolor(GRID)
    ax.grid(color=GRID, linewidth=0.5, alpha=0.8)
    return fig, ax


def _save(fig, name):
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, f"{name}.png")
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor=BG)
    plt.close(fig)
    print(f"  saved → {path}")


def _title(ax, text, sub=""):
    ax.set_title(text, color=TEXT, fontsize=13, fontweight="bold", pad=12)
    if sub:
        ax.annotate(sub, xy=(0.5, 1.01), xycoords="axes fraction",
                    ha="center", color=SUBTEXT, fontsize=9)


# ── 1. Equity Curve ───────────────────────────────────────────────────────────
def chart_equity_curve(trades: list[QuantTrade]) -> None:
    pnl = np.cumsum([t.pnl for t in trades])
    xs  = np.arange(len(pnl))

    fig, ax = _fig(14, 6)
    ax.plot(xs, pnl, color=BLUE, linewidth=1.8, zorder=3)
    ax.fill_between(xs, pnl, 0, where=(pnl >= 0), alpha=0.18, color=GREEN)
    ax.fill_between(xs, pnl, 0, where=(pnl <  0), alpha=0.18, color=RED)
    ax.axhline(0, color=SUBTEXT, linewidth=0.8, linestyle="--", alpha=0.6)

    # running peak + drawdown shading
    peak = np.maximum.accumulate(pnl)
    dd   = pnl - peak
    ax2  = ax.twinx()
    ax2.set_facecolor(PANEL)
    ax2.fill_between(xs, dd, 0, alpha=0.25, color=RED, zorder=1)
    ax2.set_ylabel("Drawdown ($)", color=RED, fontsize=9)
    ax2.tick_params(colors=RED, labelsize=8)
    ax2.yaxis.label.set_color(RED)
    for spine in ax2.spines.values():
        spine.set_edgecolor(GRID)

    ax.set_xlabel("Trade #")
    ax.set_ylabel("Cumulative P&L ($)")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"${v:+,.0f}"))
    _title(ax, "Equity Curve", f"Final: ${pnl[-1]:+,.2f}  |  Max DD: ${dd.min():,.2f}")
    _save(fig, "01_equity_curve")


# ── 2. Drawdown Underwater ────────────────────────────────────────────────────
def chart_drawdown(trades: list[QuantTrade]) -> None:
    pnl  = np.cumsum([t.pnl for t in trades])
    peak = np.maximum.accumulate(pnl)
    dd   = (pnl - peak)

    fig, ax = _fig(14, 5)
    ax.fill_between(range(len(dd)), dd, 0, color=RED, alpha=0.5)
    ax.plot(dd, color=RED, linewidth=1.2)
    ax.axhline(0, color=SUBTEXT, linewidth=0.6, linestyle="--")
    ax.set_xlabel("Trade #")
    ax.set_ylabel("Drawdown ($)")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"${v:,.0f}"))
    _title(ax, "Drawdown (Underwater Chart)", f"Max: ${dd.min():,.2f}")
    _save(fig, "02_drawdown")


# ── 3. Strategy Win Rate & P&L ────────────────────────────────────────────────
def chart_strategy_breakdown(trades: list[QuantTrade]) -> None:
    order  = ["gap_fill", "fvg", "orb", "ib_breakout", "vwap_rev", "vwap_pm", "vwap_bounce", "vwap_bounce_pm"]
    groups = defaultdict(list)
    for t in trades:
        groups[t.strategy].append(t)

    strats = [s for s in order if s in groups]
    labels = [STRAT_LABELS.get(s, s) for s in strats]
    wrs    = [len([t for t in groups[s] if t.outcome == "WIN"]) / len(groups[s]) * 100 for s in strats]
    pnls   = [sum(t.pnl for t in groups[s]) for s in strats]
    colors = [STRAT_COLORS.get(s, BLUE) for s in strats]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6), facecolor=BG)
    for ax in (ax1, ax2):
        ax.set_facecolor(PANEL)
        ax.tick_params(colors=SUBTEXT, labelsize=8)
        for spine in ax.spines.values():
            spine.set_edgecolor(GRID)
        ax.grid(color=GRID, linewidth=0.5, alpha=0.8, axis="x")

    xs = np.arange(len(strats))

    # Win rate
    bars = ax1.barh(xs, wrs, color=colors, alpha=0.85, height=0.6)
    ax1.axvline(50, color=SUBTEXT, linewidth=0.8, linestyle="--", alpha=0.6)
    ax1.set_yticks(xs); ax1.set_yticklabels(labels, color=TEXT, fontsize=9)
    ax1.set_xlabel("Win Rate (%)", color=SUBTEXT)
    ax1.set_xlim(0, 105)
    for bar, wr in zip(bars, wrs):
        ax1.text(bar.get_width() + 1, bar.get_y() + bar.get_height() / 2,
                 f"{wr:.0f}%", va="center", color=TEXT, fontsize=8)
    ax1.set_title("Win Rate by Strategy", color=TEXT, fontsize=11, fontweight="bold")

    # P&L
    bar_colors = [GREEN if p >= 0 else RED for p in pnls]
    bars2 = ax2.barh(xs, pnls, color=bar_colors, alpha=0.85, height=0.6)
    ax2.axvline(0, color=SUBTEXT, linewidth=0.8, linestyle="--", alpha=0.6)
    ax2.set_yticks(xs); ax2.set_yticklabels(labels, color=TEXT, fontsize=9)
    ax2.set_xlabel("Total P&L ($)", color=SUBTEXT)
    ax2.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"${v:+,.0f}"))
    for bar, p in zip(bars2, pnls):
        x = bar.get_width() + (5 if p >= 0 else -5)
        ax2.text(x, bar.get_y() + bar.get_height() / 2,
                 f"${p:+.0f}", va="center", ha="left" if p >= 0 else "right",
                 color=TEXT, fontsize=8)
    ax2.set_title("Total P&L by Strategy", color=TEXT, fontsize=11, fontweight="bold")

    fig.suptitle("Strategy Performance Breakdown", color=TEXT, fontsize=13, fontweight="bold", y=1.01)
    fig.tight_layout()
    _save(fig, "03_strategy_breakdown")


# ── 4. Daily P&L Distribution ─────────────────────────────────────────────────
def chart_pnl_distribution(trades: list[QuantTrade]) -> None:
    pnls = [t.pnl for t in trades]
    fig, ax = _fig(12, 6)

    n, bins, patches = ax.hist(pnls, bins=30, edgecolor=BG, linewidth=0.5)
    for patch, left in zip(patches, bins[:-1]):
        patch.set_facecolor(GREEN if left >= 0 else RED)
        patch.set_alpha(0.8)

    mu, sigma = np.mean(pnls), np.std(pnls)
    x  = np.linspace(min(pnls), max(pnls), 200)
    y  = (n.max() / (sigma * np.sqrt(2 * np.pi))) * np.exp(-0.5 * ((x - mu) / sigma) ** 2)
    ax.plot(x, y, color=YELLOW, linewidth=1.5, linestyle="--", label="Normal fit")
    ax.axvline(mu, color=BLUE, linewidth=1.2, linestyle="-", label=f"Mean ${mu:+.1f}")
    ax.axvline(0,  color=SUBTEXT, linewidth=0.8, linestyle="--", alpha=0.5)

    ax.set_xlabel("P&L per Trade ($)")
    ax.set_ylabel("Frequency")
    ax.legend(facecolor=PANEL, labelcolor=TEXT, fontsize=9, framealpha=0.8)
    _title(ax, "Trade P&L Distribution",
           f"μ=${mu:+.1f}  σ=${sigma:.1f}  Skew={pd.Series(pnls).skew():.2f}")
    _save(fig, "04_pnl_distribution")


# ── 5. Rolling Win Rate ───────────────────────────────────────────────────────
def chart_rolling_winrate(trades: list[QuantTrade], window: int = 20) -> None:
    outcomes = np.array([1 if t.outcome == "WIN" else 0 for t in trades], dtype=float)
    roll     = pd.Series(outcomes).rolling(window).mean() * 100

    fig, ax = _fig(14, 5)
    ax.plot(roll.index, roll.values, color=PURPLE, linewidth=1.6, zorder=3)
    ax.fill_between(roll.index, roll.values, 50, where=(roll.values >= 50),
                    alpha=0.2, color=GREEN)
    ax.fill_between(roll.index, roll.values, 50, where=(roll.values < 50),
                    alpha=0.2, color=RED)
    ax.axhline(50, color=SUBTEXT, linewidth=0.8, linestyle="--", alpha=0.6, label="50%")
    ax.axhline(outcomes.mean() * 100, color=BLUE, linewidth=1, linestyle=":",
               label=f"Overall {outcomes.mean()*100:.1f}%")
    ax.set_ylim(0, 100)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:.0f}%"))
    ax.set_xlabel("Trade #")
    ax.set_ylabel("Win Rate")
    ax.legend(facecolor=PANEL, labelcolor=TEXT, fontsize=9, framealpha=0.8)
    _title(ax, f"Rolling {window}-Trade Win Rate")
    _save(fig, "05_rolling_winrate")


# ── 6. Win Rate Heatmap (Day × Strategy) ─────────────────────────────────────
def chart_heatmap(trades: list[QuantTrade]) -> None:
    order_d = ["Mon", "Tue", "Wed", "Thu", "Fri"]
    order_s = ["gap_fill", "fvg", "orb", "ib_breakout", "vwap_rev", "vwap_pm", "vwap_bounce", "vwap_bounce_pm"]
    labels_s = [STRAT_LABELS.get(s, s) for s in order_s]

    matrix = pd.DataFrame(index=order_d, columns=order_s, dtype=float)
    counts = pd.DataFrame(index=order_d, columns=order_s, dtype=int)
    for d in order_d:
        for s in order_s:
            sub = [t for t in trades if t.day_name == d and t.strategy == s]
            if sub:
                matrix.loc[d, s] = len([t for t in sub if t.outcome == "WIN"]) / len(sub) * 100
                counts.loc[d, s] = len(sub)
            else:
                matrix.loc[d, s] = np.nan
                counts.loc[d, s] = 0

    fig, ax = plt.subplots(figsize=(14, 5), facecolor=BG)
    ax.set_facecolor(PANEL)

    cmap = sns.diverging_palette(10, 130, s=80, l=50, as_cmap=True)
    sns.heatmap(
        matrix.astype(float), ax=ax, cmap=cmap, vmin=0, vmax=100,
        annot=True, fmt=".0f", linewidths=0.5, linecolor=BG,
        cbar_kws={"label": "Win Rate (%)", "shrink": 0.8},
        annot_kws={"size": 9, "color": TEXT},
    )
    ax.set_xticklabels(labels_s, rotation=30, ha="right", color=TEXT, fontsize=9)
    ax.set_yticklabels(order_d, rotation=0, color=TEXT, fontsize=9)

    # overlay trade count in small text
    for i, d in enumerate(order_d):
        for j, s in enumerate(order_s):
            c = counts.loc[d, s]
            if c > 0:
                ax.text(j + 0.85, i + 0.85, str(c), ha="right", va="bottom",
                        color=TEXT, fontsize=6, alpha=0.7)

    ax.set_title("Win Rate Heatmap  (Day × Strategy)", color=TEXT, fontsize=13,
                 fontweight="bold", pad=12)
    fig.tight_layout()
    _save(fig, "06_winrate_heatmap")


# ── 7. VIX vs P&L Scatter ────────────────────────────────────────────────────
def chart_vix_scatter(trades: list[QuantTrade]) -> None:
    fig, ax = _fig(11, 7)

    for strat, color in STRAT_COLORS.items():
        sub = [t for t in trades if t.strategy == strat]
        if not sub:
            continue
        vixes = [t.vix for t in sub]
        pnls  = [t.pnl for t in sub]
        ax.scatter(vixes, pnls, color=color, alpha=0.65, s=35,
                   label=STRAT_LABELS.get(strat, strat), zorder=3)

    ax.axhline(0, color=SUBTEXT, linewidth=0.8, linestyle="--", alpha=0.6)
    ax.axvline(20, color=YELLOW, linewidth=0.8, linestyle=":", alpha=0.5, label="VIX 20")
    ax.axvline(30, color=RED,    linewidth=0.8, linestyle=":", alpha=0.5, label="VIX 30")

    # trend line
    vix_all = np.array([t.vix for t in trades])
    pnl_all = np.array([t.pnl for t in trades])
    m, b = np.polyfit(vix_all, pnl_all, 1)
    xs = np.linspace(vix_all.min(), vix_all.max(), 100)
    ax.plot(xs, m * xs + b, color=TEXT, linewidth=1, linestyle="--", alpha=0.4, label="Trend")

    ax.set_xlabel("VIX")
    ax.set_ylabel("Trade P&L ($)")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"${v:+,.0f}"))
    ax.legend(facecolor=PANEL, labelcolor=TEXT, fontsize=8, framealpha=0.8,
              loc="upper right", ncol=2)
    _title(ax, "VIX vs Trade P&L", "Each dot = 1 trade, colored by strategy")
    _save(fig, "07_vix_scatter")


# ── 8. Risk:Reward Distribution ───────────────────────────────────────────────
def chart_rr_distribution(trades: list[QuantTrade]) -> None:
    wins   = [t.rr for t in trades if t.outcome == "WIN"]
    losses = [t.rr for t in trades if t.outcome == "LOSS"]
    all_rr = [t.rr for t in trades]

    fig, ax = _fig(12, 6)
    bins = np.linspace(0, max(all_rr) * 1.1, 25)
    ax.hist(wins,   bins=bins, color=GREEN, alpha=0.7, label=f"Wins   (n={len(wins)})",   zorder=3)
    ax.hist(losses, bins=bins, color=RED,   alpha=0.7, label=f"Losses (n={len(losses)})", zorder=2)
    ax.axvline(1.0, color=YELLOW, linewidth=1, linestyle="--", alpha=0.8, label="1:1 R:R")
    ax.axvline(np.mean(all_rr), color=BLUE, linewidth=1.2, linestyle="-",
               label=f"Avg {np.mean(all_rr):.2f}")

    ax.set_xlabel("Risk:Reward Ratio")
    ax.set_ylabel("Frequency")
    ax.legend(facecolor=PANEL, labelcolor=TEXT, fontsize=9, framealpha=0.8)
    _title(ax, "Risk:Reward Distribution", f"Avg RR: {np.mean(all_rr):.2f}")
    _save(fig, "08_rr_distribution")


# ── 9. Monthly P&L Calendar Heatmap ──────────────────────────────────────────
def chart_monthly_calendar(trades: list[QuantTrade]) -> None:
    daily = defaultdict(float)
    for t in trades:
        daily[t.date] += t.pnl

    if not daily:
        return

    dates = sorted(daily.keys())
    start = date(dates[0].year, dates[0].month, 1)
    end   = dates[-1]

    months = sorted({(d.year, d.month) for d in dates})
    n_months = len(months)
    cols = min(n_months, 4)
    rows = (n_months + cols - 1) // cols

    fig, axes = plt.subplots(rows, cols, figsize=(cols * 4.5, rows * 3.5), facecolor=BG)
    axes_flat = np.array(axes).flatten() if n_months > 1 else [axes]

    import calendar
    month_names = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    day_labels  = ["M", "T", "W", "T", "F", "S", "S"]

    for idx, (yr, mo) in enumerate(months):
        ax = axes_flat[idx]
        ax.set_facecolor(PANEL)
        for spine in ax.spines.values():
            spine.set_edgecolor(GRID)
        ax.set_xticks(range(7))
        ax.set_xticklabels(day_labels, fontsize=7, color=SUBTEXT)
        ax.set_yticks([])
        ax.set_title(f"{month_names[mo]} {yr}", color=TEXT, fontsize=9, fontweight="bold")

        cal = calendar.monthcalendar(yr, mo)
        for week_n, week in enumerate(cal):
            for dow, day in enumerate(week):
                if day == 0:
                    continue
                d = date(yr, mo, day)
                pnl = daily.get(d, None)
                if pnl is not None:
                    color = GREEN if pnl > 0 else RED
                    alpha = min(0.9, 0.3 + abs(pnl) / 120)
                    rect = mpatches.FancyBboxPatch(
                        (dow - 0.4, -week_n - 0.4), 0.8, 0.75,
                        boxstyle="round,pad=0.05",
                        facecolor=color, edgecolor=BG, alpha=alpha, linewidth=0.5
                    )
                    ax.add_patch(rect)
                    ax.text(dow, -week_n + 0.12, f"{day}", ha="center", va="center",
                            color=TEXT, fontsize=6.5, fontweight="bold")
                    ax.text(dow, -week_n - 0.22, f"${pnl:+.0f}", ha="center", va="center",
                            color=TEXT, fontsize=5.5)
                else:
                    ax.text(dow, -week_n, str(day), ha="center", va="center",
                            color=SUBTEXT, fontsize=6.5, alpha=0.5)

        ax.set_xlim(-0.6, 6.6)
        ax.set_ylim(-len(cal) + 0.2, 0.8)

    for ax in axes_flat[len(months):]:
        ax.set_visible(False)

    fig.suptitle("Daily P&L Calendar", color=TEXT, fontsize=13, fontweight="bold", y=1.01)
    fig.tight_layout()
    _save(fig, "09_monthly_calendar")


# ── 10. Cumulative P&L by Strategy ───────────────────────────────────────────
def chart_strategy_equity_curves(trades: list[QuantTrade]) -> None:
    order  = ["gap_fill", "fvg", "orb", "ib_breakout", "vwap_rev", "vwap_pm", "vwap_bounce", "vwap_bounce_pm"]
    groups = defaultdict(list)
    for t in trades:
        groups[t.strategy].append(t)

    fig, ax = _fig(14, 7)

    for strat in order:
        if strat not in groups:
            continue
        strat_trades = sorted(groups[strat], key=lambda t: t.date)
        cum = np.cumsum([t.pnl for t in strat_trades])
        color = STRAT_COLORS.get(strat, BLUE)
        label = f"{STRAT_LABELS.get(strat, strat)}  ${cum[-1]:+.0f}"
        ax.plot(range(len(cum)), cum, color=color, linewidth=1.6, label=label, alpha=0.85)

    ax.axhline(0, color=SUBTEXT, linewidth=0.8, linestyle="--", alpha=0.5)
    ax.set_xlabel("Trade # (per strategy)")
    ax.set_ylabel("Cumulative P&L ($)")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"${v:+,.0f}"))
    ax.legend(facecolor=PANEL, labelcolor=TEXT, fontsize=9, framealpha=0.8, loc="upper left")
    _title(ax, "Cumulative P&L — Strategy Breakdown", "Each line = one strategy's running P&L")
    _save(fig, "10_strategy_equity_curves")


# ── Entry point ───────────────────────────────────────────────────────────────
def generate_all_charts(trades: list[QuantTrade]) -> None:
    print(f"\nGenerating charts ({len(trades)} trades) → {OUT_DIR}/")
    chart_equity_curve(trades)
    chart_drawdown(trades)
    chart_strategy_breakdown(trades)
    chart_pnl_distribution(trades)
    chart_rolling_winrate(trades)
    chart_heatmap(trades)
    chart_vix_scatter(trades)
    chart_rr_distribution(trades)
    chart_monthly_calendar(trades)
    chart_strategy_equity_curves(trades)
    print(f"\nDone — 10 charts saved to ./{OUT_DIR}/\n")
