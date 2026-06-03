"""
Institutional tearsheet charts — pyfolio / AQR research paper style.

White background, dense metrics tables, muted colors, small fonts.
Exactly how hedge funds present backtests in actual research reports.
"""
from __future__ import annotations
import os
from collections import defaultdict
from datetime import date
import calendar as cal_mod

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import matplotlib.gridspec as gridspec
import matplotlib.patches as mpatches
import matplotlib.table as mpltable
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm
import warnings
warnings.filterwarnings("ignore")

OUT_DIR = "backtest_charts"

# ── Institutional color palette ───────────────────────────────────────────────
BG       = "#FFFFFF"
PANEL    = "#FAFAFA"
GRID     = "#EEEEEE"
BORDER   = "#CCCCCC"
TEXT     = "#1A1A1A"
SUBTEXT  = "#555555"
DIM      = "#999999"

C_POS    = "#27AE60"   # muted green — positive
C_NEG    = "#C0392B"   # muted red   — negative
C_BLUE   = "#1565C0"   # primary line — institutional blue
C_ORANGE = "#E67E22"   # secondary line / benchmark
C_GRAY   = "#607D8B"   # neutral
C_TEAL   = "#00796B"   # accent
C_PURPLE = "#6A1B9A"   # strategy 2

STRAT_PALETTE = [
    "#1565C0","#C0392B","#27AE60","#E67E22",
    "#6A1B9A","#00796B","#AD1457","#37474F","#F57F17",
]
STRAT_COLORS = {
    "gap_fill": "#1565C0", "fvg": "#6A1B9A", "orb": "#E67E22",
    "ib_breakout": "#AD1457", "vwap_rev": "#27AE60", "vwap_pm": "#00796B",
    "vwap_bounce": "#C0392B", "vwap_bounce_pm": "#37474F", "va_rule": "#F57F17",
}

# Red-white-green diverging colormap
RWG = LinearSegmentedColormap.from_list(
    "rwg", ["#C0392B", "#FFFFFF", "#27AE60"], N=256)


def _font():
    plt.rcParams.update({
        "font.family":     "DejaVu Sans",
        "font.size":       8,
        "axes.titlesize":  9,
        "axes.labelsize":  8,
        "xtick.labelsize": 7,
        "ytick.labelsize": 7,
        "legend.fontsize": 7,
        "figure.dpi":      150,
        "axes.spines.top":    False,
        "axes.spines.right":  False,
    })


def _ax(ax, grid=True):
    ax.set_facecolor(PANEL)
    ax.tick_params(colors=SUBTEXT, length=2.5, width=0.5)
    ax.xaxis.label.set_color(SUBTEXT)
    ax.yaxis.label.set_color(SUBTEXT)
    for sp in ax.spines.values():
        sp.set_edgecolor(BORDER)
        sp.set_linewidth(0.6)
    if grid:
        ax.grid(color=GRID, linewidth=0.5, alpha=1.0, zorder=0)
        ax.set_axisbelow(True)


def _save(fig, name):
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, f"{name}.png")
    fig.savefig(path, dpi=150, bbox_inches="tight",
                facecolor=BG, edgecolor="none")
    plt.close(fig)
    print(f"  saved -> {path}")


def _footer(fig, text="ISOGENY ALPHA SYSTEM v7.0  |  KAIROS CAPITAL RESEARCH  |  For Internal Use Only"):
    fig.text(0.5, 0.005, text, ha="center", va="bottom",
             color=DIM, fontsize=6, style="italic")


def _title_bar(fig, title, sub=""):
    fig.text(0.5, 0.99, title, ha="center", va="top",
             color=TEXT, fontsize=11, fontweight="bold")
    if sub:
        fig.text(0.5, 0.972, sub, ha="center", va="top",
                 color=SUBTEXT, fontsize=7.5, style="italic")


def _pct_fmt(ax):
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(xmax=1.0, decimals=0))


def _dollar_fmt(ax):
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"${v:+,.0f}"))


def _compute(trades):
    """Compute all metrics needed across charts."""
    pnls  = np.array([t.pnl for t in trades])
    dates = [t.date for t in trades]
    wins  = pnls[pnls > 0]
    losses= pnls[pnls < 0]
    cum   = np.cumsum(pnls)
    peak  = np.maximum.accumulate(cum)
    dd    = cum - peak

    # Annualised (assume 3 trades/day, 252 days)
    ann   = 252 * 3
    mean_ = float(np.mean(pnls))
    std_  = float(np.std(pnls))
    sr    = mean_ / std_ * np.sqrt(ann) if std_ else 0
    neg_std = float(np.std(losses)) if len(losses) else std_
    so    = mean_ / neg_std * np.sqrt(ann) if neg_std else 0
    cal   = float(cum[-1] / abs(dd.min())) if dd.min() < 0 else 0
    pf    = abs(wins.sum() / losses.sum()) if losses.any() else 99.0
    var95 = float(np.percentile(pnls, 5))
    cvar  = float(np.mean(pnls[pnls <= var95]))

    # Omega ratio (sum positive / |sum negative|)
    omega = abs(wins.sum() / losses.sum()) if losses.any() else 99.0

    # Tail ratio: 95th pct / |5th pct|
    tail  = abs(float(np.percentile(pnls, 95)) / var95) if var95 != 0 else 0

    # Gain-to-pain: total return / sum of absolute monthly losses
    gtp   = cum[-1] / abs(sum(p for p in pnls if p < 0)) if losses.any() else 0

    # Kelly
    wr    = len(wins) / len(pnls)
    rr    = abs(float(np.mean(wins)) / float(np.mean(losses))) if losses.any() else 1
    kelly = wr - (1 - wr) / rr if rr else 0

    # Recovery factor
    rec   = float(cum[-1] / abs(dd.min())) if dd.min() < 0 else 0

    skew  = float(pd.Series(pnls).skew())
    kurt  = float(pd.Series(pnls).kurtosis())

    # Max consecutive wins/losses
    outcomes = [1 if t.outcome == "WIN" else -1 for t in trades]
    max_cw = max_cl = cur = 0
    cur_type = outcomes[0] if outcomes else 1
    for o in outcomes:
        if o == cur_type:
            cur += 1
        else:
            if cur_type == 1:  max_cw = max(max_cw, cur)
            else:              max_cl = max(max_cl, cur)
            cur = 1; cur_type = o
    if cur_type == 1: max_cw = max(max_cw, cur)
    else:             max_cl = max(max_cl, cur)

    # Drawdown periods (top 5)
    dd_periods = []
    in_dd = False; peak_i = 0; trough_i = 0; trough_val = 0
    for i, d in enumerate(dd):
        if d < 0 and not in_dd:
            in_dd = True; peak_i = i; trough_val = d; trough_i = i
        elif d < trough_val and in_dd:
            trough_val = d; trough_i = i
        elif d == 0 and in_dd:
            in_dd = False
            dd_periods.append({
                "start": dates[peak_i], "trough": dates[trough_i],
                "end":   dates[i],      "depth":  trough_val,
                "dur":   i - peak_i,    "recovery": i - trough_i,
            })
    if in_dd:
        dd_periods.append({
            "start": dates[peak_i], "trough": dates[trough_i],
            "end":   None,          "depth":  trough_val,
            "dur":   len(dd)-1-peak_i, "recovery": None,
        })
    dd_periods.sort(key=lambda x: x["depth"])

    return dict(
        pnls=pnls, cum=cum, dd=dd, peak=peak, dates=dates,
        wins=wins, losses=losses,
        wr=wr*100, avg_win=float(np.mean(wins)) if len(wins) else 0,
        avg_loss=float(np.mean(losses)) if len(losses) else 0,
        pf=pf, sharpe=sr, sortino=so, calmar=cal,
        total=float(cum[-1]), max_dd=float(dd.min()),
        var95=var95, cvar=cvar, omega=omega, tail=tail,
        gtp=gtp, kelly=kelly, rec=rec,
        skew=skew, kurt=kurt,
        max_cw=max_cw, max_cl=max_cl,
        dd_periods=dd_periods[:5],
        n=len(trades), n_days=len(set(dates)),
    )


# ── 1. MAIN TEARSHEET — Performance Overview ─────────────────────────────────
def chart_equity_curve(trades):
    _font()
    s = _compute(trades)
    fig = plt.figure(figsize=(17, 22), facecolor=BG)
    gs  = gridspec.GridSpec(5, 2, figure=fig, hspace=0.45, wspace=0.32,
                            left=0.08, right=0.96, top=0.94, bottom=0.04)

    # ── Performance stats table ───────────────────────────────────────────────
    ax_t = fig.add_subplot(gs[0, :])
    ax_t.axis("off")
    ax_t.set_title("PERFORMANCE STATISTICS", color=TEXT, fontsize=10,
                   fontweight="bold", loc="left", pad=8)

    col1 = [
        ("Total P&L",        f"${s['total']:+,.2f}"),
        ("Win Rate",         f"{s['wr']:.1f}%"),
        ("Total Trades",     f"{s['n']}"),
        ("Avg Win",          f"${s['avg_win']:+.2f}"),
        ("Avg Loss",         f"${s['avg_loss']:+.2f}"),
        ("Profit Factor",    f"{s['pf']:.2f}x"),
        ("Max Drawdown",     f"${s['max_dd']:,.2f}"),
    ]
    col2 = [
        ("Sharpe Ratio",     f"{s['sharpe']:.3f}"),
        ("Sortino Ratio",    f"{s['sortino']:.3f}"),
        ("Calmar Ratio",     f"{s['calmar']:.3f}"),
        ("Omega Ratio",      f"{s['omega']:.3f}"),
        ("Tail Ratio",       f"{s['tail']:.3f}"),
        ("Gain-to-Pain",     f"{s['gtp']:.3f}"),
        ("Recovery Factor",  f"{s['rec']:.2f}x"),
    ]
    col3 = [
        ("VaR (95%)",        f"${s['var95']:+.2f}"),
        ("CVaR (95%)",       f"${s['cvar']:+.2f}"),
        ("Skewness",         f"{s['skew']:+.3f}"),
        ("Excess Kurtosis",  f"{s['kurt']:+.3f}"),
        ("Kelly Criterion",  f"{s['kelly']*100:.1f}%"),
        ("Max Consec. Wins", f"{s['max_cw']}"),
        ("Max Consec. Loss", f"{s['max_cl']}"),
    ]

    n_rows = len(col1)
    col_w  = [0.155, 0.1, 0.155, 0.1, 0.155, 0.1]
    x_starts = [0.0, 0.17, 0.345, 0.515, 0.69, 0.86]

    for row_i, ((lbl1,v1),(lbl2,v2),(lbl3,v3)) in enumerate(zip(col1,col2,col3)):
        y = 1.0 - row_i * (1.0 / n_rows)
        bg = "#F5F5F5" if row_i % 2 == 0 else BG
        rect = mpatches.FancyBboxPatch((0, y-1.0/n_rows), 1.0, 1.0/n_rows,
            transform=ax_t.transAxes, boxstyle="square,pad=0",
            facecolor=bg, edgecolor="none", zorder=0)
        ax_t.add_patch(rect)
        for xi, (lbl, val) in [(0,(lbl1,v1)),(2,(lbl2,v2)),(4,(lbl3,v3))]:
            x_l = x_starts[xi]; x_v = x_starts[xi+1]
            ax_t.text(x_l, y-0.01, lbl, transform=ax_t.transAxes,
                      va="top", ha="left", color=SUBTEXT, fontsize=7.5)
            is_neg = str(val).startswith("-") or (lbl in ("Avg Loss","VaR (95%)","CVaR (95%)","Max Drawdown"))
            ax_t.text(x_v+0.08, y-0.01, val, transform=ax_t.transAxes,
                      va="top", ha="right", color=C_NEG if is_neg else TEXT,
                      fontsize=8, fontweight="bold")
    ax_t.set_xlim(0,1); ax_t.set_ylim(0,1)

    # ── Cumulative P&L ────────────────────────────────────────────────────────
    ax1 = fig.add_subplot(gs[1, :])
    _ax(ax1)
    xs = np.arange(len(s["cum"]))
    ax1.fill_between(xs, s["cum"], 0, where=(s["cum"]>=0),
                     alpha=0.15, color=C_POS)
    ax1.fill_between(xs, s["cum"], 0, where=(s["cum"]<0),
                     alpha=0.15, color=C_NEG)
    ax1.plot(xs, s["cum"], color=C_BLUE, linewidth=1.5, zorder=3)
    ax1.axhline(0, color=BORDER, lw=0.8, ls="--")
    # Annotate final P&L
    ax1.annotate(f"  ${s['cum'][-1]:+,.2f}",
                 xy=(xs[-1], s["cum"][-1]),
                 color=C_POS if s["cum"][-1]>=0 else C_NEG,
                 fontsize=8, fontweight="bold")
    _dollar_fmt(ax1)
    ax1.set_ylabel("Cumulative P&L ($)")
    ax1.set_title("CUMULATIVE P&L", color=TEXT, fontsize=9,
                  fontweight="bold", loc="left")

    # ── Drawdown underwater ───────────────────────────────────────────────────
    ax2 = fig.add_subplot(gs[2, :])
    _ax(ax2)
    ax2.fill_between(xs, s["dd"], 0, color=C_NEG, alpha=0.3)
    ax2.plot(xs, s["dd"], color=C_NEG, lw=1.0)
    ax2.axhline(0, color=BORDER, lw=0.8)
    _dollar_fmt(ax2)
    ax2.set_ylabel("Drawdown ($)")
    ax2.set_title("DRAWDOWN (UNDERWATER)", color=TEXT, fontsize=9,
                  fontweight="bold", loc="left")

    # ── Rolling 20-trade Sharpe ───────────────────────────────────────────────
    ax3 = fig.add_subplot(gs[3, 0])
    _ax(ax3)
    win = min(20, max(5, len(trades)//6))
    rs  = (pd.Series(s["pnls"]).rolling(win, min_periods=5).mean() /
           pd.Series(s["pnls"]).rolling(win, min_periods=5).std() * np.sqrt(252*3)).fillna(0)
    ax3.plot(xs, rs.values, color=C_BLUE, lw=1.3)
    ax3.axhline(0,   color=BORDER, lw=0.7, ls="--")
    ax3.axhline(1.0, color=C_POS,  lw=0.7, ls=":", alpha=0.8, label="Sharpe 1.0")
    ax3.axhline(2.0, color=C_TEAL, lw=0.7, ls=":", alpha=0.8, label="Sharpe 2.0")
    ax3.fill_between(xs, rs.values, 0, where=(rs.values>=0), alpha=0.1, color=C_POS)
    ax3.fill_between(xs, rs.values, 0, where=(rs.values<0),  alpha=0.1, color=C_NEG)
    ax3.set_title(f"ROLLING {win}-TRADE SHARPE RATIO", color=TEXT,
                  fontsize=9, fontweight="bold", loc="left")
    ax3.legend(fontsize=6.5, framealpha=0.8)

    # ── Rolling win rate ──────────────────────────────────────────────────────
    ax4 = fig.add_subplot(gs[3, 1])
    _ax(ax4)
    outcomes = np.array([1 if t.outcome=="WIN" else 0 for t in trades], dtype=float)
    rwr = pd.Series(outcomes).rolling(win, min_periods=3).mean() * 100
    ax4.plot(xs, rwr.values, color=C_BLUE, lw=1.3)
    ax4.axhline(50,             color=BORDER,   lw=0.7, ls="--")
    ax4.axhline(outcomes.mean()*100, color=C_ORANGE, lw=0.9, ls=":",
                label=f"Overall {outcomes.mean()*100:.1f}%")
    ax4.fill_between(xs, rwr.values, 50, where=(rwr.values>=50), alpha=0.12, color=C_POS)
    ax4.fill_between(xs, rwr.values, 50, where=(rwr.values<50),  alpha=0.12, color=C_NEG)
    ax4.set_ylim(0, 105)
    ax4.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v,_: f"{v:.0f}%"))
    ax4.set_title(f"ROLLING {win}-TRADE WIN RATE", color=TEXT,
                  fontsize=9, fontweight="bold", loc="left")
    ax4.legend(fontsize=6.5, framealpha=0.8)

    # ── Top 5 drawdown periods table ──────────────────────────────────────────
    ax5 = fig.add_subplot(gs[4, :])
    ax5.axis("off")
    ax5.set_title("TOP DRAWDOWN PERIODS", color=TEXT, fontsize=9,
                  fontweight="bold", loc="left", pad=8)

    headers = ["  #", "  Peak Date", "  Trough Date", "  Recovery Date",
               "  Depth ($)", "  Duration", "  Recovery"]
    rows_data = []
    for i, dp in enumerate(s["dd_periods"], 1):
        rec_date = str(dp["end"]) if dp["end"] else "Ongoing"
        rec_days = str(dp["recovery"]) + " days" if dp["recovery"] else "Ongoing"
        rows_data.append([
            f"  {i}", f"  {dp['start']}", f"  {dp['trough']}",
            f"  {rec_date}", f"  ${dp['depth']:,.0f}",
            f"  {dp['dur']} days", f"  {rec_days}",
        ])
    if not rows_data:
        rows_data = [["—"] * 7]

    tbl = mpltable.table(ax5, cellText=rows_data, colLabels=headers,
                         loc="center", cellLoc="left")
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(7.5)
    for (r, c), cell in tbl.get_celld().items():
        cell.set_edgecolor(BORDER)
        cell.set_linewidth(0.5)
        if r == 0:
            cell.set_facecolor("#E8EAF6")
            cell.set_text_props(color=TEXT, fontweight="bold")
        elif r % 2 == 0:
            cell.set_facecolor("#F5F5F5")
        else:
            cell.set_facecolor(BG)
        if c == 4 and r > 0:   # depth column
            cell.set_text_props(color=C_NEG)
    tbl.scale(1, 1.6)

    _title_bar(fig, "STRATEGY PERFORMANCE TEARSHEET",
               f"{s['n']} trades  |  {s['n_days']} active days  |  Sharpe {s['sharpe']:.2f}  |  Calmar {s['calmar']:.2f}  |  Max DD ${s['max_dd']:,.0f}")
    _footer(fig)
    _save(fig, "01_equity_curve")


# ── 2. RETURNS ANALYSIS ───────────────────────────────────────────────────────
def chart_drawdown(trades):
    _font()
    s   = _compute(trades)
    fig = plt.figure(figsize=(17, 14), facecolor=BG)
    gs  = gridspec.GridSpec(2, 3, figure=fig, hspace=0.45, wspace=0.35,
                            left=0.08, right=0.96, top=0.93, bottom=0.06)

    # ── P&L distribution histogram ────────────────────────────────────────────
    ax1 = fig.add_subplot(gs[0, 0])
    _ax(ax1)
    from scipy import stats as sp
    n_bins = min(50, max(20, len(trades)//4))
    n_hist, bins, patches = ax1.hist(s["pnls"], bins=n_bins, edgecolor="white", lw=0.3)
    for patch, left in zip(patches, bins[:-1]):
        patch.set_facecolor(C_POS if left >= 0 else C_NEG)
        patch.set_alpha(0.75)
    # Normal fit
    mu, sigma = float(np.mean(s["pnls"])), float(np.std(s["pnls"]))
    xf = np.linspace(s["pnls"].min(), s["pnls"].max(), 300)
    yf = (n_hist.max()/(sigma*np.sqrt(2*np.pi))) * np.exp(-0.5*((xf-mu)/sigma)**2)
    ax1.plot(xf, yf, color=TEXT, lw=1.2, ls="--", label="Normal fit")
    ax1.axvline(mu, color=C_BLUE,   lw=1.1, label=f"Mean ${mu:+.1f}")
    ax1.axvline(s["var95"], color=C_NEG, lw=1.0, ls=":",
                label=f"VaR95 ${s['var95']:+.0f}")
    ax1.legend(fontsize=6, framealpha=0.8)
    ax1.set_xlabel("P&L ($)"); ax1.set_ylabel("Frequency")
    ax1.set_title("P&L DISTRIBUTION", color=TEXT, fontsize=9,
                  fontweight="bold", loc="left")
    ax1.text(0.97, 0.96, f"skew={s['skew']:+.2f}\nkurt={s['kurt']:+.2f}",
             transform=ax1.transAxes, ha="right", va="top",
             fontsize=7, color=SUBTEXT)

    # ── Q-Q plot ──────────────────────────────────────────────────────────────
    ax2 = fig.add_subplot(gs[0, 1])
    _ax(ax2)
    (osm, osr), (slope, intercept, _) = sp.probplot(s["pnls"], dist="norm")
    ax2.scatter(osm, osr, s=14, color=C_BLUE, alpha=0.7, zorder=3)
    xq = np.linspace(osm[0], osm[-1], 100)
    ax2.plot(xq, slope*xq+intercept, color=C_NEG, lw=1.2, ls="--", label="Normal line")
    ax2.set_xlabel("Theoretical Quantiles"); ax2.set_ylabel("Sample Quantiles")
    ax2.set_title("Q-Q NORMALITY TEST", color=TEXT, fontsize=9,
                  fontweight="bold", loc="left")
    ax2.legend(fontsize=6.5, framealpha=0.8)

    # ── Return quantiles (box plots) ──────────────────────────────────────────
    ax3 = fig.add_subplot(gs[0, 2])
    _ax(ax3)
    # Group by quartile of trade index
    n = len(s["pnls"])
    buckets = {"Q1": s["pnls"][:n//4], "Q2": s["pnls"][n//4:n//2],
               "Q3": s["pnls"][n//2:3*n//4], "Q4": s["pnls"][3*n//4:]}
    bp = ax3.boxplot(buckets.values(), labels=buckets.keys(),
                     patch_artist=True, notch=False,
                     medianprops=dict(color=TEXT, lw=1.5),
                     whiskerprops=dict(color=SUBTEXT, lw=0.8),
                     capprops=dict(color=SUBTEXT, lw=0.8),
                     flierprops=dict(marker=".", color=C_NEG, markersize=4, alpha=0.5))
    for patch, col in zip(bp["boxes"], [C_BLUE]*4):
        patch.set_facecolor(col); patch.set_alpha(0.25)
    ax3.axhline(0, color=BORDER, lw=0.8, ls="--")
    ax3.set_xlabel("Session quartile"); ax3.set_ylabel("P&L ($)")
    ax3.set_title("RETURN QUANTILES (by session quarter)",
                  color=TEXT, fontsize=9, fontweight="bold", loc="left")

    # ── Autocorrelation ───────────────────────────────────────────────────────
    ax4 = fig.add_subplot(gs[1, 0])
    _ax(ax4)
    nlags = min(20, len(s["pnls"])//4)
    acf   = [1.0] + [float(pd.Series(s["pnls"]).autocorr(lag=i)) for i in range(1,nlags+1)]
    ci    = 1.96 / np.sqrt(len(s["pnls"]))
    xs_ac = range(len(acf))
    colors_ac = [C_NEG if abs(a) > ci and i > 0 else C_BLUE for i,a in enumerate(acf)]
    ax4.bar(xs_ac, acf, color=colors_ac, alpha=0.7, width=0.8)
    ax4.axhline(ci,  color=C_NEG, lw=0.8, ls="--", alpha=0.7, label="95% CI")
    ax4.axhline(-ci, color=C_NEG, lw=0.8, ls="--", alpha=0.7)
    ax4.axhline(0,   color=BORDER, lw=0.5)
    ax4.set_xlabel("Lag (# trades)"); ax4.set_ylabel("ACF")
    ax4.set_title("RETURN AUTOCORRELATION", color=TEXT,
                  fontsize=9, fontweight="bold", loc="left")
    ax4.legend(fontsize=6.5, framealpha=0.8)

    # ── Monte Carlo ───────────────────────────────────────────────────────────
    ax5 = fig.add_subplot(gs[1, 1])
    _ax(ax5)
    np.random.seed(42)
    n_sim = 500; n_tr = min(len(s["pnls"]), 30)
    sims  = np.array([np.sum(np.random.choice(s["pnls"], n_tr, replace=True))
                      for _ in range(n_sim)])
    ax5.hist(sims, bins=40, color=C_BLUE, alpha=0.65, edgecolor="white", lw=0.3)
    ax5.axvline(np.median(sims), color=TEXT,  lw=1.2, label=f"Median ${np.median(sims):+,.0f}")
    ax5.axvline(np.percentile(sims,5), color=C_NEG, lw=1.0, ls="--",
                label=f"5th pct ${np.percentile(sims,5):+,.0f}")
    ax5.axvline(0, color=BORDER, lw=0.8, ls="--")
    prob = float((sims > 0).mean() * 100)
    ax5.legend(fontsize=6.5, framealpha=0.8)
    ax5.set_xlabel(f"P&L over {n_tr} trades ($)")
    ax5.set_title(f"HISTORICAL SIMULATION ({n_sim} paths, {n_tr} trades)",
                  color=TEXT, fontsize=9, fontweight="bold", loc="left")
    ax5.text(0.97,0.96, f"P(profit) = {prob:.0f}%",
             transform=ax5.transAxes, ha="right", va="top",
             fontsize=8, color=C_POS if prob>50 else C_NEG, fontweight="bold")

    # ── Sorted waterfall ──────────────────────────────────────────────────────
    ax6 = fig.add_subplot(gs[1, 2])
    _ax(ax6)
    sp_   = np.sort(s["pnls"])[::-1]
    cs_   = np.cumsum(sp_)
    bc    = [C_POS if p >= 0 else C_NEG for p in sp_]
    ax6.bar(range(len(sp_)), sp_, color=bc, alpha=0.7, width=1.0)
    ax6b  = ax6.twinx()
    ax6b.plot(range(len(cs_)), cs_, color=TEXT, lw=1.3, zorder=4)
    ax6b.set_ylabel("Cumulative ($)", color=SUBTEXT, fontsize=7)
    ax6b.tick_params(colors=SUBTEXT)
    for sp2 in ax6b.spines.values():
        sp2.set_edgecolor(BORDER); sp2.set_linewidth(0.5)
    ax6.set_xlabel("Trade rank (sorted by P&L)")
    ax6.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v,_: f"${v:+,.0f}"))
    ax6.set_title("TRADE WATERFALL (sorted, cumulative overlay)",
                  color=TEXT, fontsize=9, fontweight="bold", loc="left")

    _title_bar(fig, "RETURNS STATISTICAL ANALYSIS")
    _footer(fig)
    _save(fig, "02_drawdown")


# ── 3. MONTHLY + YEARLY RETURNS ───────────────────────────────────────────────
def chart_strategy_breakdown(trades):
    _font()
    s   = _compute(trades)
    fig = plt.figure(figsize=(17, 14), facecolor=BG)
    gs  = gridspec.GridSpec(2, 2, figure=fig, hspace=0.45, wspace=0.32,
                            left=0.08, right=0.96, top=0.93, bottom=0.06)

    # ── Monthly returns heatmap ───────────────────────────────────────────────
    ax1 = fig.add_subplot(gs[0, :])
    ax1.set_facecolor(PANEL)
    for sp in ax1.spines.values():
        sp.set_edgecolor(BORDER); sp.set_linewidth(0.5)

    # Build year × month matrix
    daily = defaultdict(float)
    for t in trades: daily[t.date] += t.pnl

    all_years  = sorted(set(d.year for d in daily))
    month_lbls = ["Jan","Feb","Mar","Apr","May","Jun",
                  "Jul","Aug","Sep","Oct","Nov","Dec"]
    matrix = pd.DataFrame(index=all_years, columns=range(1,13), dtype=float)
    for (d, p) in daily.items():
        matrix.loc[d.year, d.month] = matrix.loc[d.year, d.month] + p \
            if not pd.isna(matrix.loc[d.year, d.month]) else p

    # Add yearly total column
    matrix["Total"] = matrix.sum(axis=1, skipna=True)
    all_vals = matrix.values.flatten()
    all_vals = all_vals[~np.isnan(all_vals)]
    vmax = np.percentile(np.abs(all_vals[all_vals!=0]), 90) if len(all_vals) else 100

    norm = TwoSlopeNorm(vcenter=0, vmin=-vmax, vmax=vmax)
    col_lbls = month_lbls + ["TOTAL"]
    for c_i, col in enumerate(list(range(1,13)) + ["Total"]):
        for r_i, yr in enumerate(all_years):
            val = matrix.loc[yr, col]
            if pd.isna(val): color = "#F0F0F0"; txt = ""
            else:
                rgba = plt.get_cmap("RdYlGn")(norm(val))
                color = matplotlib.colors.to_hex(rgba)
                txt   = f"${val:+.0f}"
            rect = mpatches.FancyBboxPatch(
                (c_i-0.45, r_i-0.45), 0.9, 0.85,
                boxstyle="square,pad=0.01",
                facecolor=color, edgecolor="white", linewidth=0.8)
            ax1.add_patch(rect)
            ax1.text(c_i, r_i+0.02, txt, ha="center", va="center",
                     fontsize=7 if col != "Total" else 8,
                     fontweight="normal" if col != "Total" else "bold",
                     color="#1A1A1A" if abs(val) < vmax*0.6 else "white"
                     if not pd.isna(val) else TEXT)

    # Year labels
    for r_i, yr in enumerate(all_years):
        ax1.text(-0.75, r_i+0.02, str(yr), ha="right", va="center",
                 fontsize=8, fontweight="bold", color=TEXT)
    # Month labels
    for c_i, lbl in enumerate(col_lbls):
        ax1.text(c_i, len(all_years)+0.2, lbl, ha="center", va="bottom",
                 fontsize=7.5, fontweight="bold" if lbl == "TOTAL" else "normal",
                 color=TEXT)

    ax1.set_xlim(-1.2, len(col_lbls)-0.4)
    ax1.set_ylim(-0.7, len(all_years)+0.6)
    ax1.axis("off")
    ax1.set_title("MONTHLY P&L HEATMAP", color=TEXT, fontsize=10,
                  fontweight="bold", loc="left", pad=10)

    # Add colorbar
    sm = plt.cm.ScalarMappable(cmap="RdYlGn", norm=norm)
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=ax1, orientation="vertical",
                        fraction=0.02, pad=0.01, shrink=0.8)
    cbar.ax.tick_params(labelsize=6.5)
    cbar.set_label("P&L ($)", fontsize=7)

    # ── Yearly returns bar ────────────────────────────────────────────────────
    ax2 = fig.add_subplot(gs[1, 0])
    _ax(ax2)
    yr_totals = [(yr, float(matrix.loc[yr,"Total"])) for yr in all_years
                 if not pd.isna(matrix.loc[yr,"Total"])]
    if yr_totals:
        yrs, vals = zip(*yr_totals)
        cols = [C_POS if v >= 0 else C_NEG for v in vals]
        xs   = np.arange(len(yrs))
        bars = ax2.bar(xs, vals, color=cols, alpha=0.8, width=0.7, zorder=3)
        ax2.axhline(0, color=BORDER, lw=0.8)
        ax2.set_xticks(xs); ax2.set_xticklabels(yrs, fontsize=7)
        for bar, v in zip(bars, vals):
            off = 5 if v >= 0 else -15
            ax2.text(bar.get_x()+bar.get_width()/2, v+off,
                     f"${v:+,.0f}", ha="center", va="bottom" if v>=0 else "top",
                     fontsize=6.5, color=TEXT)
        _dollar_fmt(ax2)
    ax2.set_title("YEARLY TOTAL P&L", color=TEXT, fontsize=9,
                  fontweight="bold", loc="left")

    # ── Win rate by year ──────────────────────────────────────────────────────
    ax3 = fig.add_subplot(gs[1, 1])
    _ax(ax3)
    by_year = defaultdict(list)
    for t in trades: by_year[t.date.year].append(t)
    yr_wr = [(yr, len([t for t in by_year[yr] if t.outcome=="WIN"])/len(by_year[yr])*100)
             for yr in sorted(by_year.keys())]
    if yr_wr:
        yrs2, wrs2 = zip(*yr_wr)
        cols2 = [C_POS if w >= 70 else (C_ORANGE if w >= 55 else C_NEG) for w in wrs2]
        xs2   = np.arange(len(yrs2))
        ax3.bar(xs2, wrs2, color=cols2, alpha=0.8, width=0.7)
        ax3.axhline(50,                   color=BORDER, lw=0.8, ls="--")
        ax3.axhline(np.mean(wrs2), color=TEXT,   lw=1.0, ls=":",
                    label=f"Avg {np.mean(wrs2):.1f}%")
        ax3.set_xticks(xs2); ax3.set_xticklabels(yrs2, fontsize=7)
        ax3.set_ylim(0, 105)
        ax3.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v,_: f"{v:.0f}%"))
        ax3.legend(fontsize=7, framealpha=0.8)
        for x, w in zip(xs2, wrs2):
            ax3.text(x, w+1, f"{w:.0f}%", ha="center", va="bottom",
                     fontsize=6.5, color=TEXT)
    ax3.set_title("WIN RATE BY YEAR", color=TEXT, fontsize=9,
                  fontweight="bold", loc="left")

    _title_bar(fig, "MONTHLY & YEARLY RETURNS ANALYSIS")
    _footer(fig)
    _save(fig, "03_strategy_breakdown")


# ── 4. STRATEGY PERFORMANCE ──────────────────────────────────────────────────
def chart_pnl_distribution(trades):
    _font()
    fig = plt.figure(figsize=(17, 14), facecolor=BG)
    gs  = gridspec.GridSpec(2, 3, figure=fig, hspace=0.48, wspace=0.35,
                            left=0.08, right=0.96, top=0.93, bottom=0.06)

    order  = ["gap_fill","fvg","orb","ib_breakout","vwap_rev","vwap_pm",
              "vwap_bounce","vwap_bounce_pm","va_rule"]
    groups = defaultdict(list)
    for t in trades: groups[t.strategy].append(t)
    strats = [s for s in order if s in groups]
    labels = [s.replace("_"," ").title() for s in strats]
    colors = [STRAT_COLORS.get(s, C_BLUE) for s in strats]
    xs     = np.arange(len(strats))

    # ── Win rate bars ─────────────────────────────────────────────────────────
    ax1 = fig.add_subplot(gs[0, 0])
    _ax(ax1)
    wrs = [len([t for t in groups[s] if t.outcome=="WIN"])/len(groups[s])*100 for s in strats]
    cnt = [len(groups[s]) for s in strats]
    bars= ax1.barh(xs, wrs, color=[C_POS if w>=70 else (C_ORANGE if w>=55 else C_NEG)
                                   for w in wrs], alpha=0.8, height=0.6)
    ax1.axvline(50, color=BORDER, lw=0.8, ls="--")
    ax1.set_yticks(xs); ax1.set_yticklabels(labels, fontsize=7.5)
    ax1.set_xlim(0, 110)
    for bar, w, c in zip(bars, wrs, cnt):
        ax1.text(w+1, bar.get_y()+bar.get_height()/2,
                 f"{w:.0f}%  (n={c})", va="center", fontsize=6.5, color=TEXT)
    ax1.set_title("WIN RATE BY STRATEGY", color=TEXT, fontsize=9,
                  fontweight="bold", loc="left")

    # ── P&L bars ──────────────────────────────────────────────────────────────
    ax2 = fig.add_subplot(gs[0, 1])
    _ax(ax2)
    pnls_ = [sum(t.pnl for t in groups[s]) for s in strats]
    bc2   = [C_POS if p >= 0 else C_NEG for p in pnls_]
    bars2 = ax2.barh(xs, pnls_, color=bc2, alpha=0.8, height=0.6)
    ax2.axvline(0, color=BORDER, lw=0.8, ls="--")
    ax2.set_yticks(xs); ax2.set_yticklabels(labels, fontsize=7.5)
    ax2.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v,_: f"${v:+,.0f}"))
    for bar, p in zip(bars2, pnls_):
        off = 3 if p >= 0 else -3
        ax2.text(p+off, bar.get_y()+bar.get_height()/2,
                 f"${p:+,.0f}", va="center",
                 ha="left" if p>=0 else "right",
                 fontsize=6.5, color=TEXT)
    ax2.set_title("TOTAL P&L BY STRATEGY", color=TEXT, fontsize=9,
                  fontweight="bold", loc="left")

    # ── Avg R:R ───────────────────────────────────────────────────────────────
    ax3 = fig.add_subplot(gs[0, 2])
    _ax(ax3)
    rrs  = [np.mean([t.rr for t in groups[s]]) for s in strats]
    bars3= ax3.barh(xs, rrs, color=C_BLUE, alpha=0.7, height=0.6)
    ax3.axvline(1.0, color=BORDER, lw=0.8, ls="--")
    ax3.set_yticks(xs); ax3.set_yticklabels(labels, fontsize=7.5)
    for bar, r in zip(bars3, rrs):
        ax3.text(r+0.05, bar.get_y()+bar.get_height()/2,
                 f"{r:.2f}x", va="center", fontsize=6.5, color=TEXT)
    ax3.set_title("AVG RISK:REWARD BY STRATEGY", color=TEXT, fontsize=9,
                  fontweight="bold", loc="left")

    # ── Strategy equity curves ────────────────────────────────────────────────
    ax4 = fig.add_subplot(gs[1, :2])
    _ax(ax4)
    for i, (strat, color) in enumerate(zip(strats, STRAT_PALETTE)):
        tl  = sorted(groups[strat], key=lambda x: x.date)
        cum = np.cumsum([t.pnl for t in tl])
        ax4.plot(range(len(cum)), cum, color=color, lw=1.5,
                 label=strat.replace("_"," ").title())
    ax4.axhline(0, color=BORDER, lw=0.8, ls="--")
    _dollar_fmt(ax4)
    ax4.legend(fontsize=7, framealpha=0.8, ncol=3)
    ax4.set_title("CUMULATIVE P&L BY STRATEGY", color=TEXT, fontsize=9,
                  fontweight="bold", loc="left")

    # ── Day × strategy win rate table ─────────────────────────────────────────
    ax5 = fig.add_subplot(gs[1, 2])
    _ax(ax5, grid=False)
    days = ["Mon","Tue","Wed","Thu","Fri"]
    dsg  = defaultdict(lambda: defaultdict(list))
    for t in trades: dsg[t.day_name][t.strategy].append(t)

    cell_data = []
    for strat in strats:
        row = [strat.replace("_"," ").title()]
        for day in days:
            tl = dsg[day][strat]
            if tl:
                wr = len([t for t in tl if t.outcome=="WIN"])/len(tl)*100
                row.append(f"{wr:.0f}%\n(n={len(tl)})")
            else:
                row.append("—")
        cell_data.append(row)

    col_labels = ["Strategy"] + days
    tbl = mpltable.table(ax5, cellText=cell_data, colLabels=col_labels,
                         loc="center", cellLoc="center")
    tbl.auto_set_font_size(False); tbl.set_fontsize(7)
    for (r, c), cell in tbl.get_celld().items():
        cell.set_edgecolor(BORDER); cell.set_linewidth(0.5)
        if r == 0:
            cell.set_facecolor("#E8EAF6")
            cell.set_text_props(fontweight="bold", color=TEXT)
        elif c == 0:
            cell.set_facecolor("#F5F5F5")
        elif r % 2 == 0:
            cell.set_facecolor("#FAFAFA")
        else:
            cell.set_facecolor(BG)
    tbl.scale(1, 1.8)
    ax5.axis("off")
    ax5.set_title("WIN RATE BY DAY × STRATEGY", color=TEXT, fontsize=9,
                  fontweight="bold", loc="left", pad=8)

    _title_bar(fig, "STRATEGY PERFORMANCE ANALYSIS")
    _footer(fig)
    _save(fig, "04_pnl_distribution")


# ── 5. ROLLING METRICS TEARSHEET ─────────────────────────────────────────────
def chart_rolling_winrate(trades, window=15):
    _font()
    s   = _compute(trades)
    fig = plt.figure(figsize=(17, 16), facecolor=BG)
    gs  = gridspec.GridSpec(4, 1, figure=fig, hspace=0.42,
                            left=0.08, right=0.96, top=0.93, bottom=0.05)
    xs  = np.arange(len(trades))
    pnls= s["pnls"]
    win = min(window, max(5, len(trades)//6))

    outcomes = np.array([1 if t.outcome=="WIN" else 0 for t in trades], dtype=float)
    roll_wr  = pd.Series(outcomes).rolling(win, min_periods=3).mean() * 100
    roll_pnl = pd.Series(pnls).rolling(win, min_periods=3).mean()
    roll_sh  = (pd.Series(pnls).rolling(win, min_periods=5).mean() /
                pd.Series(pnls).rolling(win, min_periods=5).std() * np.sqrt(252*3)).fillna(0)

    def _rolling_pf(arr, w):
        def pf(x):
            pos = x[x > 0].sum(); neg = abs(x[x < 0].sum())
            return pos / neg if neg > 0 and pos > 0 else 1.0
        return pd.Series(arr).rolling(w, min_periods=5).apply(pf, raw=True).fillna(1.0)

    roll_pf = _rolling_pf(pnls, win)

    panels = [
        (roll_wr.values,  f"ROLLING {win}-TRADE WIN RATE (%)",    "%",       50,   [(outcomes.mean()*100, C_ORANGE, ":")]),
        (roll_pnl.values, f"ROLLING {win}-TRADE AVG P&L ($)",     "$",       0,    []),
        (roll_sh.values,  f"ROLLING {win}-TRADE SHARPE RATIO",    "ratio",   0,    [(1.0,C_POS,":"),(2.0,C_TEAL,":")]),
        (roll_pf.values,  f"ROLLING {win}-TRADE PROFIT FACTOR",   "ratio",   1.0,  []),
    ]

    for i, (data, title, unit, ref0, refs) in enumerate(panels):
        ax = fig.add_subplot(gs[i])
        _ax(ax)
        ax.plot(xs, data, color=C_BLUE, lw=1.4)
        ax.fill_between(xs, data, ref0, where=(data >= ref0), alpha=0.12, color=C_POS)
        ax.fill_between(xs, data, ref0, where=(data <  ref0), alpha=0.12, color=C_NEG)
        ax.axhline(ref0, color=BORDER, lw=0.8, ls="--")
        for val, col, ls in refs:
            ax.axhline(val, color=col, lw=0.8, ls=ls, alpha=0.8)
        if unit == "%":
            ax.set_ylim(0, 105)
            ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v,_: f"{v:.0f}%"))
        elif unit == "$":
            _dollar_fmt(ax)
        if i == 3:
            ax.set_xlabel("Trade # (chronological)")
        ax.set_title(title, color=TEXT, fontsize=9, fontweight="bold", loc="left")

    _title_bar(fig, "ROLLING PERFORMANCE METRICS",
               f"Window = {win} trades | 4-panel: Win Rate / Avg P&L / Sharpe / Profit Factor")
    _footer(fig)
    _save(fig, "05_rolling_winrate")


# ── 6. REGIME HEATMAPS ───────────────────────────────────────────────────────
def chart_heatmap(trades):
    _font()
    fig = plt.figure(figsize=(17, 11), facecolor=BG)
    gs  = gridspec.GridSpec(1, 2, figure=fig, wspace=0.35,
                            left=0.07, right=0.96, top=0.91, bottom=0.10)

    order_d = ["Mon","Tue","Wed","Thu","Fri"]
    order_s = ["gap_fill","fvg","orb","ib_breakout","vwap_rev",
               "vwap_pm","vwap_bounce","vwap_bounce_pm","va_rule"]
    present = [s for s in order_s if any(t.strategy==s for t in trades)]
    labels  = [s.replace("_"," ").title() for s in present]

    for ax_idx, (metric, title, cbar_label) in enumerate([
        ("wr",  "WIN RATE (%)  Day × Strategy",   "Win Rate (%)"),
        ("pnl", "TOTAL P&L ($)  Day × Strategy",  "P&L ($)"),
    ]):
        ax = fig.add_subplot(gs[ax_idx])
        ax.set_facecolor(PANEL)
        mat = pd.DataFrame(index=order_d, columns=present, dtype=float)
        for d in order_d:
            for s in present:
                sub = [t for t in trades if t.day_name == d and t.strategy == s]
                if not sub: mat.loc[d, s] = np.nan; continue
                mat.loc[d, s] = (len([t for t in sub if t.outcome=="WIN"])/len(sub)*100
                                 if metric == "wr" else sum(t.pnl for t in sub))

        import seaborn as sns
        kw = {"vmin": 0, "vmax": 100, "center": 50} if metric == "wr" \
             else {"center": 0}
        cmap = "RdYlGn" if metric == "wr" else "RdYlGn"
        sns.heatmap(mat.astype(float), ax=ax, cmap=cmap,
                    annot=True, fmt=".0f", linewidths=0.8, linecolor="white",
                    mask=mat.astype(float).isna(), **kw,
                    cbar_kws={"shrink": 0.7, "label": cbar_label},
                    annot_kws={"size": 8, "color": "black"})
        ax.set_xticklabels(labels, rotation=30, ha="right", color=TEXT, fontsize=8)
        ax.set_yticklabels(order_d, rotation=0, color=TEXT, fontsize=9)
        ax.set_title(title, color=TEXT, fontsize=9,
                     fontweight="bold", pad=10)

    _title_bar(fig, "DAY × STRATEGY PERFORMANCE MATRIX")
    _footer(fig)
    _save(fig, "06_winrate_heatmap")


# ── 7. RISK ANALYSIS ─────────────────────────────────────────────────────────
def chart_vix_scatter(trades):
    _font()
    s   = _compute(trades)
    fig = plt.figure(figsize=(17, 12), facecolor=BG)
    gs  = gridspec.GridSpec(2, 2, figure=fig, hspace=0.45, wspace=0.35,
                            left=0.08, right=0.96, top=0.93, bottom=0.07)
    pnls= s["pnls"]
    xs  = np.arange(len(pnls))

    # ── VaR / CVaR rolling ───────────────────────────────────────────────────
    ax1 = fig.add_subplot(gs[0, 0])
    _ax(ax1)
    win = min(20, len(pnls)//4)
    r_var  = pd.Series(pnls).rolling(win, min_periods=5).quantile(0.05).fillna(0)
    r_cvar = pd.Series(pnls).rolling(win, min_periods=5).apply(
        lambda x: np.mean(x[x <= np.percentile(x,5)]), raw=True).fillna(0)
    ax1.plot(xs, r_var,  color=C_NEG,    lw=1.3, label=f"Rolling VaR(95%)")
    ax1.plot(xs, r_cvar, color=C_ORANGE, lw=1.3, label=f"Rolling CVaR(95%)")
    ax1.axhline(0, color=BORDER, lw=0.8, ls="--")
    _dollar_fmt(ax1)
    ax1.legend(fontsize=7, framealpha=0.8)
    ax1.set_title(f"ROLLING {win}-TRADE VaR / CVaR", color=TEXT,
                  fontsize=9, fontweight="bold", loc="left")

    # ── VIX regime scatter ────────────────────────────────────────────────────
    ax2 = fig.add_subplot(gs[0, 1])
    _ax(ax2)
    vixes= np.array([t.vix for t in trades])
    cols = [C_POS if t.outcome=="WIN" else C_NEG for t in trades]
    ax2.scatter(vixes, pnls, c=cols, s=20, alpha=0.6, zorder=3)
    ax2.axhline(0,  color=BORDER, lw=0.8, ls="--")
    ax2.axvline(20, color=SUBTEXT, lw=0.7, ls=":", alpha=0.7, label="VIX 20")
    ax2.axvline(30, color=C_NEG,   lw=0.7, ls=":", alpha=0.7, label="VIX 30")
    m, b = np.polyfit(vixes, pnls, 1)
    xr   = np.linspace(vixes.min(), vixes.max(), 100)
    ax2.plot(xr, m*xr+b, color=TEXT, lw=1.2, ls="--", alpha=0.6, label="Trend")
    ax2.legend(fontsize=7, framealpha=0.8)
    _dollar_fmt(ax2)
    ax2.set_xlabel("VIX")
    ax2.set_title("VIX REGIME vs TRADE P&L", color=TEXT, fontsize=9,
                  fontweight="bold", loc="left")
    ax2.text(0.97, 0.05, f"slope ${m:+.2f}/VIX pt",
             transform=ax2.transAxes, ha="right", fontsize=7, color=SUBTEXT)

    # ── Confidence score vs P&L ───────────────────────────────────────────────
    ax3 = fig.add_subplot(gs[1, 0])
    _ax(ax3)
    scores = [getattr(t, "score", 10) for t in trades]
    cols3  = [C_POS if t.outcome=="WIN" else C_NEG for t in trades]
    ax3.scatter(scores, pnls, c=cols3, s=20, alpha=0.6, zorder=3)
    if len(scores) > 3:
        m2, b2 = np.polyfit(scores, pnls, 1)
        xs3 = np.linspace(min(scores), max(scores), 60)
        ax3.plot(xs3, m2*xs3+b2, color=TEXT, lw=1.2, ls="--", alpha=0.6)
        ax3.text(0.97, 0.05, f"slope ${m2:+.1f}/point",
                 transform=ax3.transAxes, ha="right", fontsize=7, color=SUBTEXT)
    ax3.axhline(0, color=BORDER, lw=0.8, ls="--")
    _dollar_fmt(ax3)
    ax3.set_xlabel("Confidence Score")
    ax3.set_title("SCORE vs P&L  (edge per score point)",
                  color=TEXT, fontsize=9, fontweight="bold", loc="left")

    # ── Score distribution ────────────────────────────────────────────────────
    ax4 = fig.add_subplot(gs[1, 1])
    _ax(ax4)
    sg = defaultdict(list)
    for t in trades: sg[getattr(t,"score",10)].append(t)
    sc_list = sorted(sg.keys())
    wrs4  = [len([t for t in sg[sc] if t.outcome=="WIN"])/len(sg[sc])*100 for sc in sc_list]
    pnls4 = [sum(t.pnl for t in sg[sc]) for sc in sc_list]
    ax4b  = ax4.twinx()
    ax4.bar(range(len(sc_list)), pnls4,
            color=[C_POS if p>=0 else C_NEG for p in pnls4], alpha=0.6, width=0.7)
    ax4b.plot(range(len(sc_list)), wrs4, color=C_BLUE, lw=1.5,
              marker="o", markersize=4, label="Win Rate %")
    ax4b.axhline(50, color=BORDER, lw=0.7, ls="--")
    ax4b.set_ylim(0, 110)
    ax4b.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v,_: f"{v:.0f}%"))
    ax4b.tick_params(colors=SUBTEXT)
    for sp2 in ax4b.spines.values():
        sp2.set_edgecolor(BORDER); sp2.set_linewidth(0.5)
    ax4.set_xticks(range(len(sc_list)))
    ax4.set_xticklabels([str(s) for s in sc_list], fontsize=7)
    ax4.set_xlabel("Confidence Score")
    _dollar_fmt(ax4)
    ax4b.legend(fontsize=7, framealpha=0.8)
    ax4.set_title("SCORE BUCKET ANALYSIS  (bars=P&L, line=WR)",
                  color=TEXT, fontsize=9, fontweight="bold", loc="left")

    _title_bar(fig, "RISK ANALYSIS")
    _footer(fig)
    _save(fig, "07_vix_scatter")


# ── 8. FACTOR HIT RATES + HARD BLOCKS ────────────────────────────────────────
def chart_rr_distribution(trades):
    _font()
    fig = plt.figure(figsize=(17, 11), facecolor=BG)
    gs  = gridspec.GridSpec(1, 2, figure=fig, wspace=0.35,
                            left=0.08, right=0.96, top=0.91, bottom=0.12)

    # ── Factor hit rates ──────────────────────────────────────────────────────
    ax1 = fig.add_subplot(gs[0])
    _ax(ax1)
    factors: dict = defaultdict(list)
    for t in trades:
        for k, v in getattr(t, "score_breakdown", {}).items():
            factors[k].append(v)

    if factors:
        fo   = sorted(factors.keys())
        hits = [np.mean(factors[f]) * 100 for f in fo]
        cols = [C_POS if h >= 80 else (C_ORANGE if h >= 60 else C_NEG) for h in hits]
        ys   = np.arange(len(fo))
        bars = ax1.barh(ys, hits, color=cols, alpha=0.8, height=0.65)
        ax1.axvline(50, color=BORDER, lw=0.8, ls="--")
        ax1.axvline(80, color=SUBTEXT, lw=0.6, ls=":", alpha=0.6)
        ax1.set_yticks(ys)
        ax1.set_yticklabels(fo, fontsize=8)
        ax1.set_xlim(0, 110)
        for bar, h in zip(bars, hits):
            ax1.text(h+1.5, bar.get_y()+bar.get_height()/2,
                     f"{h:.0f}%", va="center", fontsize=7.5, color=TEXT)
        ax1.set_xlabel("Hit Rate (%)")
        ax1.set_title("20-POINT SCORING — FACTOR HIT RATES",
                      color=TEXT, fontsize=9, fontweight="bold", loc="left")
    else:
        ax1.text(0.5, 0.5, "Score breakdown\nnot available",
                 ha="center", va="center", color=SUBTEXT, fontsize=10,
                 transform=ax1.transAxes)

    # ── R:R distribution by outcome ───────────────────────────────────────────
    ax2 = fig.add_subplot(gs[1])
    _ax(ax2)
    rr_all = np.array([t.rr for t in trades])
    rr_w   = np.array([t.rr for t in trades if t.outcome == "WIN"])
    rr_l   = np.array([t.rr for t in trades if t.outcome == "LOSS"])
    bins   = np.linspace(0, min(rr_all.max(), 30), 35)
    ax2.hist(rr_w, bins=bins, color=C_POS, alpha=0.75,
             label=f"Wins (n={len(rr_w)})", zorder=3)
    ax2.hist(rr_l, bins=bins, color=C_NEG, alpha=0.65,
             label=f"Losses (n={len(rr_l)})", zorder=2)
    ax2.axvline(1.0, color=SUBTEXT, lw=1.0, ls="--", label="1:1 R:R")
    ax2.axvline(rr_all.mean(), color=C_BLUE, lw=1.3,
                label=f"Mean {rr_all.mean():.2f}x")
    ax2.set_xlabel("Risk:Reward Ratio"); ax2.set_ylabel("Frequency")
    ax2.legend(fontsize=7.5, framealpha=0.8)
    ax2.set_title("RISK:REWARD DISTRIBUTION — WINS vs LOSSES",
                  color=TEXT, fontsize=9, fontweight="bold", loc="left")
    rr_txt = (f"Mean R:R    {rr_all.mean():.2f}x\n"
              f"Median R:R  {np.median(rr_all):.2f}x\n"
              f"90th pct    {np.percentile(rr_all,90):.2f}x")
    ax2.text(0.97, 0.97, rr_txt, transform=ax2.transAxes,
             va="top", ha="right", fontsize=8, color=TEXT,
             bbox=dict(facecolor=PANEL, edgecolor=BORDER, alpha=0.9,
                       boxstyle="round,pad=0.4"))

    _title_bar(fig, "FACTOR ANALYSIS + RISK:REWARD DECOMPOSITION")
    _footer(fig)
    _save(fig, "08_rr_distribution")


# ── 9. CALENDAR HEATMAP ───────────────────────────────────────────────────────
def chart_monthly_calendar(trades):
    _font()
    daily = defaultdict(float)
    for t in trades: daily[t.date] += t.pnl
    if not daily: return

    dates  = sorted(daily.keys())
    months = sorted(set((d.year, d.month) for d in dates))
    n_mo   = len(months)
    cols_  = min(n_mo, 4)
    rows_  = (n_mo + cols_ - 1) // cols_

    fig, axes = plt.subplots(rows_, cols_,
                             figsize=(cols_ * 5.5, rows_ * 4.2), facecolor=BG)
    if n_mo == 1: axes = [[axes]]
    elif rows_ == 1: axes = [axes]
    flat = [ax for row in axes for ax in (row if hasattr(row,"__iter__") else [row])]

    mo_names = ["","Jan","Feb","Mar","Apr","May","Jun",
                "Jul","Aug","Sep","Oct","Nov","Dec"]
    day_lbl  = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
    max_abs  = max(abs(v) for v in daily.values()) or 1.0
    norm     = TwoSlopeNorm(vcenter=0, vmin=-max_abs, vmax=max_abs)

    for idx, (yr, mo) in enumerate(months):
        ax = flat[idx]
        ax.set_facecolor(BG)
        for sp in ax.spines.values():
            sp.set_edgecolor(BORDER); sp.set_linewidth(0.5)
        ax.set_xticks(range(7))
        ax.set_xticklabels(day_lbl, fontsize=6, color=SUBTEXT)
        ax.set_yticks([])
        mo_pnl = sum(v for d, v in daily.items() if d.year==yr and d.month==mo)
        tcol   = C_POS if mo_pnl >= 0 else C_NEG
        ax.set_title(f"{mo_names[mo]} {yr}  ${mo_pnl:+.0f}",
                     color=tcol, fontsize=8.5, fontweight="bold", pad=3)

        calendar_weeks = cal_mod.monthcalendar(yr, mo)
        for wk, week in enumerate(calendar_weeks):
            for dw, day in enumerate(week):
                if day == 0: continue
                d = date(yr, mo, day); pnl = daily.get(d, None)
                if pnl is not None:
                    rgba  = plt.get_cmap("RdYlGn")(norm(pnl))
                    color = matplotlib.colors.to_hex(rgba)
                    rect  = mpatches.FancyBboxPatch(
                        (dw-0.44, -wk-0.44), 0.88, 0.82,
                        boxstyle="round,pad=0.03",
                        facecolor=color, edgecolor="white",
                        linewidth=0.5, zorder=2)
                    ax.add_patch(rect)
                    txt_col = "#1A1A1A" if abs(pnl) < max_abs*0.5 else "white"
                    ax.text(dw, -wk+0.15, str(day), ha="center", va="center",
                            color=txt_col, fontsize=7, fontweight="bold", zorder=3)
                    ax.text(dw, -wk-0.22, f"${pnl:+.0f}", ha="center", va="center",
                            color=txt_col, fontsize=5.5, zorder=3)
                else:
                    ax.text(dw, -wk, str(day), ha="center", va="center",
                            color=DIM, fontsize=7)
        ax.set_xlim(-0.6, 6.6)
        ax.set_ylim(-len(calendar_weeks)+0.3, 0.9)

    for ax in flat[n_mo:]: ax.set_visible(False)

    total = sum(daily.values())
    fig.suptitle(f"DAILY P&L CALENDAR  |  Total ${total:+,.2f}",
                 color=TEXT, fontsize=11, fontweight="bold", y=1.01)
    fig.tight_layout()
    _footer(fig)
    _save(fig, "09_monthly_calendar")


# ── 10. STRATEGY EQUITY CURVES ───────────────────────────────────────────────
def chart_strategy_equity_curves(trades):
    _font()
    fig = plt.figure(figsize=(17, 14), facecolor=BG)
    gs  = gridspec.GridSpec(2, 2, figure=fig, hspace=0.42, wspace=0.32,
                            left=0.08, right=0.96, top=0.93, bottom=0.07)

    order  = ["gap_fill","fvg","orb","ib_breakout","vwap_rev",
              "vwap_pm","vwap_bounce","vwap_bounce_pm","va_rule"]
    groups = defaultdict(list)
    for t in trades: groups[t.strategy].append(t)
    present= [s for s in order if s in groups]

    # ── Strategy equity curves ────────────────────────────────────────────────
    ax1 = fig.add_subplot(gs[0, :])
    _ax(ax1)
    for i, strat in enumerate(present):
        tl  = sorted(groups[strat], key=lambda x: x.date)
        cum = np.cumsum([t.pnl for t in tl])
        col = STRAT_PALETTE[i % len(STRAT_PALETTE)]
        ax1.plot(range(len(cum)), cum, color=col, lw=1.6,
                 label=f"{strat.replace('_',' ').title()} ${cum[-1]:+,.0f}")
    ax1.axhline(0, color=BORDER, lw=0.8, ls="--")
    _dollar_fmt(ax1)
    ax1.legend(fontsize=7, framealpha=0.8, ncol=3)
    ax1.set_title("CUMULATIVE P&L BY STRATEGY",
                  color=TEXT, fontsize=9, fontweight="bold", loc="left")

    # ── P&L contribution bar ──────────────────────────────────────────────────
    ax2 = fig.add_subplot(gs[1, 0])
    _ax(ax2)
    pnls_ = [sum(t.pnl for t in groups[s]) for s in present]
    total = sum(pnls_) or 1
    xs2   = np.arange(len(present))
    bars  = ax2.bar(xs2, pnls_,
                    color=[C_POS if p>=0 else C_NEG for p in pnls_],
                    alpha=0.8, width=0.7)
    ax2.axhline(0, color=BORDER, lw=0.8)
    ax2.set_xticks(xs2)
    ax2.set_xticklabels([s.replace("_","\n").title() for s in present],
                        fontsize=6.5)
    _dollar_fmt(ax2)
    for bar, p in zip(bars, pnls_):
        off = 3 if p >= 0 else -3
        ax2.text(bar.get_x()+bar.get_width()/2, p+off,
                 f"{p/total*100:.0f}%", ha="center",
                 va="bottom" if p>=0 else "top",
                 fontsize=7, color=TEXT)
    ax2.set_title("P&L CONTRIBUTION (% of total)",
                  color=TEXT, fontsize=9, fontweight="bold", loc="left")

    # ── Per-strategy drawdown ─────────────────────────────────────────────────
    ax3 = fig.add_subplot(gs[1, 1])
    _ax(ax3)
    for i, strat in enumerate(present[:6]):
        tl  = sorted(groups[strat], key=lambda x: x.date)
        cum = np.cumsum([t.pnl for t in tl])
        pk  = np.maximum.accumulate(cum)
        dd  = cum - pk
        col = STRAT_PALETTE[i % len(STRAT_PALETTE)]
        ax3.plot(range(len(dd)), dd, color=col, lw=1.2,
                 label=strat.replace("_"," ").title())
    ax3.axhline(0, color=BORDER, lw=0.8, ls="--")
    _dollar_fmt(ax3)
    ax3.legend(fontsize=7, framealpha=0.8)
    ax3.set_title("PER-STRATEGY DRAWDOWN",
                  color=TEXT, fontsize=9, fontweight="bold", loc="left")

    _title_bar(fig, "STRATEGY EQUITY CURVES + ATTRIBUTION")
    _footer(fig)
    _save(fig, "10_strategy_equity_curves")


# ── Entry point ───────────────────────────────────────────────────────────────
def generate_all_charts(trades) -> None:
    print(f"\nGenerating institutional tearsheet ({len(trades)} trades) -> {OUT_DIR}/")
    for name, fn in [
        ("01 Performance Tearsheet",   chart_equity_curve),
        ("02 Returns Analysis",        chart_drawdown),
        ("03 Monthly/Yearly Returns",  chart_strategy_breakdown),
        ("04 Strategy Performance",    chart_pnl_distribution),
        ("05 Rolling Metrics",         chart_rolling_winrate),
        ("06 Regime Heatmaps",         chart_heatmap),
        ("07 Risk Analysis",           chart_vix_scatter),
        ("08 Factor Analysis",         chart_rr_distribution),
        ("09 Calendar",                chart_monthly_calendar),
        ("10 Strategy Curves",         chart_strategy_equity_curves),
    ]:
        try:
            fn(trades)
        except Exception as e:
            print(f"  [warn] {name}: {e}")
    print(f"Done — 10 charts saved to ./{OUT_DIR}/\n")
