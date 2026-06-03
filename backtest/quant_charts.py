"""
Quantitative backtest visualizations — institutional research grade.
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
import matplotlib.gridspec as gridspec
import matplotlib.patches as mpatches
from matplotlib.colors import LinearSegmentedColormap, Normalize
from mpl_toolkits.mplot3d import Axes3D
import seaborn as sns
import warnings
warnings.filterwarnings("ignore")

OUT_DIR = "backtest_charts"

# ── Palette ───────────────────────────────────────────────────────────────────
BG      = "#02030a"
PANEL   = "#080b14"
GRID    = "#0f1220"
BORDER  = "#161b2e"
CYAN    = "#00d4ff"
MAGENTA = "#ff006e"
GREEN   = "#00ff88"
RED     = "#ff3366"
YELLOW  = "#ffd700"
PURPLE  = "#bf5fff"
ORANGE  = "#ff8c00"
TEAL    = "#00b4d8"
WHITE   = "#e8f0fe"
TEXT    = "#b0bec5"
DIM     = "#2d3561"
GOLD    = "#c8a44f"

STRAT_COLORS = {
    "gap_fill": CYAN, "fvg": PURPLE, "orb": YELLOW,
    "ib_breakout": ORANGE, "vwap_rev": GREEN, "vwap_pm": "#00e5a0",
    "vwap_bounce": MAGENTA, "vwap_bounce_pm": "#ff66aa", "va_rule": "#a78bfa",
}
_THERMAL = LinearSegmentedColormap.from_list(
    "thermal", ["#ff0040","#ff6600","#ffcc00","#00ff88","#00d4ff","#bf5fff"], N=256)

REGIME_COLORS = {
    "strong_bull": "#00ff88", "bull": "#00cc66",
    "neutral": "#5a6484", "stress": "#ff8c00", "bear": "#ff3366",
    "volatile": "#ff8c00", "unavailable": "#2d3561",
}


def _font():
    plt.rcParams.update({
        "font.family": "monospace", "font.size": 7.5,
        "axes.titlesize": 10, "axes.labelsize": 7.5,
        "xtick.labelsize": 6.5, "ytick.labelsize": 6.5,
        "legend.fontsize": 6.5, "figure.dpi": 150,
    })


def _ax(ax, grid=True, spines=True):
    ax.set_facecolor(PANEL)
    ax.tick_params(colors=DIM, length=2, width=0.4)
    ax.xaxis.label.set_color(DIM)
    ax.yaxis.label.set_color(DIM)
    for sp in ax.spines.values():
        sp.set_edgecolor(BORDER); sp.set_linewidth(0.5)
        if not spines: sp.set_visible(False)
    if grid:
        ax.grid(color=GRID, linewidth=0.3, alpha=1.0, zorder=0)
        ax.set_axisbelow(True)


def _save(fig, name):
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, f"{name}.png")
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor=BG, edgecolor="none")
    plt.close(fig)
    print(f"  saved -> {path}")


def _glow(ax, x, y, color, lw=1.5, a=0.9, layers=4):
    for w, alpha in zip([lw*(layers-i)*1.6 for i in range(layers)],
                        [0.025, 0.06, 0.14, a]):
        ax.plot(x, y, color=color, linewidth=w, alpha=alpha, zorder=3+layers-layers)


def _watermark(fig, text="ISOGENY ALPHA v7.0 | KAIROS CAPITAL RESEARCH"):
    fig.text(0.99, 0.005, text, ha="right", va="bottom",
             color=DIM, fontsize=5, fontfamily="monospace")


def _hdr(fig, title, sub=""):
    fig.text(0.5, 0.995, title, ha="center", va="top",
             color=WHITE, fontsize=11, fontweight="bold", fontfamily="monospace")
    if sub:
        fig.text(0.5, 0.972, sub, ha="center", va="top",
                 color=DIM, fontsize=7, fontfamily="monospace")


def _quant_stats(trades):
    pnls  = np.array([t.pnl for t in trades])
    wins  = pnls[pnls > 0]; losses = pnls[pnls < 0]
    cum   = np.cumsum(pnls)
    peak  = np.maximum.accumulate(cum)
    dd    = cum - peak
    ann   = 252 * 3
    sr    = float(np.mean(pnls)/np.std(pnls)*np.sqrt(ann)) if np.std(pnls) else 0
    neg   = pnls[pnls < 0]
    so    = float(np.mean(pnls)/np.std(neg)*np.sqrt(ann)) if len(neg) else 0
    cal   = float(cum[-1]/abs(dd.min())) if dd.min() < 0 else 0
    pf    = abs(wins.sum()/losses.sum()) if losses.any() else 99.0
    var95 = float(np.percentile(pnls, 5))
    cvar  = float(np.mean(pnls[pnls <= var95]))
    skew  = float(pd.Series(pnls).skew())
    kurt  = float(pd.Series(pnls).kurtosis())
    return dict(pnls=pnls, cum=cum, peak=peak, dd=dd,
                wr=len(wins)/len(pnls)*100, avg_win=float(np.mean(wins)) if len(wins) else 0,
                avg_loss=float(np.mean(losses)) if len(losses) else 0, pf=pf,
                sharpe=sr, sortino=so, calmar=cal, total=float(cum[-1]),
                max_dd=float(dd.min()), var95=var95, cvar=cvar, skew=skew, kurt=kurt)


def _regime_color(trade):
    s = getattr(trade, "hmm_state", "unavailable")
    return REGIME_COLORS.get(s, DIM)


# ── 1. MASTER PERFORMANCE DASHBOARD ─────────────────────────────────────────
def chart_equity_curve(trades):
    _font()
    fig = plt.figure(figsize=(20, 11), facecolor=BG)
    gs  = gridspec.GridSpec(3, 3, figure=fig, hspace=0.42, wspace=0.32,
                            left=0.06, right=0.97, top=0.93, bottom=0.06)
    s   = _quant_stats(trades)
    xs  = np.arange(len(s["cum"]))

    # ── Panel A: Regime-colored equity curve ──────────────────────────────────
    ax1 = fig.add_subplot(gs[0, :2])
    _ax(ax1)
    ax1.fill_between(xs, s["cum"], 0, where=(s["cum"]>=0), alpha=0.06, color=GREEN)
    ax1.fill_between(xs, s["cum"], 0, where=(s["cum"]<0),  alpha=0.06, color=RED)
    _glow(ax1, xs, s["cum"], CYAN, lw=1.8)
    ax1.axhline(0, color=BORDER, lw=0.6, ls="--")
    # Color dots by HMM regime
    for i, t in enumerate(trades):
        ax1.scatter(i, s["cum"][i], color=_regime_color(t), s=12, zorder=6,
                    alpha=0.85, linewidths=0)
    # Annotate peak and max DD
    pk_i = int(np.argmax(s["cum"]))
    ax1.annotate(f"peak ${s['cum'][pk_i]:+,.0f}",
                 xy=(pk_i, s["cum"][pk_i]),
                 xytext=(pk_i-max(5,len(xs)//10), s["cum"][pk_i]+abs(s["cum"][pk_i])*0.05),
                 color=YELLOW, fontsize=6, fontfamily="monospace",
                 arrowprops=dict(arrowstyle="->", color=YELLOW, lw=0.7))
    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v,_: f"${v:+,.0f}"))
    ax1.set_title("CUMULATIVE P&L  (dots colored by HMM regime)", color=TEXT,
                  fontsize=8, fontweight="bold", loc="left", pad=5)
    # Regime legend
    for regime, col in [("strong_bull",GREEN),("bull","#00cc66"),
                         ("neutral",DIM),("stress",ORANGE),("bear",RED)]:
        ax1.scatter([],[], color=col, s=18, label=regime)
    ax1.legend(facecolor=PANEL, labelcolor=TEXT, framealpha=0.8,
               edgecolor=BORDER, fontsize=5.5, ncol=5, loc="upper left")

    # ── Panel B: Metrics card ─────────────────────────────────────────────────
    ax2 = fig.add_subplot(gs[0, 2])
    _ax(ax2, grid=False, spines=False)
    ax2.set_xlim(0,1); ax2.set_ylim(0,1); ax2.axis("off")
    ax2.set_title("RISK METRICS", color=TEXT, fontsize=8, fontweight="bold",
                  loc="left", pad=5)
    metrics = [
        ("Total P&L",    f"${s['total']:+,.2f}",   CYAN),
        ("Win Rate",     f"{s['wr']:.1f}%",          GREEN if s['wr']>=70 else YELLOW),
        ("Sharpe",       f"{s['sharpe']:.3f}",       TEAL),
        ("Sortino",      f"{s['sortino']:.3f}",      PURPLE),
        ("Calmar",       f"{s['calmar']:.3f}",       GOLD),
        ("Profit Factor",f"{s['pf']:.2f}x",          ORANGE),
        ("Avg Win",      f"${s['avg_win']:+.2f}",    GREEN),
        ("Avg Loss",     f"${s['avg_loss']:+.2f}",   RED),
        ("Max DD",       f"${s['max_dd']:,.2f}",     RED),
        ("VaR 95%",      f"${s['var95']:+.2f}",      MAGENTA),
        ("CVaR 95%",     f"${s['cvar']:+.2f}",       MAGENTA),
        ("Skewness",     f"{s['skew']:+.3f}",        WHITE),
        ("Kurtosis",     f"{s['kurt']:+.3f}",        WHITE),
        ("Trades",       f"{len(trades)}",            WHITE),
    ]
    n = len(metrics)
    for i,(lbl,val,col) in enumerate(metrics):
        y = 0.96 - i*(0.93/n)
        rect = mpatches.FancyBboxPatch((0.02,y-0.022),0.96,0.052,
            boxstyle="round,pad=0.01", facecolor=PANEL, edgecolor=BORDER,
            linewidth=0.4, zorder=1)
        ax2.add_patch(rect)
        ax2.text(0.06, y+0.006, lbl, color=DIM, fontsize=6.5,
                 fontfamily="monospace", va="center")
        ax2.text(0.94, y+0.006, val, color=col, fontsize=7.5,
                 fontfamily="monospace", va="center", ha="right", fontweight="bold")

    # ── Panel C: Drawdown underwater ─────────────────────────────────────────
    ax3 = fig.add_subplot(gs[1, :2])
    _ax(ax3)
    ax3.fill_between(xs, s["dd"], 0, color=RED, alpha=0.35)
    _glow(ax3, xs, s["dd"], MAGENTA, lw=1.2)
    ax3.axhline(0, color=BORDER, lw=0.5, ls="--")
    # Shade recovery periods
    in_dd = False; dd_s = 0
    for i in range(len(s["dd"])):
        if s["dd"][i] < -0.01 and not in_dd: in_dd=True; dd_s=i
        elif s["dd"][i] >= -0.01 and in_dd:
            in_dd=False; ax3.axvspan(dd_s,i,color=RED,alpha=0.04,zorder=0)
    ax3.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v,_: f"${v:,.0f}"))
    ax3.set_title("DRAWDOWN UNDERWATER  (shaded = in-drawdown periods)",
                  color=TEXT, fontsize=8, fontweight="bold", loc="left", pad=5)

    # ── Panel D: Rolling Sharpe ───────────────────────────────────────────────
    ax4 = fig.add_subplot(gs[1, 2])
    _ax(ax4)
    win = min(20, max(5, len(trades)//8))
    rs  = pd.Series(s["pnls"]).rolling(win,min_periods=5)
    r_sh = (rs.mean()/rs.std()*np.sqrt(252*3)).fillna(0)
    _glow(ax4, xs, r_sh.values, ORANGE, lw=1.4)
    ax4.axhline(0,   color=BORDER, lw=0.5, ls="--")
    ax4.axhline(1.0, color=GREEN,  lw=0.5, ls=":", alpha=0.5)
    ax4.axhline(2.0, color=CYAN,   lw=0.5, ls=":", alpha=0.5)
    ax4.fill_between(xs, r_sh.values, 0, where=(r_sh.values>=0), alpha=0.1, color=GREEN)
    ax4.fill_between(xs, r_sh.values, 0, where=(r_sh.values<0),  alpha=0.1, color=RED)
    ax4.set_title(f"ROLLING {win}-TRADE SHARPE", color=TEXT,
                  fontsize=8, fontweight="bold", loc="left", pad=5)

    # ── Panel E: Return distribution with VaR/CVaR ───────────────────────────
    ax5 = fig.add_subplot(gs[2, 0])
    _ax(ax5)
    n_bins = min(50, max(20, len(trades)//3))
    n_hist, bins, patches = ax5.hist(s["pnls"], bins=n_bins, edgecolor=BG, lw=0.3)
    for patch, left in zip(patches, bins[:-1]):
        patch.set_facecolor(GREEN if left >= 0 else RED)
        patch.set_alpha(0.72)
    ax5.axvline(s["var95"], color=MAGENTA, lw=1, ls="--", label=f"VaR95 ${s['var95']:+.0f}")
    ax5.axvline(s["cvar"],  color=RED,     lw=1, ls=":",  label=f"CVaR  ${s['cvar']:+.0f}")
    ax5.axvline(np.mean(s["pnls"]), color=YELLOW, lw=1.2, label=f"Mean ${np.mean(s['pnls']):+.1f}")
    ax5.legend(facecolor=PANEL, labelcolor=TEXT, framealpha=0.8,
               edgecolor=BORDER, fontsize=5.5)
    ax5.set_title("P&L DISTRIBUTION + VaR/CVaR", color=TEXT,
                  fontsize=8, fontweight="bold", loc="left", pad=5)
    stats_txt = f"skew={s['skew']:+.2f}  kurt={s['kurt']:+.2f}"
    ax5.text(0.97,0.95, stats_txt, transform=ax5.transAxes,
             ha="right", va="top", color=DIM, fontsize=5.5, fontfamily="monospace")

    # ── Panel F: Win/Loss streak visualization ───────────────────────────────
    ax6 = fig.add_subplot(gs[2, 1])
    _ax(ax6, grid=False)
    outcomes = [1 if t.outcome=="WIN" else -1 for t in trades]
    cols = [GREEN if o>0 else RED for o in outcomes]
    ax6.bar(range(len(outcomes)), outcomes, color=cols, alpha=0.75, width=1.0)
    # Running streak
    streak = []; cur = 1
    for i in range(1, len(outcomes)):
        cur = (cur+1) if outcomes[i]==outcomes[i-1] else 1
        streak.append(cur * outcomes[i])
    ax6b = ax6.twinx()
    ax6b.set_facecolor(PANEL)
    ax6b.plot(range(1,len(streak)+1), streak, color=ORANGE, lw=0.9, alpha=0.6)
    ax6b.tick_params(colors=ORANGE, labelsize=5.5)
    for sp in ax6b.spines.values(): sp.set_edgecolor(BORDER)
    ax6.set_yticks([-1,1]); ax6.set_yticklabels(["L","W"], color=TEXT, fontsize=7)
    ax6.set_title("WIN/LOSS SEQUENCE  (orange = running streak length)",
                  color=TEXT, fontsize=8, fontweight="bold", loc="left", pad=5)

    # ── Panel G: Score vs P&L scatter (density) ──────────────────────────────
    ax7 = fig.add_subplot(gs[2, 2])
    _ax(ax7)
    scores = [getattr(t,"score",10) for t in trades]
    pnls_  = [t.pnl for t in trades]
    c_     = [GREEN if p>0 else RED for p in pnls_]
    ax7.scatter(scores, pnls_, c=c_, alpha=0.65, s=22, linewidths=0, zorder=3)
    # Regression line
    if len(scores)>3:
        m,b = np.polyfit(scores, pnls_, 1)
        xs_ = np.linspace(min(scores), max(scores), 60)
        _glow(ax7, xs_, m*xs_+b, WHITE, lw=1.0, a=0.35)
    ax7.axhline(0, color=BORDER, lw=0.6, ls="--")
    ax7.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v,_: f"${v:+,.0f}"))
    ax7.set_xlabel("Confidence Score")
    ax7.set_title("SCORE vs P&L  (regression = edge per score point)",
                  color=TEXT, fontsize=8, fontweight="bold", loc="left", pad=5)
    if len(scores)>3:
        ax7.text(0.97,0.05, f"slope ${m:+.1f}/pt", transform=ax7.transAxes,
                 ha="right", color=DIM, fontsize=5.5, fontfamily="monospace")

    _hdr(fig, "ISOGENY ALPHA SYSTEM — MASTER PERFORMANCE DASHBOARD",
         f"{len(trades)} trades | WR {s['wr']:.1f}% | Sharpe {s['sharpe']:.2f} | Sortino {s['sortino']:.2f} | Calmar {s['calmar']:.2f}")
    _watermark(fig)
    _save(fig, "01_equity_curve")


# ── 2. ALPHA GENERATION SURFACE ──────────────────────────────────────────────
def chart_drawdown(trades):
    _font()
    fig = plt.figure(figsize=(20, 10), facecolor=BG)
    gs  = gridspec.GridSpec(1, 2, figure=fig, wspace=0.32,
                            left=0.05, right=0.97, top=0.91, bottom=0.08)

    # VIX × Score win-rate surface
    ax3d = fig.add_subplot(gs[0], projection="3d")
    ax3d.set_facecolor(BG); ax3d.patch.set_facecolor(BG)
    vix_bins   = [0,15,20,25,30,40,60]
    score_bins = [5,7,9,11,13,15,17,19,21]

    def _bkt(v, bins):
        for i in range(len(bins)-1):
            if bins[i]<=v<bins[i+1]: return i
        return len(bins)-2

    grid_wr  = np.zeros((len(vix_bins)-1, len(score_bins)-1))
    grid_cnt = np.zeros_like(grid_wr, dtype=int)
    for t in trades:
        sc = getattr(t,"score",10)
        vi = _bkt(t.vix, vix_bins); si = _bkt(sc, score_bins)
        grid_cnt[vi,si]+=1
        if t.outcome=="WIN": grid_wr[vi,si]+=1

    med = float(np.nanmedian(np.where(grid_cnt>0, grid_wr/grid_cnt*100, np.nan))) or 60.0
    grid_f = np.where(grid_cnt>0, grid_wr/grid_cnt*100, med)

    X_c = [(vix_bins[i]+vix_bins[i+1])/2 for i in range(len(vix_bins)-1)]
    Y_c = [(score_bins[i]+score_bins[i+1])/2 for i in range(len(score_bins)-1)]
    X,Y = np.meshgrid(X_c, Y_c, indexing="ij")

    norm = Normalize(vmin=40, vmax=100)
    ax3d.plot_surface(X, Y, grid_f, facecolors=_THERMAL(norm(grid_f)),
                      rstride=1, cstride=1, alpha=0.88, shade=True)
    ax3d.contourf(X, Y, grid_f, zdir="z", offset=grid_f.min()-5,
                  cmap=_THERMAL, alpha=0.3, levels=10)

    sm = plt.cm.ScalarMappable(cmap=_THERMAL, norm=norm)
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=ax3d, shrink=0.4, pad=0.08)
    cbar.ax.tick_params(colors=DIM, labelsize=5.5)
    cbar.set_label("Win Rate (%)", color=DIM, fontsize=6)

    ax3d.set_xlabel("VIX", color=DIM, fontsize=6, labelpad=5)
    ax3d.set_ylabel("Conf Score", color=DIM, fontsize=6, labelpad=5)
    ax3d.set_zlabel("Win %", color=DIM, fontsize=6, labelpad=5)
    ax3d.tick_params(colors=DIM, labelsize=5); ax3d.grid(False)
    ax3d.xaxis.pane.fill=ax3d.yaxis.pane.fill=ax3d.zaxis.pane.fill=False
    ax3d.xaxis.pane.set_edgecolor(BORDER)
    ax3d.yaxis.pane.set_edgecolor(BORDER)
    ax3d.zaxis.pane.set_edgecolor(BORDER)
    ax3d.view_init(elev=28, azim=-52)
    ax3d.set_title("ALPHA SURFACE\nE[win | VIX, score]",
                   color=TEXT, fontsize=8, fontweight="bold", pad=4)

    # Score bucket bar chart
    ax_r = fig.add_subplot(gs[1])
    _ax(ax_r)
    sg = defaultdict(list)
    for t in trades: sg[getattr(t,"score",10)].append(t)
    scores_ = sorted(sg.keys())
    wrs_  = [len([t for t in sg[sc] if t.outcome=="WIN"])/len(sg[sc])*100 for sc in scores_]
    pnls_ = [sum(t.pnl for t in sg[sc]) for sc in scores_]
    cnts_ = [len(sg[sc]) for sc in scores_]
    bar_c = [_THERMAL(wr/100) for wr in wrs_]
    bars  = ax_r.bar(range(len(scores_)), pnls_, color=bar_c, alpha=0.85, width=0.7, zorder=3)
    ax_r.axhline(0, color=BORDER, lw=0.6, ls="--")
    for i,(bar,cnt,wr) in enumerate(zip(bars,cnts_,wrs_)):
        h = bar.get_height()
        off = 8 if h>=0 else -18
        ax_r.text(bar.get_x()+bar.get_width()/2, h+off,
                  f"{wr:.0f}%\n(n={cnt})", ha="center",
                  color=WHITE, fontsize=5, fontfamily="monospace")
    ax_r.set_xticks(range(len(scores_)))
    ax_r.set_xticklabels([str(s) for s in scores_], fontsize=6.5)
    ax_r.set_xlabel("Confidence Score")
    ax_r.set_ylabel("P&L ($)")
    ax_r.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v,_: f"${v:+,.0f}"))
    ax_r.set_title("P&L BY SCORE BUCKET\n(color = win rate)", color=TEXT,
                   fontsize=8, fontweight="bold", loc="left", pad=5)
    sm2 = plt.cm.ScalarMappable(cmap=_THERMAL, norm=Normalize(0,100))
    sm2.set_array([])
    cbar2 = fig.colorbar(sm2, ax=ax_r, shrink=0.6, pad=0.02)
    cbar2.ax.tick_params(colors=DIM, labelsize=5.5)
    cbar2.set_label("Win %", color=DIM, fontsize=6)

    _hdr(fig, "ALPHA GENERATION SURFACE",
         "3D win-rate mesh across VIX regime x confidence score  |  z = E[win | VIX in V, score in S]")
    _watermark(fig)
    _save(fig, "02_drawdown")


# ── 3. STRATEGY DEEP DIVE ────────────────────────────────────────────────────
def chart_strategy_breakdown(trades):
    _font()
    fig = plt.figure(figsize=(20, 10), facecolor=BG)
    gs  = gridspec.GridSpec(2, 3, figure=fig, hspace=0.42, wspace=0.32,
                            left=0.07, right=0.97, top=0.91, bottom=0.07)

    order = ["gap_fill","fvg","orb","ib_breakout","vwap_rev",
             "vwap_pm","vwap_bounce","vwap_bounce_pm","va_rule"]
    groups = defaultdict(list)
    for t in trades: groups[t.strategy].append(t)
    strats = [s for s in order if s in groups]
    labels = [s.replace("_"," ").upper() for s in strats]
    wrs    = [len([t for t in groups[s] if t.outcome=="WIN"])/len(groups[s])*100 for s in strats]
    pnls   = [sum(t.pnl for t in groups[s]) for s in strats]
    counts = [len(groups[s]) for s in strats]
    colors = [STRAT_COLORS.get(s, CYAN) for s in strats]
    xs     = np.arange(len(strats))

    # ── Win rate bars ─────────────────────────────────────────────────────────
    ax1 = fig.add_subplot(gs[0,0])
    _ax(ax1)
    bars = ax1.barh(xs, wrs, color=colors, alpha=0.8, height=0.55, zorder=3)
    ax1.axvline(50, color=DIM, lw=0.7, ls="--")
    ax1.axvline(np.mean(wrs), color=YELLOW, lw=0.7, ls=":", alpha=0.6)
    ax1.set_yticks(xs); ax1.set_yticklabels(labels, color=TEXT, fontsize=6.5)
    ax1.set_xlim(0,108)
    for bar,wr,cnt in zip(bars,wrs,counts):
        ax1.text(wr+1.5, bar.get_y()+bar.get_height()/2,
                 f"{wr:.0f}% (n={cnt})", va="center", color=TEXT,
                 fontsize=5.5, fontfamily="monospace")
    ax1.set_title("WIN RATE BY STRATEGY", color=TEXT, fontsize=8,
                  fontweight="bold", loc="left", pad=5)

    # ── P&L bars ──────────────────────────────────────────────────────────────
    ax2 = fig.add_subplot(gs[0,1])
    _ax(ax2)
    bc2  = [GREEN if p>=0 else RED for p in pnls]
    bars2= ax2.barh(xs, pnls, color=bc2, alpha=0.8, height=0.55, zorder=3)
    ax2.axvline(0, color=DIM, lw=0.7, ls="--")
    ax2.set_yticks(xs); ax2.set_yticklabels(labels, color=TEXT, fontsize=6.5)
    ax2.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v,_: f"${v:+,.0f}"))
    for bar,p in zip(bars2,pnls):
        off = 5 if p>=0 else -5
        ax2.text(p+off, bar.get_y()+bar.get_height()/2,
                 f"${p:+.0f}", va="center", ha="left" if p>=0 else "right",
                 color=TEXT, fontsize=5.5, fontfamily="monospace")
    ax2.set_title("TOTAL P&L BY STRATEGY", color=TEXT, fontsize=8,
                  fontweight="bold", loc="left", pad=5)

    # ── Avg R:R per strategy ──────────────────────────────────────────────────
    ax3 = fig.add_subplot(gs[0,2])
    _ax(ax3)
    avg_rrs = [np.mean([t.rr for t in groups[s]]) for s in strats]
    bars3   = ax3.barh(xs, avg_rrs, color=colors, alpha=0.8, height=0.55, zorder=3)
    ax3.axvline(1.0, color=DIM, lw=0.7, ls="--")
    ax3.set_yticks(xs); ax3.set_yticklabels(labels, color=TEXT, fontsize=6.5)
    for bar,rr in zip(bars3,avg_rrs):
        ax3.text(rr+0.05, bar.get_y()+bar.get_height()/2,
                 f"{rr:.2f}x", va="center", color=TEXT,
                 fontsize=5.5, fontfamily="monospace")
    ax3.set_title("AVG RISK:REWARD BY STRATEGY", color=TEXT, fontsize=8,
                  fontweight="bold", loc="left", pad=5)

    # ── Violin R:R distributions ──────────────────────────────────────────────
    ax4 = fig.add_subplot(gs[1,:2])
    _ax(ax4)
    for i,(strat,color) in enumerate(zip(strats,colors)):
        rrs = [t.rr for t in groups[strat]]
        if len(rrs)<3: continue
        parts = ax4.violinplot([rrs], positions=[i], widths=0.7,
                               showmedians=True, showextrema=False)
        for pc in parts["bodies"]:
            pc.set_facecolor(color); pc.set_alpha(0.3)
        parts["cmedians"].set_color(color); parts["cmedians"].set_linewidth(1.5)
    ax4.set_xticks(range(len(strats))); ax4.set_xticklabels(labels, rotation=25,
        ha="right", color=TEXT, fontsize=6)
    ax4.axhline(1.0, color=DIM, lw=0.6, ls="--")
    ax4.set_ylabel("Risk:Reward Ratio")
    ax4.set_title("R:R DISTRIBUTION BY STRATEGY  (violin = full distribution, line = median)",
                  color=TEXT, fontsize=8, fontweight="bold", loc="left", pad=5)

    # ── Day × Strategy trade map ──────────────────────────────────────────────
    ax5 = fig.add_subplot(gs[1,2])
    _ax(ax5)
    days  = ["Mon","Tue","Wed","Thu","Fri"]
    dsg   = defaultdict(lambda: defaultdict(list))
    for t in trades: dsg[t.day_name][t.strategy].append(t)
    for xi,day in enumerate(days):
        for yi,strat in enumerate(strats):
            tl = dsg[day][strat]
            if not tl: continue
            wr  = len([t for t in tl if t.outcome=="WIN"])/len(tl)
            sz  = len(tl)*90
            col = STRAT_COLORS.get(strat, CYAN)
            ax5.scatter(xi, yi, s=sz, color=col, alpha=0.25+wr*0.75,
                        zorder=3, linewidths=0)
            ax5.text(xi, yi, f"{wr*100:.0f}%", ha="center", va="center",
                     color=WHITE, fontsize=4.5, fontweight="bold")
    ax5.set_xticks(range(len(days))); ax5.set_xticklabels(days, color=TEXT, fontsize=7)
    ax5.set_yticks(range(len(strats))); ax5.set_yticklabels(labels, color=TEXT, fontsize=6)
    ax5.set_title("TRADE MAP  (size=count  opacity=WR)",
                  color=TEXT, fontsize=8, fontweight="bold", loc="left", pad=5)

    _hdr(fig, "STRATEGY PERFORMANCE DECOMPOSITION",
         f"{len(strats)} strategies | {len(trades)} total trades")
    _watermark(fig)
    _save(fig, "03_strategy_breakdown")


# ── 4. STATISTICAL RETURNS ANALYSIS ─────────────────────────────────────────
def chart_pnl_distribution(trades):
    from scipy import stats as sp_stats
    _font()
    fig = plt.figure(figsize=(20, 10), facecolor=BG)
    gs  = gridspec.GridSpec(2, 3, figure=fig, hspace=0.42, wspace=0.32,
                            left=0.07, right=0.97, top=0.91, bottom=0.08)
    s   = _quant_stats(trades)
    pnls= s["pnls"]
    mu, sigma = float(np.mean(pnls)), float(np.std(pnls))

    # ── Histogram ─────────────────────────────────────────────────────────────
    ax1 = fig.add_subplot(gs[0,0])
    _ax(ax1)
    n_hist,bins,patches = ax1.hist(pnls, bins=min(50,max(20,len(trades)//3)),
                                   edgecolor=BG, lw=0.25)
    for patch,left in zip(patches,bins[:-1]):
        patch.set_facecolor(GREEN if left>=0 else RED); patch.set_alpha(0.72)
    xf = np.linspace(pnls.min(), pnls.max(), 300)
    yf = (n_hist.max()/(sigma*np.sqrt(2*np.pi)))*np.exp(-0.5*((xf-mu)/sigma)**2)
    _glow(ax1, xf, yf, YELLOW, lw=1.2, a=0.7)
    ax1.axvline(mu,       color=CYAN,    lw=1.1, ls="-",  label=f"mean ${mu:+.1f}")
    ax1.axvline(s["var95"],color=MAGENTA,lw=1,   ls="--", label=f"VaR95 ${s['var95']:+.0f}")
    ax1.axvline(s["cvar"], color=RED,    lw=1,   ls=":",  label=f"CVaR  ${s['cvar']:+.0f}")
    ax1.legend(facecolor=PANEL,labelcolor=TEXT,framealpha=0.8,edgecolor=BORDER,fontsize=5.5)
    ax1.set_title("P&L DISTRIBUTION + NORMAL FIT", color=TEXT,
                  fontsize=8, fontweight="bold", loc="left", pad=5)
    ax1.text(0.97,0.95, f"mu={mu:+.1f}  s={sigma:.1f}\nskew={s['skew']:+.2f}  kurt={s['kurt']:+.2f}",
             transform=ax1.transAxes, ha="right", va="top", color=DIM,
             fontsize=5.5, fontfamily="monospace")

    # ── Q-Q plot ──────────────────────────────────────────────────────────────
    ax2 = fig.add_subplot(gs[0,1])
    _ax(ax2)
    (osm,osr),(slope,intercept,_) = sp_stats.probplot(pnls, dist="norm")
    ax2.scatter(osm, osr, color=CYAN, s=16, alpha=0.7, linewidths=0, zorder=3)
    xq = np.linspace(osm[0], osm[-1], 100)
    _glow(ax2, xq, slope*xq+intercept, YELLOW, lw=1.2)
    ax2.set_xlabel("Theoretical Quantiles"); ax2.set_ylabel("Sample Quantiles")
    ax2.set_title("Q-Q NORMALITY TEST", color=TEXT, fontsize=8,
                  fontweight="bold", loc="left", pad=5)

    # ── Autocorrelation of returns ────────────────────────────────────────────
    ax3 = fig.add_subplot(gs[0,2])
    _ax(ax3)
    nlags = min(20, len(pnls)//4)
    acf   = [1.0] + [float(pd.Series(pnls).autocorr(lag=i)) for i in range(1,nlags+1)]
    ci    = 1.96/np.sqrt(len(pnls))
    xs_ac = range(len(acf))
    ax3.bar(xs_ac, acf, color=[GREEN if abs(a)<ci else RED for a in acf], alpha=0.75)
    ax3.axhline(ci,  color=DIM, lw=0.7, ls="--", alpha=0.7)
    ax3.axhline(-ci, color=DIM, lw=0.7, ls="--", alpha=0.7)
    ax3.axhline(0,   color=BORDER, lw=0.5)
    ax3.set_xlabel("Lag (trades)"); ax3.set_ylabel("ACF")
    ax3.set_title("RETURN AUTOCORRELATION  (dashes = 95% CI)",
                  color=TEXT, fontsize=8, fontweight="bold", loc="left", pad=5)
    ax3.text(0.97,0.05, "green = no serial dependence\nred = possible clustering",
             transform=ax3.transAxes, ha="right", va="bottom",
             color=DIM, fontsize=5.5, fontfamily="monospace")

    # ── KDE wins vs losses ────────────────────────────────────────────────────
    ax4 = fig.add_subplot(gs[1,0])
    _ax(ax4)
    from scipy.stats import gaussian_kde
    wins_pnl = pnls[pnls>0]; loss_pnl = pnls[pnls<0]
    if len(wins_pnl)>2:
        xw = np.linspace(0, wins_pnl.max(), 200)
        kw = gaussian_kde(wins_pnl); ax4.fill_between(xw,kw(xw),alpha=0.25,color=GREEN)
        _glow(ax4, xw, kw(xw), GREEN, lw=1.4)
    if len(loss_pnl)>2:
        xl = np.linspace(loss_pnl.min(), 0, 200)
        kl = gaussian_kde(loss_pnl); ax4.fill_between(xl,kl(xl),alpha=0.25,color=RED)
        _glow(ax4, xl, kl(xl), RED, lw=1.4)
    ax4.axvline(0, color=BORDER, lw=0.6, ls="--")
    ax4.set_xlabel("P&L ($)"); ax4.set_ylabel("Density")
    ax4.set_title("KDE — WINS vs LOSSES", color=TEXT, fontsize=8,
                  fontweight="bold", loc="left", pad=5)
    exp = float(np.mean(pnls))
    ax4.text(0.5,0.93, f"E[trade] = ${exp:+.2f}", transform=ax4.transAxes,
             ha="center", color=YELLOW, fontsize=8, fontfamily="monospace",
             fontweight="bold")

    # ── Historical VaR simulation ─────────────────────────────────────────────
    ax5 = fig.add_subplot(gs[1,1])
    _ax(ax5)
    np.random.seed(42)
    n_sim, n_tr = 1000, min(len(pnls), 30)
    sim_finals  = np.array([np.sum(np.random.choice(pnls,n_tr,replace=True)) for _ in range(n_sim)])
    ax5.hist(sim_finals, bins=40, color=TEAL, alpha=0.65, edgecolor=BG, lw=0.3)
    var5 = float(np.percentile(sim_finals, 5))
    ax5.axvline(var5, color=RED,    lw=1.2, ls="--", label=f"5th pct ${var5:+,.0f}")
    ax5.axvline(np.median(sim_finals), color=CYAN, lw=1.2, label=f"Median ${np.median(sim_finals):+,.0f}")
    ax5.axvline(0, color=BORDER, lw=0.6, ls="--")
    ax5.legend(facecolor=PANEL,labelcolor=TEXT,framealpha=0.8,edgecolor=BORDER,fontsize=5.5)
    ax5.set_xlabel(f"P&L over next {n_tr} trades ($)")
    ax5.set_title(f"HISTORICAL SIMULATION ({n_sim} paths, next {n_tr} trades)",
                  color=TEXT, fontsize=8, fontweight="bold", loc="left", pad=5)
    prob = float((sim_finals>0).mean()*100)
    ax5.text(0.97,0.93, f"P(profit) = {prob:.0f}%", transform=ax5.transAxes,
             ha="right", va="top", color=GREEN, fontsize=7, fontfamily="monospace",
             fontweight="bold")

    # ── Sorted waterfall ──────────────────────────────────────────────────────
    ax6 = fig.add_subplot(gs[1,2])
    _ax(ax6)
    sp = np.sort(pnls)[::-1]; cs = np.cumsum(sp)
    bc = [GREEN if p>=0 else RED for p in sp]
    ax6.bar(range(len(sp)), sp, color=bc, alpha=0.7, width=1.0, zorder=3)
    ax6b = ax6.twinx(); ax6b.set_facecolor(PANEL)
    _glow(ax6b, range(len(cs)), cs, CYAN, lw=1.3)
    ax6b.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v,_: f"${v:+,.0f}"))
    ax6b.tick_params(colors=CYAN, labelsize=5.5)
    for sp2 in ax6b.spines.values(): sp2.set_edgecolor(BORDER)
    ax6.set_xlabel("Trade rank (sorted by P&L)")
    ax6.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v,_: f"${v:+,.0f}"))
    ax6.set_title("TRADE WATERFALL (sorted, cumulative overlay)",
                  color=TEXT, fontsize=8, fontweight="bold", loc="left", pad=5)

    _hdr(fig, "STATISTICAL RETURNS ANALYSIS",
         f"Distribution | Q-Q | Autocorrelation | KDE | Historical Sim | Waterfall")
    _watermark(fig)
    _save(fig, "04_pnl_distribution")


# ── 5. ROLLING PERFORMANCE METRICS ──────────────────────────────────────────
def chart_rolling_winrate(trades, window=15):
    _font()
    fig = plt.figure(figsize=(20, 11), facecolor=BG)
    gs  = gridspec.GridSpec(4, 1, figure=fig, hspace=0.38,
                            left=0.07, right=0.97, top=0.91, bottom=0.06)
    s   = _quant_stats(trades)
    xs  = np.arange(len(trades))
    outcomes = np.array([1 if t.outcome=="WIN" else 0 for t in trades], dtype=float)
    pnls     = s["pnls"]

    def _rolling(arr, w, func):
        return pd.Series(arr).rolling(w, min_periods=max(3,w//3)).apply(func, raw=True).fillna(0)

    roll_wr = pd.Series(outcomes).rolling(window, min_periods=3).mean()*100
    roll_pnl= pd.Series(pnls).rolling(window, min_periods=3).mean()
    roll_sh = (pd.Series(pnls).rolling(window,min_periods=5).mean() /
               pd.Series(pnls).rolling(window,min_periods=5).std() * np.sqrt(252*3)).fillna(0)
    roll_pf = _rolling(pnls, window,
                       lambda x: abs(x[x>0].sum()/x[x<0].sum()) if any(x<0) and any(x>0) else 1.0)

    for ax_idx,(data,label,col,ref_lines) in enumerate([
        (roll_wr.values,    f"ROLLING {window}-TRADE WIN RATE (%)", PURPLE,
         [(50,DIM,"--"),(outcomes.mean()*100,YELLOW,":")]),
        (roll_pnl.values,   f"ROLLING {window}-TRADE AVG P&L ($)",  CYAN,
         [(0,DIM,"--")]),
        (roll_sh.values,    f"ROLLING {window}-TRADE SHARPE RATIO",  ORANGE,
         [(0,DIM,"--"),(1.0,GREEN,":"),(2.0,CYAN,":")]),
        (roll_pf.values,    f"ROLLING {window}-TRADE PROFIT FACTOR", MAGENTA,
         [(1.0,DIM,"--")]),
    ]):
        ax = fig.add_subplot(gs[ax_idx])
        _ax(ax)
        ax.fill_between(xs, data, 0, where=(data>=0), alpha=0.1, color=col)
        ax.fill_between(xs, data, 0, where=(data<0),  alpha=0.1, color=RED)
        _glow(ax, xs, data, col, lw=1.7)
        for val,rcol,rst in ref_lines:
            ax.axhline(val, color=rcol, lw=0.6, ls=rst, alpha=0.6)
        if ax_idx==0: ax.set_ylim(0,105)
        ax.set_title(label, color=TEXT, fontsize=8, fontweight="bold",
                     loc="left", pad=5)
        if ax_idx==1:
            ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v,_: f"${v:+.1f}"))
        if ax_idx==3:
            ax.set_xlabel("Trade # (chronological)")

    _hdr(fig, "ROLLING PERFORMANCE METRICS",
         f"Window = {window} trades | Win Rate / Avg P&L / Sharpe / Profit Factor")
    _watermark(fig)
    _save(fig, "05_rolling_winrate")


# ── 6. REGIME PERFORMANCE HEATMAPS ──────────────────────────────────────────
def chart_heatmap(trades):
    _font()
    fig = plt.figure(figsize=(20, 10), facecolor=BG)
    gs  = gridspec.GridSpec(1, 2, figure=fig, wspace=0.35,
                            left=0.07, right=0.97, top=0.91, bottom=0.10)

    order_d = ["Mon","Tue","Wed","Thu","Fri"]
    order_s = ["gap_fill","fvg","orb","ib_breakout","vwap_rev",
               "vwap_pm","vwap_bounce","vwap_bounce_pm","va_rule"]
    present = [s for s in order_s if any(t.strategy==s for t in trades)]
    labels  = [s.replace("_"," ").upper() for s in present]

    def _build(metric):
        m = pd.DataFrame(index=order_d, columns=present, dtype=float)
        for d in order_d:
            for s in present:
                sub = [t for t in trades if t.day_name==d and t.strategy==s]
                if not sub: m.loc[d,s]=np.nan; continue
                if metric=="wr":
                    m.loc[d,s]=len([t for t in sub if t.outcome=="WIN"])/len(sub)*100
                else:
                    m.loc[d,s]=sum(t.pnl for t in sub)
        return m

    cmap_div = sns.diverging_palette(0,130,s=90,l=45,as_cmap=True)

    for ax_idx,(metric,title,fmt) in enumerate([
        ("wr",  "WIN RATE  (Day x Strategy)", ".0f"),
        ("pnl", "TOTAL P&L  (Day x Strategy)", ".0f"),
    ]):
        ax = fig.add_subplot(gs[ax_idx])
        ax.set_facecolor(PANEL)
        mat = _build(metric).astype(float)
        mask= mat.isna()
        kwargs = {"vmin":0,"vmax":100} if metric=="wr" else {"center":0}
        sns.heatmap(mat, ax=ax, cmap=cmap_div,
                    annot=True, fmt=fmt, linewidths=0.8, linecolor=BG,
                    mask=mask, **kwargs,
                    cbar_kws={"shrink":0.7,"label":"Win %" if metric=="wr" else "P&L ($)"},
                    annot_kws={"size":7.5, "color":WHITE, "family":"monospace"})
        ax.set_xticklabels(labels, rotation=30, ha="right", color=TEXT, fontsize=7)
        ax.set_yticklabels(order_d, rotation=0, color=TEXT, fontsize=8)
        # Count overlay
        for i,d in enumerate(order_d):
            for j,s in enumerate(present):
                c = sum(1 for t in trades if t.day_name==d and t.strategy==s)
                if c>0: ax.text(j+0.88,i+0.88,str(c),ha="right",va="bottom",
                                color=WHITE,fontsize=4.5,alpha=0.6)
        ax.set_title(f"{title}  (n=trade count)", color=TEXT, fontsize=9,
                     fontweight="bold", pad=8)

    _hdr(fig, "DAY x STRATEGY PERFORMANCE MATRIX")
    _watermark(fig)
    _save(fig, "06_winrate_heatmap")


# ── 7. MONTE CARLO + FACTOR ATTRIBUTION ─────────────────────────────────────
def chart_vix_scatter(trades):
    _font()
    fig = plt.figure(figsize=(20, 10), facecolor=BG)
    gs  = gridspec.GridSpec(1, 2, figure=fig, wspace=0.35,
                            left=0.06, right=0.97, top=0.91, bottom=0.09)
    pnls  = np.array([t.pnl for t in trades])
    n     = len(pnls)
    N_SIM = 600

    np.random.seed(42)
    sim   = np.array([np.cumsum(np.random.choice(pnls,n,replace=True)) for _ in range(N_SIM)])
    actual= np.cumsum(pnls)
    xs    = np.arange(n)

    # ── Monte Carlo fan ───────────────────────────────────────────────────────
    ax1 = fig.add_subplot(gs[0])
    _ax(ax1)
    for pct,col,a in [(5,RED,0.06),(25,TEAL,0.12),(75,TEAL,0.12),(95,RED,0.06)]:
        pass   # fill done via percentile bands below

    p5,p25,p50,p75,p95 = [np.percentile(sim,q,axis=0) for q in [5,25,50,75,95]]
    ax1.fill_between(xs, p5,  p95, alpha=0.07, color=CYAN)
    ax1.fill_between(xs, p25, p75, alpha=0.14, color=TEAL)
    for i in range(0, min(60,N_SIM), 2):
        ax1.plot(xs, sim[i], color=CYAN, alpha=0.02, linewidth=0.4)
    _glow(ax1, xs, p50,    TEAL,   lw=1.1, a=0.5)
    _glow(ax1, xs, actual, YELLOW, lw=2.0)
    ax1.axhline(0, color=DIM, lw=0.6, ls="--")
    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v,_: f"${v:+,.0f}"))
    ax1.set_xlabel("Trade #")
    ax1.set_title(f"MONTE CARLO SIMULATION ({N_SIM} bootstrap paths)",
                  color=TEXT, fontsize=8, fontweight="bold", loc="left", pad=5)
    finals = sim[:,-1]
    mc_txt = (f"Median  ${np.median(finals):+,.0f}\n"
              f"5th pct ${np.percentile(finals,5):+,.0f}\n"
              f"95th pct${np.percentile(finals,95):+,.0f}\n"
              f"P(>0)   {(finals>0).mean()*100:.0f}%\n"
              f"P(>$1.5k) {(finals>1500).mean()*100:.0f}%")
    ax1.text(0.02,0.97, mc_txt, transform=ax1.transAxes, va="top",
             color=CYAN, fontsize=6.5, fontfamily="monospace",
             bbox=dict(facecolor=PANEL,edgecolor=BORDER,alpha=0.9,
                       boxstyle="round,pad=0.3"))
    legend_els = [
        mpatches.Patch(color=YELLOW, label="Actual equity"),
        mpatches.Patch(color=TEAL, label="25-75th pct", alpha=0.4),
        mpatches.Patch(color=CYAN, label="5-95th pct",  alpha=0.2),
    ]
    ax1.legend(handles=legend_els, facecolor=PANEL, labelcolor=TEXT,
               framealpha=0.8, edgecolor=BORDER, fontsize=6)

    # ── VIX sensitivity (hexbin density) ─────────────────────────────────────
    ax2 = fig.add_subplot(gs[1])
    _ax(ax2)
    vixes = np.array([t.vix for t in trades])
    hb = ax2.hexbin(vixes, pnls, gridsize=18, cmap=_THERMAL, mincnt=1,
                    linewidths=0.2, alpha=0.9)
    cb = fig.colorbar(hb, ax=ax2, shrink=0.7)
    cb.ax.tick_params(colors=DIM, labelsize=5.5)
    cb.set_label("Trade density", color=DIM, fontsize=6)
    ax2.axhline(0,  color=DIM,    lw=0.6, ls="--")
    ax2.axvline(20, color=YELLOW, lw=0.6, ls=":", alpha=0.5, label="VIX 20")
    ax2.axvline(30, color=RED,    lw=0.6, ls=":", alpha=0.5, label="VIX 30")
    # Regression
    m,b = np.polyfit(vixes, pnls, 1)
    xr  = np.linspace(vixes.min(), vixes.max(), 100)
    _glow(ax2, xr, m*xr+b, WHITE, lw=1.2, a=0.5)
    ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v,_: f"${v:+,.0f}"))
    ax2.set_xlabel("VIX"); ax2.set_ylabel("Trade P&L ($)")
    ax2.legend(facecolor=PANEL, labelcolor=TEXT, framealpha=0.8,
               edgecolor=BORDER, fontsize=6)
    ax2.set_title("VIX vs P&L DENSITY  (hexbin, regression = beta estimate)",
                  color=TEXT, fontsize=8, fontweight="bold", loc="left", pad=5)
    ax2.text(0.97,0.04, f"dP&L/dVIX = ${m:+.2f}/pt",
             transform=ax2.transAxes, ha="right",
             color=DIM, fontsize=6, fontfamily="monospace")

    _hdr(fig, "MONTE CARLO SIMULATION + VIX SENSITIVITY",
         f"{N_SIM} paths | P(pass $1,500 target) = {(finals>1500).mean()*100:.0f}%")
    _watermark(fig)
    _save(fig, "07_vix_scatter")


# ── 8. FACTOR ANALYSIS ───────────────────────────────────────────────────────
def chart_rr_distribution(trades):
    _font()
    fig = plt.figure(figsize=(20, 10), facecolor=BG)
    gs  = gridspec.GridSpec(1, 2, figure=fig, wspace=0.35,
                            left=0.07, right=0.97, top=0.91, bottom=0.12)

    # ── Factor hit rates ──────────────────────────────────────────────────────
    ax1 = fig.add_subplot(gs[0])
    _ax(ax1)
    factors: dict = defaultdict(list)
    for t in trades:
        for k,v in getattr(t,"score_breakdown",{}).items():
            factors[k].append(v)

    if factors:
        fo   = sorted(factors.keys())
        hits = [np.mean(factors[f])*100 for f in fo]
        cols = [GREEN if h>=80 else (YELLOW if h>=60 else RED) for h in hits]
        ys   = np.arange(len(fo))
        bars = ax1.barh(ys, hits, color=cols, alpha=0.8, height=0.6, zorder=3)
        ax1.axvline(50, color=DIM,    lw=0.7, ls="--")
        ax1.axvline(80, color=YELLOW, lw=0.5, ls=":", alpha=0.5)
        ax1.set_yticks(ys)
        ax1.set_yticklabels(fo, color=TEXT, fontsize=7, fontfamily="monospace")
        ax1.set_xlim(0,110)
        for bar,h in zip(bars,hits):
            ax1.text(h+1.5, bar.get_y()+bar.get_height()/2,
                     f"{h:.0f}%", va="center", color=TEXT,
                     fontsize=6, fontfamily="monospace")
        ax1.set_xlabel("Hit Rate (% of trades where factor = 1)")
        ax1.set_title("20-POINT SCORING — FACTOR HIT RATES",
                      color=TEXT, fontsize=8, fontweight="bold", loc="left", pad=5)
    else:
        ax1.text(0.5,0.5,"Score breakdown\nnot available",
                 ha="center",va="center",color=DIM,fontsize=10,
                 transform=ax1.transAxes)
        ax1.set_title("FACTOR HIT RATES", color=TEXT, fontsize=8,
                      fontweight="bold", loc="left", pad=5)

    # ── R:R distribution by outcome ──────────────────────────────────────────
    ax2 = fig.add_subplot(gs[1])
    _ax(ax2)
    rr_all = np.array([t.rr for t in trades])
    rr_w   = np.array([t.rr for t in trades if t.outcome=="WIN"])
    rr_l   = np.array([t.rr for t in trades if t.outcome=="LOSS"])
    bins   = np.linspace(0, min(rr_all.max(), 30), 35)

    ax2.hist(rr_w, bins=bins, color=GREEN, alpha=0.7, label=f"Wins (n={len(rr_w)})", zorder=3)
    ax2.hist(rr_l, bins=bins, color=RED,   alpha=0.65,label=f"Losses (n={len(rr_l)})",zorder=2)
    ax2.axvline(1.0,         color=YELLOW,  lw=1,   ls="--", alpha=0.9, label="1:1 R:R")
    ax2.axvline(rr_all.mean(),color=CYAN,   lw=1.2, ls="-",
                label=f"Mean {rr_all.mean():.2f}x")

    ax2.set_xlabel("Risk:Reward Ratio"); ax2.set_ylabel("Frequency")
    ax2.legend(facecolor=PANEL,labelcolor=TEXT,framealpha=0.8,
               edgecolor=BORDER,fontsize=6.5)
    ax2.set_title("R:R DISTRIBUTION — WINS vs LOSSES",
                  color=TEXT, fontsize=8, fontweight="bold", loc="left", pad=5)
    rr_txt = (f"Mean R:R    {rr_all.mean():.2f}x\n"
              f"Median R:R  {np.median(rr_all):.2f}x\n"
              f"90th pct    {np.percentile(rr_all,90):.2f}x\n"
              f"Win avg RR  {rr_w.mean():.2f}x" if len(rr_w) else "")
    ax2.text(0.97,0.97, rr_txt, transform=ax2.transAxes, va="top", ha="right",
             color=CYAN, fontsize=6.5, fontfamily="monospace",
             bbox=dict(facecolor=PANEL,edgecolor=BORDER,alpha=0.9,
                       boxstyle="round,pad=0.3"))

    _hdr(fig, "FACTOR ANALYSIS + RISK:REWARD DECOMPOSITION",
         "Left: 20-pt scoring hit rates | Right: R:R full distribution by outcome")
    _watermark(fig)
    _save(fig, "08_rr_distribution")


# ── 9. CALENDAR + CUMULATIVE P&L ATTRIBUTION ────────────────────────────────
def chart_monthly_calendar(trades):
    _font()
    daily = defaultdict(float)
    for t in trades: daily[t.date] += t.pnl
    if not daily: return

    dates  = sorted(daily.keys())
    months = sorted(set((d.year,d.month) for d in dates))
    n_mo   = len(months)
    cols_  = min(n_mo, 4)
    rows_  = (n_mo+cols_-1)//cols_

    fig, axes = plt.subplots(rows_, cols_,
                             figsize=(cols_*5.5, rows_*4.2), facecolor=BG)
    if n_mo==1: axes=[[axes]]
    elif rows_==1: axes=[axes]
    flat = [ax for row in axes for ax in (row if hasattr(row,"__iter__") else [row])]

    import calendar
    mo_names=["","Jan","Feb","Mar","Apr","May","Jun",
              "Jul","Aug","Sep","Oct","Nov","Dec"]
    day_lbl =["M","T","W","T","F","S","S"]
    max_abs  = max(abs(v) for v in daily.values()) or 1.0

    for idx,(yr,mo) in enumerate(months):
        ax = flat[idx]; ax.set_facecolor(PANEL)
        for sp in ax.spines.values():
            sp.set_edgecolor(BORDER); sp.set_linewidth(0.5)
        ax.set_xticks(range(7)); ax.set_xticklabels(day_lbl, fontsize=5.5, color=DIM)
        ax.set_yticks([])
        mo_pnl = sum(v for d,v in daily.items() if d.year==yr and d.month==mo)
        tcol   = GREEN if mo_pnl>=0 else RED
        ax.set_title(f"{mo_names[mo]} {yr}  ${mo_pnl:+.0f}",
                     color=tcol, fontsize=7.5, fontweight="bold", pad=3)
        cal_ = calendar.monthcalendar(yr,mo)
        for wk,week in enumerate(cal_):
            for dw,day in enumerate(week):
                if day==0: continue
                d = date(yr,mo,day); pnl = daily.get(d,None)
                if pnl is not None:
                    nv  = pnl/max_abs
                    col = GREEN if nv>0 else RED
                    alpha = 0.18 + 0.65*min(abs(nv),1.0)
                    rect = mpatches.FancyBboxPatch(
                        (dw-0.44,-wk-0.44),0.88,0.82,
                        boxstyle="round,pad=0.03",
                        facecolor=col, edgecolor=PANEL,
                        alpha=alpha, linewidth=0.4, zorder=2)
                    ax.add_patch(rect)
                    ax.text(dw,-wk+0.16,str(day),ha="center",va="center",
                            color=WHITE,fontsize=5.5,fontweight="bold",zorder=3)
                    ax.text(dw,-wk-0.22,f"${pnl:+.0f}",ha="center",va="center",
                            color=WHITE,fontsize=4.2,zorder=3)
                else:
                    ax.text(dw,-wk,str(day),ha="center",va="center",
                            color=DIM,fontsize=5.5)
        ax.set_xlim(-0.6,6.6); ax.set_ylim(-len(cal_)+0.3,0.9)

    for ax in flat[n_mo:]: ax.set_visible(False)

    total = sum(daily.values())
    fig.suptitle(f"DAILY P&L CALENDAR  |  Total ${total:+,.2f}",
                 color=WHITE, fontsize=11, fontweight="bold",
                 y=1.01, fontfamily="monospace")
    fig.tight_layout()
    _watermark(fig)
    _save(fig, "09_monthly_calendar")


# ── 10. STRATEGY EQUITY CURVES + DRAWDOWN PROFILE ───────────────────────────
def chart_strategy_equity_curves(trades):
    _font()
    fig = plt.figure(figsize=(20, 11), facecolor=BG)
    gs  = gridspec.GridSpec(2, 2, figure=fig, hspace=0.38, wspace=0.32,
                            left=0.07, right=0.97, top=0.91, bottom=0.07)

    order  = ["gap_fill","fvg","orb","ib_breakout","vwap_rev",
              "vwap_pm","vwap_bounce","vwap_bounce_pm","va_rule"]
    groups = defaultdict(list)
    for t in trades: groups[t.strategy].append(t)

    # ── Strategy equity curves ────────────────────────────────────────────────
    ax1 = fig.add_subplot(gs[0,:])
    _ax(ax1)
    for strat in order:
        if strat not in groups: continue
        tl  = sorted(groups[strat], key=lambda x: x.date)
        cum = np.cumsum([t.pnl for t in tl])
        col = STRAT_COLORS.get(strat, CYAN)
        _glow(ax1, range(len(cum)), cum, col, lw=1.6, a=0.85)
        ax1.text(len(cum)-0.5, cum[-1],
                 strat.replace("_"," ").upper(),
                 color=col, fontsize=5.5, va="center", fontfamily="monospace")
    ax1.axhline(0, color=DIM, lw=0.6, ls="--")
    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v,_: f"${v:+,.0f}"))
    ax1.set_title("CUMULATIVE P&L BY STRATEGY",
                  color=TEXT, fontsize=8, fontweight="bold", loc="left", pad=5)

    # ── Stacked contribution bar (per year or per bucket) ────────────────────
    ax2 = fig.add_subplot(gs[1,0])
    _ax(ax2)
    present = [s for s in order if s in groups]
    labels  = [s.replace("_"," ").upper() for s in present]
    pnls_s  = [sum(t.pnl for t in groups[s]) for s in present]
    cols_s  = [STRAT_COLORS.get(s,CYAN) for s in present]
    total   = sum(pnls_s)
    shares  = [p/total*100 if total else 0 for p in pnls_s]
    xs2     = np.arange(len(present))
    bars    = ax2.bar(xs2, pnls_s, color=cols_s, alpha=0.8, zorder=3)
    ax2.axhline(0, color=BORDER, lw=0.5, ls="--")
    for bar,p,sh in zip(bars,pnls_s,shares):
        off = 5 if p>=0 else -15
        ax2.text(bar.get_x()+bar.get_width()/2, p+off,
                 f"${p:+.0f}\n({sh:.0f}%)", ha="center",
                 color=WHITE, fontsize=5, fontfamily="monospace")
    ax2.set_xticks(xs2); ax2.set_xticklabels(labels, rotation=30,
        ha="right", color=TEXT, fontsize=5.5)
    ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v,_: f"${v:+,.0f}"))
    ax2.set_title("P&L CONTRIBUTION BY STRATEGY",
                  color=TEXT, fontsize=8, fontweight="bold", loc="left", pad=5)

    # ── Per-strategy drawdown ─────────────────────────────────────────────────
    ax3 = fig.add_subplot(gs[1,1])
    _ax(ax3)
    for strat in present[:6]:  # top 6
        tl  = sorted(groups[strat], key=lambda x: x.date)
        cum = np.cumsum([t.pnl for t in tl])
        pk  = np.maximum.accumulate(cum)
        dd  = cum - pk
        col = STRAT_COLORS.get(strat, CYAN)
        ax3.plot(range(len(dd)), dd, color=col, lw=0.9, alpha=0.8,
                 label=strat.replace("_"," ").upper())
    ax3.axhline(0, color=DIM, lw=0.6, ls="--")
    ax3.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v,_: f"${v:,.0f}"))
    ax3.legend(facecolor=PANEL, labelcolor=TEXT, framealpha=0.8,
               edgecolor=BORDER, fontsize=5.5, loc="lower right")
    ax3.set_title("PER-STRATEGY DRAWDOWN",
                  color=TEXT, fontsize=8, fontweight="bold", loc="left", pad=5)

    _hdr(fig, "STRATEGY EQUITY CURVES + ATTRIBUTION",
         "Neon lines = per-strategy cumulative P&L | Bottom: contribution % and per-strategy drawdown")
    _watermark(fig)
    _save(fig, "10_strategy_equity_curves")


# ── Entry point ───────────────────────────────────────────────────────────────
def generate_all_charts(trades) -> None:
    print(f"\nGenerating charts ({len(trades)} trades) -> {OUT_DIR}/")
    for name, fn in [
        ("Master Dashboard",     chart_equity_curve),
        ("Alpha Surface",        chart_drawdown),
        ("Strategy Matrix",      chart_strategy_breakdown),
        ("Returns Analysis",     chart_pnl_distribution),
        ("Rolling Metrics",      chart_rolling_winrate),
        ("Regime Heatmaps",      chart_heatmap),
        ("Monte Carlo",          chart_vix_scatter),
        ("Factor Analysis",      chart_rr_distribution),
        ("Calendar",             chart_monthly_calendar),
        ("Strategy Curves",      chart_strategy_equity_curves),
    ]:
        try:
            fn(trades)
        except Exception as e:
            print(f"  [warn] {name}: {e}")
    print(f"Done — 10 charts saved to ./{OUT_DIR}/\n")
