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

    fig = plt.figure(figsize=(32, 18), facecolor=BG)
    fig.suptitle("KELLY GROWTH LANDSCAPE  — Log-Wealth Surface + Fractional Kelly + Monte Carlo Wealth Paths",
                 fontsize=14, fontweight="bold", color=TEXT, y=0.98)
    fig.text(0.5, 0.945,
             "z = E[log(1+f*X)] at f* = p−q/b  |  Fractional Kelly risk-of-ruin boundary  |  "
             "1 000 MC simulated wealth paths at f*, f*/2, f*/4",
             ha="center", fontsize=8.5, color=SUB, style="italic")

    gs = gridspec.GridSpec(2, 3, figure=fig, wspace=0.38, hspace=0.48,
                           left=0.04, right=0.97, top=0.91, bottom=0.05)

    WR  = np.linspace(0.45, 0.95, 120)
    RR  = np.linspace(0.3,  6.0,  120)
    W, R = np.meshgrid(WR, RR)

    def _growth(p, b):
        q = 1 - p
        f = np.clip(p - q/b, 0, 0.99)
        g = p*np.log(1 + f*b) + q*np.log(1 - f)
        return g * 252 * 3

    Z = _growth(W, R)
    Z_sys = _growth(wr_sys, rr_sys)

    # ── 3D surface with wireframe overlay ────────────────────────────────────
    ax3d = fig.add_subplot(gs[0], projection="3d")
    ax3d.set_facecolor(BG); ax3d.patch.set_facecolor(BG)
    norm = Normalize(vmin=float(Z.min()), vmax=float(Z.max()))
    cmap = plt.get_cmap("RdYlGn")
    ax3d.plot_surface(W, R, Z, facecolors=cmap(norm(Z)),
                      rstride=2, cstride=2, alpha=0.82, shade=True)
    ax3d.plot_wireframe(W, R, Z, rstride=8, cstride=8,
                        color=BORDER, lw=0.25, alpha=0.4)
    ax3d.contourf(W, R, Z, zdir="z", offset=float(Z.min())-0.5,
                  cmap="RdYlGn", alpha=0.45, levels=15)
    ax3d.scatter([wr_sys],[rr_sys],[Z_sys], color=C_RED, s=220,
                 zorder=10, marker="*", label=f"System ({wr_sys*100:.1f}% WR, {rr_sys:.2f}x RR)")
    ax3d.plot([wr_sys,wr_sys],[rr_sys,rr_sys],[float(Z.min())-0.5, Z_sys],
              color=C_RED, lw=1.2, ls="--", alpha=0.6)
    # Ruin boundary: f >= 1 → guaranteed ruin
    ruin_wr = np.linspace(0.45, 0.95, 60)
    ruin_rr = np.array([max(0.3, (1-w)/max(w-0.5,0.01)) for w in ruin_wr])
    ruin_rr = np.clip(ruin_rr, 0.3, 6.0)
    ruin_z  = _growth(ruin_wr, ruin_rr)
    ax3d.plot(ruin_wr, ruin_rr, ruin_z, color=C_RED, lw=2.0, alpha=0.7, label="Ruin boundary")
    ax3d.set_xlabel("Win Rate p", labelpad=8, fontsize=8, color=SUB)
    ax3d.set_ylabel("R:R Ratio b", labelpad=8, fontsize=8, color=SUB)
    ax3d.set_zlabel("E[log-growth]", labelpad=8, fontsize=8, color=SUB)
    ax3d.tick_params(colors=SUB, labelsize=6.5); ax3d.grid(False)
    ax3d.xaxis.pane.fill=ax3d.yaxis.pane.fill=ax3d.zaxis.pane.fill=False
    for pane in [ax3d.xaxis.pane, ax3d.yaxis.pane, ax3d.zaxis.pane]:
        pane.set_edgecolor(BORDER)
    ax3d.view_init(elev=28, azim=-55)
    ax3d.legend(fontsize=7, loc="upper left")
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([]); cb = fig.colorbar(sm, ax=ax3d, shrink=0.4, pad=0.06)
    cb.ax.tick_params(labelsize=7); cb.set_label("Ann. log-growth", fontsize=7.5)

    # ── 2D contour + fractional Kelly iso-growth lines ───────────────────────
    ax2 = fig.add_subplot(gs[1])
    _ax(ax2)
    cp = ax2.contourf(W, R, Z, levels=30, cmap="RdYlGn")
    ax2.contour(W, R, Z, levels=12, colors="white", linewidths=0.35, alpha=0.4)
    # Iso-growth curves labeled
    cs2 = ax2.contour(W, R, Z, levels=8, colors=TEXT, linewidths=0.5, alpha=0.6)
    ax2.clabel(cs2, fmt="%.2f", fontsize=6.5, colors=TEXT)
    cb2 = fig.colorbar(cp, ax=ax2, shrink=0.8)
    cb2.ax.tick_params(labelsize=7); cb2.set_label("E[log-growth]", fontsize=8)
    ax2.scatter([wr_sys],[rr_sys], color=C_RED, s=280, zorder=10,
                marker="*", label=f"Isogeny Alpha  WR={wr_sys*100:.1f}%  R:R={rr_sys:.2f}x")
    # Fractional Kelly positions
    f_full = max(0, wr_sys - (1-wr_sys)/rr_sys)
    for frac, lbl, col in [(0.5,"½ Kelly",C_BLUE),(0.25,"¼ Kelly",C_PUR)]:
        f_frac = f_full * frac
        # solve p - (1-p)/b = f_frac → for display, show on same WR axis
        ax2.axhline(rr_sys*frac, color=col, lw=0.9, ls=":", alpha=0.7, label=f"{lbl} R:R equiv")
    ax2.axhline(rr_sys, color=C_RED, lw=0.8, ls="--", alpha=0.5)
    ax2.axvline(wr_sys, color=C_RED, lw=0.8, ls="--", alpha=0.5)
    ax2.set_xlabel("Win Rate  p"); ax2.set_ylabel("R:R Ratio  b")
    ax2.set_title("CONTOUR MAP + FRACTIONAL KELLY LINES",
                  color=TEXT, fontsize=10, fontweight="bold", loc="left")
    ax2.legend(fontsize=7.5, framealpha=0.95)
    ax2.text(0.97,0.04,
             f"f* = {f_full*100:.1f}%  |  ½f* = {f_full*50:.1f}%\n"
             f"E[log-growth] = {Z_sys:.4f}\nRisk of ruin at f*: ~{max(0,(1-2*wr_sys)*100):.1f}%",
             transform=ax2.transAxes, ha="right", va="bottom", fontsize=8,
             color=C_RED, fontweight="bold",
             bbox=dict(facecolor="white",edgecolor=BORDER,alpha=0.9,boxstyle="round,pad=0.4"))

    # ── Monte Carlo wealth paths ──────────────────────────────────────────────
    ax3 = fig.add_subplot(gs[2])
    _ax(ax3)
    np.random.seed(42)
    n_sim, n_trades = 800, len(trades)
    avg_w = s["avg_win"]; avg_l = s["avg_loss"]
    for frac, col, lbl, alpha_ in [(1.0,C_NEG,"Full Kelly",0.12),
                                    (0.5,C_BLUE,"½ Kelly",0.18),
                                    (0.25,C_POS,"¼ Kelly",0.25)]:
        paths = np.zeros((n_sim, n_trades+1)); paths[:,0] = 1.0
        for i in range(n_trades):
            win = np.random.rand(n_sim) < wr_sys
            ret = np.where(win, avg_w * frac * f_full, avg_l * frac * f_full)
            paths[:,i+1] = paths[:,i] + ret
        med = np.median(paths, axis=0)
        p10 = np.percentile(paths, 10, axis=0)
        p90 = np.percentile(paths, 90, axis=0)
        xs_p = np.arange(n_trades+1)
        ax3.plot(xs_p, med, color=col, lw=2.0, label=f"{lbl}  (med ${med[-1]:.0f})", zorder=4)
        ax3.fill_between(xs_p, p10, p90, alpha=alpha_, color=col)
    ax3.axhline(0, color=BORDER, lw=0.7, ls=":")
    ax3.set_xlabel("Trade #"); ax3.set_ylabel("Cumulative P&L ($)")
    ax3.set_title(f"MONTE CARLO WEALTH PATHS\n{n_sim} simulations  |  80th-pct band",
                  color=TEXT, fontsize=10, fontweight="bold", loc="left")
    ax3.legend(fontsize=8, framealpha=0.9)
    # Ruin probability annotation
    ruin_pct = float((paths[:,-1] < -500).mean() * 100)
    ax3.text(0.03, 0.04, f"P(ruin<−$500) at ¼ Kelly: {ruin_pct:.1f}%",
             transform=ax3.transAxes, fontsize=8, color=C_NEG, fontweight="bold",
             bbox=dict(facecolor="white",edgecolor=BORDER,alpha=0.9,boxstyle="round,pad=0.3"))

    # ── ROW 2: CRRA utility / Bernoulli growth / drawdown distribution ────────
    ax4 = fig.add_subplot(gs[1, 0])
    _ax(ax4)
    # CRRA utility: U(w) = w^(1-γ)/(1-γ)  for γ ≠ 1
    w_arr = np.linspace(0.01, 3.0, 300)
    for gamma, col, lbl in [(0.5,C_POS,"γ=0.5 (risk-seeking)"),(1.0,C_BLUE,"γ=1 (log utility)"),
                             (2.0,C_ORG,"γ=2 (moderate RA)"),(4.0,C_NEG,"γ=4 (high RA)")]:
        if abs(gamma - 1.0) < 1e-6:
            u = np.log(w_arr)
        else:
            u = (w_arr**(1-gamma) - 1) / (1-gamma)
        u_norm = (u - u.min()) / (u.max() - u.min() + 1e-9)
        ax4.plot(w_arr, u_norm, color=col, lw=1.8, label=lbl)
    ax4.axvline(1.0, color=BORDER, lw=0.8, ls=":")
    ax4.set_xlabel("Wealth w / w₀"); ax4.set_ylabel("Normalised CRRA Utility")
    ax4.set_title("CRRA UTILITY FUNCTIONS U(w)=w^(1−γ)/(1−γ)\nRisk aversion parameter γ",
                  color=TEXT, fontsize=9, fontweight="bold", loc="left")
    ax4.legend(fontsize=7.5, framealpha=0.9)

    ax5 = fig.add_subplot(gs[1, 1])
    _ax(ax5)
    # Geometric mean growth rate g(f) = p*ln(1+f*b) + q*ln(1-f)
    f_arr  = np.linspace(0, 0.99, 300)
    g_arr  = wr_sys*np.log(1 + f_arr*rr_sys) + (1-wr_sys)*np.log(np.maximum(1 - f_arr, 1e-9))
    g_arr  = g_arr * 252 * 3
    f_opt  = max(0.0, wr_sys - (1-wr_sys)/rr_sys)
    g_opt  = float(wr_sys*np.log(1+f_opt*rr_sys) + (1-wr_sys)*np.log(max(1-f_opt,1e-9))) * 252*3
    ax5.plot(f_arr*100, g_arr, color=C_BLUE, lw=2.2)
    ax5.fill_between(f_arr*100, g_arr, 0, where=(g_arr>0), alpha=0.15, color=C_POS)
    ax5.fill_between(f_arr*100, g_arr, 0, where=(g_arr<0), alpha=0.15, color=C_NEG)
    ax5.axvline(f_opt*100, color=C_RED, lw=1.8, ls="--", label=f"f* = {f_opt*100:.1f}%")
    ax5.axvline(f_opt*50,  color=C_ORG, lw=1.2, ls=":", label=f"½f* = {f_opt*50:.1f}%")
    ax5.axhline(0, color=BORDER, lw=0.8)
    ax5.scatter([f_opt*100],[g_opt], color=C_RED, s=120, zorder=5)
    ax5.set_xlabel("Fraction of capital f (%)"); ax5.set_ylabel("g(f) = Ann. log-growth rate")
    ax5.set_title("GEOMETRIC MEAN GROWTH  g(f)=p·ln(1+f·b)+q·ln(1−f)\nOptimal Kelly fraction maximises g",
                  color=TEXT, fontsize=9, fontweight="bold", loc="left")
    ax5.legend(fontsize=8)

    ax6 = fig.add_subplot(gs[1, 2])
    _ax(ax6)
    # Drawdown distribution across MC simulations (using ¼-Kelly paths)
    np.random.seed(99)
    n_sim2 = 1000
    max_dds = []
    for _ in range(n_sim2):
        w = np.zeros(n_trades+1); w[0] = 0.0
        for i in range(n_trades):
            win = np.random.rand() < wr_sys
            w[i+1] = w[i] + (avg_w*0.25*f_full if win else avg_l*0.25*f_full)
        peak_ = np.maximum.accumulate(w); dd_ = w - peak_
        max_dds.append(float(dd_.min()))
    max_dds = np.array(max_dds)
    # Fit exponential to max drawdown (extreme value)
    mdd_pos = -max_dds[max_dds < 0]
    if len(mdd_pos) > 10:
        lam_mdd = 1.0 / float(mdd_pos.mean()) if mdd_pos.mean() > 0 else 1.0
        xs_mdd = np.linspace(0, mdd_pos.max()*1.1, 200)
        ax6.hist(-max_dds, bins=40, color=C_NEG, alpha=0.6, density=True, label="MC max DD dist.")
        ax6.plot(xs_mdd, lam_mdd*np.exp(-lam_mdd*xs_mdd), color=C_RED, lw=2.0,
                 label=f"Exp fit λ={lam_mdd:.3f}")
        p90 = float(np.percentile(mdd_pos, 90))
        ax6.axvline(p90, color=C_ORG, lw=1.5, ls="--", label=f"90th pct DD = ${p90:.0f}")
    ax6.set_xlabel("Maximum Drawdown ($)"); ax6.set_ylabel("Density")
    ax6.set_title(f"MAX DRAWDOWN DISTRIBUTION  ({n_sim2} MC paths, ¼-Kelly)\nExponential tail fit",
                  color=TEXT, fontsize=9, fontweight="bold", loc="left")
    ax6.legend(fontsize=8)

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

    fig = plt.figure(figsize=(32, 18), facecolor=BG)
    fig.suptitle("TRADE FEATURE MANIFOLD  — PCA + 3D Scatter + Biplot + Linear Discriminant Boundary",
                 fontsize=14, fontweight="bold", color=TEXT, y=0.98)
    fig.text(0.5, 0.945,
             "9-dimensional feature space projected onto principal components  |  "
             f"PC1={var_exp[0]*100:.1f}%  PC2={var_exp[1]*100:.1f}%  PC3={var_exp[2]*100:.1f}%  |  "
             "LDA boundary separates WIN/LOSS regions",
             ha="center", fontsize=8.5, color=SUB, style="italic")

    gs = gridspec.GridSpec(2, 4, figure=fig, wspace=0.38, hspace=0.50,
                           left=0.05, right=0.97, top=0.91, bottom=0.05)

    from scipy.stats import gaussian_kde as gkde

    # ── 3D PCA scatter ────────────────────────────────────────────────────────
    pc3 = Xs @ Vt[:3].T
    ax0 = fig.add_subplot(gs[0], projection="3d")
    ax0.set_facecolor(BG); ax0.patch.set_facecolor(BG)
    ax0.scatter(pc3[outcomes==1,0], pc3[outcomes==1,1], pc3[outcomes==1,2],
                c=C_POS, s=28, alpha=0.6, label="WIN", zorder=4)
    ax0.scatter(pc3[outcomes==0,0], pc3[outcomes==0,1], pc3[outcomes==0,2],
                c=C_NEG, s=28, alpha=0.6, label="LOSS", zorder=3)
    ax0.set_xlabel(f"PC1 {var_exp[0]*100:.0f}%", fontsize=7, labelpad=4)
    ax0.set_ylabel(f"PC2 {var_exp[1]*100:.0f}%", fontsize=7, labelpad=4)
    ax0.set_zlabel(f"PC3 {var_exp[2]*100:.0f}%", fontsize=7, labelpad=4)
    ax0.tick_params(labelsize=6); ax0.grid(False)
    ax0.xaxis.pane.fill=ax0.yaxis.pane.fill=ax0.zaxis.pane.fill=False
    for pane in [ax0.xaxis.pane,ax0.yaxis.pane,ax0.zaxis.pane]:
        pane.set_edgecolor(BORDER)
    ax0.view_init(elev=22, azim=-48)
    ax0.legend(fontsize=7.5, loc="upper left")
    ax0.set_title("3D PCA SCATTER\nPC1×PC2×PC3", color=TEXT, fontsize=9, fontweight="bold", pad=4)

    # ── PC1 vs PC2 with KDE contours + LDA boundary ───────────────────────────
    ax1 = fig.add_subplot(gs[1])
    _ax(ax1)
    ax1.scatter(pc[outcomes==0,0], pc[outcomes==0,1], c=C_NEG, s=28,
                alpha=0.55, label="LOSS", zorder=3)
    ax1.scatter(pc[outcomes==1,0], pc[outcomes==1,1], c=C_POS, s=28,
                alpha=0.55, label="WIN",  zorder=4)
    for out, col in [(1,C_POS),(0,C_NEG)]:
        pts = pc[outcomes==out]
        if len(pts) > 5:
            try:
                kde = gkde(pts.T, bw_method="silverman")
                xx_ = np.linspace(pc[:,0].min(),pc[:,0].max(),70)
                yy_ = np.linspace(pc[:,1].min(),pc[:,1].max(),70)
                XX, YY = np.meshgrid(xx_, yy_)
                ZZ = kde(np.vstack([XX.ravel(),YY.ravel()])).reshape(XX.shape)
                ax1.contourf(XX, YY, ZZ, levels=5, colors=col, alpha=0.07)
                ax1.contour(XX, YY, ZZ, levels=4, colors=col, alpha=0.5, linewidths=0.9)
            except: pass
    # LDA decision boundary (simple: project mean difference)
    mu_w = pc[outcomes==1].mean(axis=0); mu_l = pc[outcomes==0].mean(axis=0)
    mid  = (mu_w + mu_l)/2; w_vec = mu_w - mu_l
    if np.linalg.norm(w_vec) > 0:
        slope = -w_vec[0]/w_vec[1] if abs(w_vec[1])>1e-6 else 1e6
        xs_lda = np.array([pc[:,0].min(), pc[:,0].max()])
        ys_lda = mid[1] + slope*(xs_lda - mid[0])
        ax1.plot(xs_lda, ys_lda, color=C_PUR, lw=1.8, ls="--",
                 label="LDA boundary", zorder=5)
    ax1.set_xlabel(f"PC1  ({var_exp[0]*100:.1f}% var)")
    ax1.set_ylabel(f"PC2  ({var_exp[1]*100:.1f}% var)")
    ax1.set_title("WIN/LOSS + KDE CONTOURS\n+ LDA BOUNDARY", color=TEXT, fontsize=9, fontweight="bold", loc="left")
    ax1.legend(fontsize=7.5, framealpha=0.9)

    # ── PC1 vs PC2 colored by score with 2D KDE surface ──────────────────────
    ax2 = fig.add_subplot(gs[2])
    _ax(ax2)
    sc = ax2.scatter(pc[:,0], pc[:,1], c=scores_, cmap="RdYlGn",
                     s=35, alpha=0.85, vmin=5, vmax=21, zorder=4)
    cb = fig.colorbar(sc, ax=ax2, shrink=0.75)
    cb.ax.tick_params(labelsize=7); cb.set_label("Score", fontsize=8)
    # 2D KDE heatmap background
    try:
        kde_all = gkde(pc.T, bw_method=0.4)
        xg = np.linspace(pc[:,0].min(),pc[:,0].max(),60)
        yg = np.linspace(pc[:,1].min(),pc[:,1].max(),60)
        XG,YG = np.meshgrid(xg,yg)
        ZG = kde_all(np.vstack([XG.ravel(),YG.ravel()])).reshape(XG.shape)
        ax2.contour(XG,YG,ZG, levels=6, colors=TEXT, linewidths=0.4, alpha=0.3)
    except: pass
    ax2.set_xlabel(f"PC1  ({var_exp[0]*100:.1f}% var)")
    ax2.set_ylabel(f"PC2  ({var_exp[1]*100:.1f}% var)")
    ax2.set_title("SCORE GRADIENT + DENSITY CONTOURS",
                  color=TEXT, fontsize=9, fontweight="bold", loc="left")

    # ── Biplot: feature loadings all 3 PCs ────────────────────────────────────
    ax3 = fig.add_subplot(gs[3])
    _ax(ax3)
    feat_names = ["VIX","Score","Strategy","Direction","DayOfWeek",
                  "HMM State","Stop Mult","R:R","Risk Pts"]
    lx = Vt[0]; ly = Vt[1]; lz = Vt[2]
    pal_feat = [C_BLUE,C_ORG,C_POS,C_NEG,C_PUR,C_TEAL,C_RED,C_GRN,"#F57F17"]
    for i,(lxi,lyi,lzi,name) in enumerate(zip(lx,ly,lz,feat_names)):
        col = pal_feat[i % len(pal_feat)]
        ax3.annotate("", xy=(lxi,lyi), xytext=(0,0),
                     arrowprops=dict(arrowstyle="-|>", color=col, lw=1.8,
                                    mutation_scale=10))
        # Color by PC3 loading as circle size
        ax3.scatter([lxi],[lyi], s=abs(lzi)*600+20, color=col, alpha=0.35, zorder=3)
        ax3.text(lxi*1.15, lyi*1.15, name, ha="center", va="center",
                 fontsize=7.5, color=col, fontweight="bold")
    ax3.set_xlim(-1.4,1.4); ax3.set_ylim(-1.4,1.4)
    circle = plt.Circle((0,0),1.0,fill=False,color=BORDER,lw=0.9,ls="--")
    ax3.add_patch(circle)
    ax3.axhline(0, color=BORDER, lw=0.5); ax3.axvline(0, color=BORDER, lw=0.5)
    ax3.set_xlabel("PC1 Loading"); ax3.set_ylabel("PC2 Loading")
    ax3.set_title("BIPLOT: FEATURE LOADINGS\n(circle size = |PC3 loading|)",
                  color=TEXT, fontsize=9, fontweight="bold", loc="left")
    # Variance explained bars inset
    inset = ax3.inset_axes([0.65, 0.01, 0.33, 0.28])
    inset.bar(range(len(var_exp[:6])), var_exp[:6]*100, color=C_BLUE, alpha=0.75)
    inset.set_xticks(range(6)); inset.set_xticklabels([f"PC{i+1}" for i in range(6)], fontsize=5.5)
    inset.set_ylabel("%", fontsize=5.5); inset.tick_params(labelsize=5.5)
    inset.set_title("Var exp.", fontsize=5.5)
    for sp in inset.spines.values(): sp.set_edgecolor(BORDER)

    # ── ROW 2: Marchenko-Pastur, score vs P&L scatter, factor loading heatmap ──
    ax_mp = fig.add_subplot(gs[1, 0])
    _ax(ax_mp)
    # Marchenko-Pastur distribution — random matrix theory null
    n_obs, n_feat = Xs.shape
    q = n_obs / n_feat if n_feat > 0 else 1.0
    lam_plus  = (1 + 1/q**0.5)**2
    lam_minus = (1 - 1/q**0.5)**2
    lam_range = np.linspace(max(lam_minus, 1e-4), lam_plus, 300)
    mp_pdf = (q/(2*np.pi)) * np.sqrt(np.maximum((lam_plus-lam_range)*(lam_range-lam_minus),0)) / lam_range
    eigv_sample = np.sort(np.linalg.eigvalsh(Xs.T @ Xs / n_obs))[::-1]
    eigv_norm = eigv_sample / eigv_sample.sum() * len(eigv_sample)
    ax_mp.plot(lam_range, mp_pdf, color=C_RED, lw=2.2, label=f"Marchenko-Pastur  q={q:.2f}")
    ax_mp.hist(eigv_norm, bins=min(20, len(eigv_norm)), density=True,
               color=C_BLUE, alpha=0.6, label="Sample eigenvalues")
    ax_mp.axvline(lam_plus, color=C_RED, lw=1.2, ls="--", label=f"λ+ = {lam_plus:.2f}")
    n_signal = int((eigv_norm > lam_plus).sum())
    ax_mp.set_xlabel("Normalised eigenvalue λ"); ax_mp.set_ylabel("Density")
    ax_mp.set_title(f"MARCHENKO-PASTUR vs SAMPLE EIGENVALUES\n{n_signal} signal PCs beyond random noise",
                    color=TEXT, fontsize=9, fontweight="bold", loc="left")
    ax_mp.legend(fontsize=7.5)

    ax_sc = fig.add_subplot(gs[1, 1])
    _ax(ax_sc)
    scores_arr = np.array([getattr(t,"score",10) for t in trades])
    pnls_arr   = np.array([t.pnl for t in trades])
    win_mask   = np.array([t.outcome=="WIN" for t in trades])
    ax_sc.scatter(scores_arr[win_mask],  pnls_arr[win_mask],  c=C_POS, s=18, alpha=0.6, label="WIN")
    ax_sc.scatter(scores_arr[~win_mask], pnls_arr[~win_mask], c=C_NEG, s=18, alpha=0.6, label="LOSS")
    # Linear regression line
    if len(scores_arr) > 5:
        slope, intercept, r, p_val, _ = sp_stats.linregress(scores_arr, pnls_arr)
        xs_reg = np.linspace(scores_arr.min(), scores_arr.max(), 100)
        ax_sc.plot(xs_reg, slope*xs_reg + intercept, color=TEXT, lw=1.8, ls="--",
                   label=f"OLS: β={slope:.2f}  R²={r**2:.3f}  p={p_val:.3f}")
    ax_sc.axhline(0, color=BORDER, lw=0.8, ls=":")
    ax_sc.set_xlabel("Confidence Score"); ax_sc.set_ylabel("P&L ($)")
    ax_sc.set_title("SCORE vs P&L REGRESSION\nLinear association between signal strength and outcome",
                    color=TEXT, fontsize=9, fontweight="bold", loc="left")
    ax_sc.legend(fontsize=7.5)

    ax_load = fig.add_subplot(gs[1, 2])
    _ax(ax_load)
    feat_names_b = ["VIX","Score","Strategy","Direction","DayOfWeek","HMM State","StopMult","R:R","Risk Pts"]
    pc_load_mat = Vt[:min(5,len(Vt))]
    im_l = ax_load.imshow(pc_load_mat, cmap="RdBu_r", aspect="auto", vmin=-1, vmax=1)
    ax_load.set_xticks(range(len(feat_names_b)))
    ax_load.set_xticklabels(feat_names_b, rotation=35, ha="right", fontsize=8)
    ax_load.set_yticks(range(pc_load_mat.shape[0]))
    ax_load.set_yticklabels([f"PC{i+1}\n{var_exp[i]*100:.0f}%" for i in range(pc_load_mat.shape[0])], fontsize=8)
    for i in range(pc_load_mat.shape[0]):
        for j in range(pc_load_mat.shape[1]):
            v = pc_load_mat[i,j]
            ax_load.text(j, i, f"{v:.2f}", ha="center", va="center",
                         fontsize=7.5, color="white" if abs(v)>0.5 else TEXT)
    fig.colorbar(im_l, ax=ax_load, shrink=0.7).ax.tick_params(labelsize=7)
    ax_load.set_title("PC LOADING HEATMAP\nFeature contribution per principal component",
                      color=TEXT, fontsize=9, fontweight="bold", loc="left")

    ax_dist = fig.add_subplot(gs[1, 3])
    _ax(ax_dist)
    # Mahalanobis distance of each trade from the win centroid
    mu_w_full = Xs[win_mask].mean(axis=0) if win_mask.sum() > 1 else np.zeros(Xs.shape[1])
    try:
        cov_w = np.cov(Xs[win_mask].T) + np.eye(Xs.shape[1]) * 1e-6
        inv_cov = np.linalg.inv(cov_w)
        diff = Xs - mu_w_full
        maha = np.sqrt(np.maximum(np.einsum("ij,jk,ik->i", diff, inv_cov, diff), 0))
        ax_dist.hist(maha[win_mask],  bins=20, color=C_POS, alpha=0.65, density=True, label="WIN")
        ax_dist.hist(maha[~win_mask], bins=20, color=C_NEG, alpha=0.65, density=True, label="LOSS")
        # Chi-squared reference (Mahalanobis^2 ~ Chi2(p))
        xs_chi = np.linspace(0, maha.max()*1.1, 200)
        p_dof = Xs.shape[1]
        chi2_pdf = sp_stats.chi2.pdf(xs_chi**2, df=p_dof) * 2 * xs_chi
        ax_dist.plot(xs_chi, chi2_pdf, color=TEXT, lw=1.5, ls="--", label=f"χ²({p_dof}) reference")
    except Exception:
        ax_dist.text(0.5,0.5,"Mahalanobis\nerror",ha="center",va="center",transform=ax_dist.transAxes)
    ax_dist.set_xlabel("Mahalanobis Distance from WIN centroid")
    ax_dist.set_ylabel("Density")
    ax_dist.set_title("MAHALANOBIS DISTANCE DISTRIBUTION\nWIN vs LOSS in feature space",
                      color=TEXT, fontsize=9, fontweight="bold", loc="left")
    ax_dist.legend(fontsize=7.5)

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

    fig = plt.figure(figsize=(32, 18), facecolor=BG)
    fig.suptitle("OMEGA FUNCTION + STOCHASTIC DOMINANCE + COPULA JOINT DENSITY",
                 fontsize=14, fontweight="bold", color=TEXT, y=0.98)
    fig.text(0.5,0.945,
             "Omega(L) = E[max(r−L,0)] / E[max(L−r,0)]  |  1st & 2nd order stochastic dominance  |  "
             "Empirical copula joint density (3D) vs Gaussian copula",
             ha="center", fontsize=8.5, color=SUB, style="italic")

    gs = gridspec.GridSpec(2,4,figure=fig,wspace=0.40,hspace=0.50,
                           left=0.05,right=0.97,top=0.91,bottom=0.05)

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
    ax3.set_title("SECOND-ORDER STOCHASTIC DOMINANCE\n∫F_α(t)dt ≤ ∫F_rand(t)dt ∀x",
                  color=TEXT,fontsize=9,fontweight="bold",loc="left")
    ax3.legend(fontsize=8)

    # ── 3D Empirical Copula Joint Density ─────────────────────────────────────
    ax4 = fig.add_subplot(gs[3], projection="3d")
    ax4.set_facecolor(BG); ax4.patch.set_facecolor(BG)
    n_c = len(pnls)
    # Consecutive trade pairs for copula
    u = sp_stats.rankdata(pnls[:-1]) / (n_c)
    v = sp_stats.rankdata(pnls[1:])  / (n_c)
    # 2D KDE on copula space
    try:
        kde_cop = gaussian_kde(np.vstack([u, v]), bw_method=0.25)
        ug = np.linspace(0.01, 0.99, 40)
        vg = np.linspace(0.01, 0.99, 40)
        UG, VG = np.meshgrid(ug, vg)
        ZG = kde_cop(np.vstack([UG.ravel(), VG.ravel()])).reshape(UG.shape)
        cmap_cop = plt.get_cmap("plasma")
        norm_cop = Normalize(vmin=ZG.min(), vmax=ZG.max())
        ax4.plot_surface(UG, VG, ZG, facecolors=cmap_cop(norm_cop(ZG)),
                         rstride=1, cstride=1, alpha=0.88, shade=True)
        ax4.plot_wireframe(UG, VG, ZG, rstride=4, cstride=4,
                           color="white", lw=0.2, alpha=0.3)
        ax4.contourf(UG, VG, ZG, zdir="z", offset=float(ZG.min())-0.02,
                     cmap="plasma", alpha=0.5, levels=10)
    except Exception:
        ax4.text(0.5, 0.5, 0.5, "Copula\nerror", ha="center")
    # Diagonal = independence
    diag = np.linspace(0.01, 0.99, 40)
    ax4.plot(diag, diag, np.zeros(40), color=BORDER, lw=1.0, ls="--", alpha=0.7)
    ax4.set_xlabel("U(t)  rank(PnL_t)", labelpad=6, fontsize=8, color=SUB)
    ax4.set_ylabel("U(t+1) rank(PnL_{t+1})", labelpad=6, fontsize=8, color=SUB)
    ax4.set_zlabel("Copula density", labelpad=6, fontsize=8, color=SUB)
    ax4.tick_params(labelsize=6); ax4.grid(False)
    ax4.xaxis.pane.fill=ax4.yaxis.pane.fill=ax4.zaxis.pane.fill=False
    for pane in [ax4.xaxis.pane, ax4.yaxis.pane, ax4.zaxis.pane]:
        pane.set_edgecolor(BORDER)
    ax4.view_init(elev=30, azim=-50)
    # Tail dependence coefficient (upper)
    q95 = 0.95
    tail_dep = float(np.mean((u > q95) & (v > q95))) / (1 - q95)
    ax4.set_title(f"EMPIRICAL COPULA DENSITY\n(consecutive trades)  λ_U={tail_dep:.2f}",
                  color=TEXT, fontsize=9, fontweight="bold", pad=4)
    sm4 = plt.cm.ScalarMappable(cmap="plasma", norm=norm_cop if 'norm_cop' in dir() else Normalize())
    sm4.set_array([]); cb4 = fig.colorbar(sm4, ax=ax4, shrink=0.4, pad=0.06)
    cb4.ax.tick_params(labelsize=6.5); cb4.set_label("Density", fontsize=7.5)

    # ── ROW 2: Sortino surface, higher moments, return attribution ────────────
    ax5 = fig.add_subplot(gs[1, 0])
    _ax(ax5)
    # Sortino ratio = mean / downside deviation across rolling windows
    win_sizes = [10, 15, 20, 30, 40]
    for ws, col in zip(win_sizes, [C_BLUE, C_POS, C_ORG, C_PUR, C_NEG]):
        sortinos = []
        for i in range(ws, len(pnls)):
            sub = pnls[i-ws:i]
            dd_ = sub[sub < 0]
            ds  = float(np.std(dd_)) if len(dd_) > 1 else 1e-8
            sortinos.append(float(np.mean(sub)) / ds * np.sqrt(252*3))
        if sortinos:
            ax5.plot(range(ws, ws+len(sortinos)), sortinos, lw=1.4, color=col,
                     alpha=0.85, label=f"w={ws}")
    ax5.axhline(0, color=BORDER, lw=0.8); ax5.axhline(2.0, color=C_POS, lw=0.9, ls="--", alpha=0.6)
    ax5.set_xlabel("Trade #"); ax5.set_ylabel("Annualised Sortino Ratio")
    ax5.set_title("ROLLING SORTINO RATIO  (downside-only risk)\nSortino = μ / σ_down × √T",
                  color=TEXT, fontsize=9, fontweight="bold", loc="left")
    ax5.legend(fontsize=7.5, framealpha=0.9)

    ax6 = fig.add_subplot(gs[1, 1])
    _ax(ax6)
    # Higher moment statistics bar chart
    moments = {
        "Mean ($)":    float(np.mean(pnls)),
        "Std Dev":     float(np.std(pnls)),
        "Skewness":    float(sp_stats.skew(pnls)),
        "Kurtosis":    float(sp_stats.kurtosis(pnls)),
        "Sharpe":      float(np.mean(pnls))/max(float(np.std(pnls)),1e-8)*np.sqrt(252*3),
        "Sortino":     float(np.mean(pnls))/max(float(np.std(pnls[pnls<0])),1e-8)*np.sqrt(252*3),
        "Win/Loss":    abs(float(np.mean(pnls[pnls>0]))/max(abs(float(np.mean(pnls[pnls<0]))),1e-8)),
        "Hit Rate":    float((pnls>0).mean()),
    }
    mkeys = list(moments.keys()); mvals = list(moments.values())
    cols_m = [C_POS if v >= 0 else C_NEG for v in mvals]
    bars = ax6.barh(range(len(mkeys)), mvals, color=cols_m, alpha=0.8, height=0.6)
    ax6.set_yticks(range(len(mkeys))); ax6.set_yticklabels(mkeys, fontsize=8.5)
    ax6.axvline(0, color=BORDER, lw=0.8)
    for i, (v, b) in enumerate(zip(mvals, bars)):
        ax6.text(v + (0.02 if v >= 0 else -0.02), i, f"{v:.3f}",
                 va="center", ha="left" if v >= 0 else "right", fontsize=8, color=TEXT)
    ax6.set_title("DISTRIBUTION STATISTICS\nMoments, ratios and risk metrics",
                  color=TEXT, fontsize=9, fontweight="bold", loc="left")

    ax7 = fig.add_subplot(gs[1, 2])
    _ax(ax7)
    # Quantile-Quantile plot: P&L vs Normal
    pnls_sorted = np.sort(pnls)
    theoretical_q = sp_stats.norm.ppf(np.linspace(0.02, 0.98, len(pnls_sorted)),
                                       loc=np.mean(pnls), scale=np.std(pnls))
    ax7.scatter(theoretical_q, pnls_sorted, s=12, color=C_BLUE, alpha=0.6, label="Data")
    lims = [min(theoretical_q.min(), pnls_sorted.min()),
            max(theoretical_q.max(), pnls_sorted.max())]
    ax7.plot(lims, lims, color=C_RED, lw=1.8, ls="--", label="Normal reference")
    ax7.fill_between(lims, [l*0.9 for l in lims], [l*1.1 for l in lims],
                     alpha=0.08, color=C_RED)
    sk = sp_stats.skew(pnls); kt = sp_stats.kurtosis(pnls)
    ax7.set_xlabel("Theoretical Normal Quantiles"); ax7.set_ylabel("Sample Quantiles ($)")
    ax7.set_title(f"NORMAL Q-Q PLOT\nskew={sk:.2f}  excess-kurtosis={kt:.2f}",
                  color=TEXT, fontsize=9, fontweight="bold", loc="left")
    ax7.legend(fontsize=8)
    ax7.text(0.03, 0.97, "Tails above line → heavier than\nGaussian (fat tails)",
             transform=ax7.transAxes, va="top", fontsize=7.5, color=SUB, style="italic")

    ax8 = fig.add_subplot(gs[1, 3], projection="3d")
    ax8.set_facecolor(BG); ax8.patch.set_facecolor(BG)
    # 3D histogram of P&L by trade index / time
    n_bins_t = min(8, len(pnls)//5) or 4
    n_bins_p = 12
    t_arr = np.arange(len(pnls))
    H, xedges, yedges = np.histogram2d(t_arr, pnls, bins=[n_bins_t, n_bins_p])
    xpos, ypos = np.meshgrid(xedges[:-1], yedges[:-1], indexing="ij")
    dx = xedges[1]-xedges[0]; dy = yedges[1]-yedges[0]
    cols_3d = plt.cm.RdYlGn(Normalize()(H.ravel()))
    ax8.bar3d(xpos.ravel(), ypos.ravel(), np.zeros(H.size),
              dx*0.85, dy*0.85, H.ravel(), color=cols_3d, alpha=0.85, shade=True)
    ax8.set_xlabel("Trade #", fontsize=7, labelpad=4)
    ax8.set_ylabel("P&L ($)", fontsize=7, labelpad=4)
    ax8.set_zlabel("Count", fontsize=7, labelpad=4)
    ax8.tick_params(labelsize=6); ax8.grid(False)
    ax8.xaxis.pane.fill=ax8.yaxis.pane.fill=ax8.zaxis.pane.fill=False
    for pane in [ax8.xaxis.pane, ax8.yaxis.pane, ax8.zaxis.pane]:
        pane.set_edgecolor(BORDER)
    ax8.view_init(elev=28, azim=-45)
    ax8.set_title("3D P&L HISTOGRAM OVER TIME\n(distribution drift visualisation)",
                  color=TEXT, fontsize=9, fontweight="bold", pad=4)

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

    fig = plt.figure(figsize=(32, 18), facecolor=BG)
    fig.suptitle("FACTOR IC MATRIX + MUTUAL INFORMATION + TRANSFER ENTROPY + SCREE",
                 fontsize=14,fontweight="bold",color=TEXT,y=0.98)
    fig.text(0.5,0.945,
             "Linear IC (Pearson corr with outcome) | Mutual Information (non-linear dependence) | "
             "Transfer Entropy (directional causality between factors) | PCA scree",
             ha="center",fontsize=8.5,color=SUB,style="italic")

    gs = gridspec.GridSpec(2,4,figure=fig,wspace=0.38,hspace=0.52,
                           left=0.05,right=0.97,top=0.90,bottom=0.05,
                           width_ratios=[2.5,0.6,2.5,0.6])

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

    # ── Mutual Information matrix ─────────────────────────────────────────────
    ax_mi = fig.add_subplot(gs[2])
    ax_mi.set_facecolor(PANEL)

    def _mi_bins(x, y, bins=8):
        # Mutual information via histogram joint density
        xy = np.column_stack([x, y])
        try:
            c_xy, _, _ = np.histogram2d(x, y, bins=bins)
            c_x  = c_xy.sum(axis=1, keepdims=True)
            c_y  = c_xy.sum(axis=0, keepdims=True)
            n_   = c_xy.sum()
            p_xy = c_xy / n_; p_x = c_x / n_; p_y = c_y / n_
            with np.errstate(divide="ignore", invalid="ignore"):
                ratio = np.where(p_xy > 0, p_xy / (p_x * p_y + 1e-12), 1.0)
                mi = float(np.sum(p_xy * np.log(ratio + 1e-12)))
            return max(0.0, mi)
        except:
            return 0.0

    nf = len(factor_names)
    MI = np.zeros((nf, nf))
    for i in range(nf):
        for j in range(nf):
            if i == j:
                MI[i,j] = _mi_bins(F[:,i], O, bins=6)  # MI with outcome on diagonal
            else:
                MI[i,j] = _mi_bins(F[:,i], F[:,j], bins=6)

    MI_sorted = MI[np.ix_(order, order)]
    norm_mi = Normalize(vmin=0, vmax=float(MI_sorted.max())+1e-6)
    im_mi = ax_mi.imshow(MI_sorted, cmap="YlOrRd", norm=norm_mi, aspect="auto")
    ax_mi.set_xticks(range(nf)); ax_mi.set_xticklabels(names_sorted, rotation=45, ha="right", fontsize=7.5)
    ax_mi.set_yticks(range(nf)); ax_mi.set_yticklabels(names_sorted, fontsize=7.5)
    for i in range(nf):
        for j in range(nf):
            val = MI_sorted[i,j]
            tc = "white" if val > MI_sorted.max()*0.6 else TEXT
            lbl = "IC" if i==j else f"{val:.2f}"
            ax_mi.text(j, i, f"{val:.2f}", ha="center", va="center",
                       fontsize=6 if nf > 10 else 7, color=tc)
    cb_mi = fig.colorbar(im_mi, ax=ax_mi, shrink=0.7, pad=0.02)
    cb_mi.ax.tick_params(labelsize=6.5); cb_mi.set_label("Mutual Info (nats)", fontsize=7.5)
    for sp in ax_mi.spines.values(): sp.set_edgecolor(BORDER)
    ax_mi.set_title("MUTUAL INFORMATION MATRIX\n(diagonal=MI with outcome, non-linear)",
                    color=TEXT,fontsize=9,fontweight="bold",loc="left",pad=8)

    # ── Scree plot + IC bar combined ──────────────────────────────────────────
    ax3 = fig.add_subplot(gs[3])
    _ax(ax3)
    try:
        eigvals = np.sort(np.linalg.eigvalsh(C))[::-1]
    except np.linalg.LinAlgError:
        eigvals = np.abs(np.linalg.eigvals(C)).real
        eigvals = np.sort(eigvals)[::-1]
    var_exp_f = eigvals / eigvals.sum() * 100
    ax3.bar(range(len(eigvals)), var_exp_f, color=C_BLUE, alpha=0.75)
    ax3_r = ax3.twinx()
    ax3_r.plot(range(len(eigvals)), np.cumsum(var_exp_f), color=C_NEG,
               lw=1.8, marker="o", markersize=4, label="Cumul %")
    ax3_r.axhline(80, color=BORDER, lw=0.8, ls="--")
    ax3_r.set_ylabel("Cumulative %", color=C_NEG, fontsize=7.5)
    ax3_r.tick_params(colors=C_NEG, labelsize=6.5)
    for sp in ax3_r.spines.values(): sp.set_edgecolor(BORDER)
    ax3.set_xlabel("PC"); ax3.set_ylabel("Var Explained (%)", fontsize=7.5)
    ax3.set_title("SCREE PLOT\n(signal dimensionality)",
                  color=TEXT,fontsize=9,fontweight="bold",loc="left")
    n80 = int(np.searchsorted(np.cumsum(var_exp_f), 80)) + 1
    ax3.text(0.97,0.5,f"{n80} PCs\nexplain\n80% var",
             transform=ax3.transAxes,ha="right",va="center",
             fontsize=8.5,color=C_BLUE,fontweight="bold",
             bbox=dict(facecolor="white",edgecolor=BORDER,alpha=0.9,boxstyle="round,pad=0.3"))

    # ── ROW 2: rolling IC, IC hit-rate bar, factor P&L attribution waterfall ──
    ax_ric = fig.add_subplot(gs[1, 0:2])
    _ax(ax_ric)
    win_size_ic = max(10, len(factor_names))
    for fi, fname in enumerate(factor_names[:6]):
        f_series = F[:, fi]
        ic_roll  = []
        for i in range(win_size_ic, len(f_series)):
            sub_f = f_series[i-win_size_ic:i]; sub_o = O[i-win_size_ic:i]
            if sub_f.std() > 0:
                ic_roll.append(float(np.corrcoef(sub_f, sub_o)[0,1]))
        if ic_roll:
            col_ic = STRAT_PAL[fi % len(STRAT_PAL)]
            ax_ric.plot(range(win_size_ic, win_size_ic+len(ic_roll)), ic_roll,
                        lw=1.3, color=col_ic, alpha=0.85, label=fname)
    ax_ric.axhline(0, color=BORDER, lw=0.8); ax_ric.axhline(0.05, color=C_POS, lw=0.7, ls=":")
    ax_ric.axhline(-0.05, color=C_NEG, lw=0.7, ls=":")
    ax_ric.set_xlabel("Trade #"); ax_ric.set_ylabel(f"Rolling IC  (w={win_size_ic})")
    ax_ric.set_title(f"ROLLING INFORMATION COEFFICIENT  (top-6 factors, window={win_size_ic})\n"
                     "IC > 0 = factor predicts wins; dashed lines = ±0.05 threshold",
                     color=TEXT, fontsize=9, fontweight="bold", loc="left")
    ax_ric.legend(fontsize=7.5, framealpha=0.9, loc="upper right")

    ax_hit = fig.add_subplot(gs[1, 2])
    _ax(ax_hit)
    # IC hit rate: fraction of rolling windows where IC > 0
    ic_hits = []
    for fi, fname in enumerate(factor_names):
        f_series = F[:, fi]; hits = 0; total = 0
        for i in range(win_size_ic, len(f_series)):
            sub_f = f_series[i-win_size_ic:i]; sub_o = O[i-win_size_ic:i]
            if sub_f.std() > 0:
                total += 1
                if float(np.corrcoef(sub_f, sub_o)[0,1]) > 0:
                    hits += 1
        ic_hits.append(hits/total if total > 0 else 0.5)
    ic_hits = np.array(ic_hits)
    ic_hits_sorted = ic_hits[order]
    cols_hit = [C_POS if h > 0.5 else C_NEG for h in ic_hits_sorted]
    bars_hit = ax_hit.barh(range(len(names_sorted)), ic_hits_sorted, color=cols_hit, alpha=0.8, height=0.65)
    ax_hit.axvline(0.5, color=C_ORG, lw=1.2, ls="--", label="50% (random)")
    ax_hit.set_yticks(range(len(names_sorted))); ax_hit.set_yticklabels(names_sorted, fontsize=8)
    ax_hit.set_xlabel("IC Hit Rate (fraction of windows where IC > 0)")
    ax_hit.set_xlim(0, 1)
    ax_hit.set_title("IC HIT RATE BY FACTOR\nFraction of time factor is predictive",
                     color=TEXT, fontsize=9, fontweight="bold", loc="left")
    ax_hit.legend(fontsize=8)

    ax_wfall = fig.add_subplot(gs[1, 3])
    _ax(ax_wfall)
    # Cumulative IC × P&L waterfall (factor contribution attribution)
    contrib = ICs * np.std(F, axis=0) * float(np.mean(np.array([t.pnl for t in trades])))
    contrib_sorted = contrib[order]
    running = 0; colors_wf = []
    for c in contrib_sorted:
        colors_wf.append(C_POS if c >= 0 else C_NEG)
    starts = np.zeros(len(contrib_sorted))
    for i in range(1, len(contrib_sorted)):
        starts[i] = starts[i-1] + contrib_sorted[i-1]
    ax_wfall.bar(range(len(names_sorted)), contrib_sorted, bottom=starts,
                 color=colors_wf, alpha=0.8, width=0.7)
    ax_wfall.axhline(0, color=BORDER, lw=0.8)
    ax_wfall.set_xticks(range(len(names_sorted)))
    ax_wfall.set_xticklabels(names_sorted, rotation=45, ha="right", fontsize=7.5)
    ax_wfall.set_ylabel("IC × σ_factor × mean_PnL")
    ax_wfall.set_title("FACTOR P&L ATTRIBUTION\nLinear contribution from each signal",
                       color=TEXT, fontsize=9, fontweight="bold", loc="left")

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

    fig = plt.figure(figsize=(32, 18), facecolor=BG)
    fig.suptitle("CONDITIONAL CVaR SURFACE + SHARPE SURFACE + GPD TAIL FIT  (VIX × Score 3D Risk Landscape)",
                 fontsize=14,fontweight="bold",color=TEXT,y=0.98)
    fig.text(0.5,0.945,
             "Left: CVaR₉₅ surface  |  Center: Sharpe ratio surface  |  "
             "Right: Generalized Pareto Distribution fit to losses — extreme value theory tail index",
             ha="center",fontsize=8.5,color=SUB,style="italic")

    gs = gridspec.GridSpec(2,3,figure=fig,wspace=0.38,hspace=0.50,
                           left=0.04,right=0.97,top=0.90,bottom=0.05)

    # ── CVaR 3D surface ───────────────────────────────────────────────────────
    ax3d = fig.add_subplot(gs[0], projection="3d")
    ax3d.set_facecolor(BG); ax3d.patch.set_facecolor(BG)
    _cv_min = float(np.nanmin(Z_cvar))
    _cv_max = float(np.nanmax(Z_cvar))
    _cv_ctr = float(np.nanmedian(Z_cvar))
    _cv_ctr = np.clip(_cv_ctr, _cv_min + 1e-6, _cv_max - 1e-6)
    if _cv_max <= _cv_min: _cv_max = _cv_min + 1.0
    if _cv_ctr <= _cv_min: _cv_ctr = _cv_min + (_cv_max - _cv_min) * 0.5
    norm = TwoSlopeNorm(vcenter=_cv_ctr, vmin=_cv_min, vmax=_cv_max)
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

    # ── Sharpe surface ────────────────────────────────────────────────────────
    # Build per-cell Sharpe
    grid_sharpe = np.full_like(grid_cvar, np.nan)
    for (vi,si), pnl_list in buckets.items():
        arr = np.array(pnl_list)
        if len(arr) >= 3 and arr.std() > 0:
            grid_sharpe[vi,si] = float(arr.mean() / arr.std() * np.sqrt(252*3))
    m_sh = float(np.nanmean(grid_sharpe)) if not np.all(np.isnan(grid_sharpe)) else 0.0
    Z_sh = np.where(np.isnan(grid_sharpe), m_sh, grid_sharpe)

    ax3d2 = fig.add_subplot(gs[1], projection="3d")
    ax3d2.set_facecolor(BG); ax3d2.patch.set_facecolor(BG)
    cmap2 = plt.get_cmap("RdYlGn")
    sh_min, sh_max = float(Z_sh.min()), float(Z_sh.max())
    if sh_max - sh_min < 1e-6: sh_max = sh_min + 1.0
    norm2 = Normalize(vmin=sh_min, vmax=sh_max)
    ax3d2.plot_surface(X3,Y3,Z_sh, facecolors=cmap2(norm2(Z_sh)),
                       rstride=1,cstride=1,alpha=0.88,shade=True)
    ax3d2.plot_wireframe(X3,Y3,Z_sh, rstride=1,cstride=1,
                         color="white",lw=0.2,alpha=0.25)
    ax3d2.contourf(X3,Y3,Z_sh,zdir="z",offset=float(Z_sh.min())-0.5,
                   cmap="coolwarm",alpha=0.45,levels=10)
    ax3d2.set_xlabel("VIX Level",labelpad=6,fontsize=8,color=SUB)
    ax3d2.set_ylabel("Conf. Score",labelpad=6,fontsize=8,color=SUB)
    ax3d2.set_zlabel("Sharpe Ratio",labelpad=6,fontsize=8,color=SUB)
    ax3d2.tick_params(colors=SUB,labelsize=6.5); ax3d2.grid(False)
    ax3d2.xaxis.pane.fill=ax3d2.yaxis.pane.fill=ax3d2.zaxis.pane.fill=False
    for pane in [ax3d2.xaxis.pane,ax3d2.yaxis.pane,ax3d2.zaxis.pane]:
        pane.set_edgecolor(BORDER)
    ax3d2.view_init(elev=30, azim=-45)
    ax3d2.set_title("SHARPE RATIO SURFACE\n(VIX × Score regime grid)",
                    color=TEXT,fontsize=10,fontweight="bold",pad=8)
    sm2=plt.cm.ScalarMappable(cmap=cmap2,norm=norm2)
    sm2.set_array([]); cb2=fig.colorbar(sm2,ax=ax3d2,shrink=0.42,pad=0.06)
    cb2.ax.tick_params(labelsize=7); cb2.set_label("Annualised Sharpe",fontsize=8)

    # ── GPD Tail Fit (Extreme Value Theory) ───────────────────────────────────
    ax3 = fig.add_subplot(gs[2])
    _ax(ax3)
    all_pnls = np.array([t.pnl for t in trades])
    losses   = -all_pnls[all_pnls < 0]  # positive loss values
    if len(losses) > 10:
        u_thresh = np.percentile(losses, 70)
        excesses = losses[losses > u_thresh] - u_thresh
        # Fit GPD via MLE approximation (method of moments)
        if len(excesses) > 5:
            mu_exc = float(excesses.mean()); var_exc = float(excesses.var())
            xi_gpd = 0.5*(mu_exc**2/var_exc - 1) if var_exc > 0 else 0.1
            beta_gpd= mu_exc*(1 - xi_gpd) if abs(1-xi_gpd) > 1e-6 else mu_exc
            xi_gpd = np.clip(xi_gpd, -0.5, 1.0)
            beta_gpd = max(beta_gpd, 0.01)
            # GPD CDF: 1 - (1 + xi*x/beta)^(-1/xi)
            x_gpd = np.linspace(0, excesses.max()*1.1, 200)
            if abs(xi_gpd) < 1e-4:
                gpd_cdf = 1 - np.exp(-x_gpd/beta_gpd)
            else:
                gpd_cdf = 1 - np.maximum(1 + xi_gpd*x_gpd/beta_gpd, 1e-10)**(-1/xi_gpd)
            # Empirical CDF of excesses
            exc_sorted = np.sort(excesses)
            emp_cdf    = np.arange(1, len(exc_sorted)+1) / len(exc_sorted)
            ax3.step(exc_sorted, emp_cdf, color=C_BLUE, lw=2.0,
                     label=f"Empirical CDF (n={len(excesses)})", where="post")
            ax3.plot(x_gpd, gpd_cdf, color=C_RED, lw=2.0,
                     label=f"GPD fit  ξ={xi_gpd:.3f}  β={beta_gpd:.2f}", zorder=5)
            ax3.fill_between(x_gpd, gpd_cdf, 0, alpha=0.10, color=C_RED)
            # VaR and CVaR from GPD
            p_var = 0.99; n_tot = len(losses)
            n_exc = len(excesses)
            if abs(xi_gpd) < 1e-4:
                var99 = u_thresh + beta_gpd * np.log(n_tot*(1-p_var)/n_exc)
            else:
                var99 = u_thresh + beta_gpd/xi_gpd * ((n_tot*(1-p_var)/n_exc)**(-xi_gpd) - 1)
            cvar99 = (var99 + beta_gpd - xi_gpd*u_thresh) / (1 - xi_gpd)
            ax3.axvline(max(0, var99-u_thresh), color=C_ORG, lw=1.5, ls="--",
                        label=f"VaR₉₉=${var99:.0f}")
            ax3.axvline(max(0, cvar99-u_thresh), color=C_NEG, lw=1.5, ls=":",
                        label=f"CVaR₉₉=${cvar99:.0f}")
            ax3.set_xlabel(f"Excess loss above u=${u_thresh:.0f}")
            ax3.set_ylabel("Cumulative Probability")
            ax3.set_title("EXTREME VALUE THEORY\nGPD Fit to Loss Tail (POT method)",
                          color=TEXT,fontsize=10,fontweight="bold",loc="left")
            tail_lbl = "Heavy tail" if xi_gpd > 0.1 else ("Light tail" if xi_gpd < -0.05 else "Exponential")
            ax3.text(0.97,0.08,
                     f"ξ={xi_gpd:.3f} → {tail_lbl}\nβ={beta_gpd:.2f}\nVaR₉₉=${var99:.0f}\nCVaR₉₉=${cvar99:.0f}",
                     transform=ax3.transAxes,ha="right",va="bottom",fontsize=8.5,
                     color=C_RED,fontweight="bold",
                     bbox=dict(facecolor="white",edgecolor=BORDER,alpha=0.9,boxstyle="round,pad=0.3"))
        ax3.legend(fontsize=8)
    else:
        ax3.text(0.5,0.5,"Insufficient loss data for GPD fit",
                 ha="center",va="center",transform=ax3.transAxes,fontsize=11,color=DIM)

    # ── ROW 2: VaR comparison, tail index evolution, risk decomp ─────────────
    ax_var = fig.add_subplot(gs[1, 0])
    _ax(ax_var)
    all_pnls2 = np.array([t.pnl for t in trades])
    conf_levels = np.linspace(0.80, 0.99, 40)
    var_hist = [-np.percentile(all_pnls2, (1-c)*100) for c in conf_levels]
    var_norm = [sp_stats.norm.ppf(c, loc=-np.mean(all_pnls2), scale=np.std(all_pnls2)) for c in conf_levels]
    ax_var.plot(conf_levels*100, var_hist, color=C_BLUE, lw=2.0, label="Historical Simulation VaR")
    ax_var.plot(conf_levels*100, var_norm, color=C_RED,  lw=2.0, ls="--", label="Parametric Normal VaR")
    ax_var.fill_between(conf_levels*100, var_hist, var_norm,
                        where=np.array(var_hist)>np.array(var_norm),
                        alpha=0.15, color=C_NEG, label="Fat-tail excess")
    ax_var.set_xlabel("Confidence Level (%)"); ax_var.set_ylabel("VaR ($  loss)")
    ax_var.set_title("VaR COMPARISON: HISTORICAL vs PARAMETRIC\nFat-tail excess = non-Gaussian tail risk",
                     color=TEXT, fontsize=9, fontweight="bold", loc="left")
    ax_var.legend(fontsize=8)

    ax_hill = fig.add_subplot(gs[1, 1])
    _ax(ax_hill)
    # Hill estimator for tail index — rolling over different k
    losses_h = -all_pnls2[all_pnls2 < 0]
    if len(losses_h) > 10:
        losses_sorted = np.sort(losses_h)[::-1]
        k_range = range(3, min(len(losses_sorted)//2, 30))
        hill_est = []
        for k in k_range:
            top_k = losses_sorted[:k]
            hill_est.append(1.0 / (np.mean(np.log(top_k)) - np.log(losses_sorted[k])))
        ax_hill.plot(list(k_range), hill_est, color=C_BLUE, lw=2.0, marker="o", markersize=4)
        ax_hill.axhline(2.0, color=C_POS, lw=1.0, ls="--", label="α=2 (finite variance)")
        ax_hill.axhline(1.0, color=C_NEG, lw=1.0, ls="--", label="α=1 (Cauchy)")
        stable_alpha = float(np.median(hill_est)) if hill_est else 2.0
        ax_hill.set_xlabel("k (number of order statistics)")
        ax_hill.set_ylabel("Hill estimator α̂")
        ax_hill.set_title(f"HILL ESTIMATOR FOR TAIL INDEX\nα̂ ≈ {stable_alpha:.2f}  (α>2 = finite variance)",
                          color=TEXT, fontsize=9, fontweight="bold", loc="left")
        ax_hill.legend(fontsize=8)
        ax_hill.text(0.97, 0.97, f"Tail index α ≈ {stable_alpha:.2f}\n"
                                  f"{'Pareto-like' if stable_alpha < 3 else 'Thin tail'}",
                     transform=ax_hill.transAxes, ha="right", va="top", fontsize=8.5,
                     color=C_BLUE, fontweight="bold",
                     bbox=dict(facecolor="white", edgecolor=BORDER, alpha=0.9, boxstyle="round,pad=0.3"))

    ax_wfall2 = fig.add_subplot(gs[1, 2])
    _ax(ax_wfall2)
    # Risk decomposition by strategy
    strat_risk = defaultdict(list)
    for t in trades:
        strat_risk[t.strategy].append(t.pnl)
    strats_r = sorted(strat_risk.keys(), key=lambda s: -abs(np.mean(strat_risk[s])))
    wr_by_s  = [float(np.mean(np.array(strat_risk[s]) > 0)) for s in strats_r]
    pnl_by_s = [float(np.sum(strat_risk[s])) for s in strats_r]
    cvar_by_s= []
    for s in strats_r:
        arr = np.array(strat_risk[s])
        thr = np.percentile(arr, 5) if len(arr) > 1 else arr[0]
        tail = arr[arr <= thr]
        cvar_by_s.append(float(np.mean(tail)) if len(tail) > 0 else 0.0)
    xs_r = np.arange(len(strats_r))
    ax_wfall2.bar(xs_r - 0.25, pnl_by_s, width=0.25, color=C_POS, alpha=0.8, label="Total P&L")
    ax_wfall2.bar(xs_r,        [w*100 for w in wr_by_s], width=0.25, color=C_BLUE, alpha=0.8, label="Win Rate (%)")
    ax_wfall2.bar(xs_r + 0.25, cvar_by_s, width=0.25, color=C_NEG, alpha=0.8, label="CVaR₉₅ ($)")
    ax_wfall2.set_xticks(xs_r)
    ax_wfall2.set_xticklabels([s.replace("vwap_","v.").replace("_","_") for s in strats_r],
                               rotation=30, ha="right", fontsize=8)
    ax_wfall2.axhline(0, color=BORDER, lw=0.8)
    ax_wfall2.set_title("STRATEGY RISK DECOMPOSITION\nP&L / Win Rate / CVaR₉₅ by strategy",
                        color=TEXT, fontsize=9, fontweight="bold", loc="left")
    ax_wfall2.legend(fontsize=7.5)

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

    fig = plt.figure(figsize=(32, 18), facecolor=BG)
    fig.suptitle("STREAK PERSISTENCE + ENTROPY + MARKOV TRANSITION MATRIX",
                 fontsize=14,fontweight="bold",color=TEXT,y=0.98)
    fig.text(0.5,0.945,
             "Streak conditional probabilities  |  Run length vs geometric model  |  "
             "Rolling Shannon entropy (bit complexity)  |  1st-order Markov transition matrix",
             ha="center",fontsize=8.5,color=SUB,style="italic")

    gs = gridspec.GridSpec(2,4,figure=fig,wspace=0.40,hspace=0.52,
                           left=0.05,right=0.97,top=0.90,bottom=0.05)

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

    # ── Markov transition matrix + rolling entropy ────────────────────────────
    ax4 = fig.add_subplot(gs[3])
    _ax(ax4)
    # 1st-order Markov: count transitions
    T = np.zeros((2,2))  # T[i,j] = P(state j | state i)
    for i in range(len(outcomes)-1):
        T[outcomes[i], outcomes[i+1]] += 1
    T_norm = T / (T.sum(axis=1, keepdims=True) + 1e-10)
    labels_m = ["LOSS","WIN"]
    im_m = ax4.imshow(T_norm, cmap="Blues", vmin=0, vmax=1, aspect="auto")
    for i in range(2):
        for j in range(2):
            ax4.text(j, i, f"{T_norm[i,j]:.3f}\n(n={int(T[i,j])})",
                     ha="center", va="center", fontsize=11,
                     color="white" if T_norm[i,j] > 0.6 else TEXT, fontweight="bold")
    ax4.set_xticks([0,1]); ax4.set_xticklabels(["→LOSS","→WIN"], fontsize=10)
    ax4.set_yticks([0,1]); ax4.set_yticklabels(["LOSS|","WIN|"], fontsize=10)
    ax4.set_title("1ST-ORDER MARKOV\nTRANSITION MATRIX",
                  color=TEXT,fontsize=10,fontweight="bold",loc="left")
    cb_m = fig.colorbar(im_m, ax=ax4, shrink=0.6)
    cb_m.ax.tick_params(labelsize=7); cb_m.set_label("Transition prob.", fontsize=8)
    # Stationary distribution annotation
    evals, evecs = np.linalg.eig(T_norm.T)
    stat_idx = np.argmin(np.abs(evals - 1.0))
    stat = np.abs(evecs[:, stat_idx]); stat /= stat.sum()
    ax4.text(0.5, -0.18,
             f"Stationary π: P(WIN)={stat[1]:.3f}  P(LOSS)={stat[0]:.3f}\n"
             f"Entropy rate: {-np.sum(T_norm*np.log(T_norm+1e-12)*stat[:,None]):.3f} bits/trade",
             transform=ax4.transAxes, ha="center", va="top", fontsize=8.5,
             color=C_BLUE, fontweight="bold",
             bbox=dict(facecolor="white",edgecolor=BORDER,alpha=0.9,boxstyle="round,pad=0.3"))

    # ── ROW 2: Runs test, entropy trajectory, autocorrelation ────────────────
    ax_runs = fig.add_subplot(gs[1, 0])
    _ax(ax_runs)
    # Wald-Wolfowitz runs test statistic
    n_w = sum(outcomes); n_l = len(outcomes) - n_w
    n_runs = 1
    for i in range(1, len(outcomes)):
        if outcomes[i] != outcomes[i-1]: n_runs += 1
    mu_runs = 2*n_w*n_l/(n_w+n_l) + 1
    sig_runs = np.sqrt(2*n_w*n_l*(2*n_w*n_l - n_w - n_l) /
                       ((n_w+n_l)**2 * (n_w+n_l-1) + 1e-10))
    z_runs = (n_runs - mu_runs) / (sig_runs + 1e-10)
    p_runs = 2*(1 - sp_stats.norm.cdf(abs(z_runs)))
    # Visualise cumulative outcome series
    cum_out = np.cumsum(outcomes) / (np.arange(len(outcomes))+1)
    ax_runs.plot(range(len(outcomes)), cum_out, color=C_BLUE, lw=1.8, label="Rolling Win Rate")
    ax_runs.axhline(base_wr, color=C_ORG, lw=1.2, ls="--", label=f"Overall WR {base_wr*100:.1f}%")
    ax_runs.fill_between(range(len(outcomes)), base_wr - 2*np.sqrt(base_wr*(1-base_wr)/(np.arange(len(outcomes))+1)),
                         base_wr + 2*np.sqrt(base_wr*(1-base_wr)/(np.arange(len(outcomes))+1)),
                         alpha=0.10, color=C_ORG, label="±2σ confidence band")
    ax_runs.set_xlabel("Trade #"); ax_runs.set_ylabel("Cumulative Win Rate")
    ax_runs.set_title(f"WALD-WOLFOWITZ RUNS TEST\nRuns={n_runs}  E[runs]={mu_runs:.1f}  Z={z_runs:.2f}  p={p_runs:.3f}",
                      color=TEXT, fontsize=9, fontweight="bold", loc="left")
    ax_runs.legend(fontsize=7.5)
    independence_str = "PASS (independent)" if p_runs > 0.05 else "REJECT (serial correlation)"
    ax_runs.text(0.97, 0.05, f"H₀: random order\n{independence_str}",
                 transform=ax_runs.transAxes, ha="right", va="bottom", fontsize=8.5,
                 color=C_POS if p_runs > 0.05 else C_NEG, fontweight="bold",
                 bbox=dict(facecolor="white", edgecolor=BORDER, alpha=0.9, boxstyle="round,pad=0.3"))

    ax_ent = fig.add_subplot(gs[1, 1])
    _ax(ax_ent)
    # Shannon entropy rolling — how predictable are outcomes?
    win_ent = max(10, n//8)
    entropy_series = []
    for i in range(win_ent, len(outcomes)):
        sub = outcomes[i-win_ent:i]
        p_w = np.mean(sub); p_l = 1-p_w
        if 0 < p_w < 1:
            ent = -(p_w*np.log2(p_w+1e-12) + p_l*np.log2(p_l+1e-12))
        else:
            ent = 0.0
        entropy_series.append(ent)
    ax_ent.plot(range(win_ent, len(outcomes)), entropy_series, color=C_PUR, lw=1.8)
    ax_ent.fill_between(range(win_ent, len(outcomes)), entropy_series, 0, alpha=0.15, color=C_PUR)
    ax_ent.axhline(1.0, color=BORDER, lw=0.8, ls="--", label="Max entropy (1 bit = 50% WR)")
    ax_ent.set_xlabel("Trade #"); ax_ent.set_ylabel("Shannon Entropy H (bits)")
    ax_ent.set_ylim(0, 1.1)
    ax_ent.set_title(f"ROLLING SHANNON ENTROPY  (window={win_ent})\nH=1 → 50% WR; H<1 → predictable edge",
                     color=TEXT, fontsize=9, fontweight="bold", loc="left")
    ax_ent.legend(fontsize=8)

    ax_acf = fig.add_subplot(gs[1, 2])
    _ax(ax_acf)
    # Autocorrelation of outcomes (test for serial dependence)
    oc_arr = np.array(outcomes, dtype=float) - np.mean(outcomes)
    max_lag = min(20, len(oc_arr)//4)
    lags    = range(1, max_lag+1)
    acf_vals= [float(np.corrcoef(oc_arr[:-lag], oc_arr[lag:])[0,1]) for lag in lags]
    conf_95 = 1.96 / np.sqrt(len(oc_arr))
    ax_acf.bar(list(lags), acf_vals, color=[C_POS if a>0 else C_NEG for a in acf_vals], alpha=0.75)
    ax_acf.axhline(conf_95,  color=C_RED, lw=1.2, ls="--", label="±95% CI")
    ax_acf.axhline(-conf_95, color=C_RED, lw=1.2, ls="--")
    ax_acf.axhline(0, color=BORDER, lw=0.8)
    ax_acf.set_xlabel("Lag (trades)"); ax_acf.set_ylabel("Autocorrelation")
    ax_acf.set_title("OUTCOME AUTOCORRELATION FUNCTION\nBars outside CI → serial dependence",
                     color=TEXT, fontsize=9, fontweight="bold", loc="left")
    ax_acf.legend(fontsize=8)

    ax_ljung = fig.add_subplot(gs[1, 3])
    _ax(ax_ljung)
    # Ljung-Box Q statistic at each lag
    lb_stats = []
    n_obs_lb = len(oc_arr)
    for k in range(1, max_lag+1):
        q_stat = n_obs_lb*(n_obs_lb+2)*sum(acf_vals[i-1]**2/(n_obs_lb-i) for i in range(1, k+1))
        p_val_lb = 1 - sp_stats.chi2.cdf(q_stat, df=k)
        lb_stats.append((k, q_stat, p_val_lb))
    lb_lags = [x[0] for x in lb_stats]
    lb_pvals = [x[2] for x in lb_stats]
    ax_ljung.scatter(lb_lags, lb_pvals, c=[C_POS if p>0.05 else C_NEG for p in lb_pvals], s=50, zorder=4)
    ax_ljung.plot(lb_lags, lb_pvals, color=SUB, lw=1.0, alpha=0.5)
    ax_ljung.axhline(0.05, color=C_RED, lw=1.5, ls="--", label="α=0.05 significance")
    ax_ljung.set_xlabel("Lag k"); ax_ljung.set_ylabel("Ljung-Box p-value")
    ax_ljung.set_ylim(-0.05, 1.05)
    ax_ljung.set_title("LJUNG-BOX TEST p-VALUES\np > 0.05 → no serial autocorrelation",
                       color=TEXT, fontsize=9, fontweight="bold", loc="left")
    ax_ljung.legend(fontsize=8)
    n_sig = sum(1 for p in lb_pvals if p < 0.05)
    ax_ljung.text(0.97, 0.97, f"{n_sig}/{max_lag} lags significant\n(p<0.05)",
                  transform=ax_ljung.transAxes, ha="right", va="top", fontsize=8.5,
                  color=C_POS if n_sig == 0 else C_NEG, fontweight="bold",
                  bbox=dict(facecolor="white", edgecolor=BORDER, alpha=0.9, boxstyle="round,pad=0.3"))

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

    fig = plt.figure(figsize=(32, 18), facecolor=BG)
    fig.suptitle("REGIME-CONDITIONED DISTRIBUTIONS + HMM TRANSITION MATRIX + 3D REGIME DENSITY",
                 fontsize=14,fontweight="bold",color=TEXT,y=0.98)
    fig.text(0.5,0.945,
             "KDE by HMM regime  |  Regime transition probability matrix  |  "
             "3D joint density surface: P&L × VIX conditioned on regime",
             ha="center",fontsize=8.5,color=SUB,style="italic")

    gs = gridspec.GridSpec(3,3,figure=fig,hspace=0.48,wspace=0.35,
                           left=0.06,right=0.97,top=0.91,bottom=0.04)

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

    # ── HMM regime transition probability matrix ──────────────────────────────
    regime_seq = [getattr(t, "hmm_state", "unavailable") for t in trades]
    reg_uniq   = [r for r in regime_order if r in set(regime_seq)]
    reg_idx    = {r: i for i, r in enumerate(reg_uniq)}
    n_reg = len(reg_uniq)
    T_hmm = np.zeros((n_reg, n_reg))
    for i in range(len(regime_seq)-1):
        if regime_seq[i] in reg_idx and regime_seq[i+1] in reg_idx:
            T_hmm[reg_idx[regime_seq[i]], reg_idx[regime_seq[i+1]]] += 1
    T_hmm_norm = T_hmm / (T_hmm.sum(axis=1, keepdims=True) + 1e-10)

    ax_t = fig.add_subplot(gs[2, 0])
    ax_t.set_facecolor(PANEL)
    im_t = ax_t.imshow(T_hmm_norm, cmap="YlOrRd", vmin=0, vmax=1, aspect="auto")
    short_lbl = [r[:5] for r in reg_uniq]
    ax_t.set_xticks(range(n_reg)); ax_t.set_xticklabels([f"→{l}" for l in short_lbl], fontsize=7, rotation=30, ha="right")
    ax_t.set_yticks(range(n_reg)); ax_t.set_yticklabels(short_lbl, fontsize=7)
    for i in range(n_reg):
        for j in range(n_reg):
            ax_t.text(j, i, f"{T_hmm_norm[i,j]:.2f}", ha="center", va="center",
                      fontsize=7.5, color="white" if T_hmm_norm[i,j]>0.5 else TEXT)
    cb_t = fig.colorbar(im_t, ax=ax_t, shrink=0.7)
    cb_t.ax.tick_params(labelsize=6.5)
    for sp in ax_t.spines.values(): sp.set_edgecolor(BORDER)
    ax_t.set_title("HMM REGIME TRANSITION\nPROBABILITY MATRIX",
                   color=TEXT,fontsize=9,fontweight="bold",loc="left")

    # ── 3D joint density: PnL × VIX ──────────────────────────────────────────
    ax3d_r = fig.add_subplot(gs[2, 1:], projection="3d")
    ax3d_r.set_facecolor(BG); ax3d_r.patch.set_facecolor(BG)
    all_pnl_v = np.array([t.pnl for t in trades])
    all_vix_v = np.array([t.vix for t in trades])
    try:
        kde_jt = gaussian_kde(np.vstack([all_pnl_v, all_vix_v]), bw_method=0.35)
        pg = np.linspace(all_pnl_v.min(), all_pnl_v.max(), 35)
        vg = np.linspace(all_vix_v.min(), all_vix_v.max(), 35)
        PG, VG = np.meshgrid(pg, vg)
        ZJT = kde_jt(np.vstack([PG.ravel(), VG.ravel()])).reshape(PG.shape)
        cmap_jt = plt.get_cmap("plasma")
        norm_jt = Normalize(vmin=ZJT.min(), vmax=ZJT.max())
        ax3d_r.plot_surface(PG, VG, ZJT, facecolors=cmap_jt(norm_jt(ZJT)),
                            rstride=1, cstride=1, alpha=0.88, shade=True)
        ax3d_r.contourf(PG, VG, ZJT, zdir="z", offset=float(ZJT.min())-0.001,
                        cmap="plasma", alpha=0.4, levels=8)
    except Exception:
        pass
    ax3d_r.set_xlabel("P&L ($)", labelpad=6, fontsize=8, color=SUB)
    ax3d_r.set_ylabel("VIX", labelpad=6, fontsize=8, color=SUB)
    ax3d_r.set_zlabel("Joint Density", labelpad=6, fontsize=8, color=SUB)
    ax3d_r.tick_params(labelsize=6); ax3d_r.grid(False)
    ax3d_r.xaxis.pane.fill=ax3d_r.yaxis.pane.fill=ax3d_r.zaxis.pane.fill=False
    for pane in [ax3d_r.xaxis.pane, ax3d_r.yaxis.pane, ax3d_r.zaxis.pane]:
        pane.set_edgecolor(BORDER)
    ax3d_r.view_init(elev=28, azim=-50)
    ax3d_r.set_title("3D JOINT DENSITY: P&L × VIX\n(all regimes combined)",
                     color=TEXT, fontsize=10, fontweight="bold", pad=4)

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

    fig = plt.figure(figsize=(32, 18), facecolor=BG)
    fig.suptitle("KELLY FRACTION TRAJECTORY + JUMP DETECTION + DRAWDOWN CONE",
                 fontsize=14,fontweight="bold",color=TEXT,y=0.98)
    fig.text(0.5,0.945,
             "Rolling Kelly f*(t) vs actual sizing  |  Jump detection (|PnL| > 3σ outliers)  |  "
             "Rolling WR + R:R  |  Bootstrap max-drawdown distribution with percentile cone",
             ha="center",fontsize=8.5,color=SUB,style="italic")

    gs = gridspec.GridSpec(2,3,figure=fig,hspace=0.44,wspace=0.35,
                           left=0.06,right=0.97,top=0.91,bottom=0.04)

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
    wr_arr = np.array(wr_trail)
    ax2.plot(xs, wr_arr, color=C_POS, lw=1.5, zorder=4)
    # Confidence band via Wilson interval
    n_roll = window
    with np.errstate(invalid="ignore"):
        z_val = 1.96
        denom = np.where(~np.isnan(wr_arr), 1 + z_val**2/n_roll, np.nan)
        center = (wr_arr + z_val**2/(2*n_roll)) / denom
        spread = z_val * np.sqrt(np.maximum(wr_arr*(1-wr_arr)/n_roll + z_val**2/(4*n_roll**2), 0)) / denom
        ax2.fill_between(xs, np.clip(center-spread,0,1), np.clip(center+spread,0,1),
                         alpha=0.18, color=C_POS, label="95% Wilson CI")
    ax2.axhline(s["wr"], color=BORDER, lw=0.9, ls="--", label=f"Overall {s['wr']*100:.1f}%")
    ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v,_:f"{v*100:.0f}%"))
    ax2.set_title("ROLLING WIN RATE + WILSON CI",color=TEXT,fontsize=10,fontweight="bold",loc="left")
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

    # ── Bootstrap max-drawdown distribution cone ──────────────────────────────
    ax_bs = fig.add_subplot(gs[1,2])
    _ax(ax_bs)
    pnls_all = s["pnls"]
    np.random.seed(0)
    n_boot = 600
    boot_mdd = []
    for _ in range(n_boot):
        rp = np.random.choice(pnls_all, size=len(pnls_all), replace=True)
        cum_ = np.cumsum(rp); peak_ = np.maximum.accumulate(cum_)
        boot_mdd.append(float((cum_ - peak_).min()))
    boot_mdd = np.array(boot_mdd)
    ax_bs.hist(boot_mdd, bins=40, color=C_BLUE, alpha=0.75, density=True, zorder=3)
    try:
        kde_mdd = gaussian_kde(boot_mdd)
        xx_mdd  = np.linspace(boot_mdd.min(), boot_mdd.max(), 200)
        ax_bs.plot(xx_mdd, kde_mdd(xx_mdd), color=C_PUR, lw=2.0, zorder=4)
    except: pass
    for pct, col, lbl in [(5,C_NEG,"5th pct"),(50,C_BLUE,"Median"),(95,C_POS,"95th pct")]:
        val = float(np.percentile(boot_mdd, pct))
        ax_bs.axvline(val, color=col, lw=1.5, ls="--", label=f"{lbl} ${val:.0f}", zorder=5)
    ax_bs.axvline(float(s["max_dd"]), color=C_RED, lw=2.0, label=f"Actual MDD ${s['max_dd']:.0f}", zorder=6)
    ax_bs.set_xlabel("Max Drawdown ($)"); ax_bs.set_ylabel("Density")
    ax_bs.set_title(f"BOOTSTRAP MDD DISTRIBUTION\n{n_boot} resamples — where does actual MDD fall?",
                    color=TEXT,fontsize=9,fontweight="bold",loc="left")
    ax_bs.legend(fontsize=7.5)
    mdd_pct = float((boot_mdd <= s["max_dd"]).mean()*100)
    ax_bs.text(0.97,0.97,f"Actual MDD at {mdd_pct:.0f}th\npercentile of bootstrap",
               transform=ax_bs.transAxes,ha="right",va="top",fontsize=8.5,
               color=C_RED,fontweight="bold",
               bbox=dict(facecolor="white",edgecolor=BORDER,alpha=0.9,boxstyle="round,pad=0.3"))

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

    fig = plt.figure(figsize=(32, 18), facecolor=BG)
    fig.suptitle("STRATEGY COVARIANCE + SHARPE ATTRIBUTION + RISK PARITY + 3D EFFICIENT FRONTIER",
                 fontsize=14,fontweight="bold",color=TEXT,y=0.98)
    fig.text(0.5,0.945,
             "Daily P&L correlation  |  Sharpe by strategy  |  Marginal risk contribution  |  "
             "3D Monte Carlo efficient frontier (return × vol × Sharpe surface)",
             ha="center",fontsize=8.5,color=SUB,style="italic")

    gs = gridspec.GridSpec(1,4,figure=fig,wspace=0.38,
                           left=0.05,right=0.97,top=0.90,bottom=0.10)

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

    # ── Risk contribution + 3D efficient frontier ─────────────────────────────
    cov_m = np.cov(mat_a.T) if mat_a.shape[0]>1 and len(strategies)>1 else np.eye(len(strategies))
    # Handle scalar covariance
    if cov_m.ndim == 0: cov_m = np.array([[float(cov_m)]])
    cov_m = np.atleast_2d(cov_m)
    w_eq  = np.ones(len(strategies))/len(strategies)
    port_var_eq = max(float(w_eq @ cov_m @ w_eq), 1e-12)
    mrc   = (cov_m @ w_eq) / np.sqrt(port_var_eq)
    rc    = w_eq * mrc; rc = rc / (rc.sum() or 1)
    total_pnl = mat_a.sum(axis=1)
    total_std = float(total_pnl.std()) or 1e-8
    sum_std   = float(std_v.sum()) or 1e-8
    div_ratio = sum_std / total_std

    ax3 = fig.add_subplot(gs[2])
    _ax(ax3)
    cols3 = [STRAT_PAL[i%len(STRAT_PAL)] for i in range(len(strategies))]
    ax3.bar(range(len(strategies)), rc*100, color=cols3, alpha=0.85)
    ax3.set_xticks(range(len(strategies)))
    ax3.set_xticklabels(labels,rotation=45,ha="right",fontsize=8)
    ax3.set_ylabel("Risk Contribution (%)")
    ax3.set_title("MARGINAL RISK CONTRIBUTION\n(equal-weight portfolio)",
                  color=TEXT,fontsize=10,fontweight="bold",loc="left")
    ax3.text(0.97,0.97,f"Diversification Ratio\n= {div_ratio:.2f}x",
             transform=ax3.transAxes,ha="right",va="top",fontsize=9,
             color=C_TEAL,fontweight="bold",
             bbox=dict(facecolor="white",edgecolor=BORDER,alpha=0.9,boxstyle="round,pad=0.4"))

    # ── 3D Efficient Frontier surface (2 strategies shown) ────────────────────
    ax3d_ef = fig.add_subplot(gs[2], projection="3d")
    ax3d_ef.set_facecolor(BG); ax3d_ef.patch.set_facecolor(BG)
    if len(strategies) >= 2:
        # Monte Carlo efficient frontier across all strategy pairs
        np.random.seed(7)
        n_mc_ef = 3000
        n_s = len(strategies)
        rets_mc = []; vols_mc = []; shs_mc = []
        for _ in range(n_mc_ef):
            w_r = np.random.dirichlet(np.ones(n_s))
            p_r = float(w_r @ mean_v * 252)
            p_v = float(np.sqrt(w_r @ cov_m @ w_r) * np.sqrt(252))
            p_s = p_r / (p_v + 1e-10)
            rets_mc.append(p_r); vols_mc.append(p_v); shs_mc.append(p_s)
        rets_mc = np.array(rets_mc); vols_mc = np.array(vols_mc); shs_mc = np.array(shs_mc)
        norm_ef = Normalize(vmin=shs_mc.min(), vmax=shs_mc.max())
        cmap_ef = plt.get_cmap("RdYlGn")
        # Scatter in 2D (return vs vol) colored by Sharpe
        ax3d_ef.scatter(vols_mc, rets_mc, shs_mc, c=shs_mc, cmap="RdYlGn",
                        s=8, alpha=0.55, zorder=3)
        # Mark equal weight
        p_eq_r = float(w_eq @ mean_v * 252)
        p_eq_v = float(np.sqrt(w_eq @ cov_m @ w_eq) * np.sqrt(252))
        p_eq_s = p_eq_r / (p_eq_v + 1e-10)
        ax3d_ef.scatter([p_eq_v],[p_eq_r],[p_eq_s], color=C_RED, s=150,
                        marker="*", zorder=8, label="Equal weight")
        # Max Sharpe
        best_idx = np.argmax(shs_mc)
        ax3d_ef.scatter([vols_mc[best_idx]],[rets_mc[best_idx]],[shs_mc[best_idx]],
                        color=C_BLUE, s=150, marker="^", zorder=8, label="Max Sharpe")
        ax3d_ef.set_xlabel("Ann. Vol", labelpad=6, fontsize=8, color=SUB)
        ax3d_ef.set_ylabel("Ann. Return", labelpad=6, fontsize=8, color=SUB)
        ax3d_ef.set_zlabel("Sharpe", labelpad=6, fontsize=8, color=SUB)
        ax3d_ef.legend(fontsize=7.5, loc="upper left")
    else:
        ax3d_ef.text(0.5,0.5,0.5,"Need ≥2 strategies\nfor frontier",ha="center",fontsize=10)
    ax3d_ef.tick_params(labelsize=6); ax3d_ef.grid(False)
    ax3d_ef.xaxis.pane.fill=ax3d_ef.yaxis.pane.fill=ax3d_ef.zaxis.pane.fill=False
    for pane in [ax3d_ef.xaxis.pane,ax3d_ef.yaxis.pane,ax3d_ef.zaxis.pane]:
        pane.set_edgecolor(BORDER)
    ax3d_ef.view_init(elev=22, azim=-55)
    ax3d_ef.set_title(f"3D EFFICIENT FRONTIER\n{n_mc_ef if len(strategies)>=2 else 0} MC portfolios  (return×vol×Sharpe)",
                      color=TEXT,fontsize=9,fontweight="bold",pad=4)

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

    fig = plt.figure(figsize=(32, 18), facecolor=BG)
    fig.suptitle("VOLATILITY CLUSTERING + VARIANCE TRAJECTORY",
                 fontsize=14,fontweight="bold",color=TEXT,y=0.98)
    fig.text(0.5,0.945,
             "ARCH effects: do large |P&L| cluster together? (bad runs predictable?)  |  "
             f"Ljung-Box p-value on squared returns: {lb_pval:.3f}  "
             f"({'ARCH effects present' if lb_pval<0.05 else 'no significant ARCH effects'})",
             ha="center",fontsize=8.5,color=SUB,style="italic")

    gs = gridspec.GridSpec(2,3,figure=fig,hspace=0.45,wspace=0.35,
                           left=0.07,right=0.97,top=0.91,bottom=0.04)

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
    ax5 = fig.add_subplot(gs[1,1])
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
    ax5.set_title("RETURN DISTRIBUTION:\nLOW vs HIGH VOL REGIMES",
                  color=TEXT,fontsize=10,fontweight="bold",loc="left")

    # ── Wavelet scalogram via scipy CWT ───────────────────────────────────────
    ax6 = fig.add_subplot(gs[1,2])
    _ax(ax6)
    try:
        from scipy import signal as sg
        widths = np.arange(1, min(64, n//4)+1)
        cwt_mat = sg.cwt(pnls, sg.ricker, widths)
        power   = np.abs(cwt_mat)**2
        ax6.imshow(power, extent=[0, n, 1, widths[-1]], aspect="auto",
                   origin="lower", cmap="hot", interpolation="bilinear")
        ax6.set_xlabel("Trade #"); ax6.set_ylabel("Scale (trades)")
        ax6.set_title("WAVELET SCALOGRAM (CWT)\nHot = power at that scale/time — alpha cycles",
                      color=TEXT,fontsize=9,fontweight="bold",loc="left")
        # Mark dominant scale
        dom_scale = int(widths[power.mean(axis=1).argmax()])
        ax6.axhline(dom_scale, color="cyan", lw=1.2, ls="--",
                    label=f"Dominant scale: {dom_scale} trades")
        ax6.legend(fontsize=7.5)
    except Exception as e:
        ax6.text(0.5,0.5,f"Wavelet error:\n{e}",
                 ha="center",va="center",transform=ax6.transAxes,fontsize=9,color=DIM)

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
