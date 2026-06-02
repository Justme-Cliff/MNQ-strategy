"""
Quantitative backtest visualizations — professional dark-theme research output.
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
import matplotlib.gridspec as gridspec
from matplotlib.colors import LinearSegmentedColormap
from mpl_toolkits.mplot3d import Axes3D
import seaborn as sns
import warnings
warnings.filterwarnings("ignore")

OUT_DIR = "backtest_charts"

# ── Color palette ─────────────────────────────────────────────────────────────
BG      = "#05060f"       # near-black background
PANEL   = "#0b0d1a"       # dark panel
PANEL2  = "#0f1120"       # slightly lighter panel
GRID    = "#161929"       # subtle grid
BORDER  = "#1e2235"       # border color

CYAN    = "#00d4ff"       # electric cyan (primary)
MAGENTA = "#ff006e"       # hot pink (secondary)
GREEN   = "#00ff88"       # neon green
RED     = "#ff3366"       # hot red
YELLOW  = "#ffcc00"       # electric yellow
PURPLE  = "#bf5fff"       # electric purple
ORANGE  = "#ff8c00"       # orange
TEAL    = "#00b4d8"       # teal

WHITE   = "#e8f0fe"       # near white
TEXT    = "#c9d1d9"       # main text
SUBTEXT = "#5a6484"       # dim text
DIM     = "#2d3153"       # very dim

STRAT_COLORS = {
    "gap_fill":       CYAN,
    "fvg":            PURPLE,
    "orb":            YELLOW,
    "ib_breakout":    ORANGE,
    "vwap_rev":       GREEN,
    "vwap_pm":        "#00e5a0",
    "vwap_bounce":    MAGENTA,
    "vwap_bounce_pm": "#ff66aa",
    "va_rule":        "#a78bfa",
}

STRAT_LABELS = {
    "gap_fill":       "Gap Fill",
    "fvg":            "FVG",
    "orb":            "ORB",
    "ib_breakout":    "IB Breakout",
    "vwap_rev":       "VWAP Rev",
    "vwap_pm":        "VWAP Rev PM",
    "vwap_bounce":    "VWAP Bounce",
    "vwap_bounce_pm": "VWAP Bounce PM",
    "va_rule":        "VA Rule (80%)",
}

# Custom thermal colormap (cool=red → warm=cyan like the IG post)
_THERMAL = LinearSegmentedColormap.from_list(
    "thermal",
    ["#ff0040", "#ff6600", "#ffcc00", "#00ff88", "#00d4ff", "#bf5fff"],
    N=256,
)

_REDGREEN = LinearSegmentedColormap.from_list(
    "rg", ["#ff0040", "#1a1a2e", "#00ff88"], N=256
)


def _font():
    plt.rcParams.update({
        "font.family":      "monospace",
        "font.size":        8,
        "axes.titlesize":   11,
        "axes.labelsize":   8,
        "xtick.labelsize":  7,
        "ytick.labelsize":  7,
        "legend.fontsize":  7,
        "figure.dpi":       150,
    })


def _base_ax(ax, grid=True):
    ax.set_facecolor(PANEL)
    ax.tick_params(colors=SUBTEXT, length=2, width=0.5)
    ax.xaxis.label.set_color(SUBTEXT)
    ax.yaxis.label.set_color(SUBTEXT)
    for spine in ax.spines.values():
        spine.set_edgecolor(BORDER)
        spine.set_linewidth(0.6)
    if grid:
        ax.grid(color=GRID, linewidth=0.4, alpha=1.0, zorder=0)
        ax.set_axisbelow(True)


def _fig(w=16, h=8, subplots=(1, 1), **kw):
    _font()
    fig, axes = plt.subplots(*subplots, figsize=(w, h), facecolor=BG, **kw)
    if subplots == (1, 1):
        _base_ax(axes)
        return fig, axes
    flat = np.array(axes).flatten()
    for ax in flat:
        _base_ax(ax)
    return fig, axes


def _save(fig, name):
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, f"{name}.png")
    fig.savefig(path, dpi=150, bbox_inches="tight",
                facecolor=BG, edgecolor="none")
    plt.close(fig)
    print(f"  saved → {path}")


def _glow(ax, x, y, color, lw=1.5, alpha_base=0.9, n_layers=4):
    """Plot a line with a neon glow effect (multiple alpha passes)."""
    widths = [lw * (n_layers - i) * 1.5 for i in range(n_layers)]
    alphas = [0.03, 0.06, 0.12, alpha_base]
    for w, a in zip(widths, alphas):
        ax.plot(x, y, color=color, linewidth=w, alpha=a, zorder=3 + alphas.index(a))


def _watermark(fig, text="TJR-NQ HYBRID SYSTEM v7"):
    fig.text(0.99, 0.01, text, ha="right", va="bottom",
             color=DIM, fontsize=6, fontfamily="monospace")


def _header(fig, title, subtitle=""):
    fig.text(0.5, 0.99, title, ha="center", va="top",
             color=WHITE, fontsize=13, fontweight="bold", fontfamily="monospace")
    if subtitle:
        fig.text(0.5, 0.965, subtitle, ha="center", va="top",
                 color=SUBTEXT, fontsize=8, fontfamily="monospace")


def _quant_stats(trades):
    """Compute quant metrics."""
    pnls   = np.array([t.pnl for t in trades])
    wins   = pnls[pnls > 0]
    losses = pnls[pnls < 0]
    cum    = np.cumsum(pnls)
    peak   = np.maximum.accumulate(cum)
    dd     = cum - peak

    wr = len(wins) / len(pnls) * 100 if len(pnls) else 0
    avg_w = float(np.mean(wins)) if len(wins) else 0
    avg_l = float(np.mean(losses)) if len(losses) else 0
    pf = abs(avg_w * len(wins) / (avg_l * len(losses))) if losses.any() else 99.0

    # Sharpe (per-trade, annualized assuming 3 trades/day, 252 days)
    ann = 252 * 3
    sharpe = float(np.mean(pnls) / np.std(pnls) * np.sqrt(ann)) if np.std(pnls) > 0 else 0
    sortino_neg = pnls[pnls < 0]
    sortino = float(np.mean(pnls) / np.std(sortino_neg) * np.sqrt(ann)) if len(sortino_neg) > 0 else 0
    calmar = float(cum[-1] / abs(dd.min())) if abs(dd.min()) > 0 else 0

    return {
        "pnls": pnls, "cum": cum, "peak": peak, "dd": dd,
        "wr": wr, "avg_win": avg_w, "avg_loss": avg_l, "pf": pf,
        "sharpe": sharpe, "sortino": sortino, "calmar": calmar,
        "total": float(cum[-1]) if len(cum) else 0,
        "max_dd": float(dd.min()),
    }


# ── 1. MASTER DASHBOARD ──────────────────────────────────────────────────────
def chart_equity_curve(trades):
    _font()
    fig = plt.figure(figsize=(18, 10), facecolor=BG)
    gs  = gridspec.GridSpec(2, 3, figure=fig, hspace=0.38, wspace=0.35,
                            left=0.06, right=0.97, top=0.90, bottom=0.08)

    s = _quant_stats(trades)
    pnls, cum, dd = s["pnls"], s["cum"], s["dd"]
    xs = np.arange(len(cum))

    # --- Panel A: Equity curve ---
    ax1 = fig.add_subplot(gs[0, :2])
    _base_ax(ax1)
    ax1.fill_between(xs, cum, 0, where=(cum >= 0), alpha=0.08, color=GREEN, zorder=1)
    ax1.fill_between(xs, cum, 0, where=(cum <  0), alpha=0.08, color=RED,   zorder=1)
    _glow(ax1, xs, cum, CYAN, lw=1.8)
    ax1.axhline(0, color=BORDER, lw=0.8, ls="--")

    # Color dots by outcome
    for i, t in enumerate(trades):
        c = GREEN if t.outcome == "WIN" else RED
        ax1.scatter(i, cum[i], color=c, s=14, zorder=6, alpha=0.9, linewidths=0)

    # Annotate peak
    peak_i = int(np.argmax(cum))
    ax1.annotate(f"${cum[peak_i]:+,.0f}", xy=(peak_i, cum[peak_i]),
                 xytext=(peak_i + 1, cum[peak_i] + 30),
                 color=YELLOW, fontsize=7, fontfamily="monospace",
                 arrowprops=dict(arrowstyle="->", color=YELLOW, lw=0.8))

    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"${v:+,.0f}"))
    ax1.set_title("CUMULATIVE P&L", color=TEXT, fontsize=9,
                  fontweight="bold", loc="left", pad=6)
    ax1.tick_params(colors=SUBTEXT)

    # Stat box
    stats_txt = (
        f"TOTAL    ${s['total']:+,.2f}\n"
        f"WIN RATE  {s['wr']:.1f}%\n"
        f"SHARPE   {s['sharpe']:.2f}\n"
        f"CALMAR   {s['calmar']:.2f}\n"
        f"MAX DD   ${s['max_dd']:,.0f}"
    )
    ax1.text(0.01, 0.97, stats_txt, transform=ax1.transAxes,
             va="top", ha="left", color=CYAN, fontsize=7.5,
             fontfamily="monospace",
             bbox=dict(facecolor=PANEL2, edgecolor=BORDER, alpha=0.9,
                       boxstyle="round,pad=0.4", linewidth=0.6))

    # --- Panel B: Drawdown ---
    ax2 = fig.add_subplot(gs[1, :2])
    _base_ax(ax2)
    ax2.fill_between(xs, dd, 0, color=RED, alpha=0.4, zorder=1)
    _glow(ax2, xs, dd, MAGENTA, lw=1.2)
    ax2.axhline(0, color=BORDER, lw=0.6, ls="--")
    ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"${v:,.0f}"))
    ax2.set_title("DRAWDOWN  (underwater)", color=TEXT, fontsize=9,
                  fontweight="bold", loc="left", pad=6)
    # Recovery lines
    in_dd = False
    dd_start = 0
    for i in range(len(dd)):
        if dd[i] < 0 and not in_dd:
            in_dd, dd_start = True, i
        elif dd[i] == 0 and in_dd:
            in_dd = False
            ax2.axvspan(dd_start, i, color=RED, alpha=0.03, zorder=0)

    # --- Panel C: Metrics cards ---
    ax3 = fig.add_subplot(gs[:, 2])
    _base_ax(ax3, grid=False)
    ax3.set_xlim(0, 1); ax3.set_ylim(0, 1)
    ax3.axis("off")
    ax3.set_title("SYSTEM METRICS", color=TEXT, fontsize=9,
                  fontweight="bold", loc="left", pad=6)

    metrics = [
        ("TOTAL P&L",       f"${s['total']:+,.2f}",   CYAN),
        ("WIN RATE",         f"{s['wr']:.1f}%",        GREEN if s['wr'] >= 70 else YELLOW),
        ("TOTAL TRADES",     f"{len(trades)}",          WHITE),
        ("AVG WIN",          f"${s['avg_win']:+.2f}",  GREEN),
        ("AVG LOSS",         f"${s['avg_loss']:+.2f}", RED),
        ("PROFIT FACTOR",    f"{s['pf']:.2f}",         YELLOW),
        ("SHARPE RATIO",     f"{s['sharpe']:.3f}",     CYAN),
        ("SORTINO RATIO",    f"{s['sortino']:.3f}",    PURPLE),
        ("CALMAR RATIO",     f"{s['calmar']:.3f}",     TEAL),
        ("MAX DRAWDOWN",     f"${s['max_dd']:,.2f}",   RED),
        ("AVG R:R",
         f"{np.mean([t.rr for t in trades]):.2f}x",  ORANGE),
        ("ACTIVE DAYS",
         f"{len(set(t.date for t in trades))}",       WHITE),
    ]
    n = len(metrics)
    for i, (label, val, color) in enumerate(metrics):
        y = 0.94 - i * (0.87 / n)
        # background strip
        rect = mpatches.FancyBboxPatch(
            (0.02, y - 0.025), 0.96, 0.056,
            boxstyle="round,pad=0.01",
            facecolor=PANEL2, edgecolor=BORDER,
            linewidth=0.4, zorder=1,
        )
        ax3.add_patch(rect)
        ax3.text(0.06, y + 0.008, label, color=SUBTEXT, fontsize=7,
                 fontfamily="monospace", va="center")
        ax3.text(0.94, y + 0.008, val, color=color, fontsize=8.5,
                 fontfamily="monospace", va="center", ha="right",
                 fontweight="bold")

    _header(fig, "NQ HYBRID SYSTEM — MASTER DASHBOARD",
            f"Strategy: v7  |  {len(trades)} trades  |  {len(set(t.date for t in trades))} active days")
    _watermark(fig)
    _save(fig, "01_equity_curve")


# ── 2. ALPHA GENERATION SURFACE (3D) ─────────────────────────────────────────
def chart_drawdown(trades):
    """Alpha Generation Surface: Win Rate across VIX × Score bins."""
    _font()
    fig = plt.figure(figsize=(18, 9), facecolor=BG)

    # Left: 3D surface
    ax3d = fig.add_subplot(121, projection="3d")
    ax3d.set_facecolor(BG)
    ax3d.patch.set_facecolor(BG)

    # Build VIX × Score grid
    vix_bins   = [0, 15, 20, 25, 30, 40, 60]
    score_bins = [5, 7, 9, 11, 13, 15, 17, 19, 21]

    def _bucket(v, bins):
        for i in range(len(bins) - 1):
            if bins[i] <= v < bins[i + 1]:
                return i
        return len(bins) - 2

    grid_wr  = np.zeros((len(vix_bins)-1, len(score_bins)-1))
    grid_cnt = np.zeros_like(grid_wr, dtype=int)

    for t in trades:
        sc = getattr(t, "score", 10)
        vi = _bucket(t.vix, vix_bins)
        si = _bucket(sc, score_bins)
        grid_cnt[vi, si] += 1
        if t.outcome == "WIN":
            grid_wr[vi, si] += 1

    with np.errstate(divide="ignore", invalid="ignore"):
        grid_wr = np.where(grid_cnt > 0, grid_wr / grid_cnt * 100, np.nan)

    # Fill NaN with median for surface plotting
    med = float(np.nanmedian(grid_wr)) if not np.all(np.isnan(grid_wr)) else 60.0
    grid_filled = np.where(np.isnan(grid_wr), med, grid_wr)

    X_c = [(vix_bins[i] + vix_bins[i+1]) / 2 for i in range(len(vix_bins)-1)]
    Y_c = [(score_bins[i] + score_bins[i+1]) / 2 for i in range(len(score_bins)-1)]
    X, Y = np.meshgrid(X_c, Y_c, indexing="ij")

    norm = plt.Normalize(vmin=40, vmax=100)
    surf = ax3d.plot_surface(
        X, Y, grid_filled,
        facecolors=_THERMAL(norm(grid_filled)),
        rstride=1, cstride=1,
        alpha=0.88, linewidth=0.3,
        shade=True,
    )

    # Contour projection
    ax3d.contourf(X, Y, grid_filled, zdir="z", offset=grid_filled.min() - 5,
                  cmap=_THERMAL, alpha=0.35, levels=10)

    ax3d.set_xlabel("VIX", color=SUBTEXT, fontsize=7, labelpad=6)
    ax3d.set_ylabel("Conf Score", color=SUBTEXT, fontsize=7, labelpad=6)
    ax3d.set_zlabel("Win Rate %", color=SUBTEXT, fontsize=7, labelpad=6)
    ax3d.tick_params(colors=SUBTEXT, labelsize=6)
    ax3d.xaxis.pane.fill = False
    ax3d.yaxis.pane.fill = False
    ax3d.zaxis.pane.fill = False
    ax3d.xaxis.pane.set_edgecolor(BORDER)
    ax3d.yaxis.pane.set_edgecolor(BORDER)
    ax3d.zaxis.pane.set_edgecolor(BORDER)
    ax3d.grid(False)
    ax3d.view_init(elev=28, azim=-50)

    sm = plt.cm.ScalarMappable(cmap=_THERMAL, norm=norm)
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=ax3d, shrink=0.4, pad=0.08)
    cbar.ax.tick_params(colors=SUBTEXT, labelsize=6)
    cbar.set_label("Win Rate (%)", color=SUBTEXT, fontsize=7)

    # Math formula overlay
    formula = (r"$\hat{p}(v,s) = \frac{\sum_i \mathbf{1}[W_i]\mathbf{1}[v_i \in V]\mathbf{1}[s_i \in S]}"
               r"{\sum_i \mathbf{1}[v_i \in V]\mathbf{1}[s_i \in S]}$")
    fig.text(0.25, 0.02, formula, ha="center", color=SUBTEXT,
             fontsize=7.5, usetex=False)

    # Right: Score bucket P&L bars
    ax_r = fig.add_subplot(122)
    _base_ax(ax_r)

    score_groups = defaultdict(list)
    for t in trades:
        sc = getattr(t, "score", 10)
        score_groups[sc].append(t)

    scores = sorted(score_groups.keys())
    wrs_by_score  = []
    pnl_by_score  = []
    cnt_by_score  = []
    for sc in scores:
        tl = score_groups[sc]
        wrs_by_score.append(len([t for t in tl if t.outcome == "WIN"]) / len(tl) * 100)
        pnl_by_score.append(sum(t.pnl for t in tl))
        cnt_by_score.append(len(tl))

    xs2 = np.arange(len(scores))
    bar_colors = [_THERMAL(wr / 100) for wr in wrs_by_score]

    bars = ax_r.bar(xs2, pnl_by_score, color=bar_colors, alpha=0.85,
                    width=0.65, zorder=3)
    ax_r.axhline(0, color=BORDER, lw=0.8, ls="--")

    for bar, cnt, wr in zip(bars, cnt_by_score, wrs_by_score):
        h = bar.get_height()
        offset = 5 if h >= 0 else -15
        ax_r.text(bar.get_x() + bar.get_width() / 2, h + offset,
                  f"{wr:.0f}%\n(n={cnt})",
                  ha="center", va="bottom" if h >= 0 else "top",
                  color=WHITE, fontsize=5.5, fontfamily="monospace")

    ax_r.set_xticks(xs2)
    ax_r.set_xticklabels([str(s) for s in scores], fontsize=7)
    ax_r.set_xlabel("Confidence Score")
    ax_r.set_ylabel("P&L ($)")
    ax_r.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"${v:+,.0f}"))
    ax_r.set_title("P&L BY CONFIDENCE SCORE", color=TEXT, fontsize=9,
                   fontweight="bold", loc="left", pad=6)

    _header(fig, "ALPHA GENERATION SURFACE",
            f"Win rate surface across VIX regime × confidence score  |  z = E[win | VIX ∈ V, score ∈ S]")
    _watermark(fig)
    _save(fig, "02_drawdown")


# ── 3. STRATEGY PERFORMANCE MATRIX ───────────────────────────────────────────
def chart_strategy_breakdown(trades):
    _font()
    fig = plt.figure(figsize=(18, 9), facecolor=BG)
    gs  = gridspec.GridSpec(2, 2, figure=fig, hspace=0.42, wspace=0.35,
                            left=0.07, right=0.97, top=0.88, bottom=0.08)

    order   = ["gap_fill", "fvg", "orb", "ib_breakout", "vwap_rev",
               "vwap_pm", "vwap_bounce", "vwap_bounce_pm", "va_rule"]
    groups  = defaultdict(list)
    for t in trades:
        groups[t.strategy].append(t)
    strats  = [s for s in order if s in groups]
    labels  = [STRAT_LABELS.get(s, s) for s in strats]
    wrs     = [len([t for t in groups[s] if t.outcome=="WIN"])/len(groups[s])*100 for s in strats]
    pnls    = [sum(t.pnl for t in groups[s]) for s in strats]
    counts  = [len(groups[s]) for s in strats]
    colors  = [STRAT_COLORS.get(s, CYAN) for s in strats]

    xs = np.arange(len(strats))

    # Top-left: Win rate horizontal bars
    ax1 = fig.add_subplot(gs[0, 0])
    _base_ax(ax1)
    bars = ax1.barh(xs, wrs, color=colors, alpha=0.8, height=0.55, zorder=3)
    ax1.axvline(50, color=DIM, lw=0.8, ls="--")
    ax1.axvline(np.mean(wrs), color=YELLOW, lw=0.8, ls=":", alpha=0.6,
                label=f"Avg {np.mean(wrs):.0f}%")
    ax1.set_yticks(xs); ax1.set_yticklabels(labels, color=TEXT, fontsize=7.5)
    ax1.set_xlim(0, 110)
    for bar, wr, cnt in zip(bars, wrs, counts):
        ax1.text(wr + 1.5, bar.get_y() + bar.get_height()/2,
                 f"{wr:.0f}%  (n={cnt})", va="center", color=TEXT, fontsize=6.5,
                 fontfamily="monospace")
    ax1.set_title("WIN RATE BY STRATEGY", color=TEXT, fontsize=9,
                  fontweight="bold", loc="left", pad=6)
    ax1.legend(facecolor=PANEL2, labelcolor=SUBTEXT, framealpha=0.8,
               edgecolor=BORDER, fontsize=6)

    # Top-right: P&L waterfall bars
    ax2 = fig.add_subplot(gs[0, 1])
    _base_ax(ax2)
    bar_colors2 = [GREEN if p >= 0 else RED for p in pnls]
    bars2 = ax2.barh(xs, pnls, color=bar_colors2, alpha=0.8, height=0.55, zorder=3)
    ax2.axvline(0, color=SUBTEXT, lw=0.8, ls="--")
    ax2.set_yticks(xs); ax2.set_yticklabels(labels, color=TEXT, fontsize=7.5)
    ax2.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"${v:+,.0f}"))
    for bar, p in zip(bars2, pnls):
        offset = 5 if p >= 0 else -5
        ha = "left" if p >= 0 else "right"
        ax2.text(p + offset, bar.get_y() + bar.get_height()/2,
                 f"${p:+.0f}", va="center", ha=ha, color=TEXT, fontsize=6.5,
                 fontfamily="monospace")
    ax2.set_title("TOTAL P&L BY STRATEGY", color=TEXT, fontsize=9,
                  fontweight="bold", loc="left", pad=6)

    # Bottom-left: R:R distribution per strategy
    ax3 = fig.add_subplot(gs[1, 0])
    _base_ax(ax3)
    for i, (strat, color) in enumerate(zip(strats, colors)):
        rrs = [t.rr for t in groups[strat]]
        parts = ax3.violinplot([rrs], positions=[i], widths=0.6, showmedians=True,
                               showextrema=False)
        for pc in parts["bodies"]:
            pc.set_facecolor(color); pc.set_alpha(0.35)
        parts["cmedians"].set_color(color); parts["cmedians"].set_linewidth(1.5)

    ax3.set_xticks(range(len(strats)))
    ax3.set_xticklabels(labels, rotation=30, ha="right", color=TEXT, fontsize=6.5)
    ax3.set_ylabel("Risk:Reward Ratio")
    ax3.axhline(1.0, color=DIM, lw=0.8, ls="--")
    ax3.set_title("R:R DISTRIBUTION BY STRATEGY", color=TEXT, fontsize=9,
                  fontweight="bold", loc="left", pad=6)

    # Bottom-right: Trades per day bubble chart
    ax4 = fig.add_subplot(gs[1, 1])
    _base_ax(ax4)
    day_strat = defaultdict(lambda: defaultdict(list))
    for t in trades:
        day_strat[t.day_name][t.strategy].append(t)

    days = ["Mon", "Tue", "Wed", "Thu", "Fri"]
    for xi, day in enumerate(days):
        for yi, strat in enumerate(strats):
            tl = day_strat[day][strat]
            if not tl:
                continue
            wr = len([t for t in tl if t.outcome=="WIN"]) / len(tl)
            size = len(tl) * 120
            color = STRAT_COLORS.get(strat, CYAN)
            alpha = 0.3 + wr * 0.7
            ax4.scatter(xi, yi, s=size, color=color, alpha=alpha,
                        zorder=3, linewidths=0)
            ax4.text(xi, yi, f"{wr*100:.0f}%", ha="center", va="center",
                     color=WHITE, fontsize=5.5, fontweight="bold")

    ax4.set_xticks(range(len(days))); ax4.set_xticklabels(days, color=TEXT, fontsize=7.5)
    ax4.set_yticks(range(len(strats))); ax4.set_yticklabels(labels, color=TEXT, fontsize=7)
    ax4.set_title("TRADE MAP  (size=count, color=strategy, opacity=WR)",
                  color=TEXT, fontsize=9, fontweight="bold", loc="left", pad=6)

    _header(fig, "STRATEGY PERFORMANCE MATRIX",
            f"4-panel decomposition  |  {len(trades)} total trades across {len(strats)} strategies")
    _watermark(fig)
    _save(fig, "03_strategy_breakdown")


# ── 4. RETURNS DISTRIBUTION (statistical) ────────────────────────────────────
def chart_pnl_distribution(trades):
    _font()
    fig = plt.figure(figsize=(18, 9), facecolor=BG)
    gs  = gridspec.GridSpec(2, 2, figure=fig, hspace=0.4, wspace=0.32,
                            left=0.07, right=0.97, top=0.88, bottom=0.08)

    pnls = np.array([t.pnl for t in trades])
    mu, sigma = float(np.mean(pnls)), float(np.std(pnls))

    # VaR and CVaR
    var_95  = float(np.percentile(pnls, 5))
    cvar_95 = float(np.mean(pnls[pnls <= var_95]))
    skew    = float(pd.Series(pnls).skew())
    kurt    = float(pd.Series(pnls).kurtosis())

    # Top-left: histogram with normal overlay
    ax1 = fig.add_subplot(gs[0, 0])
    _base_ax(ax1)
    n, bins, patches = ax1.hist(pnls, bins=35, edgecolor=BG, linewidth=0.3, zorder=3)
    for patch, left in zip(patches, bins[:-1]):
        patch.set_facecolor(GREEN if left >= 0 else RED)
        patch.set_alpha(0.75)
    x_fit = np.linspace(pnls.min(), pnls.max(), 300)
    y_fit = (n.max() / (sigma * np.sqrt(2*np.pi))) * np.exp(-0.5*((x_fit - mu)/sigma)**2)
    _glow(ax1, x_fit, y_fit, YELLOW, lw=1.2, alpha_base=0.8)
    ax1.axvline(mu,      color=CYAN,    lw=1.2, ls="-",  label=f"μ = ${mu:+.1f}")
    ax1.axvline(var_95,  color=MAGENTA, lw=1,   ls="--", label=f"VaR₉₅ = ${var_95:+.1f}")
    ax1.axvline(cvar_95, color=RED,     lw=1,   ls=":",  label=f"CVaR₉₅ = ${cvar_95:+.1f}")
    ax1.legend(facecolor=PANEL2, labelcolor=TEXT, framealpha=0.9,
               edgecolor=BORDER, fontsize=6.5)
    ax1.set_xlabel("P&L per Trade ($)")
    ax1.set_ylabel("Frequency")
    ax1.set_title("P&L DISTRIBUTION + NORMAL FIT", color=TEXT, fontsize=9,
                  fontweight="bold", loc="left", pad=6)
    stats_str = f"μ=${mu:+.1f}  σ=${sigma:.1f}\nskew={skew:.2f}  kurt={kurt:.2f}"
    ax1.text(0.97, 0.97, stats_str, transform=ax1.transAxes, va="top", ha="right",
             color=SUBTEXT, fontsize=6.5, fontfamily="monospace",
             bbox=dict(facecolor=PANEL2, edgecolor=BORDER, alpha=0.8, boxstyle="round,pad=0.3"))

    # Top-right: Q-Q plot
    ax2 = fig.add_subplot(gs[0, 1])
    _base_ax(ax2)
    from scipy import stats as scipy_stats
    (osm, osr), (slope, intercept, _) = scipy_stats.probplot(pnls, dist="norm")
    ax2.scatter(osm, osr, color=CYAN, s=18, alpha=0.7, zorder=3, linewidths=0)
    x_qq = np.linspace(osm[0], osm[-1], 100)
    _glow(ax2, x_qq, slope*x_qq + intercept, YELLOW, lw=1.2)
    ax2.set_xlabel("Theoretical Quantiles")
    ax2.set_ylabel("Sample Quantiles")
    ax2.set_title("Q-Q PLOT  (normality test)", color=TEXT, fontsize=9,
                  fontweight="bold", loc="left", pad=6)

    # Bottom-left: KDE by outcome
    ax3 = fig.add_subplot(gs[1, 0])
    _base_ax(ax3)
    wins_pnl = pnls[pnls > 0]
    loss_pnl = pnls[pnls < 0]
    if len(wins_pnl) > 2:
        from scipy.stats import gaussian_kde
        kde_w = gaussian_kde(wins_pnl)
        x_w = np.linspace(wins_pnl.min(), wins_pnl.max(), 200)
        ax3.fill_between(x_w, kde_w(x_w), alpha=0.3, color=GREEN)
        _glow(ax3, x_w, kde_w(x_w), GREEN, lw=1.5)
    if len(loss_pnl) > 2:
        kde_l = gaussian_kde(loss_pnl)
        x_l = np.linspace(loss_pnl.min(), loss_pnl.max(), 200)
        ax3.fill_between(x_l, kde_l(x_l), alpha=0.3, color=RED)
        _glow(ax3, x_l, kde_l(x_l), RED, lw=1.5)
    ax3.axvline(0, color=BORDER, lw=0.8, ls="--")
    ax3.set_xlabel("P&L ($)")
    ax3.set_ylabel("Density")
    ax3.set_title("KDE — WINS vs LOSSES", color=TEXT, fontsize=9,
                  fontweight="bold", loc="left", pad=6)
    # Expectancy annotation
    exp = float(np.mean(pnls))
    ax3.text(0.5, 0.92, f"E[trade] = ${exp:+.2f}", transform=ax3.transAxes,
             ha="center", color=YELLOW, fontsize=8, fontfamily="monospace",
             fontweight="bold")

    # Bottom-right: Cumulative return distribution (sorted waterfall)
    ax4 = fig.add_subplot(gs[1, 1])
    _base_ax(ax4)
    sorted_pnl = np.sort(pnls)[::-1]
    cum_sorted  = np.cumsum(sorted_pnl)
    bar_c = [GREEN if p >= 0 else RED for p in sorted_pnl]
    ax4.bar(range(len(sorted_pnl)), sorted_pnl, color=bar_c, alpha=0.75,
            width=1.0, zorder=3)
    ax4b = ax4.twinx()
    ax4b.set_facecolor(PANEL)
    _glow(ax4b, range(len(cum_sorted)), cum_sorted, CYAN, lw=1.4)
    ax4b.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"${v:+,.0f}"))
    ax4b.tick_params(colors=CYAN, labelsize=6)
    for spine in ax4b.spines.values():
        spine.set_edgecolor(BORDER)
    ax4.set_xlabel("Trade rank (sorted by P&L)")
    ax4.set_ylabel("Individual P&L ($)")
    ax4.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"${v:+,.0f}"))
    ax4.set_title("TRADE WATERFALL  (sorted, cumulative overlay)",
                  color=TEXT, fontsize=9, fontweight="bold", loc="left", pad=6)

    _header(fig, "RETURNS STATISTICAL ANALYSIS",
            f"Distribution  |  Q-Q  |  KDE decomp  |  Waterfall  —  VaR₉₅={var_95:+.1f}  CVaR₉₅={cvar_95:+.1f}")
    _watermark(fig)
    _save(fig, "04_pnl_distribution")


# ── 5. ROLLING METRICS ────────────────────────────────────────────────────────
def chart_rolling_winrate(trades, window=15):
    _font()
    fig = plt.figure(figsize=(18, 10), facecolor=BG)
    gs  = gridspec.GridSpec(3, 1, figure=fig, hspace=0.35,
                            left=0.07, right=0.97, top=0.90, bottom=0.08)

    outcomes = np.array([1 if t.outcome == "WIN" else 0 for t in trades], dtype=float)
    pnls     = np.array([t.pnl for t in trades])
    roll_wr  = pd.Series(outcomes).rolling(window, min_periods=3).mean() * 100
    roll_pnl = pd.Series(pnls).rolling(window, min_periods=3).mean()

    # Sharpe rolling
    def _rolling_sharpe(arr, w):
        s = pd.Series(arr)
        m = s.rolling(w, min_periods=5).mean()
        d = s.rolling(w, min_periods=5).std()
        return (m / d * np.sqrt(252 * 3)).fillna(0)

    roll_sh = _rolling_sharpe(pnls, window)
    xs = np.arange(len(trades))

    # Panel 1: Rolling win rate
    ax1 = fig.add_subplot(gs[0])
    _base_ax(ax1)
    ax1.fill_between(xs, roll_wr.values, 50,
                     where=(roll_wr.values >= 50), alpha=0.15, color=GREEN)
    ax1.fill_between(xs, roll_wr.values, 50,
                     where=(roll_wr.values < 50),  alpha=0.15, color=RED)
    _glow(ax1, xs, roll_wr.values, PURPLE, lw=1.8)
    ax1.axhline(50, color=DIM, lw=0.8, ls="--")
    ax1.axhline(outcomes.mean()*100, color=YELLOW, lw=0.8, ls=":",
                label=f"Overall {outcomes.mean()*100:.1f}%")
    ax1.set_ylim(0, 105)
    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:.0f}%"))
    ax1.set_title(f"ROLLING {window}-TRADE WIN RATE", color=TEXT, fontsize=9,
                  fontweight="bold", loc="left", pad=6)
    ax1.legend(facecolor=PANEL2, labelcolor=TEXT, framealpha=0.8,
               edgecolor=BORDER, fontsize=7)

    # Panel 2: Rolling avg P&L
    ax2 = fig.add_subplot(gs[1])
    _base_ax(ax2)
    ax2.fill_between(xs, roll_pnl.values, 0,
                     where=(roll_pnl.values >= 0), alpha=0.15, color=GREEN)
    ax2.fill_between(xs, roll_pnl.values, 0,
                     where=(roll_pnl.values < 0),  alpha=0.15, color=RED)
    _glow(ax2, xs, roll_pnl.values, CYAN, lw=1.6)
    ax2.axhline(0, color=DIM, lw=0.8, ls="--")
    ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"${v:+.1f}"))
    ax2.set_title(f"ROLLING {window}-TRADE AVG P&L", color=TEXT, fontsize=9,
                  fontweight="bold", loc="left", pad=6)

    # Panel 3: Rolling Sharpe
    ax3 = fig.add_subplot(gs[2])
    _base_ax(ax3)
    ax3.fill_between(xs, roll_sh.values, 0,
                     where=(roll_sh.values >= 0), alpha=0.15, color=TEAL)
    ax3.fill_between(xs, roll_sh.values, 0,
                     where=(roll_sh.values < 0),  alpha=0.15, color=MAGENTA)
    _glow(ax3, xs, roll_sh.values, ORANGE, lw=1.6)
    ax3.axhline(0,   color=DIM,    lw=0.8, ls="--")
    ax3.axhline(1.0, color=YELLOW, lw=0.7, ls=":", alpha=0.5, label="Sharpe 1.0")
    ax3.axhline(2.0, color=GREEN,  lw=0.7, ls=":", alpha=0.5, label="Sharpe 2.0")
    ax3.set_xlabel("Trade #")
    ax3.set_title(f"ROLLING {window}-TRADE SHARPE RATIO", color=TEXT, fontsize=9,
                  fontweight="bold", loc="left", pad=6)
    ax3.legend(facecolor=PANEL2, labelcolor=TEXT, framealpha=0.8,
               edgecolor=BORDER, fontsize=7)

    _header(fig, "ROLLING PERFORMANCE METRICS",
            f"Window = {window} trades  |  3-panel: WR / Avg P&L / Sharpe")
    _watermark(fig)
    _save(fig, "05_rolling_winrate")


# ── 6. REGIME HEATMAP ────────────────────────────────────────────────────────
def chart_heatmap(trades):
    _font()
    fig = plt.figure(figsize=(18, 9), facecolor=BG)
    gs  = gridspec.GridSpec(1, 2, figure=fig, wspace=0.38,
                            left=0.07, right=0.97, top=0.88, bottom=0.1)

    order_d = ["Mon", "Tue", "Wed", "Thu", "Fri"]
    order_s = ["gap_fill", "fvg", "orb", "ib_breakout",
               "vwap_rev", "vwap_pm", "vwap_bounce", "vwap_bounce_pm", "va_rule"]
    labels_s = [STRAT_LABELS.get(s, s) for s in order_s]
    present_s = [s for s in order_s if any(t.strategy == s for t in trades)]
    present_l = [STRAT_LABELS.get(s, s) for s in present_s]

    # Win rate matrix
    matrix = pd.DataFrame(index=order_d, columns=present_s, dtype=float)
    counts = pd.DataFrame(index=order_d, columns=present_s, dtype=int)
    for d in order_d:
        for s in present_s:
            sub = [t for t in trades if t.day_name == d and t.strategy == s]
            if sub:
                matrix.loc[d, s] = len([t for t in sub if t.outcome == "WIN"]) / len(sub) * 100
                counts.loc[d, s] = len(sub)
            else:
                matrix.loc[d, s] = np.nan
                counts.loc[d, s] = 0

    ax1 = fig.add_subplot(gs[0])
    ax1.set_facecolor(PANEL)
    cmap_rg = sns.diverging_palette(0, 130, s=90, l=45, as_cmap=True)
    mask = matrix.astype(float).isna()
    sns.heatmap(
        matrix.astype(float), ax=ax1, cmap=cmap_rg, vmin=0, vmax=100,
        annot=True, fmt=".0f", linewidths=0.8, linecolor=BG,
        cbar_kws={"label": "Win Rate (%)", "shrink": 0.7},
        annot_kws={"size": 8, "color": WHITE, "family": "monospace"},
        mask=mask,
    )
    ax1.set_xticklabels(present_l, rotation=30, ha="right", color=TEXT, fontsize=7.5)
    ax1.set_yticklabels(order_d, rotation=0, color=TEXT, fontsize=8)
    # overlay count
    for i, d in enumerate(order_d):
        for j, s in enumerate(present_s):
            c = counts.loc[d, s]
            if c > 0:
                ax1.text(j + 0.9, i + 0.9, str(c), ha="right", va="bottom",
                         color=WHITE, fontsize=5, alpha=0.6)
    ax1.set_title("WIN RATE HEATMAP  (Day × Strategy)  n=trade count",
                  color=TEXT, fontsize=9, fontweight="bold", pad=10)

    # P&L heatmap (right)
    pnl_matrix = pd.DataFrame(index=order_d, columns=present_s, dtype=float)
    for d in order_d:
        for s in present_s:
            sub = [t for t in trades if t.day_name == d and t.strategy == s]
            pnl_matrix.loc[d, s] = sum(t.pnl for t in sub) if sub else np.nan

    ax2 = fig.add_subplot(gs[1])
    ax2.set_facecolor(PANEL)
    cmap_pnl = sns.diverging_palette(0, 130, s=90, l=45, as_cmap=True)
    mask2 = pnl_matrix.astype(float).isna()
    sns.heatmap(
        pnl_matrix.astype(float), ax=ax2, cmap=cmap_pnl,
        center=0,
        annot=True, fmt=".0f", linewidths=0.8, linecolor=BG,
        cbar_kws={"label": "Total P&L ($)", "shrink": 0.7},
        annot_kws={"size": 7, "color": WHITE, "family": "monospace"},
        mask=mask2,
    )
    ax2.set_xticklabels(present_l, rotation=30, ha="right", color=TEXT, fontsize=7.5)
    ax2.set_yticklabels(order_d, rotation=0, color=TEXT, fontsize=8)
    ax2.set_title("P&L HEATMAP  (Day × Strategy)",
                  color=TEXT, fontsize=9, fontweight="bold", pad=10)

    _header(fig, "DAY × STRATEGY PERFORMANCE MATRIX")
    _watermark(fig)
    _save(fig, "06_winrate_heatmap")


# ── 7. MONTE CARLO SIMULATION ─────────────────────────────────────────────────
def chart_vix_scatter(trades):
    """Monte Carlo equity curve simulation."""
    _font()
    fig = plt.figure(figsize=(18, 9), facecolor=BG)
    gs  = gridspec.GridSpec(1, 2, figure=fig, wspace=0.35,
                            left=0.07, right=0.97, top=0.88, bottom=0.09)

    pnls = np.array([t.pnl for t in trades])
    n    = len(pnls)
    N_SIM = 500

    np.random.seed(42)
    sim_curves = np.zeros((N_SIM, n))
    for i in range(N_SIM):
        sim_pnls      = np.random.choice(pnls, size=n, replace=True)
        sim_curves[i] = np.cumsum(sim_pnls)

    actual = np.cumsum(pnls)
    xs     = np.arange(n)

    # Left: Monte Carlo fan
    ax1 = fig.add_subplot(gs[0])
    _base_ax(ax1)

    # Percentile bands
    p5  = np.percentile(sim_curves, 5,  axis=0)
    p25 = np.percentile(sim_curves, 25, axis=0)
    p50 = np.percentile(sim_curves, 50, axis=0)
    p75 = np.percentile(sim_curves, 75, axis=0)
    p95 = np.percentile(sim_curves, 95, axis=0)

    ax1.fill_between(xs, p5,  p95, alpha=0.08, color=CYAN, zorder=1)
    ax1.fill_between(xs, p25, p75, alpha=0.15, color=CYAN, zorder=2)
    # Some random paths
    for i in range(0, min(80, N_SIM), 1):
        ax1.plot(xs, sim_curves[i], color=CYAN, alpha=0.03, linewidth=0.5, zorder=1)
    _glow(ax1, xs, p50, TEAL, lw=1.2, alpha_base=0.6)
    _glow(ax1, xs, actual, YELLOW, lw=2.0)
    ax1.axhline(0, color=DIM, lw=0.8, ls="--")
    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"${v:+,.0f}"))
    ax1.set_xlabel("Trade #")
    ax1.set_ylabel("Cumulative P&L ($)")
    ax1.set_title(f"MONTE CARLO  ({N_SIM} paths, bootstrap resampling)",
                  color=TEXT, fontsize=9, fontweight="bold", loc="left", pad=6)

    # Legend
    legend_els = [
        mpatches.Patch(color=YELLOW,  label="Actual equity curve"),
        mpatches.Patch(color=TEAL,    label="Median simulation", alpha=0.6),
        mpatches.Patch(color=CYAN,    label="25–75th pct band",   alpha=0.3),
        mpatches.Patch(color=CYAN,    label="5–95th pct band",    alpha=0.1),
    ]
    ax1.legend(handles=legend_els, facecolor=PANEL2, labelcolor=TEXT,
               framealpha=0.9, edgecolor=BORDER, fontsize=7)

    # MC stats
    final_vals  = sim_curves[:, -1]
    mc_stats = (
        f"Simulated final P&L\n"
        f"  Median  ${np.median(final_vals):+,.0f}\n"
        f"  5th pct ${np.percentile(final_vals, 5):+,.0f}\n"
        f"  95th pct${np.percentile(final_vals, 95):+,.0f}\n"
        f"  Prob > 0  {(final_vals > 0).mean()*100:.0f}%\n"
        f"  Prob > $1.5k  {(final_vals > 1500).mean()*100:.0f}%"
    )
    ax1.text(0.01, 0.98, mc_stats, transform=ax1.transAxes, va="top",
             color=CYAN, fontsize=7, fontfamily="monospace",
             bbox=dict(facecolor=PANEL2, edgecolor=BORDER, alpha=0.9,
                       boxstyle="round,pad=0.4"))

    # Right: VIX scatter
    ax2 = fig.add_subplot(gs[1])
    _base_ax(ax2)
    present_s = list(set(t.strategy for t in trades))
    for strat in present_s:
        sub = [t for t in trades if t.strategy == strat]
        vixes = [t.vix for t in sub]
        tpnls = [t.pnl for t in sub]
        color = STRAT_COLORS.get(strat, CYAN)
        ax2.scatter(vixes, tpnls, color=color, alpha=0.7, s=40, zorder=3,
                    label=STRAT_LABELS.get(strat, strat), linewidths=0)

    ax2.axhline(0, color=DIM, lw=0.8, ls="--")
    ax2.axvline(20, color=YELLOW, lw=0.8, ls=":", alpha=0.5)
    ax2.axvline(30, color=RED,    lw=0.8, ls=":", alpha=0.5)
    # Regression line
    vix_all = np.array([t.vix for t in trades])
    pnl_all = np.array([t.pnl for t in trades])
    m, b = np.polyfit(vix_all, pnl_all, 1)
    xs_r  = np.linspace(vix_all.min(), vix_all.max(), 100)
    _glow(ax2, xs_r, m * xs_r + b, WHITE, lw=1.2, alpha_base=0.4)

    ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"${v:+,.0f}"))
    ax2.set_xlabel("VIX")
    ax2.set_ylabel("Trade P&L ($)")
    ax2.legend(facecolor=PANEL2, labelcolor=TEXT, framealpha=0.8,
               edgecolor=BORDER, fontsize=6.5, ncol=2, loc="upper right")
    ax2.set_title("VIX REGIME vs P&L  (regression line = $\\beta$ estimate)",
                  color=TEXT, fontsize=9, fontweight="bold", loc="left", pad=6)
    slope_txt = f"∂P&L/∂VIX = ${m:+.2f}/pt"
    ax2.text(0.97, 0.04, slope_txt, transform=ax2.transAxes, ha="right",
             color=SUBTEXT, fontsize=7, fontfamily="monospace")

    _header(fig, "MONTE CARLO SIMULATION + VIX SENSITIVITY",
            f"{N_SIM} bootstrap paths  |  P(profit > $1,500) = {(final_vals > 1500).mean()*100:.0f}%")
    _watermark(fig)
    _save(fig, "07_vix_scatter")


# ── 8. FACTOR ANALYSIS ────────────────────────────────────────────────────────
def chart_rr_distribution(trades):
    _font()
    fig = plt.figure(figsize=(18, 9), facecolor=BG)
    gs  = gridspec.GridSpec(1, 2, figure=fig, wspace=0.38,
                            left=0.07, right=0.97, top=0.88, bottom=0.12)

    # Left: Scoring factor hit rates (horizontal bar)
    ax1 = fig.add_subplot(gs[0])
    _base_ax(ax1)

    all_factors: dict[str, list] = defaultdict(list)
    for t in trades:
        bd = getattr(t, "score_breakdown", {})
        for k, v in bd.items():
            all_factors[k].append(v)

    if all_factors:
        factor_order = sorted(all_factors.keys())
        hit_rates = [np.mean(all_factors[f]) * 100 for f in factor_order]
        colors_f  = [GREEN if h >= 80 else (YELLOW if h >= 60 else RED)
                     for h in hit_rates]

        ys = np.arange(len(factor_order))
        bars = ax1.barh(ys, hit_rates, color=colors_f, alpha=0.80, height=0.6, zorder=3)
        ax1.axvline(50, color=DIM,    lw=0.8, ls="--")
        ax1.axvline(80, color=YELLOW, lw=0.6, ls=":", alpha=0.5)
        ax1.set_yticks(ys)
        ax1.set_yticklabels(factor_order, color=TEXT, fontsize=8, fontfamily="monospace")
        ax1.set_xlim(0, 110)
        for bar, h in zip(bars, hit_rates):
            ax1.text(h + 1.5, bar.get_y() + bar.get_height()/2,
                     f"{h:.0f}%", va="center", color=TEXT, fontsize=6.5,
                     fontfamily="monospace")
        ax1.set_xlabel("Hit Rate (% of trades where factor = 1)")
        ax1.set_title("20-POINT SCORING — FACTOR HIT RATES",
                      color=TEXT, fontsize=9, fontweight="bold", loc="left", pad=6)
    else:
        ax1.text(0.5, 0.5, "Score breakdown\nnot available\n(QuantTrade)",
                 ha="center", va="center", color=SUBTEXT, fontsize=10,
                 transform=ax1.transAxes)
        ax1.set_title("FACTOR HIT RATES", color=TEXT, fontsize=9,
                      fontweight="bold", loc="left", pad=6)

    # Right: R:R distribution stacked
    ax2 = fig.add_subplot(gs[1])
    _base_ax(ax2)
    rr_all   = np.array([t.rr for t in trades])
    rr_wins  = np.array([t.rr for t in trades if t.outcome == "WIN"])
    rr_loss  = np.array([t.rr for t in trades if t.outcome == "LOSS"])
    bins_rr  = np.linspace(0, min(rr_all.max(), 30), 30)

    ax2.hist(rr_wins, bins=bins_rr, color=GREEN,   alpha=0.7, zorder=3,
             label=f"Wins (n={len(rr_wins)})")
    ax2.hist(rr_loss, bins=bins_rr, color=RED,     alpha=0.7, zorder=2,
             label=f"Losses (n={len(rr_loss)})")
    ax2.axvline(1.0, color=YELLOW,  lw=1,   ls="--", alpha=0.9, label="1:1 R:R")
    ax2.axvline(rr_all.mean(), color=CYAN, lw=1.2, ls="-",
                label=f"Mean R:R {rr_all.mean():.2f}x")

    ax2.set_xlabel("Risk:Reward Ratio")
    ax2.set_ylabel("Frequency")
    ax2.legend(facecolor=PANEL2, labelcolor=TEXT, framealpha=0.9,
               edgecolor=BORDER, fontsize=7)
    ax2.set_title("R:R DISTRIBUTION — WIN vs LOSS",
                  color=TEXT, fontsize=9, fontweight="bold", loc="left", pad=6)

    # Stats box
    rr_txt = (
        f"Mean R:R    {rr_all.mean():.2f}x\n"
        f"Median R:R  {np.median(rr_all):.2f}x\n"
        f"90th pct    {np.percentile(rr_all, 90):.2f}x\n"
        f"Win R:R avg {rr_wins.mean():.2f}x" if len(rr_wins) else ""
    )
    ax2.text(0.97, 0.97, rr_txt, transform=ax2.transAxes, va="top", ha="right",
             color=CYAN, fontsize=7, fontfamily="monospace",
             bbox=dict(facecolor=PANEL2, edgecolor=BORDER, alpha=0.9,
                       boxstyle="round,pad=0.3"))

    _header(fig, "FACTOR ANALYSIS + RISK:REWARD DECOMPOSITION",
            "Left: 20-point scoring hit rates  |  Right: R:R distribution by outcome")
    _watermark(fig)
    _save(fig, "08_rr_distribution")


# ── 9. CALENDAR HEATMAP ───────────────────────────────────────────────────────
def chart_monthly_calendar(trades):
    _font()
    daily = defaultdict(float)
    for t in trades:
        daily[t.date] += t.pnl
    if not daily:
        return

    dates  = sorted(daily.keys())
    months = sorted(set((d.year, d.month) for d in dates))
    n_mo   = len(months)
    cols   = min(n_mo, 3)
    rows   = (n_mo + cols - 1) // cols

    fig, axes = plt.subplots(rows, cols,
                             figsize=(cols * 5.5, rows * 4.2),
                             facecolor=BG)
    if n_mo == 1:
        axes = [[axes]]
    elif rows == 1:
        axes = [axes]
    axes_flat = [ax for row in axes for ax in (row if hasattr(row, '__iter__') else [row])]

    import calendar
    mo_names = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    day_lbl  = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]

    max_abs = max(abs(v) for v in daily.values()) or 1.0

    for idx, (yr, mo) in enumerate(months):
        ax = axes_flat[idx]
        ax.set_facecolor(PANEL)
        for spine in ax.spines.values():
            spine.set_edgecolor(BORDER); spine.set_linewidth(0.6)
        ax.set_xticks(range(7))
        ax.set_xticklabels(day_lbl, fontsize=5.5, color=SUBTEXT)
        ax.set_yticks([])
        mo_pnl = sum(v for d, v in daily.items() if d.year == yr and d.month == mo)
        color_title = GREEN if mo_pnl >= 0 else RED
        ax.set_title(f"{mo_names[mo]} {yr}  {mo_pnl:+.0f}",
                     color=color_title, fontsize=8, fontweight="bold", pad=4)

        cal = calendar.monthcalendar(yr, mo)
        for wk, week in enumerate(cal):
            for dw, day in enumerate(week):
                if day == 0:
                    continue
                d   = date(yr, mo, day)
                pnl = daily.get(d, None)
                if pnl is not None:
                    norm_val = pnl / max_abs
                    if norm_val > 0:
                        col   = GREEN
                        alpha = 0.2 + 0.6 * min(norm_val, 1.0)
                    else:
                        col   = RED
                        alpha = 0.2 + 0.6 * min(abs(norm_val), 1.0)
                    rect = mpatches.FancyBboxPatch(
                        (dw - 0.44, -wk - 0.44), 0.88, 0.82,
                        boxstyle="round,pad=0.03",
                        facecolor=col, edgecolor=PANEL2,
                        alpha=alpha, linewidth=0.4, zorder=2,
                    )
                    ax.add_patch(rect)
                    ax.text(dw, -wk + 0.16, str(day), ha="center", va="center",
                            color=WHITE, fontsize=6, fontweight="bold", zorder=3)
                    ax.text(dw, -wk - 0.2, f"${pnl:+.0f}", ha="center", va="center",
                            color=WHITE, fontsize=4.8, zorder=3)
                else:
                    ax.text(dw, -wk, str(day), ha="center", va="center",
                            color=DIM, fontsize=6)

        ax.set_xlim(-0.6, 6.6)
        ax.set_ylim(-len(cal) + 0.3, 0.9)

    for ax in axes_flat[n_mo:]:
        ax.set_visible(False)

    total_pnl = sum(daily.values())
    fig.suptitle(f"DAILY P&L CALENDAR  —  Total ${total_pnl:+,.2f}",
                 color=WHITE, fontsize=12, fontweight="bold", y=1.01,
                 fontfamily="monospace")
    fig.tight_layout()
    _watermark(fig)
    _save(fig, "09_monthly_calendar")


# ── 10. STRATEGY EQUITY CURVES + WIN STREAK ──────────────────────────────────
def chart_strategy_equity_curves(trades):
    _font()
    fig = plt.figure(figsize=(18, 10), facecolor=BG)
    gs  = gridspec.GridSpec(2, 1, figure=fig, hspace=0.38,
                            left=0.07, right=0.97, top=0.90, bottom=0.08)

    order  = ["gap_fill", "fvg", "orb", "ib_breakout", "vwap_rev",
              "vwap_pm", "vwap_bounce", "vwap_bounce_pm", "va_rule"]
    groups = defaultdict(list)
    for t in trades:
        groups[t.strategy].append(t)

    ax1 = fig.add_subplot(gs[0])
    _base_ax(ax1)

    for strat in order:
        if strat not in groups:
            continue
        tl    = sorted(groups[strat], key=lambda x: x.date)
        cum   = np.cumsum([t.pnl for t in tl])
        color = STRAT_COLORS.get(strat, CYAN)
        label = f"{STRAT_LABELS.get(strat, strat)}  ${cum[-1]:+.0f}"
        _glow(ax1, range(len(cum)), cum, color, lw=1.6, alpha_base=0.85)
        ax1.text(len(cum) - 0.5, cum[-1], STRAT_LABELS.get(strat, strat),
                 color=color, fontsize=6.5, va="center", fontfamily="monospace")

    ax1.axhline(0, color=DIM, lw=0.7, ls="--")
    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"${v:+,.0f}"))
    ax1.set_xlabel("Trade # (per strategy)")
    ax1.set_ylabel("Cumulative P&L ($)")
    ax1.set_title("CUMULATIVE P&L BY STRATEGY", color=TEXT, fontsize=9,
                  fontweight="bold", loc="left", pad=6)

    # Bottom: Win/Loss sequence bar
    ax2 = fig.add_subplot(gs[1])
    _base_ax(ax2)

    outcomes = [1 if t.outcome == "WIN" else -1 for t in trades]
    colors2  = [GREEN if o > 0 else RED for o in outcomes]
    ax2.bar(range(len(outcomes)), outcomes, color=colors2, alpha=0.75,
            width=1.0, zorder=3)

    # Streak shading
    streak = 0
    streak_start = 0
    prev_outcome = outcomes[0] if outcomes else 1
    for i, o in enumerate(outcomes):
        if o == prev_outcome:
            streak += 1
        else:
            if abs(streak) >= 3:
                ax2.axvspan(streak_start, i - 1,
                            color=GREEN if prev_outcome > 0 else RED,
                            alpha=0.08, zorder=1)
            streak = 1
            streak_start = i
        prev_outcome = o

    # Rolling streak length
    streak_lens = []
    cur_streak = 0
    cur_o = outcomes[0] if outcomes else 1
    for o in outcomes:
        if o == cur_o:
            cur_streak += 1
        else:
            cur_streak = 1
            cur_o = o
        streak_lens.append(cur_streak * cur_o)

    ax2b = ax2.twinx()
    ax2b.set_facecolor(PANEL)
    ax2b.plot(range(len(streak_lens)), streak_lens, color=ORANGE, lw=1.0,
              alpha=0.6, zorder=4)
    ax2b.axhline(0, color=DIM, lw=0.4)
    ax2b.set_ylabel("Streak length", color=ORANGE, fontsize=7)
    ax2b.tick_params(colors=ORANGE, labelsize=6)
    for spine in ax2b.spines.values():
        spine.set_edgecolor(BORDER)

    ax2.set_yticks([-1, 1]); ax2.set_yticklabels(["LOSS", "WIN"], color=TEXT, fontsize=8)
    ax2.set_xlabel("Trade sequence (chronological)")
    ax2.set_title("WIN / LOSS SEQUENCE  (shaded = streak ≥3, orange = running streak)",
                  color=TEXT, fontsize=9, fontweight="bold", loc="left", pad=6)

    _header(fig, "STRATEGY EQUITY CURVES + WIN/LOSS SEQUENCE",
            "Each neon line = one strategy  |  Bottom panel = chronological win/loss run")
    _watermark(fig)
    _save(fig, "10_strategy_equity_curves")


# ── Entry point ───────────────────────────────────────────────────────────────
def generate_all_charts(trades) -> None:
    print(f"\nGenerating charts ({len(trades)} trades) → {OUT_DIR}/")
    try: chart_equity_curve(trades)
    except Exception as e: print(f"  [warn] chart 1 failed: {e}")
    try: chart_drawdown(trades)
    except Exception as e: print(f"  [warn] chart 2 failed: {e}")
    try: chart_strategy_breakdown(trades)
    except Exception as e: print(f"  [warn] chart 3 failed: {e}")
    try: chart_pnl_distribution(trades)
    except Exception as e: print(f"  [warn] chart 4 failed: {e}")
    try: chart_rolling_winrate(trades)
    except Exception as e: print(f"  [warn] chart 5 failed: {e}")
    try: chart_heatmap(trades)
    except Exception as e: print(f"  [warn] chart 6 failed: {e}")
    try: chart_vix_scatter(trades)
    except Exception as e: print(f"  [warn] chart 7 failed: {e}")
    try: chart_rr_distribution(trades)
    except Exception as e: print(f"  [warn] chart 8 failed: {e}")
    try: chart_monthly_calendar(trades)
    except Exception as e: print(f"  [warn] chart 9 failed: {e}")
    try: chart_strategy_equity_curves(trades)
    except Exception as e: print(f"  [warn] chart 10 failed: {e}")
    print(f"Done — 10 charts saved to ./{OUT_DIR}/\n")
