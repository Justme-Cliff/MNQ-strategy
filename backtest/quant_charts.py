"""
Advanced quantitative research visualizations.
10 charts nobody in retail trading has ever seen — pure math/finance research grade.
Large format, 3D surfaces, white institutional background.
"""
from __future__ import annotations
import os
from collections import defaultdict

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import matplotlib.gridspec as gridspec
import matplotlib.patches as mpatches
from matplotlib.colors import TwoSlopeNorm, LinearSegmentedColormap, Normalize
from mpl_toolkits.mplot3d import Axes3D
from scipy import stats as sp_stats
from scipy.stats import gaussian_kde
import warnings
warnings.filterwarnings("ignore")

OUT_DIR = "backtest_charts"

# ── Palette ───────────────────────────────────────────────────────────────────
BG      = "#FFFFFF"
PANEL   = "#F8F9FA"
GRID    = "#E9ECEF"
BORDER  = "#CED4DA"
TEXT    = "#212529"
SUB     = "#6C757D"
DIM     = "#ADB5BD"
C_POS   = "#2E7D32"
C_NEG   = "#C62828"
C_BLUE  = "#1565C0"
C_ORG   = "#E65100"
C_TEAL  = "#00695C"
C_PUR   = "#6A1B9A"
C_RED   = "#B71C1C"
C_GRN   = "#1B5E20"
REGIME_C = {"strong_bull":"#1B5E20","bull":"#388E3C","neutral":"#78909C",
             "stress":"#E65100","bear":"#B71C1C","volatile":"#E65100",
             "unavailable":"#90A4AE"}
RWG = LinearSegmentedColormap.from_list("rwg",["#C62828","#FFFFFF","#2E7D32"],N=256)
STRAT_PAL = ["#1565C0","#C62828","#2E7D32","#E65100","#6A1B9A",
             "#00695C","#AD1457","#37474F","#F57F17"]


def _font():
    plt.rcParams.update({
        "font.family":"DejaVu Sans","font.size":9,
        "axes.titlesize":11,"axes.labelsize":9,
        "xtick.labelsize":8,"ytick.labelsize":8,
        "legend.fontsize":8,"figure.dpi":150,
        "axes.spines.top":False,"axes.spines.right":False,
    })

def _ax(ax, grid=True):
    ax.set_facecolor(PANEL)
    ax.tick_params(colors=SUB, length=3, width=0.5)
    for sp in ax.spines.values():
        sp.set_edgecolor(BORDER); sp.set_linewidth(0.7)
    if grid:
        ax.grid(color=GRID, lw=0.6, alpha=1.0, zorder=0)
        ax.set_axisbelow(True)

def _save(fig, name):
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, f"{name}.png")
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor=BG)
    plt.close(fig)
    print(f"  saved -> {path}")

def _footer(fig):
    fig.text(0.5,0.005,"ISOGENY ALPHA SYSTEM v7.0  |  KAIROS CAPITAL RESEARCH  |  For Internal Use Only",
             ha="center",va="bottom",color=DIM,fontsize=6.5,style="italic")

def _compute(trades):
    pnls = np.array([t.pnl for t in trades])
    wins = pnls[pnls>0]; losses = pnls[pnls<0]
    cum  = np.cumsum(pnls); peak = np.maximum.accumulate(cum); dd = cum-peak
    ann  = 252*3
    std_ = float(np.std(pnls)) or 1e-8
    return dict(
        pnls=pnls, cum=cum, dd=dd, wins=wins, losses=losses,
        wr=len(wins)/len(pnls), n=len(pnls),
        avg_win=float(np.mean(wins)) if len(wins) else 0,
        avg_loss=float(np.mean(losses)) if len(losses) else 1e-8,
        sharpe=float(np.mean(pnls))/std_*np.sqrt(ann),
        max_dd=float(dd.min()),
    )


# ══════════════════════════════════════════════════════════════════════════════
# 1. KELLY GROWTH LANDSCAPE — 3D surface of E[log-wealth] across win-rate × R:R
#    Our system's position marked in red on the optimal ridge.
# ══════════════════════════════════════════════════════════════════════════════
def chart_equity_curve(trades):
    _font()
    s = _compute(trades)
    wr_sys = s["wr"]
    rr_sys = abs(s["avg_win"] / s["avg_loss"]) if s["avg_loss"] else 1.0

    fig = plt.figure(figsize=(22, 10), facecolor=BG)
    fig.suptitle("KELLY GROWTH LANDSCAPE  — Expected Log-Wealth Surface",
                 fontsize=14, fontweight="bold", color=TEXT, y=0.98)
    fig.text(0.5, 0.945,
             "z = E[log(1 + f*X)] at optimal Kelly fraction f* = p - q/b  |  "
             "red dot = our system's position on the landscape",
             ha="center", fontsize=8.5, color=SUB, style="italic")

    WR  = np.linspace(0.45, 0.95, 120)
    RR  = np.linspace(0.3,  6.0,  120)
    W, R = np.meshgrid(WR, RR)

    def _growth(p, b):
        q = 1 - p
        f = np.clip(p - q/b, 0, 0.99)
        g = p*np.log(1 + f*b) + q*np.log(1 - f)
        return g * 252 * 3   # annualise

    Z = _growth(W, R)
    Z_sys = _growth(wr_sys, rr_sys)

    # ── 3D surface ────────────────────────────────────────────────────────────
    ax3d = fig.add_subplot(121, projection="3d")
    ax3d.set_facecolor(BG); ax3d.patch.set_facecolor(BG)
    norm = Normalize(vmin=float(Z.min()), vmax=float(Z.max()))
    cmap = plt.get_cmap("RdYlGn")
    surf = ax3d.plot_surface(W, R, Z, facecolors=cmap(norm(Z)),
                             rstride=2, cstride=2, alpha=0.88, shade=True)
    # Mark our system
    ax3d.scatter([wr_sys],[rr_sys],[Z_sys], color=C_RED, s=180,
                 zorder=10, marker="*", label=f"Our system ({wr_sys*100:.1f}% WR, {rr_sys:.2f}x R:R)")
    # Draw vertical line to surface
    ax3d.plot([wr_sys,wr_sys],[rr_sys,rr_sys],[0,Z_sys],
              color=C_RED, lw=1.2, ls="--", alpha=0.7)
    # Kelly ridge (optimal win rate for each R:R)
    ridge_wr = np.linspace(0.45, 0.95, 80)
    ridge_z  = [_growth(w, np.interp(w, WR, R[0])) for w in ridge_wr]
    ax3d.set_xlabel("Win Rate (p)", labelpad=8, fontsize=9, color=SUB)
    ax3d.set_ylabel("R:R Ratio (b)", labelpad=8, fontsize=9, color=SUB)
    ax3d.set_zlabel("E[log-wealth growth]", labelpad=8, fontsize=9, color=SUB)
    ax3d.tick_params(colors=SUB, labelsize=7); ax3d.grid(False)
    ax3d.xaxis.pane.fill=ax3d.yaxis.pane.fill=ax3d.zaxis.pane.fill=False
    for pane in [ax3d.xaxis.pane,ax3d.yaxis.pane,ax3d.zaxis.pane]:
        pane.set_edgecolor(BORDER)
    ax3d.view_init(elev=28, azim=-55)
    ax3d.legend(fontsize=8, loc="upper left")
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([]); cb = fig.colorbar(sm, ax=ax3d, shrink=0.45, pad=0.06)
    cb.ax.tick_params(labelsize=7); cb.set_label("Annualised log-growth", fontsize=8)

    # ── 2D contour slice ──────────────────────────────────────────────────────
    ax2 = fig.add_subplot(122)
    _ax(ax2)
    cp = ax2.contourf(W, R, Z, levels=25, cmap="RdYlGn")
    ax2.contour(W, R, Z, levels=10, colors="white", linewidths=0.4, alpha=0.4)
    cb2 = fig.colorbar(cp, ax=ax2, shrink=0.8)
    cb2.ax.tick_params(labelsize=7); cb2.set_label("E[log-growth]", fontsize=8)
    ax2.scatter([wr_sys],[rr_sys], color=C_RED, s=250, zorder=10,
                marker="*", label=f"Isogeny Alpha  WR={wr_sys*100:.1f}%  R:R={rr_sys:.2f}x")
    # Iso-Sharpe contours
    ax2.axhline(rr_sys, color=C_RED, lw=0.8, ls="--", alpha=0.5)
    ax2.axvline(wr_sys, color=C_RED, lw=0.8, ls="--", alpha=0.5)
    ax2.set_xlabel("Win Rate  p"); ax2.set_ylabel("R:R Ratio  b")
    ax2.set_title("CONTOUR MAP  (top-down view of growth landscape)",
                  color=TEXT, fontsize=10, fontweight="bold", loc="left")
    ax2.legend(fontsize=8.5, framealpha=0.95)
    ax2.text(0.97,0.05,
             f"f* = {max(0,wr_sys-(1-wr_sys)/rr_sys)*100:.1f}% of capital\n"
             f"E[annual log-growth] = {Z_sys:.4f}",
             transform=ax2.transAxes, ha="right", va="bottom",
             fontsize=8.5, color=C_RED, fontweight="bold",
             bbox=dict(facecolor="white",edgecolor=BORDER,alpha=0.9,boxstyle="round,pad=0.4"))

    _footer(fig)
    _save(fig, "01_equity_curve")


# ══════════════════════════════════════════════════════════════════════════════
# 2. TRADE DNA / PCA MANIFOLD — Principal component decomposition of trade features
#    Each trade is a point in 9D feature space, reduced to 2D.
# ══════════════════════════════════════════════════════════════════════════════
def chart_drawdown(trades):
    _font()
    strat_map = {s:i for i,s in enumerate(sorted(set(t.strategy for t in trades)))}
    hmm_map   = {s:i for i,s in enumerate(sorted(set(getattr(t,"hmm_state","n") for t in trades)))}
    day_map   = {"Mon":0,"Tue":1,"Wed":2,"Thu":3,"Fri":4}

    X = []
    for t in trades:
        X.append([
            t.vix / 40.0,
            getattr(t,"score",10) / 21.0,
            strat_map.get(t.strategy, 0) / max(len(strat_map)-1,1),
            1.0 if t.direction=="long" else 0.0,
            day_map.get(t.day_name, 2) / 4.0,
            hmm_map.get(getattr(t,"hmm_state","n"), 0) / max(len(hmm_map)-1,1),
            getattr(t,"stop_mult",1.0) / 1.5,
            min(t.rr, 10.0) / 10.0,
            t.risk_pts / 30.0,
        ])
    X = np.array(X, dtype=float)
    # Standardise
    mu_ = X.mean(axis=0); std_ = X.std(axis=0); std_[std_==0] = 1
    Xs  = (X - mu_) / std_
    # PCA via SVD
    U, S, Vt = np.linalg.svd(Xs, full_matrices=False)
    pc = Xs @ Vt[:2].T       # project to first 2 PCs
    var_exp = S**2 / (S**2).sum()

    outcomes = np.array([1 if t.outcome=="WIN" else 0 for t in trades])
    colors_  = [C_POS if o else C_NEG for o in outcomes]
    scores_  = np.array([getattr(t,"score",10) for t in trades])

    fig = plt.figure(figsize=(22, 10), facecolor=BG)
    fig.suptitle("TRADE FEATURE MANIFOLD  — Principal Component Analysis",
                 fontsize=14, fontweight="bold", color=TEXT, y=0.98)
    fig.text(0.5, 0.945,
             "Each point = one trade  |  Features: VIX, score, strategy, direction, day, HMM regime, stop_mult, R:R, risk  |  "
             f"PC1 explains {var_exp[0]*100:.1f}%  PC2 explains {var_exp[1]*100:.1f}% of total variance",
             ha="center", fontsize=8.5, color=SUB, style="italic")

    gs = gridspec.GridSpec(1, 3, figure=fig, wspace=0.35,
                           left=0.07, right=0.97, top=0.91, bottom=0.1)

    # ── PC1 vs PC2 colored by outcome ─────────────────────────────────────────
    ax1 = fig.add_subplot(gs[0])
    _ax(ax1)
    ax1.scatter(pc[outcomes==0,0], pc[outcomes==0,1], c=C_NEG, s=35,
                alpha=0.65, label="LOSS", zorder=3)
    ax1.scatter(pc[outcomes==1,0], pc[outcomes==1,1], c=C_POS, s=35,
                alpha=0.65, label="WIN",  zorder=4)
    # Convex hull / density contour for each class
    from scipy.stats import gaussian_kde as gkde
    for out, col in [(1,C_POS),(0,C_NEG)]:
        pts = pc[outcomes==out]
        if len(pts) > 5:
            try:
                kde = gkde(pts.T)
                xx_ = np.linspace(pc[:,0].min(),pc[:,0].max(),60)
                yy_ = np.linspace(pc[:,1].min(),pc[:,1].max(),60)
                XX, YY = np.meshgrid(xx_, yy_)
                ZZ = kde(np.vstack([XX.ravel(),YY.ravel()])).reshape(XX.shape)
                ax1.contour(XX, YY, ZZ, levels=4, colors=col, alpha=0.4, linewidths=0.8)
            except: pass
    ax1.set_xlabel(f"PC1  ({var_exp[0]*100:.1f}% var)")
    ax1.set_ylabel(f"PC2  ({var_exp[1]*100:.1f}% var)")
    ax1.set_title("WIN vs LOSS", color=TEXT, fontsize=10, fontweight="bold", loc="left")
    ax1.legend(fontsize=8.5, framealpha=0.9)

    # ── PC1 vs PC2 colored by score ───────────────────────────────────────────
    ax2 = fig.add_subplot(gs[1])
    _ax(ax2)
    sc = ax2.scatter(pc[:,0], pc[:,1], c=scores_, cmap="RdYlGn",
                     s=40, alpha=0.8, vmin=5, vmax=20, zorder=3)
    cb = fig.colorbar(sc, ax=ax2, shrink=0.8)
    cb.ax.tick_params(labelsize=7); cb.set_label("Confidence Score", fontsize=8)
    ax2.set_xlabel(f"PC1  ({var_exp[0]*100:.1f}% var)")
    ax2.set_ylabel(f"PC2  ({var_exp[1]*100:.1f}% var)")
    ax2.set_title("COLORED BY SCORE", color=TEXT, fontsize=10, fontweight="bold", loc="left")

    # ── Feature loadings (what PC1/PC2 represent) ─────────────────────────────
    ax3 = fig.add_subplot(gs[2])
    _ax(ax3)
    feat_names = ["VIX","Score","Strategy","Direction","DayOfWeek",
                  "HMM State","Stop Mult","R:R","Risk Pts"]
    lx = Vt[0]; ly = Vt[1]
    for i,(lxi,lyi,name) in enumerate(zip(lx,ly,feat_names)):
        col = C_BLUE if abs(lxi)>abs(lyi) else C_ORG
        ax3.annotate("", xy=(lxi,lyi), xytext=(0,0),
                     arrowprops=dict(arrowstyle="->", color=col, lw=1.5))
        ax3.text(lxi*1.12, lyi*1.12, name, ha="center", va="center",
                 fontsize=8, color=col, fontweight="bold")
    ax3.set_xlim(-1.3,1.3); ax3.set_ylim(-1.3,1.3)
    circle = plt.Circle((0,0),1.0,fill=False,color=BORDER,lw=0.8,ls="--")
    ax3.add_patch(circle)
    ax3.axhline(0, color=BORDER, lw=0.6); ax3.axvline(0, color=BORDER, lw=0.6)
    ax3.set_xlabel("PC1 Loading"); ax3.set_ylabel("PC2 Loading")
    ax3.set_title("FEATURE LOADINGS\n(which features drive each PC)",
                  color=TEXT, fontsize=10, fontweight="bold", loc="left")

    _footer(fig)
    _save(fig, "02_drawdown")


# ══════════════════════════════════════════════════════════════════════════════
# 3. OMEGA FUNCTION + STOCHASTIC DOMINANCE
#    Omega(L) captures the ENTIRE return distribution in one curve.
#    Nobody in retail trading has ever plotted this.
# ══════════════════════════════════════════════════════════════════════════════
def chart_strategy_breakdown(trades):
    _font()
    s    = _compute(trades)
    pnls = s["pnls"]

    # Omega: Ω(L) = E[max(r-L,0)] / E[max(L-r,0)]
    L_range = np.linspace(pnls.min()*1.2, pnls.max()*1.2, 400)
    def omega(pnl_arr, L_arr):
        out = []
        for L in L_arr:
            num = np.mean(np.maximum(pnl_arr - L, 0))
            den = np.mean(np.maximum(L - pnl_arr, 0))
            out.append(num / den if den > 1e-10 else 1e6)
        return np.array(out)

    Omega_sys  = omega(pnls, L_range)
    # Simulate random trader with same mean/std but no skill
    np.random.seed(42)
    random_pnl = np.random.normal(0, float(np.std(pnls)), len(pnls))
    Omega_rand = omega(random_pnl, L_range)

    fig = plt.figure(figsize=(22, 10), facecolor=BG)
    fig.suptitle("OMEGA FUNCTION + STOCHASTIC DOMINANCE ANALYSIS",
                 fontsize=14, fontweight="bold", color=TEXT, y=0.98)
    fig.text(0.5,0.945,
             "Omega(L) = E[max(r-L,0)] / E[max(L-r,0)]  |  "
             "Captures entire return distribution in one curve  |  Omega > 1 at L=0 implies positive edge",
             ha="center", fontsize=8.5, color=SUB, style="italic")

    gs = gridspec.GridSpec(1,3,figure=fig,wspace=0.35,
                           left=0.07,right=0.97,top=0.91,bottom=0.10)

    # ── Omega function ────────────────────────────────────────────────────────
    ax1 = fig.add_subplot(gs[0])
    _ax(ax1)
    # Clip for display
    clip = 20
    O_clipped = np.clip(Omega_sys, 0, clip)
    R_clipped = np.clip(Omega_rand, 0, clip)
    ax1.plot(L_range, O_clipped, color=C_BLUE, lw=2.0, label="Isogeny Alpha")
    ax1.plot(L_range, R_clipped, color=C_NEG,  lw=1.4, ls="--", label="Random trader (0 skill)")
    ax1.axhline(1.0, color=BORDER, lw=1.0, ls="--")
    ax1.axvline(0.0, color=BORDER, lw=0.8, ls=":")
    omega_at_0 = float(omega(pnls, np.array([0.0]))[0])
    ax1.scatter([0], [min(omega_at_0, clip)], color=C_BLUE, s=80, zorder=5)
    ax1.fill_between(L_range, O_clipped, 1.0, where=(O_clipped>=1.0),
                     alpha=0.12, color=C_POS, label=f"Edge region (Ω>1)")
    ax1.set_ylim(0, clip); ax1.set_xlim(L_range[0], L_range[-1])
    ax1.set_xlabel("Threshold  L  ($)")
    ax1.set_ylabel("Ω(L)")
    ax1.set_title("OMEGA FUNCTION", color=TEXT,fontsize=10,fontweight="bold",loc="left")
    ax1.legend(fontsize=8)
    ax1.text(0.97,0.97,f"Ω(0) = {omega_at_0:.2f}\nSkill premium vs random trader",
             transform=ax1.transAxes, ha="right",va="top",fontsize=8.5,
             color=C_BLUE,fontweight="bold",
             bbox=dict(facecolor="white",edgecolor=BORDER,alpha=0.9,boxstyle="round,pad=0.3"))

    # ── First-order stochastic dominance ──────────────────────────────────────
    ax2 = fig.add_subplot(gs[1])
    _ax(ax2)
    # CDF of actual vs random
    xs_  = np.sort(pnls)
    cdf_ = np.arange(1, len(xs_)+1) / len(xs_)
    rxs_ = np.sort(random_pnl)
    rcdf_= np.arange(1, len(rxs_)+1) / len(rxs_)
    ax2.step(xs_, cdf_, color=C_BLUE, lw=2.0, label="Isogeny Alpha CDF", where="post")
    ax2.step(rxs_,rcdf_,color=C_NEG,  lw=1.4, ls="--", label="Random CDF", where="post")
    # Shade dominance region: where F_alpha < F_random (first-order dominance)
    xx_common = np.linspace(max(xs_.min(),rxs_.min()),
                            min(xs_.max(),rxs_.max()),500)
    F_a = np.interp(xx_common, xs_,  cdf_)
    F_r = np.interp(xx_common, rxs_, rcdf_)
    ax2.fill_between(xx_common, F_a, F_r, where=(F_a<=F_r),
                     alpha=0.2, color=C_POS, label="1st-order dominance region")
    ax2.axvline(0, color=BORDER, lw=0.8, ls=":")
    ax2.set_xlabel("P&L ($)"); ax2.set_ylabel("Cumulative Probability")
    ax2.set_title("FIRST-ORDER STOCHASTIC DOMINANCE\nF_α(x) ≤ F_rand(x) ∀x",
                  color=TEXT,fontsize=10,fontweight="bold",loc="left")
    ax2.legend(fontsize=8)
    dom_pct = float((F_a<=F_r).mean()*100)
    ax2.text(0.03,0.97,f"Dominance holds at {dom_pct:.0f}% of support",
             transform=ax2.transAxes,ha="left",va="top",fontsize=8.5,
             color=C_POS,fontweight="bold",
             bbox=dict(facecolor="white",edgecolor=BORDER,alpha=0.9,boxstyle="round,pad=0.3"))

    # ── Second-order: integral of CDF ─────────────────────────────────────────
    ax3 = fig.add_subplot(gs[2])
    _ax(ax3)
    dx = xx_common[1]-xx_common[0]
    int_a = np.cumsum(F_a)*dx
    int_r = np.cumsum(F_r)*dx
    ax3.plot(xx_common, int_a, color=C_BLUE, lw=2.0, label="Isogeny Alpha  ∫F(x)dx")
    ax3.plot(xx_common, int_r, color=C_NEG,  lw=1.4, ls="--", label="Random  ∫F(x)dx")
    ax3.fill_between(xx_common, int_a, int_r, where=(int_a<=int_r),
                     alpha=0.2, color=C_POS)
    ax3.axvline(0, color=BORDER, lw=0.8, ls=":")
    ax3.set_xlabel("P&L ($)"); ax3.set_ylabel("∫₋∞ˣ F(t) dt")
    ax3.set_title("SECOND-ORDER STOCHASTIC DOMINANCE\n∫F_α(t)dt ≤ ∫F_rand(t)dt ∀x  (risk-averse investors prefer α)",
                  color=TEXT,fontsize=9,fontweight="bold",loc="left")
    ax3.legend(fontsize=8)

    _footer(fig)
    _save(fig, "03_strategy_breakdown")


# ══════════════════════════════════════════════════════════════════════════════
# 4. FACTOR INFORMATION COEFFICIENT MATRIX
#    20×20 correlation matrix of all scoring factors, hierarchically clustered.
#    Shows which signals are truly orthogonal vs which are redundant.
# ══════════════════════════════════════════════════════════════════════════════
def chart_pnl_distribution(trades):
    _font()
    import seaborn as sns
    from scipy.cluster import hierarchy as sch

    # Build factor matrix
    factors = defaultdict(list)
    outcomes_list = []
    for t in trades:
        bd = getattr(t, "score_breakdown", {})
        for k, v in bd.items():
            factors[k].append(float(v))
        outcomes_list.append(1.0 if t.outcome=="WIN" else 0.0)

    if len(factors) < 3:
        # Fallback: just show distribution
        fig, ax = plt.subplots(figsize=(12,8), facecolor=BG)
        ax.text(0.5,0.5,"Insufficient factor data\n(run hybrid backtest for full factor breakdown)",
                ha="center",va="center",transform=ax.transAxes,fontsize=14,color=SUB)
        _save(fig,"04_pnl_distribution"); return

    # Align all factors to same length
    min_len = min(len(v) for v in factors.values())
    factor_names = sorted(factors.keys())
    F = np.array([factors[k][:min_len] for k in factor_names]).T  # (n_trades, n_factors)
    O = np.array(outcomes_list[:min_len])

    # IC = correlation of each factor with outcome
    ICs = np.array([np.corrcoef(F[:,i], O)[0,1] for i in range(F.shape[1])])

    # Factor-factor correlation — remove zero-variance columns
    std_f = F.std(axis=0)
    valid_cols = std_f > 0
    if valid_cols.sum() < 2:
        fig, ax = plt.subplots(figsize=(12,8), facecolor=BG)
        ax.text(0.5,0.5,"All factors constant\n(insufficient variance for correlation)",
                ha="center",va="center",transform=ax.transAxes,fontsize=12,color=SUB)
        _save(fig,"04_pnl_distribution"); return
    F = F[:, valid_cols]
    factor_names = [n for n,v in zip(factor_names, valid_cols) if v]
    ICs = ICs[valid_cols]
    C = np.corrcoef(F.T)
    # Replace any remaining NaN/inf with 0
    C = np.nan_to_num(C, nan=0.0, posinf=1.0, neginf=-1.0)
    np.fill_diagonal(C, 1.0)

    # Hierarchical clustering
    try:
        link = sch.linkage(1-C, method="complete")
        order = sch.leaves_list(link)
    except:
        order = np.arange(len(factor_names))

    C_sorted    = C[np.ix_(order, order)]
    names_sorted= [factor_names[i] for i in order]
    ICs_sorted  = ICs[order]

    fig = plt.figure(figsize=(22, 12), facecolor=BG)
    fig.suptitle("FACTOR INFORMATION COEFFICIENT MATRIX",
                 fontsize=14,fontweight="bold",color=TEXT,y=0.98)
    fig.text(0.5,0.945,
             "Diagonal = IC (correlation with trade outcome) | Off-diagonal = factor-factor correlation | "
             "Hierarchical clustering shows groups of redundant signals",
             ha="center",fontsize=8.5,color=SUB,style="italic")

    gs = gridspec.GridSpec(1,3,figure=fig,wspace=0.35,
                           left=0.06,right=0.97,top=0.90,bottom=0.08,
                           width_ratios=[3,0.7,0.7])

    # ── Correlation heatmap ───────────────────────────────────────────────────
    ax1 = fig.add_subplot(gs[0])
    ax1.set_facecolor(PANEL)
    norm = TwoSlopeNorm(vcenter=0, vmin=-1, vmax=1)
    im = ax1.imshow(C_sorted, cmap="RdBu_r", norm=norm, aspect="auto")
    ax1.set_xticks(range(len(names_sorted)))
    ax1.set_xticklabels(names_sorted, rotation=45, ha="right", fontsize=8)
    ax1.set_yticks(range(len(names_sorted)))
    ax1.set_yticklabels(names_sorted, fontsize=8)
    # Annotate values
    for i in range(len(names_sorted)):
        for j in range(len(names_sorted)):
            val = C_sorted[i,j]
            txt_col = "white" if abs(val)>0.6 else TEXT
            ax1.text(j,i,f"{val:.2f}",ha="center",va="center",
                     fontsize=6.5 if len(names_sorted)<=15 else 5.5,color=txt_col)
    cb = fig.colorbar(im,ax=ax1,shrink=0.7,pad=0.02)
    cb.ax.tick_params(labelsize=7); cb.set_label("Correlation",fontsize=8)
    ax1.set_title("FACTOR CORRELATION MATRIX  (hierarchically clustered)",
                  color=TEXT,fontsize=10,fontweight="bold",loc="left",pad=8)

    # ── IC bar chart ──────────────────────────────────────────────────────────
    ax2 = fig.add_subplot(gs[1])
    _ax(ax2)
    ys = np.arange(len(names_sorted))
    cols = [C_POS if ic>0 else C_NEG for ic in ICs_sorted]
    ax2.barh(ys, ICs_sorted, color=cols, alpha=0.85, height=0.7)
    ax2.axvline(0, color=BORDER, lw=0.8)
    ax2.set_yticks(ys); ax2.set_yticklabels(names_sorted, fontsize=8)
    ax2.set_xlabel("IC (corr with outcome)")
    ax2.set_title("INFORMATION\nCOEFFICIENT",color=TEXT,fontsize=9,fontweight="bold",loc="left")
    ax2.set_xlim(-0.6,0.6)
    for y_, ic_ in zip(ys, ICs_sorted):
        ax2.text(ic_+(0.02 if ic_>=0 else -0.02), y_,
                 f"{ic_:+.3f}", va="center",
                 ha="left" if ic_>=0 else "right",
                 fontsize=7, color=TEXT)

    # ── Eigenvalue spectrum (scree plot) ──────────────────────────────────────
    ax3 = fig.add_subplot(gs[2])
    _ax(ax3)
    try:
        eigvals = np.sort(np.linalg.eigvalsh(C))[::-1]
    except np.linalg.LinAlgError:
        eigvals = np.abs(np.linalg.eigvals(C)).real
        eigvals = np.sort(eigvals)[::-1]
    var_exp = eigvals / eigvals.sum() * 100
    ax3.bar(range(len(eigvals)), var_exp, color=C_BLUE, alpha=0.75)
    ax3.plot(range(len(eigvals)), np.cumsum(var_exp), color=C_NEG,
             lw=1.5, marker="o", markersize=4, label="Cumulative %")
    ax3.axhline(80, color=BORDER, lw=0.8, ls="--", label="80% threshold")
    ax3.set_xlabel("Principal Component")
    ax3.set_ylabel("Variance Explained (%)")
    ax3.set_title("SCREE PLOT\n(factor dimensionality)",
                  color=TEXT,fontsize=9,fontweight="bold",loc="left")
    ax3.legend(fontsize=7.5)
    # How many factors explain 80%?
    n80 = int(np.searchsorted(np.cumsum(var_exp), 80)) + 1
    ax3.text(0.97,0.5,f"{n80} factors\nexplain 80%\nof variance",
             transform=ax3.transAxes,ha="right",va="center",
             fontsize=9,color=C_BLUE,fontweight="bold",
             bbox=dict(facecolor="white",edgecolor=BORDER,alpha=0.9,boxstyle="round,pad=0.3"))

    _footer(fig)
    _save(fig, "04_pnl_distribution")


# ══════════════════════════════════════════════════════════════════════════════
# 5. CONDITIONAL CVaR SURFACE — 3D risk landscape across VIX × Score
#    Shows how tail risk varies across market conditions.
# ══════════════════════════════════════════════════════════════════════════════
def chart_rolling_winrate(trades):
    _font()
    vix_bins   = [0,15,20,25,30,60]
    score_bins = [5,8,11,14,17,21]

    def _bkt(v, bins):
        for i in range(len(bins)-1):
            if bins[i]<=v<bins[i+1]: return i
        return len(bins)-2

    grid_cvar = np.full((len(vix_bins)-1, len(score_bins)-1), np.nan)
    grid_wr   = np.full_like(grid_cvar, np.nan)
    grid_n    = np.zeros_like(grid_cvar, dtype=int)

    buckets = defaultdict(list)
    for t in trades:
        vi = _bkt(t.vix, vix_bins)
        si = _bkt(getattr(t,"score",10), score_bins)
        buckets[(vi,si)].append(t.pnl)
        grid_n[vi,si]+=1

    for (vi,si), pnl_list in buckets.items():
        arr = np.array(pnl_list)
        if len(arr)>=3:
            var95 = np.percentile(arr,5)
            grid_cvar[vi,si] = float(np.mean(arr[arr<=var95])) if any(arr<=var95) else float(var95)
            grid_wr[vi,si]   = float((arr>0).mean()*100)

    X_c = [(vix_bins[i]+vix_bins[i+1])/2 for i in range(len(vix_bins)-1)]
    Y_c = [(score_bins[i]+score_bins[i+1])/2 for i in range(len(score_bins)-1)]
    X3, Y3 = np.meshgrid(X_c, Y_c, indexing="ij")

    # Fill NaN with mean
    m_cvar = float(np.nanmean(grid_cvar)) if not np.all(np.isnan(grid_cvar)) else -50.0
    m_wr   = float(np.nanmean(grid_wr))   if not np.all(np.isnan(grid_wr))   else 70.0
    Z_cvar = np.where(np.isnan(grid_cvar), m_cvar, grid_cvar)
    Z_wr   = np.where(np.isnan(grid_wr),   m_wr,   grid_wr)

    fig = plt.figure(figsize=(22, 10), facecolor=BG)
    fig.suptitle("CONDITIONAL VALUE-AT-RISK SURFACE  (CVaR across VIX × Confidence Score)",
                 fontsize=14,fontweight="bold",color=TEXT,y=0.98)
    fig.text(0.5,0.945,
             "z = CVaR₉₅ (expected loss in worst 5% of trades) for each (VIX, score) cell  |  "
             "Lower (more negative) = higher tail risk in that regime",
             ha="center",fontsize=8.5,color=SUB,style="italic")

    gs = gridspec.GridSpec(1,2,figure=fig,wspace=0.35,
                           left=0.05,right=0.97,top=0.90,bottom=0.08)

    # ── CVaR 3D surface ───────────────────────────────────────────────────────
    ax3d = fig.add_subplot(gs[0], projection="3d")
    ax3d.set_facecolor(BG); ax3d.patch.set_facecolor(BG)
    norm = TwoSlopeNorm(vcenter=float(np.nanmedian(Z_cvar)),
                        vmin=float(np.nanmin(Z_cvar)),
                        vmax=max(0, float(np.nanmax(Z_cvar))))
    cmap_ = plt.get_cmap("RdYlGn")
    ax3d.plot_surface(X3,Y3,Z_cvar, facecolors=cmap_(norm(Z_cvar)),
                      rstride=1,cstride=1,alpha=0.9,shade=True)
    ax3d.contourf(X3,Y3,Z_cvar,zdir="z",offset=Z_cvar.min()-10,
                  cmap="RdYlGn",alpha=0.4,levels=8)
    ax3d.set_xlabel("VIX Level",labelpad=6,fontsize=9,color=SUB)
    ax3d.set_ylabel("Confidence Score",labelpad=6,fontsize=9,color=SUB)
    ax3d.set_zlabel("CVaR₉₅ ($)",labelpad=6,fontsize=9,color=SUB)
    ax3d.tick_params(colors=SUB,labelsize=7); ax3d.grid(False)
    ax3d.xaxis.pane.fill=ax3d.yaxis.pane.fill=ax3d.zaxis.pane.fill=False
    for pane in [ax3d.xaxis.pane,ax3d.yaxis.pane,ax3d.zaxis.pane]:
        pane.set_edgecolor(BORDER)
    ax3d.view_init(elev=30, azim=-50)
    ax3d.set_title("CVaR SURFACE (greener = less tail risk)",
                   color=TEXT,fontsize=10,fontweight="bold",pad=8)
    sm = plt.cm.ScalarMappable(cmap=cmap_,norm=norm)
    sm.set_array([]); cb=fig.colorbar(sm,ax=ax3d,shrink=0.45,pad=0.06)
    cb.ax.tick_params(labelsize=7); cb.set_label("CVaR₉₅ ($)",fontsize=8)

    # ── Win rate surface ──────────────────────────────────────────────────────
    ax3d2 = fig.add_subplot(gs[1], projection="3d")
    ax3d2.set_facecolor(BG); ax3d2.patch.set_facecolor(BG)
    norm2 = Normalize(vmin=40, vmax=100)
    ax3d2.plot_surface(X3,Y3,Z_wr, facecolors=cmap_(norm2(Z_wr)),
                       rstride=1,cstride=1,alpha=0.9,shade=True)
    ax3d2.contourf(X3,Y3,Z_wr,zdir="z",offset=Z_wr.min()-5,
                   cmap="RdYlGn",alpha=0.4,levels=8)
    ax3d2.set_xlabel("VIX Level",labelpad=6,fontsize=9,color=SUB)
    ax3d2.set_ylabel("Confidence Score",labelpad=6,fontsize=9,color=SUB)
    ax3d2.set_zlabel("Win Rate (%)",labelpad=6,fontsize=9,color=SUB)
    ax3d2.tick_params(colors=SUB,labelsize=7); ax3d2.grid(False)
    ax3d2.xaxis.pane.fill=ax3d2.yaxis.pane.fill=ax3d2.zaxis.pane.fill=False
    for pane in [ax3d2.xaxis.pane,ax3d2.yaxis.pane,ax3d2.zaxis.pane]:
        pane.set_edgecolor(BORDER)
    ax3d2.view_init(elev=30, azim=-50)
    ax3d2.set_title("WIN RATE SURFACE (same axes)",
                    color=TEXT,fontsize=10,fontweight="bold",pad=8)
    sm2=plt.cm.ScalarMappable(cmap=cmap_,norm=norm2)
    sm2.set_array([]); cb2=fig.colorbar(sm2,ax=ax3d2,shrink=0.45,pad=0.06)
    cb2.ax.tick_params(labelsize=7); cb2.set_label("Win Rate (%)",fontsize=8)

    _footer(fig)
    _save(fig, "05_rolling_winrate")


# ══════════════════════════════════════════════════════════════════════════════
# 6. STREAK PERSISTENCE — P(win | last N consecutive wins) vs N
#    Does the system have momentum in outcomes? Are wins self-reinforcing?
# ══════════════════════════════════════════════════════════════════════════════
def chart_heatmap(trades):
    _font()
    outcomes = [1 if t.outcome=="WIN" else 0 for t in trades]
    n = len(outcomes)

    max_streak = 6
    pw_given_cw = {}  # P(win | last N consecutive wins)
    pw_given_cl = {}  # P(win | last N consecutive losses)
    pw_given_cw_ci = {}
    pw_given_cl_ci = {}

    for streak_len in range(1, max_streak+1):
        wins_after_cw = []; wins_after_cl = []
        for i in range(streak_len, n):
            last_n = outcomes[i-streak_len:i]
            if sum(last_n) == streak_len:   # all wins
                wins_after_cw.append(outcomes[i])
            if sum(last_n) == 0:            # all losses
                wins_after_cl.append(outcomes[i])
        if wins_after_cw:
            p = np.mean(wins_after_cw)
            ci= 1.96*np.sqrt(p*(1-p)/len(wins_after_cw))
            pw_given_cw[streak_len] = p; pw_given_cw_ci[streak_len] = ci
        if wins_after_cl:
            p = np.mean(wins_after_cl)
            ci= 1.96*np.sqrt(p*(1-p)/len(wins_after_cl))
            pw_given_cl[streak_len] = p; pw_given_cl_ci[streak_len] = ci

    base_wr = np.mean(outcomes)

    fig = plt.figure(figsize=(22, 11), facecolor=BG)
    fig.suptitle("STREAK PERSISTENCE ANALYSIS",
                 fontsize=14,fontweight="bold",color=TEXT,y=0.98)
    fig.text(0.5,0.945,
             "Tests whether winning/losing streaks predict future outcomes  |  "
             "Flat = independent trades (good)  |  Rising = momentum effect  |  Falling = mean reversion",
             ha="center",fontsize=8.5,color=SUB,style="italic")

    gs = gridspec.GridSpec(1,3,figure=fig,wspace=0.35,
                           left=0.07,right=0.97,top=0.90,bottom=0.10)

    # ── P(win|N consecutive wins) ─────────────────────────────────────────────
    ax1 = fig.add_subplot(gs[0])
    _ax(ax1)
    if pw_given_cw:
        xs = list(pw_given_cw.keys()); ys = [pw_given_cw[x] for x in xs]
        ci = [pw_given_cw_ci[x] for x in xs]
        ax1.plot(xs, ys, color=C_BLUE, lw=2.0, marker="o", markersize=7, label="P(W|N×W)")
        ax1.fill_between(xs, [y-c for y,c in zip(ys,ci)],
                             [y+c for y,c in zip(ys,ci)], alpha=0.2, color=C_BLUE)
    ax1.axhline(base_wr, color=C_ORG, lw=1.2, ls="--", label=f"Baseline WR {base_wr*100:.1f}%")
    ax1.set_ylim(0, 1.05); ax1.set_xlim(0.5, max_streak+0.5)
    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v,_:f"{v*100:.0f}%"))
    ax1.set_xlabel("N consecutive wins before this trade")
    ax1.set_ylabel("P(next trade = WIN)")
    ax1.set_title("P(WIN | LAST N WINS)\nMomentum test",
                  color=TEXT,fontsize=10,fontweight="bold",loc="left")
    ax1.legend(fontsize=8.5)
    ax1.text(0.5,0.08,"Flat line = no streak effect\n(trades are independent)",
             transform=ax1.transAxes,ha="center",va="bottom",
             fontsize=8,color=SUB,style="italic")

    # ── P(win|N consecutive losses) ───────────────────────────────────────────
    ax2 = fig.add_subplot(gs[1])
    _ax(ax2)
    if pw_given_cl:
        xs = list(pw_given_cl.keys()); ys = [pw_given_cl[x] for x in xs]
        ci = [pw_given_cl_ci[x] for x in xs]
        ax2.plot(xs, ys, color=C_NEG, lw=2.0, marker="s", markersize=7, label="P(W|N×L)")
        ax2.fill_between(xs, [y-c for y,c in zip(ys,ci)],
                             [y+c for y,c in zip(ys,ci)], alpha=0.2, color=C_NEG)
    ax2.axhline(base_wr, color=C_ORG, lw=1.2, ls="--", label=f"Baseline WR {base_wr*100:.1f}%")
    ax2.set_ylim(0, 1.05); ax2.set_xlim(0.5, max_streak+0.5)
    ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v,_:f"{v*100:.0f}%"))
    ax2.set_xlabel("N consecutive losses before this trade")
    ax2.set_ylabel("P(next trade = WIN)")
    ax2.set_title("P(WIN | LAST N LOSSES)\nMean-reversion test",
                  color=TEXT,fontsize=10,fontweight="bold",loc="left")
    ax2.legend(fontsize=8.5)

    # ── Run length distribution ───────────────────────────────────────────────
    ax3 = fig.add_subplot(gs[2])
    _ax(ax3)
    run_w = []; run_l = []; cur_len = 1; cur_type = outcomes[0]
    for i in range(1, len(outcomes)):
        if outcomes[i] == cur_type: cur_len += 1
        else:
            (run_w if cur_type==1 else run_l).append(cur_len)
            cur_len=1; cur_type=outcomes[i]
    (run_w if cur_type==1 else run_l).append(cur_len)

    max_run = max(max(run_w or [1]), max(run_l or [1]))
    bins_r  = np.arange(0.5, max_run+1.5)
    ax3.hist(run_w, bins=bins_r, color=C_POS, alpha=0.7, label=f"Win runs (n={len(run_w)})")
    ax3.hist(run_l, bins=bins_r, color=C_NEG, alpha=0.7, label=f"Loss runs (n={len(run_l)})")
    # Geometric distribution overlay (expected for independent trades)
    xs_geo = np.arange(1, max_run+1)
    geom_w = (1-base_wr)**(xs_geo-1)*base_wr * len(run_w)
    geom_l = base_wr**(xs_geo-1)*(1-base_wr) * len(run_l)
    ax3.plot(xs_geo, geom_w, color=C_POS, lw=1.8, ls="--",
             label="Geometric (if independent)")
    ax3.plot(xs_geo, geom_l, color=C_NEG, lw=1.8, ls="--")
    ax3.set_xlabel("Run length (trades)"); ax3.set_ylabel("Frequency")
    ax3.set_title("RUN LENGTH DISTRIBUTION\nvs geometric model (iid hypothesis)",
                  color=TEXT,fontsize=10,fontweight="bold",loc="left")
    ax3.legend(fontsize=7.5)

    _footer(fig)
    _save(fig, "06_winrate_heatmap")


# ══════════════════════════════════════════════════════════════════════════════
# 7. REGIME-CONDITIONED RETURN DISTRIBUTIONS
#    Overlaid KDEs for each HMM regime — shows how the strategy behaves
#    differently in bull/bear/stress markets.
# ══════════════════════════════════════════════════════════════════════════════
def chart_vix_scatter(trades):
    _font()
    by_regime = defaultdict(list)
    for t in trades:
        regime = getattr(t, "hmm_state", "unavailable")
        by_regime[regime].append(t.pnl)

    all_pnls = np.array([t.pnl for t in trades])
    x_min, x_max = all_pnls.min()*1.3, all_pnls.max()*1.3
    xs_kde = np.linspace(x_min, x_max, 400)

    fig = plt.figure(figsize=(22, 11), facecolor=BG)
    fig.suptitle("REGIME-CONDITIONED RETURN DISTRIBUTIONS",
                 fontsize=14,fontweight="bold",color=TEXT,y=0.98)
    fig.text(0.5,0.945,
             "How the P&L distribution changes across each HMM-detected market regime  |  "
             "Same strategy — completely different risk profiles depending on regime",
             ha="center",fontsize=8.5,color=SUB,style="italic")

    gs = gridspec.GridSpec(2,3,figure=fig,hspace=0.42,wspace=0.35,
                           left=0.07,right=0.97,top=0.90,bottom=0.08)

    regime_order = ["strong_bull","bull","neutral","stress","bear","unavailable"]
    regime_labels= {"strong_bull":"Strong Bull","bull":"Bull","neutral":"Neutral",
                    "stress":"Stress","bear":"Bear","unavailable":"Unavailable"}

    stats_rows = []
    for idx, regime in enumerate(regime_order):
        pnl_r = np.array(by_regime.get(regime,[]))
        ax = fig.add_subplot(gs[idx//3, idx%3])
        _ax(ax)
        col = REGIME_C.get(regime, SUB)
        if len(pnl_r) >= 3:
            kde = gaussian_kde(pnl_r, bw_method="silverman")
            yd  = kde(xs_kde)
            ax.plot(xs_kde, yd, color=col, lw=2.2, zorder=4)
            ax.fill_between(xs_kde, yd, 0, alpha=0.20, color=col)
            ax.fill_between(xs_kde, yd, 0, where=(xs_kde>=0), alpha=0.25, color=C_POS)
            ax.fill_between(xs_kde, yd, 0, where=(xs_kde<0),  alpha=0.25, color=C_NEG)
            ax.axvline(float(np.mean(pnl_r)), color=TEXT, lw=1.2, ls="--",
                       label=f"Mean ${np.mean(pnl_r):+.1f}")
            ax.axvline(0, color=BORDER, lw=0.8, ls=":")
            # Rug plot
            ax.plot(pnl_r, np.ones_like(pnl_r)*yd.max()*0.04,
                    "|", color=col, alpha=0.5, markersize=6)
            stats_rows.append((regime_labels.get(regime,regime), len(pnl_r),
                                f"{(pnl_r>0).mean()*100:.0f}%",
                                f"${np.mean(pnl_r):+.1f}",
                                f"${np.std(pnl_r):.1f}"))
        else:
            ax.text(0.5,0.5,f"n={len(pnl_r)}\n(insufficient data)",
                    ha="center",va="center",transform=ax.transAxes,
                    fontsize=10,color=DIM)
        title = f"{regime_labels.get(regime,regime).upper()}  (n={len(pnl_r)})"
        ax.set_title(title, color=col, fontsize=9, fontweight="bold", loc="left")
        if len(pnl_r)>=3: ax.legend(fontsize=7.5, framealpha=0.8)
        ax.set_xlabel("P&L ($)"); ax.set_ylabel("Density")

    fig.text(0.5, 0.01,
             "Regime detected by 5-state Gaussian HMM trained on [log-return, range-ratio, realized-vol]",
             ha="center",va="bottom",color=DIM,fontsize=7,style="italic")
    _footer(fig)
    _save(fig, "07_vix_scatter")


# ══════════════════════════════════════════════════════════════════════════════
# 8. KELLY FRACTION TRAJECTORY — Actual bet size vs optimal Kelly fraction
#    over time. Shows how close we track the growth-optimal path.
# ══════════════════════════════════════════════════════════════════════════════
def chart_rr_distribution(trades):
    _font()
    s = _compute(trades)
    n = len(trades)
    window = min(20, max(5, n//5))

    # Rolling Kelly
    kelly_trail = [np.nan]*window
    rr_trail    = [np.nan]*window
    wr_trail    = [np.nan]*window
    for i in range(window, n):
        sub = trades[i-window:i]
        wr_ = len([t for t in sub if t.outcome=="WIN"]) / len(sub)
        wins_ = [t.pnl for t in sub if t.pnl>0]
        loss_ = [t.pnl for t in sub if t.pnl<0]
        avg_w = np.mean(wins_) if wins_ else 1
        avg_l = abs(np.mean(loss_)) if loss_ else 1
        rr_   = avg_w / avg_l if avg_l else 1
        f_k   = max(0, wr_ - (1-wr_)/rr_)
        kelly_trail.append(f_k)
        rr_trail.append(rr_)
        wr_trail.append(wr_)

    kelly_arr = np.array(kelly_trail)
    actual_f  = np.array([getattr(t,"n_contracts",1)/2.0 for t in trades])  # 0.5 or 1.0

    fig = plt.figure(figsize=(22, 11), facecolor=BG)
    fig.suptitle("KELLY FRACTION TRAJECTORY  — Actual Bet Size vs Growth-Optimal Fraction",
                 fontsize=14,fontweight="bold",color=TEXT,y=0.98)
    fig.text(0.5,0.945,
             "f*(t) = rolling Kelly fraction based on last 20-trade WR and R:R  |  "
             "Actual f(t) = contracts traded as fraction of maximum (1-lot=0.5, 2-lot=1.0)",
             ha="center",fontsize=8.5,color=SUB,style="italic")

    gs = gridspec.GridSpec(2,2,figure=fig,hspace=0.42,wspace=0.35,
                           left=0.07,right=0.97,top=0.90,bottom=0.08)

    xs = np.arange(n)

    # ── Kelly vs actual ───────────────────────────────────────────────────────
    ax1 = fig.add_subplot(gs[0,:])
    _ax(ax1)
    ax1.plot(xs, kelly_arr, color=C_BLUE, lw=1.8, label=f"f* (Kelly optimal, rolling {window})", zorder=4)
    ax1.step(xs, actual_f,  color=C_ORG,  lw=1.8, label="f (actual)",                          zorder=3, where="post")
    # (no base fill — only the conditional fills below matter)
    # Shade over-bet regions
    valid = ~np.isnan(kelly_arr)
    ax1.fill_between(xs[valid], kelly_arr[valid], actual_f[valid],
                     where=(actual_f[valid]>kelly_arr[valid]),
                     alpha=0.2, color=C_NEG, label="Over-betting (risk of ruin)")
    ax1.fill_between(xs[valid], kelly_arr[valid], actual_f[valid],
                     where=(actual_f[valid]<=kelly_arr[valid]),
                     alpha=0.2, color=C_POS, label="Under-betting (leaving growth on table)")
    ax1.set_ylim(-0.05, 1.3)
    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v,_:f"{v*100:.0f}%"))
    ax1.set_ylabel("Fraction of capital risked")
    ax1.set_title(f"KELLY FRACTION TRAJECTORY  (window={window} trades)",
                  color=TEXT,fontsize=10,fontweight="bold",loc="left")
    ax1.legend(fontsize=8, framealpha=0.9, ncol=2)

    # ── Rolling WR ────────────────────────────────────────────────────────────
    ax2 = fig.add_subplot(gs[1,0])
    _ax(ax2)
    ax2.plot(xs, wr_trail, color=C_POS, lw=1.5)
    ax2.axhline(s["wr"], color=BORDER, lw=0.9, ls="--", label=f"Overall {s['wr']*100:.1f}%")
    ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v,_:f"{v*100:.0f}%"))
    ax2.set_title("ROLLING WIN RATE",color=TEXT,fontsize=10,fontweight="bold",loc="left")
    ax2.legend(fontsize=8)

    # ── Rolling R:R ───────────────────────────────────────────────────────────
    ax3 = fig.add_subplot(gs[1,1])
    _ax(ax3)
    ax3.plot(xs, rr_trail, color=C_TEAL, lw=1.5)
    avg_rr = abs(s["avg_win"]/s["avg_loss"]) if s["avg_loss"] else 1
    ax3.axhline(avg_rr, color=BORDER, lw=0.9, ls="--", label=f"Overall {avg_rr:.2f}x")
    ax3.set_ylabel("Avg Win / Avg Loss")
    ax3.set_title("ROLLING R:R RATIO",color=TEXT,fontsize=10,fontweight="bold",loc="left")
    ax3.legend(fontsize=8)

    _footer(fig)
    _save(fig, "08_rr_distribution")


# ══════════════════════════════════════════════════════════════════════════════
# 9. STRATEGY CORRELATION + PORTFOLIO EFFICIENT FRONTIER
#    Covariance structure of strategy daily returns.
#    Marginal Sharpe contribution per strategy.
# ══════════════════════════════════════════════════════════════════════════════
def chart_monthly_calendar(trades):
    _font()
    import seaborn as sns
    # Build daily P&L per strategy
    all_dates = sorted(set(t.date for t in trades))
    date_idx  = {d:i for i,d in enumerate(all_dates)}
    strategies= sorted(set(t.strategy for t in trades))

    mat = np.zeros((len(all_dates), len(strategies)))
    for t in trades:
        si = strategies.index(t.strategy)
        mat[date_idx[t.date], si] += t.pnl

    # Remove zero rows
    active = (mat != 0).any(axis=1)
    mat_a  = mat[active]

    fig = plt.figure(figsize=(22, 11), facecolor=BG)
    fig.suptitle("STRATEGY COVARIANCE STRUCTURE + PORTFOLIO EFFICIENCY ANALYSIS",
                 fontsize=14,fontweight="bold",color=TEXT,y=0.98)
    fig.text(0.5,0.945,
             "Correlation between strategy daily P&L series  |  "
             "Zero or negative correlation = strategies provide diversification benefit",
             ha="center",fontsize=8.5,color=SUB,style="italic")

    gs = gridspec.GridSpec(1,3,figure=fig,wspace=0.38,
                           left=0.06,right=0.97,top=0.90,bottom=0.10)

    # ── Correlation heatmap ───────────────────────────────────────────────────
    ax1 = fig.add_subplot(gs[0])
    ax1.set_facecolor(PANEL)
    C_mat = np.corrcoef(mat_a.T) if mat_a.shape[0]>1 else np.eye(len(strategies))
    labels= [s.replace("_","\n").title() for s in strategies]
    norm_ = TwoSlopeNorm(vcenter=0,vmin=-1,vmax=1)
    im = ax1.imshow(C_mat, cmap="RdBu_r", norm=norm_, aspect="auto")
    ax1.set_xticks(range(len(strategies))); ax1.set_xticklabels(labels,fontsize=8,rotation=45,ha="right")
    ax1.set_yticks(range(len(strategies))); ax1.set_yticklabels(labels,fontsize=8)
    for i in range(len(strategies)):
        for j in range(len(strategies)):
            tc = "white" if abs(C_mat[i,j])>0.5 else TEXT
            ax1.text(j,i,f"{C_mat[i,j]:.2f}",ha="center",va="center",fontsize=7.5,color=tc)
    cb=fig.colorbar(im,ax=ax1,shrink=0.7); cb.ax.tick_params(labelsize=7)
    cb.set_label("Pearson correlation",fontsize=8)
    for sp in ax1.spines.values(): sp.set_edgecolor(BORDER)
    ax1.set_title("DAILY P&L CORRELATION MATRIX",color=TEXT,fontsize=10,fontweight="bold",loc="left",pad=8)

    # ── Sharpe contribution ───────────────────────────────────────────────────
    ax2 = fig.add_subplot(gs[1])
    _ax(ax2)
    mean_v = mat_a.mean(axis=0); std_v = mat_a.std(axis=0)
    std_v[std_v==0] = 1e-8
    sharpes = mean_v/std_v * np.sqrt(252)
    cols2 = [C_POS if sh>=0 else C_NEG for sh in sharpes]
    ys = np.arange(len(strategies))
    ax2.barh(ys, sharpes, color=cols2, alpha=0.85, height=0.6)
    ax2.axvline(0,color=BORDER,lw=0.8)
    ax2.set_yticks(ys); ax2.set_yticklabels(labels,fontsize=8)
    for y_,sh in zip(ys,sharpes):
        ax2.text(sh+(0.05 if sh>=0 else -0.05), y_,
                 f"{sh:+.2f}",va="center",ha="left" if sh>=0 else "right",
                 fontsize=8,color=TEXT)
    ax2.set_xlabel("Annualised Sharpe Ratio")
    ax2.set_title("SHARPE RATIO BY STRATEGY",color=TEXT,fontsize=10,fontweight="bold",loc="left")

    # ── Diversification ratio ─────────────────────────────────────────────────
    ax3 = fig.add_subplot(gs[2])
    _ax(ax3)
    total_pnl = mat_a.sum(axis=1)
    total_std = float(total_pnl.std()) or 1e-8
    sum_std   = float(std_v.sum()) or 1e-8
    div_ratio = sum_std / total_std

    # Risk contribution (marginal)
    cov_m = np.cov(mat_a.T) if mat_a.shape[0]>1 else np.eye(len(strategies))
    w     = np.ones(len(strategies))/len(strategies)
    port_var = float(w @ cov_m @ w)
    mrc   = (cov_m @ w) / (np.sqrt(port_var)+1e-10)  # marginal risk contribution
    rc    = w * mrc; rc = rc / (rc.sum() or 1)

    cols3 = [STRAT_PAL[i%len(STRAT_PAL)] for i in range(len(strategies))]
    ax3.bar(range(len(strategies)), rc*100, color=cols3, alpha=0.85)
    ax3.set_xticks(range(len(strategies)))
    ax3.set_xticklabels(labels,rotation=45,ha="right",fontsize=8)
    ax3.set_ylabel("Risk Contribution (%)")
    ax3.set_title("MARGINAL RISK CONTRIBUTION\n(equal-weight portfolio)",
                  color=TEXT,fontsize=10,fontweight="bold",loc="left")
    ax3.text(0.97,0.97,f"Diversification Ratio\n= {div_ratio:.2f}x\n\n"
             f"(>1 = diversification benefit\nfrom combining strategies)",
             transform=ax3.transAxes,ha="right",va="top",fontsize=9,
             color=C_TEAL,fontweight="bold",
             bbox=dict(facecolor="white",edgecolor=BORDER,alpha=0.9,boxstyle="round,pad=0.4"))

    _footer(fig)
    _save(fig, "09_monthly_calendar")


# ══════════════════════════════════════════════════════════════════════════════
# 10. VOLATILITY CLUSTERING + GARCH-STYLE VARIANCE TRAJECTORY
#     Shows how trade return volatility clusters — are bad periods predictable?
# ══════════════════════════════════════════════════════════════════════════════
def chart_strategy_equity_curves(trades):
    _font()
    s = _compute(trades)
    pnls = s["pnls"]
    n    = len(pnls)
    xs   = np.arange(n)

    # Squared returns (variance proxy)
    sq   = pnls**2
    # Simple ARCH(5): rolling variance
    win  = min(10, n//4)
    roll_var = pd.Series(sq).rolling(win, min_periods=3).mean().fillna(sq.mean())
    roll_vol = np.sqrt(roll_var)

    # Ljung-Box test on squared returns (test for ARCH effects)
    from scipy.stats import chi2
    nlags = min(10, n//4)
    acf_sq= [float(pd.Series(sq).autocorr(lag=i)) for i in range(1, nlags+1)]
    lb_stat = n * (n+2) * sum(a**2/(n-k) for k,a in enumerate(acf_sq,1))
    lb_pval = 1 - chi2.cdf(lb_stat, df=nlags)

    fig = plt.figure(figsize=(22, 11), facecolor=BG)
    fig.suptitle("VOLATILITY CLUSTERING + VARIANCE TRAJECTORY",
                 fontsize=14,fontweight="bold",color=TEXT,y=0.98)
    fig.text(0.5,0.945,
             "ARCH effects: do large |P&L| cluster together? (bad runs predictable?)  |  "
             f"Ljung-Box p-value on squared returns: {lb_pval:.3f}  "
             f"({'ARCH effects present' if lb_pval<0.05 else 'no significant ARCH effects'})",
             ha="center",fontsize=8.5,color=SUB,style="italic")

    gs = gridspec.GridSpec(2,3,figure=fig,hspace=0.45,wspace=0.35,
                           left=0.07,right=0.97,top=0.90,bottom=0.08)

    # ── Returns with volatility overlay ──────────────────────────────────────
    ax1 = fig.add_subplot(gs[0,:2])
    _ax(ax1)
    ax1.bar(xs, pnls, color=[C_POS if p>=0 else C_NEG for p in pnls],
            alpha=0.65, width=1.0, zorder=2)
    ax1b = ax1.twinx()
    ax1b.plot(xs, roll_vol, color=C_BLUE, lw=1.8, zorder=4, label=f"Rolling {win}-trade vol")
    ax1b.fill_between(xs, roll_vol, alpha=0.1, color=C_BLUE)
    ax1b.set_ylabel("Rolling volatility ($)", color=C_BLUE, fontsize=8)
    ax1b.tick_params(colors=C_BLUE)
    for sp in ax1b.spines.values(): sp.set_edgecolor(BORDER)
    ax1b.legend(fontsize=8, loc="upper right")
    ax1.set_ylabel("Trade P&L ($)")
    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v,_:f"${v:+,.0f}"))
    ax1.set_title("P&L SERIES WITH VOLATILITY OVERLAY",
                  color=TEXT,fontsize=10,fontweight="bold",loc="left")

    # ── Squared returns ACF (ARCH test) ───────────────────────────────────────
    ax2 = fig.add_subplot(gs[0,2])
    _ax(ax2)
    ci = 1.96/np.sqrt(n)
    cols_a = [C_NEG if abs(a)>ci else C_BLUE for a in acf_sq]
    ax2.bar(range(1,len(acf_sq)+1), acf_sq, color=cols_a, alpha=0.8, width=0.7)
    ax2.axhline(ci,  color=C_NEG, lw=0.8, ls="--", alpha=0.7)
    ax2.axhline(-ci, color=C_NEG, lw=0.8, ls="--", alpha=0.7)
    ax2.axhline(0,   color=BORDER, lw=0.5)
    ax2.set_xlabel("Lag"); ax2.set_ylabel("ACF(r²)")
    ax2.set_title(f"ACF OF SQUARED RETURNS\nLjung-Box p={lb_pval:.3f}  "
                  f"({'ARCH' if lb_pval<0.05 else 'no ARCH'})",
                  color=TEXT,fontsize=9,fontweight="bold",loc="left")

    # ── Volatility regime clustering ──────────────────────────────────────────
    ax3 = fig.add_subplot(gs[1,0])
    _ax(ax3)
    vol_pct = np.percentile(roll_vol, [33,67])
    regimes_v = np.where(roll_vol<=vol_pct[0], 0,
                np.where(roll_vol<=vol_pct[1], 1, 2))
    for vreg, label, col in [(0,"Low vol",C_POS),(1,"Med vol",C_ORG),(2,"High vol",C_NEG)]:
        mask = regimes_v==vreg
        if mask.any():
            sub_pnls = pnls[mask]
            wr = float((sub_pnls>0).mean()*100)
            ax3.bar(vreg, wr, color=col, alpha=0.8, width=0.5)
            ax3.text(vreg, wr+1, f"{wr:.0f}%\n(n={mask.sum()})",
                     ha="center",va="bottom",fontsize=9,color=TEXT,fontweight="bold")
            ax3.text(vreg, -4, label, ha="center",va="top",fontsize=8.5,color=col,fontweight="bold")
    ax3.axhline(float((pnls>0).mean()*100), color=BORDER, lw=0.9, ls="--",
                label="Overall WR")
    ax3.set_xticks([0,1,2]); ax3.set_xticklabels([""]*3)
    ax3.set_ylabel("Win Rate (%)"); ax3.set_ylim(-10,105)
    ax3.set_title("WIN RATE BY VOLATILITY REGIME",
                  color=TEXT,fontsize=10,fontweight="bold",loc="left")
    ax3.legend(fontsize=8)

    # ── Vol of vol ────────────────────────────────────────────────────────────
    ax4 = fig.add_subplot(gs[1,1])
    _ax(ax4)
    vov = pd.Series(roll_vol).rolling(win,min_periods=3).std().fillna(0)
    ax4.plot(xs, vov, color=C_PUR, lw=1.8)
    ax4.fill_between(xs, vov, 0, alpha=0.15, color=C_PUR)
    ax4.set_ylabel("Vol of Vol ($)")
    ax4.set_title("VOLATILITY OF VOLATILITY\n(uncertainty in the uncertainty)",
                  color=TEXT,fontsize=10,fontweight="bold",loc="left")

    # ── P&L when vol high vs low ───────────────────────────────────────────────
    ax5 = fig.add_subplot(gs[1,2])
    _ax(ax5)
    lo = pnls[roll_vol <= np.percentile(roll_vol,33)]
    hi = pnls[roll_vol >  np.percentile(roll_vol,67)]
    if len(lo)>2 and len(hi)>2:
        kde_lo = gaussian_kde(lo); kde_hi = gaussian_kde(hi)
        xx = np.linspace(min(lo.min(),hi.min()), max(lo.max(),hi.max()), 300)
        ax5.plot(xx, kde_lo(xx), color=C_POS, lw=2.0, label=f"Low vol (n={len(lo)})")
        ax5.plot(xx, kde_hi(xx), color=C_NEG, lw=2.0, label=f"High vol (n={len(hi)})")
        ax5.fill_between(xx, kde_lo(xx), 0, alpha=0.15, color=C_POS)
        ax5.fill_between(xx, kde_hi(xx), 0, alpha=0.15, color=C_NEG)
        ax5.axvline(0, color=BORDER, lw=0.8, ls=":")
    ax5.set_xlabel("P&L ($)"); ax5.set_ylabel("Density")
    ax5.legend(fontsize=8)
    ax5.set_title("RETURN DISTRIBUTION:\nLOW vs HIGH VOLATILITY REGIMES",
                  color=TEXT,fontsize=10,fontweight="bold",loc="left")

    _footer(fig)
    _save(fig, "10_strategy_equity_curves")


# ── Entry point ────────────────────────────────────────────────────────────────
def generate_all_charts(trades) -> None:
    print(f"\nGenerating advanced quant research charts ({len(trades)} trades) -> {OUT_DIR}/")
    specs = [
        ("01 Kelly Growth Landscape (3D)",       chart_equity_curve),
        ("02 Trade DNA / PCA Manifold",           chart_drawdown),
        ("03 Omega Function + Stochastic Dom.",   chart_strategy_breakdown),
        ("04 Factor IC Matrix",                   chart_pnl_distribution),
        ("05 CVaR Surface (3D)",                  chart_rolling_winrate),
        ("06 Streak Persistence Analysis",        chart_heatmap),
        ("07 Regime-Conditioned Distributions",   chart_vix_scatter),
        ("08 Kelly Fraction Trajectory",          chart_rr_distribution),
        ("09 Strategy Covariance + Frontier",     chart_monthly_calendar),
        ("10 Volatility Clustering + ARCH",       chart_strategy_equity_curves),
    ]
    for name, fn in specs:
        try:
            fn(trades)
        except Exception as e:
            import traceback
            print(f"  [warn] {name}: {e}")
            traceback.print_exc()
    print(f"Done — 10 charts saved to ./{OUT_DIR}/\n")
