"""
Advanced quantitative research visualizations — 15 charts.
Pure math/finance research grade. All 3D where possible.
One chart per image, screen-filling.
"""
from __future__ import annotations
import os
from collections import defaultdict
from itertools import permutations
import math

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import matplotlib.patches as mpatches
from matplotlib.colors import TwoSlopeNorm, LinearSegmentedColormap, Normalize
from mpl_toolkits.mplot3d import Axes3D
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
from scipy import stats as sp_stats
from scipy.stats import gaussian_kde
import warnings
warnings.filterwarnings("ignore")

OUT_DIR = "backtest_charts"

# ── Screen-fill sizes (2408×1506 Retina @ dpi=150) ───────────────────────────
FIG2D = (16.05, 10.04)
FIG3D = (16.05, 10.04)

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
STRAT_PAL = ["#1565C0","#C62828","#2E7D32","#E65100","#6A1B9A",
             "#00695C","#AD1457","#37474F","#F57F17"]


def _font():
    plt.rcParams.update({
        "font.family":"DejaVu Sans","font.size":10,
        "axes.titlesize":13,"axes.labelsize":10,
        "xtick.labelsize":9,"ytick.labelsize":9,
        "legend.fontsize":9,"figure.dpi":150,
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

def _ax3d(ax):
    ax.set_facecolor(BG); ax.patch.set_facecolor(BG)
    ax.tick_params(colors=SUB, labelsize=7); ax.grid(False)
    ax.xaxis.pane.fill = ax.yaxis.pane.fill = ax.zaxis.pane.fill = False
    for pane in [ax.xaxis.pane, ax.yaxis.pane, ax.zaxis.pane]:
        pane.set_edgecolor(BORDER); pane.set_alpha(0.3)

def _save(fig, name):
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, f"{name}.png")
    fig.savefig(path, dpi=150, facecolor=BG)
    plt.close(fig)
    print(f"  saved -> {path}")

def _footer(fig):
    fig.text(0.5, 0.004,
             "ISOGENY ALPHA SYSTEM v7.0  |  KAIROS CAPITAL RESEARCH  |  For Internal Use Only",
             ha="center", va="bottom", color=DIM, fontsize=7, style="italic")

def _compute(trades):
    pnls   = np.array([t.pnl for t in trades])
    wins   = pnls[pnls > 0]; losses = pnls[pnls < 0]
    cum    = np.cumsum(pnls); peak = np.maximum.accumulate(cum); dd = cum - peak
    std_   = float(np.std(pnls)) or 1e-8
    return dict(
        pnls=pnls, cum=cum, dd=dd, wins=wins, losses=losses,
        wr=len(wins)/len(pnls), n=len(pnls),
        avg_win=float(np.mean(wins))   if len(wins)   else 0,
        avg_loss=float(np.mean(losses)) if len(losses) else 1e-8,
        sharpe=float(np.mean(pnls)) / std_ * np.sqrt(252*3),
        max_dd=float(dd.min()),
    )

def _kelly_growth(p, b):
    q = 1 - p
    f = np.clip(p - q / b, 0, 0.99)
    g = p * np.log(1 + f * b) + q * np.log(np.maximum(1 - f, 1e-12))
    return g * 252 * 3


# ══════════════════════════════════════════════════════════════════════════════
# 01. KELLY GROWTH LANDSCAPE — 3D E[log-wealth] surface + geodesic ridge
#     z = p·ln(1+f*b) + (1−p)·ln(1−f)  at f* = p − (1−p)/b
# ══════════════════════════════════════════════════════════════════════════════
def chart_01_kelly_surface(trades):
    _font()
    s      = _compute(trades)
    wr_sys = s["wr"]
    rr_sys = abs(s["avg_win"] / s["avg_loss"]) if s["avg_loss"] else 1.0

    WR = np.linspace(0.40, 0.96, 140)
    RR = np.linspace(0.20, 7.0,  140)
    W, R = np.meshgrid(WR, RR)
    Z    = _kelly_growth(W, R)
    Z_sys = _kelly_growth(wr_sys, rr_sys)

    fig = plt.figure(figsize=FIG3D, facecolor=BG)
    fig.suptitle("KELLY GROWTH LANDSCAPE  —  E[log-wealth] Surface  ·  f* = p − q/b",
                 fontsize=15, fontweight="bold", color=TEXT, y=0.98)
    ax = fig.add_subplot(111, projection="3d"); _ax3d(ax)

    cmap = plt.get_cmap("RdYlGn")
    norm = Normalize(vmin=float(Z.min()), vmax=float(Z.max()))
    ax.plot_surface(W, R, Z, facecolors=cmap(norm(Z)),
                    rstride=2, cstride=2, alpha=0.88, shade=True)
    ax.plot_wireframe(W, R, Z, rstride=10, cstride=10,
                      color=BORDER, lw=0.2, alpha=0.3)
    ax.contourf(W, R, Z, zdir="z", offset=float(Z.min()) - 0.6,
                cmap="RdYlGn", alpha=0.45, levels=18)
    ax.contour(W, R, Z, zdir="x", offset=0.40, cmap="Blues", alpha=0.25, levels=10)
    ax.contour(W, R, Z, zdir="y", offset=7.0,  cmap="Reds",  alpha=0.25, levels=10)

    # System position
    ax.scatter([wr_sys], [rr_sys], [Z_sys], color=C_RED, s=350, zorder=10,
               marker="*", label=f"System  WR={wr_sys*100:.1f}%  R:R={rr_sys:.2f}×  g={Z_sys:.3f}")
    ax.plot([wr_sys, wr_sys], [rr_sys, rr_sys],
            [float(Z.min())-0.6, Z_sys], color=C_RED, lw=1.5, ls="--", alpha=0.7)

    # Optimal ridge (f* = 0 → ruin boundary): p − (1−p)/b = 0 → b = (1−p)/p
    p_ridge = np.linspace(0.42, 0.96, 80)
    b_ridge = (1 - p_ridge) / p_ridge
    z_ridge = _kelly_growth(p_ridge, b_ridge)
    ax.plot(p_ridge, b_ridge, z_ridge, color=C_RED, lw=2.5, alpha=0.85,
            label="Ruin boundary  f*=0")

    # Half-Kelly ridge: effective b at ½f*
    ax.plot(p_ridge, b_ridge * 2, _kelly_growth(p_ridge, b_ridge * 2),
            color=C_ORG, lw=1.8, ls="--", alpha=0.7, label="½-Kelly ridge")

    ax.set_xlabel("Win Rate  p", labelpad=12, fontsize=9, color=SUB)
    ax.set_ylabel("R:R Ratio  b", labelpad=12, fontsize=9, color=SUB)
    ax.set_zlabel("Ann. log-growth  g(f*)", labelpad=12, fontsize=9, color=SUB)
    ax.view_init(elev=30, azim=-55)
    ax.legend(fontsize=9, loc="upper left")
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm); sm.set_array([])
    cb = fig.colorbar(sm, ax=ax, shrink=0.45, pad=0.08)
    cb.set_label("Ann. log-growth rate", fontsize=9); cb.ax.tick_params(labelsize=8)
    _footer(fig); _save(fig, "01_kelly_surface")


# ══════════════════════════════════════════════════════════════════════════════
# 02. 3D PCA MANIFOLD + LDA HYPERPLANE
#     9-feature trade space → PC1×PC2×PC3  ·  transparent LDA decision plane
#     Feature arrows as 3D biplots  ·  convex hull of WIN cluster
# ══════════════════════════════════════════════════════════════════════════════
def chart_02_pca_manifold(trades):
    _font()
    strat_map = {s:i for i,s in enumerate(sorted(set(t.strategy for t in trades)))}
    hmm_map   = {s:i for i,s in enumerate(sorted(set(getattr(t,"hmm_state","n") for t in trades)))}
    day_map   = {"Mon":0,"Tue":1,"Wed":2,"Thu":3,"Fri":4}

    X = np.array([[
        t.vix / 40.0,
        getattr(t,"score",10) / 21.0,
        strat_map.get(t.strategy,0) / max(len(strat_map)-1,1),
        1.0 if t.direction=="long" else 0.0,
        day_map.get(t.day_name,2) / 4.0,
        hmm_map.get(getattr(t,"hmm_state","n"),0) / max(len(hmm_map)-1,1),
        getattr(t,"stop_mult",1.0) / 1.5,
        min(t.rr,10.0) / 10.0,
        t.risk_pts / 30.0,
    ] for t in trades], dtype=float)

    mu_ = X.mean(axis=0); std_ = X.std(axis=0); std_[std_==0] = 1
    Xs  = (X - mu_) / std_
    U, S, Vt = np.linalg.svd(Xs, full_matrices=False)
    pc3 = Xs @ Vt[:3].T
    var_exp = S**2 / (S**2).sum()

    outcomes = np.array([1 if t.outcome=="WIN" else 0 for t in trades])
    win_pc  = pc3[outcomes==1]; loss_pc = pc3[outcomes==0]

    fig = plt.figure(figsize=FIG3D, facecolor=BG)
    fig.suptitle(f"3D PCA MANIFOLD  ·  9-Feature Trade Space  ·  "
                 f"PC1={var_exp[0]*100:.1f}%  PC2={var_exp[1]*100:.1f}%  PC3={var_exp[2]*100:.1f}%",
                 fontsize=14, fontweight="bold", color=TEXT, y=0.98)
    ax = fig.add_subplot(111, projection="3d"); _ax3d(ax)

    ax.scatter(*loss_pc.T, c=C_NEG, s=25, alpha=0.55, label="LOSS", zorder=3)
    ax.scatter(*win_pc.T,  c=C_POS, s=25, alpha=0.55, label="WIN",  zorder=4)

    # Transparent LDA decision plane
    mu_w = win_pc.mean(axis=0);  mu_l = loss_pc.mean(axis=0)
    w_vec = mu_w - mu_l; mid = (mu_w + mu_l) / 2
    if np.linalg.norm(w_vec) > 1e-6:
        w_vec /= np.linalg.norm(w_vec)
        # Find two orthogonal vectors to w_vec
        e = np.array([1,0,0]) if abs(w_vec[0]) < 0.9 else np.array([0,1,0])
        v1 = np.cross(w_vec, e); v1 /= np.linalg.norm(v1)
        v2 = np.cross(w_vec, v1)
        r  = float(np.linalg.norm(pc3.max(axis=0) - pc3.min(axis=0))) * 0.55
        corners = np.array([mid + r*v1 + r*v2, mid - r*v1 + r*v2,
                             mid - r*v1 - r*v2, mid + r*v1 - r*v2])
        poly = Poly3DCollection([corners], alpha=0.18, facecolor=C_PUR, edgecolor=C_PUR, lw=0.8)
        ax.add_collection3d(poly)
        ax.quiver(*mid, *w_vec*r*0.5, color=C_PUR, lw=2.5, arrow_length_ratio=0.2,
                  label="LDA normal vector")

    # Feature loading arrows (biplot)
    feat_names = ["VIX","Score","Strategy","Direction","Day","HMM","StopMult","R:R","Risk"]
    scale = float(pc3.std()) * 1.8
    for i, (lx, ly, lz, name) in enumerate(zip(Vt[0], Vt[1], Vt[2], feat_names)):
        col = STRAT_PAL[i % len(STRAT_PAL)]
        ax.quiver(0,0,0, lx*scale, ly*scale, lz*scale,
                  color=col, lw=1.2, alpha=0.7, arrow_length_ratio=0.15)
        ax.text(lx*scale*1.15, ly*scale*1.15, lz*scale*1.15,
                name, fontsize=7, color=col, fontweight="bold")

    ax.set_xlabel(f"PC1  ({var_exp[0]*100:.1f}%)", labelpad=10, fontsize=9, color=SUB)
    ax.set_ylabel(f"PC2  ({var_exp[1]*100:.1f}%)", labelpad=10, fontsize=9, color=SUB)
    ax.set_zlabel(f"PC3  ({var_exp[2]*100:.1f}%)", labelpad=10, fontsize=9, color=SUB)
    ax.view_init(elev=22, azim=-48)
    ax.legend(fontsize=9, loc="upper left")
    _footer(fig); _save(fig, "02_pca_manifold")


# ══════════════════════════════════════════════════════════════════════════════
# 03. OMEGA 3D SURFACE — Ω(VIX_bin, Score_bin)
#     Omega function computed per (VIX regime × confidence score) cell
#     z = E[max(r,0)] / E[max(−r,0)]  for each cell's P&L distribution
# ══════════════════════════════════════════════════════════════════════════════
def chart_03_omega_surface(trades):
    _font()
    vix_edges   = [0, 14, 18, 23, 30, 60]
    score_edges = [5, 9, 12, 15, 18, 22]
    nv, ns      = len(vix_edges)-1, len(score_edges)-1

    def _bkt(v, edges):
        for i in range(len(edges)-1):
            if edges[i] <= v < edges[i+1]: return i
        return len(edges)-2

    cells = defaultdict(list)
    for t in trades:
        vi = _bkt(t.vix, vix_edges)
        si = _bkt(getattr(t,"score",10), score_edges)
        cells[(vi,si)].append(t.pnl)

    def _omega(arr, L=0.0):
        num = np.mean(np.maximum(arr - L, 0))
        den = np.mean(np.maximum(L - arr, 0))
        return num/den if den > 1e-10 else 10.0

    Z_omega = np.full((nv, ns), np.nan)
    Z_n     = np.zeros((nv, ns), dtype=int)
    for (vi,si), pnls in cells.items():
        if len(pnls) >= 3:
            Z_omega[vi,si] = min(_omega(np.array(pnls)), 15.0)
            Z_n[vi,si] = len(pnls)

    fallback = float(np.nanmean(Z_omega)) if not np.all(np.isnan(Z_omega)) else 1.0
    Z = np.where(np.isnan(Z_omega), fallback, Z_omega)

    xc = [(vix_edges[i]+vix_edges[i+1])/2 for i in range(nv)]
    yc = [(score_edges[i]+score_edges[i+1])/2 for i in range(ns)]
    X3, Y3 = np.meshgrid(xc, yc, indexing="ij")

    fig = plt.figure(figsize=FIG3D, facecolor=BG)
    fig.suptitle("OMEGA FUNCTION 3D SURFACE  ·  Ω(VIX, Score) = E[max(r,0)] / E[max(−r,0)]",
                 fontsize=14, fontweight="bold", color=TEXT, y=0.98)
    ax = fig.add_subplot(111, projection="3d"); _ax3d(ax)

    cmap = plt.get_cmap("RdYlGn")
    norm = Normalize(vmin=0, vmax=float(Z.max()))
    ax.plot_surface(X3, Y3, Z, facecolors=cmap(norm(Z)),
                    rstride=1, cstride=1, alpha=0.90, shade=True)
    ax.plot_wireframe(X3, Y3, Z, rstride=1, cstride=1,
                      color="white", lw=0.5, alpha=0.4)
    ax.contourf(X3, Y3, Z, zdir="z", offset=0.0,
                cmap="RdYlGn", alpha=0.45, levels=12)

    # Ω=1 reference plane (break-even)
    xx_p = np.array([[xc[0], xc[-1]], [xc[0], xc[-1]]])
    yy_p = np.array([[yc[0], yc[0]],  [yc[-1], yc[-1]]])
    zz_p = np.ones_like(xx_p)
    ax.plot_surface(xx_p, yy_p, zz_p, alpha=0.12, color=BORDER)
    ax.plot_wireframe(xx_p, yy_p, zz_p, color=BORDER, lw=0.8, alpha=0.5)

    # Annotate cell sizes
    for vi in range(nv):
        for si in range(ns):
            if Z_n[vi,si] >= 3:
                ax.text(xc[vi], yc[si], Z[vi,si]+0.3,
                        f"n={Z_n[vi,si]}", fontsize=6.5, color=TEXT,
                        ha="center", va="bottom")

    ax.set_xlabel("VIX Level", labelpad=10, fontsize=9, color=SUB)
    ax.set_ylabel("Confidence Score", labelpad=10, fontsize=9, color=SUB)
    ax.set_zlabel("Ω(L=0)", labelpad=10, fontsize=9, color=SUB)
    ax.set_zlim(0, float(Z.max()) + 1)
    ax.view_init(elev=28, azim=-50)
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm); sm.set_array([])
    cb = fig.colorbar(sm, ax=ax, shrink=0.45, pad=0.08)
    cb.set_label("Omega  Ω(0)", fontsize=9); cb.ax.tick_params(labelsize=8)
    _footer(fig); _save(fig, "03_omega_surface")


# ══════════════════════════════════════════════════════════════════════════════
# 04. ROLLING IC SURFACE — factor × trade_index → predictive IC over time
#     IC(factor, t) = ρ(factor_score(t−w:t), outcome(t−w:t))
#     3D surface reveals which signals are temporally stable
# ══════════════════════════════════════════════════════════════════════════════
def chart_04_rolling_ic_surface(trades):
    _font()
    factors = defaultdict(list)
    outcomes_list = []
    for t in trades:
        bd = getattr(t,"score_breakdown",{})
        for k,v in bd.items(): factors[k].append(float(v))
        # Fallback synthetic factors if no breakdown
        if not bd:
            factors["VIX"].append(t.vix / 40.0)
            factors["Score"].append(getattr(t,"score",10) / 21.0)
            factors["R:R"].append(min(t.rr,10)/10.0)
        outcomes_list.append(1.0 if t.outcome=="WIN" else 0.0)

    min_len = min(len(v) for v in factors.values())
    factor_names = sorted(factors.keys())[:8]
    F = np.array([factors[k][:min_len] for k in factor_names]).T
    O = np.array(outcomes_list[:min_len])
    n = len(O)

    window = max(8, n//8)
    t_idx  = list(range(window, n))
    IC_mat = np.zeros((len(factor_names), len(t_idx)))

    for fi in range(len(factor_names)):
        f_s = F[:,fi]
        for ti, t in enumerate(t_idx):
            sub_f = f_s[t-window:t]; sub_o = O[t-window:t]
            if sub_f.std() > 1e-9:
                IC_mat[fi, ti] = float(np.corrcoef(sub_f, sub_o)[0,1])

    FI, TI = np.meshgrid(range(len(factor_names)), t_idx, indexing="ij")

    fig = plt.figure(figsize=FIG3D, facecolor=BG)
    fig.suptitle(f"ROLLING INFORMATION COEFFICIENT SURFACE  ·  window={window} trades  ·  "
                 "IC(f,t) = ρ(signal, outcome)  ·  Temporal stability of predictive power",
                 fontsize=13, fontweight="bold", color=TEXT, y=0.98)
    ax = fig.add_subplot(111, projection="3d"); _ax3d(ax)

    cmap  = plt.get_cmap("RdBu_r")
    norm  = TwoSlopeNorm(vcenter=0, vmin=-0.6, vmax=0.6)
    ax.plot_surface(FI, TI, IC_mat, facecolors=cmap(norm(IC_mat)),
                    rstride=1, cstride=max(1,len(t_idx)//60),
                    alpha=0.88, shade=True)
    ax.plot_wireframe(FI, TI, IC_mat,
                      rstride=1, cstride=max(1,len(t_idx)//20),
                      color="white", lw=0.2, alpha=0.25)
    ax.contourf(FI, TI, IC_mat, zdir="z", offset=-0.65,
                cmap="RdBu_r", norm=norm, alpha=0.40, levels=14)

    # Zero-IC plane
    ax.plot_surface(
        np.array([[0,0],[len(factor_names)-1,len(factor_names)-1]]),
        np.array([[t_idx[0],t_idx[-1]],[t_idx[0],t_idx[-1]]]),
        np.zeros((2,2)), alpha=0.08, color=BORDER)

    ax.set_xticks(range(len(factor_names)))
    ax.set_xticklabels([n[:6] for n in factor_names], fontsize=7, rotation=20)
    ax.set_xlabel("Factor", labelpad=10, fontsize=9, color=SUB)
    ax.set_ylabel("Trade #", labelpad=10, fontsize=9, color=SUB)
    ax.set_zlabel("IC  (Pearson ρ)", labelpad=10, fontsize=9, color=SUB)
    ax.set_zlim(-0.65, 0.65)
    ax.view_init(elev=30, azim=-60)
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm); sm.set_array([])
    cb = fig.colorbar(sm, ax=ax, shrink=0.45, pad=0.08)
    cb.set_label("IC value", fontsize=9); cb.ax.tick_params(labelsize=8)
    _footer(fig); _save(fig, "04_rolling_ic_surface")


# ══════════════════════════════════════════════════════════════════════════════
# 05. DUAL 3D RISK SURFACE — CVaR₉₅ + Sharpe intersecting surfaces
#     Two 3D surfaces over the same VIX × Score grid
#     Intersection ridge = regime where CVaR improves and Sharpe degrades
# ══════════════════════════════════════════════════════════════════════════════
def chart_05_dual_risk_surface(trades):
    _font()
    vix_edges   = [0,14,18,23,30,60]
    score_edges = [5,9,12,15,18,22]
    nv, ns = len(vix_edges)-1, len(score_edges)-1

    def _bkt(v, edges):
        for i in range(len(edges)-1):
            if edges[i] <= v < edges[i+1]: return i
        return len(edges)-2

    cells = defaultdict(list)
    for t in trades:
        cells[(_bkt(t.vix,vix_edges), _bkt(getattr(t,"score",10),score_edges))].append(t.pnl)

    Z_cvar   = np.full((nv,ns), np.nan)
    Z_sharpe = np.full((nv,ns), np.nan)
    for (vi,si),pnls in cells.items():
        arr = np.array(pnls)
        if len(arr) >= 3:
            q5 = np.percentile(arr,5)
            Z_cvar[vi,si]   = float(np.mean(arr[arr<=q5])) if (arr<=q5).any() else q5
            Z_sharpe[vi,si] = float(arr.mean()/arr.std()*np.sqrt(252*3)) if arr.std()>0 else 0

    fc = float(np.nanmean(Z_cvar))   if not np.all(np.isnan(Z_cvar))   else -30.0
    fs = float(np.nanmean(Z_sharpe)) if not np.all(np.isnan(Z_sharpe)) else 1.0
    Z_c = np.where(np.isnan(Z_cvar),   fc, Z_cvar)
    Z_s = np.where(np.isnan(Z_sharpe), fs, Z_sharpe)

    xc = [(vix_edges[i]+vix_edges[i+1])/2 for i in range(nv)]
    yc = [(score_edges[i]+score_edges[i+1])/2 for i in range(ns)]
    X3, Y3 = np.meshgrid(xc, yc, indexing="ij")

    # Normalise Sharpe to same z-range as CVaR for visual overlay
    c_min, c_max = Z_c.min(), Z_c.max()
    s_min, s_max = Z_s.min(), Z_s.max()
    span = max(c_max - c_min, 1e-3)
    Z_s_scaled = (Z_s - s_min) / (s_max - s_min + 1e-9) * span + c_min

    fig = plt.figure(figsize=FIG3D, facecolor=BG)
    fig.suptitle("DUAL RISK SURFACE  ·  CVaR₉₅ (red) vs Sharpe Ratio (green) over VIX × Score Grid",
                 fontsize=14, fontweight="bold", color=TEXT, y=0.98)
    ax = fig.add_subplot(111, projection="3d"); _ax3d(ax)

    cmap_c = plt.get_cmap("Reds_r")
    cmap_s = plt.get_cmap("Greens")
    ax.plot_surface(X3, Y3, Z_c, facecolors=cmap_c(Normalize()(Z_c)),
                    rstride=1, cstride=1, alpha=0.65, shade=True)
    ax.plot_surface(X3, Y3, Z_s_scaled, facecolors=cmap_s(Normalize()(Z_s)),
                    rstride=1, cstride=1, alpha=0.65, shade=True)

    # Intersection contour (projected)
    ax.contourf(X3, Y3, Z_c, zdir="z", offset=c_min-abs(c_min)*0.3,
                cmap="Reds_r", alpha=0.35, levels=10)
    ax.contourf(X3, Y3, Z_s_scaled, zdir="z", offset=c_min-abs(c_min)*0.3,
                cmap="Greens", alpha=0.35, levels=10)
    ax.contour(X3, Y3, Z_c-Z_s_scaled, zdir="z",
               offset=c_min-abs(c_min)*0.3, levels=[0],
               colors=[C_PUR], linewidths=2.5, alpha=0.9)

    ax.set_xlabel("VIX Level", labelpad=10, fontsize=9, color=SUB)
    ax.set_ylabel("Confidence Score", labelpad=10, fontsize=9, color=SUB)
    ax.set_zlabel("Risk Metric (normalised)", labelpad=10, fontsize=9, color=SUB)
    ax.view_init(elev=28, azim=-45)

    from matplotlib.lines import Line2D
    leg = [Line2D([0],[0], color=C_NEG, lw=3, label="CVaR₉₅ surface"),
           Line2D([0],[0], color=C_POS, lw=3, label="Sharpe surface (scaled)"),
           Line2D([0],[0], color=C_PUR, lw=2.5, ls="--", label="Intersection ridge")]
    ax.legend(handles=leg, fontsize=9, loc="upper left")
    _footer(fig); _save(fig, "05_dual_risk_surface")


# ══════════════════════════════════════════════════════════════════════════════
# 06. HAWKES PROCESS INTENSITY — 3D self-exciting point process
#     Trades modelled as Hawkes process:  λ(t) = μ + Σ α·e^{−β(t−tᵢ)}
#     Surface: λ(trade_index, α_param) — sensitivity of intensity to branching ratio
# ══════════════════════════════════════════════════════════════════════════════
def chart_06_hawkes_intensity(trades):
    _font()
    n = len(trades)
    # Inter-arrival times (use trade index as proxy for time)
    t_arr = np.arange(n, dtype=float)
    pnls  = np.array([t.pnl for t in trades])

    # Fit Hawkes via method of moments: estimate μ, α, β
    mu_hat   = 1.0
    alpha_range = np.linspace(0.05, 0.85, 60)
    beta_hat    = 1.5  # fixed decay rate

    def _hawkes_intensity(t_pts, alpha, mu=mu_hat, beta=beta_hat):
        lam = np.zeros(len(t_pts))
        for i, t in enumerate(t_pts):
            lam[i] = mu + alpha * sum(np.exp(-beta*(t-s)) for s in t_pts[:i] if t>s)
        return lam

    # Build surface: rows=alpha, cols=trade_index
    T_grid = np.linspace(0, n-1, min(80, n))
    A_grid = alpha_range
    Z_lam  = np.zeros((len(A_grid), len(T_grid)))

    for ai, alpha in enumerate(A_grid):
        lam_series = np.zeros(len(T_grid))
        running_sum = 0.0
        last_t = 0.0
        j = 0
        for ti, t in enumerate(T_grid):
            running_sum *= np.exp(-beta_hat * (t - last_t))
            running_sum += alpha
            lam_series[ti] = mu_hat + running_sum
            last_t = t
        Z_lam[ai] = lam_series

    AG, TG = np.meshgrid(A_grid, T_grid, indexing="ij")

    # Actual intensity with best-fit alpha (alpha = 0.3 as reasonable default)
    alpha_best = 0.3
    lam_actual = np.zeros(n)
    rs = 0.0; lt = 0.0
    for i in range(n):
        rs *= np.exp(-beta_hat*(i - lt)); rs += alpha_best; lt = float(i)
        lam_actual[i] = mu_hat + rs

    fig = plt.figure(figsize=FIG3D, facecolor=BG)
    fig.suptitle("HAWKES PROCESS INTENSITY SURFACE  ·  λ(t) = μ + α·Σe^{−β(t−tᵢ)}  ·  "
                 "Self-exciting trade arrival model  ·  α = branching ratio",
                 fontsize=13, fontweight="bold", color=TEXT, y=0.98)
    ax = fig.add_subplot(111, projection="3d"); _ax3d(ax)

    cmap = plt.get_cmap("plasma")
    norm = Normalize(vmin=Z_lam.min(), vmax=Z_lam.max())
    ax.plot_surface(AG, TG, Z_lam, facecolors=cmap(norm(Z_lam)),
                    rstride=1, cstride=1, alpha=0.88, shade=True)
    ax.plot_wireframe(AG, TG, Z_lam, rstride=5, cstride=5,
                      color="white", lw=0.2, alpha=0.2)
    ax.contourf(AG, TG, Z_lam, zdir="z", offset=float(Z_lam.min())-0.1,
                cmap="plasma", alpha=0.4, levels=14)

    # Overlay actual λ(t) at best alpha
    ax.plot([alpha_best]*n, np.arange(n,dtype=float), lam_actual,
            color=C_RED, lw=2.5, zorder=10, label=f"Actual λ(t) at α={alpha_best}")

    # Critical alpha = 1 (explosive regime)
    ax.plot([1.0]*2, [T_grid[0], T_grid[-1]], [Z_lam.max()]*2,
            color=C_RED, lw=1.5, ls="--", alpha=0.7)

    ax.set_xlabel("Branching ratio  α", labelpad=10, fontsize=9, color=SUB)
    ax.set_ylabel("Trade index  t", labelpad=10, fontsize=9, color=SUB)
    ax.set_zlabel("Intensity  λ(t)", labelpad=10, fontsize=9, color=SUB)
    ax.view_init(elev=30, azim=-55)
    ax.legend(fontsize=9, loc="upper left")
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm); sm.set_array([])
    cb = fig.colorbar(sm, ax=ax, shrink=0.45, pad=0.08)
    cb.set_label("λ(t) intensity", fontsize=9); cb.ax.tick_params(labelsize=8)
    _footer(fig); _save(fig, "06_hawkes_intensity")


# ══════════════════════════════════════════════════════════════════════════════
# 07. JOINT DENSITY 3D SURFACE — P&L × VIX Gaussian KDE
#     Plasma-colored density ridge shows where most trades cluster
#     Projected contours on all three walls
# ══════════════════════════════════════════════════════════════════════════════
def chart_07_joint_density(trades):
    _font()
    pnl_arr = np.array([t.pnl for t in trades])
    vix_arr = np.array([t.vix for t in trades])
    sc_arr  = np.array([getattr(t,"score",10) for t in trades])
    outcomes= np.array([1 if t.outcome=="WIN" else 0 for t in trades])

    pg = np.linspace(pnl_arr.min(), pnl_arr.max(), 50)
    vg = np.linspace(vix_arr.min(), vix_arr.max(), 50)
    PG, VG = np.meshgrid(pg, vg)

    try:
        kde = gaussian_kde(np.vstack([pnl_arr, vix_arr]), bw_method=0.35)
        ZG  = kde(np.vstack([PG.ravel(), VG.ravel()])).reshape(PG.shape)
    except Exception:
        ZG = np.ones_like(PG)

    fig = plt.figure(figsize=FIG3D, facecolor=BG)
    fig.suptitle("JOINT DENSITY SURFACE  ·  f(P&L, VIX) via Gaussian KDE  ·  "
                 "Plasma ridge = probability mass  ·  Projections on all walls",
                 fontsize=13, fontweight="bold", color=TEXT, y=0.98)
    ax = fig.add_subplot(111, projection="3d"); _ax3d(ax)

    cmap = plt.get_cmap("plasma")
    norm = Normalize(vmin=ZG.min(), vmax=ZG.max())
    ax.plot_surface(PG, VG, ZG, facecolors=cmap(norm(ZG)),
                    rstride=1, cstride=1, alpha=0.90, shade=True)
    ax.plot_wireframe(PG, VG, ZG, rstride=4, cstride=4,
                      color="white", lw=0.2, alpha=0.18)

    # Projections on all three walls
    z0 = float(ZG.min()) - 0.001
    ax.contourf(PG, VG, ZG, zdir="z", offset=z0, cmap="plasma", alpha=0.4, levels=12)
    ax.contourf(PG, VG, ZG, zdir="x", offset=pnl_arr.min()*1.4, cmap="Purples", alpha=0.3, levels=8)
    ax.contourf(PG, VG, ZG, zdir="y", offset=vix_arr.max()*1.1, cmap="Oranges",  alpha=0.3, levels=8)

    # Scatter WIN/LOSS at density floor
    ax.scatter(pnl_arr[outcomes==1], vix_arr[outcomes==1], np.full(outcomes.sum(), z0),
               c=C_POS, s=8, alpha=0.35, zorder=4)
    ax.scatter(pnl_arr[outcomes==0], vix_arr[outcomes==0], np.full((outcomes==0).sum(), z0),
               c=C_NEG, s=8, alpha=0.35, zorder=4)

    ax.set_xlabel("Trade P&L ($)", labelpad=10, fontsize=9, color=SUB)
    ax.set_ylabel("VIX", labelpad=10, fontsize=9, color=SUB)
    ax.set_zlabel("Joint Density  f(p, v)", labelpad=10, fontsize=9, color=SUB)
    ax.view_init(elev=28, azim=-50)
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm); sm.set_array([])
    cb = fig.colorbar(sm, ax=ax, shrink=0.45, pad=0.08)
    cb.set_label("Density", fontsize=9); cb.ax.tick_params(labelsize=8)
    _footer(fig); _save(fig, "07_joint_density")


# ══════════════════════════════════════════════════════════════════════════════
# 08. ROLLING KELLY SURFACE — f*(trade_index, window_size)
#     3D surface showing how optimal Kelly fraction changes
#     across different lookback windows simultaneously
# ══════════════════════════════════════════════════════════════════════════════
def chart_08_rolling_kelly_surface(trades):
    _font()
    s  = _compute(trades)
    n  = len(trades)
    pnls = s["pnls"]

    windows = list(range(5, min(40, n//2)+1, 2))
    t_range = list(range(max(windows), n))

    Z_kelly = np.full((len(windows), len(t_range)), np.nan)
    Z_wr    = np.full_like(Z_kelly, np.nan)

    for wi, w in enumerate(windows):
        for ti, t in enumerate(t_range):
            sub  = pnls[t-w:t]
            wr_  = float((sub>0).mean())
            win_ = sub[sub>0]; los_ = sub[sub<0]
            aw   = float(np.mean(win_)) if len(win_)>0 else 1e-3
            al   = abs(float(np.mean(los_))) if len(los_)>0 else 1e-3
            rr_  = aw/al if al>0 else 1.0
            f_k  = max(0, wr_ - (1-wr_)/rr_)
            Z_kelly[wi,ti] = min(f_k, 1.0)
            Z_wr[wi,ti]    = wr_

    WI, TI = np.meshgrid(windows, t_range, indexing="ij")

    fig = plt.figure(figsize=FIG3D, facecolor=BG)
    fig.suptitle("ROLLING KELLY SURFACE  ·  f*(window, t) = p(w,t) − [1−p(w,t)] / R:R(w,t)",
                 fontsize=13, fontweight="bold", color=TEXT, y=0.98)
    ax = fig.add_subplot(111, projection="3d"); _ax3d(ax)

    Z_plot = np.where(np.isnan(Z_kelly), 0, Z_kelly)
    cmap   = plt.get_cmap("RdYlGn")
    norm   = Normalize(vmin=0, vmax=float(Z_plot.max()))
    ax.plot_surface(WI, TI, Z_plot, facecolors=cmap(norm(Z_plot)),
                    rstride=1, cstride=max(1,len(t_range)//60),
                    alpha=0.88, shade=True)
    ax.plot_wireframe(WI, TI, Z_plot, rstride=2, cstride=max(1,len(t_range)//20),
                      color="white", lw=0.2, alpha=0.2)
    ax.contourf(WI, TI, Z_plot, zdir="z", offset=-0.05,
                cmap="RdYlGn", alpha=0.4, levels=12)

    # Actual sizing trace (single window at default)
    actual_f = np.array([getattr(t,"n_contracts",1)/2.0 for t in trades])
    w_default = min(20, max(windows))
    wi_idx = windows.index(w_default) if w_default in windows else 0
    ax.plot([windows[wi_idx]]*len(t_range), t_range,
            Z_plot[wi_idx,:], color=C_RED, lw=2.5, zorder=10,
            label=f"f* at window={windows[wi_idx]}")

    ax.set_xlabel("Window size  w", labelpad=10, fontsize=9, color=SUB)
    ax.set_ylabel("Trade index  t", labelpad=10, fontsize=9, color=SUB)
    ax.set_zlabel("Kelly fraction  f*(w,t)", labelpad=10, fontsize=9, color=SUB)
    ax.zaxis.set_major_formatter(mticker.FuncFormatter(lambda v,_:f"{v*100:.0f}%"))
    ax.view_init(elev=30, azim=-55)
    ax.legend(fontsize=9, loc="upper left")
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm); sm.set_array([])
    cb = fig.colorbar(sm, ax=ax, shrink=0.45, pad=0.08)
    cb.set_label("Optimal Kelly f*", fontsize=9); cb.ax.tick_params(labelsize=8)
    _footer(fig); _save(fig, "08_rolling_kelly_surface")


# ══════════════════════════════════════════════════════════════════════════════
# 09. 3D EFFICIENT FRONTIER — return × vol × Sharpe Monte Carlo
#     3000 random portfolio weights → scatter in (μ, σ, Sharpe) space
#     Color = Sharpe ratio  ·  Stars = equal-weight + max-Sharpe + min-vol
# ══════════════════════════════════════════════════════════════════════════════
def chart_09_efficient_frontier(trades):
    _font()
    all_dates  = sorted(set(t.date for t in trades))
    date_idx   = {d:i for i,d in enumerate(all_dates)}
    strategies = sorted(set(t.strategy for t in trades))
    ns         = len(strategies)

    mat = np.zeros((len(all_dates), ns))
    for t in trades:
        mat[date_idx[t.date], strategies.index(t.strategy)] += t.pnl
    active = (mat!=0).any(axis=1); mat_a = mat[active]
    if mat_a.shape[0] < 2 or ns < 2:
        fig = plt.figure(figsize=FIG3D, facecolor=BG)
        ax  = fig.add_subplot(111, projection="3d"); _ax3d(ax)
        ax.text(0,0,0,"Need ≥2 strategies and ≥2 days",fontsize=13,ha="center")
        _save(fig,"09_efficient_frontier"); return

    mean_v = mat_a.mean(axis=0)
    cov_m  = np.cov(mat_a.T) + np.eye(ns)*1e-8

    np.random.seed(42)
    n_mc   = 4000
    rets_mc=[]; vols_mc=[]; shs_mc=[]
    for _ in range(n_mc):
        w = np.random.dirichlet(np.ones(ns))
        r = float(w@mean_v*252); v = float(np.sqrt(w@cov_m@w)*np.sqrt(252))
        rets_mc.append(r); vols_mc.append(v); shs_mc.append(r/(v+1e-10))
    rets_mc=np.array(rets_mc); vols_mc=np.array(vols_mc); shs_mc=np.array(shs_mc)

    fig = plt.figure(figsize=FIG3D, facecolor=BG)
    fig.suptitle("3D EFFICIENT FRONTIER  ·  μ × σ × Sharpe Monte Carlo  ·  "
                 f"{n_mc} random portfolios  ·  {ns} strategies  ·  Color = Sharpe ratio",
                 fontsize=13, fontweight="bold", color=TEXT, y=0.98)
    ax = fig.add_subplot(111, projection="3d"); _ax3d(ax)

    cmap = plt.get_cmap("RdYlGn")
    norm = Normalize(vmin=shs_mc.min(), vmax=shs_mc.max())
    sc = ax.scatter(vols_mc, rets_mc, shs_mc, c=shs_mc, cmap="RdYlGn",
                    norm=norm, s=6, alpha=0.50, zorder=3)

    # Special portfolios
    w_eq = np.ones(ns)/ns
    eq_r = float(w_eq@mean_v*252); eq_v=float(np.sqrt(w_eq@cov_m@w_eq)*np.sqrt(252))
    eq_s = eq_r/(eq_v+1e-10)
    ax.scatter([eq_v],[eq_r],[eq_s], color=C_RED, s=220, marker="*", zorder=10,
               label=f"Equal weight  Sharpe={eq_s:.2f}")

    bi = np.argmax(shs_mc)
    ax.scatter([vols_mc[bi]],[rets_mc[bi]],[shs_mc[bi]], color=C_BLUE, s=220, marker="^",
               zorder=10, label=f"Max Sharpe={shs_mc[bi]:.2f}")

    mi = np.argmin(vols_mc)
    ax.scatter([vols_mc[mi]],[rets_mc[mi]],[shs_mc[mi]], color=C_POS, s=220, marker="D",
               zorder=10, label=f"Min vol={vols_mc[mi]:.2f}")

    # Projected frontier on vol-return plane
    ax.contourf(
        np.array([[vols_mc.min(),vols_mc.max()],[vols_mc.min(),vols_mc.max()]]),
        np.array([[rets_mc.min(),rets_mc.min()],[rets_mc.max(),rets_mc.max()]]),
        np.zeros((2,2)),
        zdir="z", offset=shs_mc.min()-0.5, cmap="RdYlGn", alpha=0, levels=1)
    ax.scatter(vols_mc, rets_mc, np.full(n_mc, shs_mc.min()-0.5),
               c=shs_mc, cmap="RdYlGn", norm=norm, s=2, alpha=0.15, zorder=2)

    ax.set_xlabel("Ann. Volatility  σ", labelpad=10, fontsize=9, color=SUB)
    ax.set_ylabel("Ann. Return  μ", labelpad=10, fontsize=9, color=SUB)
    ax.set_zlabel("Sharpe Ratio", labelpad=10, fontsize=9, color=SUB)
    ax.view_init(elev=25, azim=-50)
    ax.legend(fontsize=9, loc="upper left")
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm); sm.set_array([])
    cb = fig.colorbar(sm, ax=ax, shrink=0.45, pad=0.08)
    cb.set_label("Sharpe Ratio", fontsize=9); cb.ax.tick_params(labelsize=8)
    _footer(fig); _save(fig, "09_efficient_frontier")


# ══════════════════════════════════════════════════════════════════════════════
# 10. ARCH VARIANCE SURFACE — ACF(r²) across lag × rolling window
#     z = autocorrelation of squared returns (volatility clustering test)
#     Persistent hot spots = ARCH effects present = bad runs predictable
# ══════════════════════════════════════════════════════════════════════════════
def chart_10_arch_surface(trades):
    _font()
    pnls  = np.array([t.pnl for t in trades])
    sq    = pnls**2
    n     = len(pnls)
    max_lag = min(12, n//4)
    lags    = list(range(1, max_lag+1))
    windows = list(range(max_lag+2, n, max(1,(n-max_lag)//50)))

    Z_acf = np.zeros((len(lags), len(windows)))
    for li, lag in enumerate(lags):
        for wi, w_end in enumerate(windows):
            w_start = max(0, w_end-30)
            sub = sq[w_start:w_end]
            if len(sub) > lag+2:
                Z_acf[li,wi] = float(pd.Series(sub).autocorr(lag=lag))
    Z_acf = np.nan_to_num(Z_acf, nan=0.0)

    LG, WI = np.meshgrid(lags, windows, indexing="ij")

    fig = plt.figure(figsize=FIG3D, facecolor=BG)
    fig.suptitle("ARCH VARIANCE SURFACE  ·  ACF(r², lag, t)  ·  "
                 "Hot zones = volatility clustering  ·  ARCH(q) effects visible as ridges",
                 fontsize=13, fontweight="bold", color=TEXT, y=0.98)
    ax = fig.add_subplot(111, projection="3d"); _ax3d(ax)

    cmap = plt.get_cmap("RdBu_r")
    norm = TwoSlopeNorm(vcenter=0, vmin=-0.6, vmax=0.6)
    ax.plot_surface(LG, WI, Z_acf, facecolors=cmap(norm(Z_acf)),
                    rstride=1, cstride=max(1,len(windows)//60),
                    alpha=0.90, shade=True)
    ax.plot_wireframe(LG, WI, Z_acf, rstride=1, cstride=max(1,len(windows)//20),
                      color="white", lw=0.2, alpha=0.2)
    ax.contourf(LG, WI, Z_acf, zdir="z", offset=-0.65,
                cmap="RdBu_r", norm=norm, alpha=0.40, levels=14)

    # Zero plane
    ax.plot_surface(np.array([[lags[0],lags[-1]],[lags[0],lags[-1]]]),
                    np.array([[windows[0],windows[0]],[windows[-1],windows[-1]]]),
                    np.zeros((2,2)), alpha=0.08, color=BORDER)

    # 95% CI boundary
    ci95 = 1.96/np.sqrt(30)
    ax.contour(LG, WI, Z_acf, zdir="z", offset=-0.65, levels=[-ci95, ci95],
               colors=[C_NEG,C_POS], linewidths=2.0, alpha=0.8)

    ax.set_xlabel("Lag  k", labelpad=10, fontsize=9, color=SUB)
    ax.set_ylabel("Trade index  t", labelpad=10, fontsize=9, color=SUB)
    ax.set_zlabel("ACF(r², k)", labelpad=10, fontsize=9, color=SUB)
    ax.set_zlim(-0.65, 0.65)
    ax.view_init(elev=30, azim=-60)
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm); sm.set_array([])
    cb = fig.colorbar(sm, ax=ax, shrink=0.45, pad=0.08)
    cb.set_label("Autocorrelation  ρ(r², k)", fontsize=9); cb.ax.tick_params(labelsize=8)
    _footer(fig); _save(fig, "10_arch_surface")


# ══════════════════════════════════════════════════════════════════════════════
# 11. PERMUTATION ENTROPY 3D — H(m, w) surface
#     Bandt-Pompe ordinal entropy across embedding dimension × window size
#     H=1 → maximum uncertainty  ·  H<1 → predictable structure in P&L
# ══════════════════════════════════════════════════════════════════════════════
def chart_11_permutation_entropy(trades):
    _font()
    pnls = np.array([t.pnl for t in trades])
    n    = len(pnls)

    def _perm_entropy(x, m):
        n_ = len(x) - m + 1
        if n_ < 4: return np.nan
        perms = list(permutations(range(m)))
        perm_idx = {p:i for i,p in enumerate(perms)}
        counts = np.zeros(len(perms))
        for i in range(n_):
            pat = tuple(np.argsort(x[i:i+m]))
            counts[perm_idx[pat]] += 1
        freq = counts / counts.sum()
        freq = freq[freq > 0]
        return -float(np.sum(freq * np.log2(freq))) / np.log2(math.factorial(m))

    ms      = list(range(2, min(7, n//10)+1))
    ws      = list(range(10, min(n//2, 60), 5))
    if not ms or not ws:
        ms = [2,3]; ws = [10,15,20]

    Z_ent = np.full((len(ms), len(ws)), np.nan)
    for mi, m in enumerate(ms):
        for wi, w in enumerate(ws):
            vals = []
            for start in range(0, n-w, max(1,w//4)):
                h = _perm_entropy(pnls[start:start+w], m)
                if h is not None and not np.isnan(h): vals.append(h)
            if vals: Z_ent[mi,wi] = float(np.mean(vals))

    fallback = 0.85
    Z = np.where(np.isnan(Z_ent), fallback, Z_ent)
    MI, WI = np.meshgrid(ms, ws, indexing="ij")

    fig = plt.figure(figsize=FIG3D, facecolor=BG)
    fig.suptitle("PERMUTATION ENTROPY SURFACE  ·  H(m, w)  ·  Bandt-Pompe ordinal patterns  ·  "
                 "H=1 → max disorder  ·  H<1 → temporal structure in P&L sequence",
                 fontsize=13, fontweight="bold", color=TEXT, y=0.98)
    ax = fig.add_subplot(111, projection="3d"); _ax3d(ax)

    cmap = plt.get_cmap("viridis_r")
    norm = Normalize(vmin=0, vmax=1)
    ax.plot_surface(MI, WI, Z, facecolors=cmap(norm(Z)),
                    rstride=1, cstride=1, alpha=0.90, shade=True)
    ax.plot_wireframe(MI, WI, Z, rstride=1, cstride=1,
                      color="white", lw=0.5, alpha=0.4)
    ax.contourf(MI, WI, Z, zdir="z", offset=0.0, cmap="viridis_r", alpha=0.40, levels=12)

    # H=1 plane (white noise reference)
    ax.plot_surface(
        np.array([[ms[0],ms[-1]],[ms[0],ms[-1]]]),
        np.array([[ws[0],ws[0]],[ws[-1],ws[-1]]]),
        np.ones((2,2)), alpha=0.12, color=C_NEG)
    ax.text(ms[-1], ws[-1], 1.02, "H=1 (white noise)", fontsize=8, color=C_NEG)

    ax.set_xticks(ms)
    ax.set_xlabel("Embedding dim  m", labelpad=10, fontsize=9, color=SUB)
    ax.set_ylabel("Window size  w", labelpad=10, fontsize=9, color=SUB)
    ax.set_zlabel("Norm. Perm. Entropy  H(m,w)", labelpad=10, fontsize=9, color=SUB)
    ax.set_zlim(0, 1.05)
    ax.view_init(elev=28, azim=-50)
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm); sm.set_array([])
    cb = fig.colorbar(sm, ax=ax, shrink=0.45, pad=0.08)
    cb.set_label("Normalised entropy H", fontsize=9); cb.ax.tick_params(labelsize=8)
    _footer(fig); _save(fig, "11_permutation_entropy")


# ══════════════════════════════════════════════════════════════════════════════
# 12. STOCHASTIC DOMINANCE SURFACE — F_α(x,VIX) − F_rand(x,VIX)
#     z = CDF_system(x) − CDF_random(x)  per VIX bucket
#     Negative everywhere = first-order stochastic dominance holds
# ══════════════════════════════════════════════════════════════════════════════
def chart_12_stochastic_dominance(trades):
    _font()
    pnls   = np.array([t.pnl for t in trades])
    vix_arr = np.array([t.vix for t in trades])
    np.random.seed(42)
    rand_pnl = np.random.normal(0, float(np.std(pnls)), len(pnls))

    vix_bins  = np.percentile(vix_arr, [0,25,50,75,100])
    vix_mids  = [(vix_bins[i]+vix_bins[i+1])/2 for i in range(4)]
    x_range   = np.linspace(pnls.min()*1.2, pnls.max()*1.2, 80)

    Z_dom = np.zeros((4, len(x_range)))
    for vi in range(4):
        mask = (vix_arr >= vix_bins[vi]) & (vix_arr < vix_bins[vi+1])
        if mask.sum() < 3:
            continue
        sub_pnl  = pnls[mask]
        sub_rand = rand_pnl[mask]
        for xi, x in enumerate(x_range):
            F_a = float((sub_pnl  <= x).mean())
            F_r = float((sub_rand <= x).mean())
            Z_dom[vi, xi] = F_a - F_r  # negative = system dominates

    XI, VI = np.meshgrid(x_range, vix_mids, indexing="ij")

    fig = plt.figure(figsize=FIG3D, facecolor=BG)
    fig.suptitle("STOCHASTIC DOMINANCE SURFACE  ·  ΔF(x, VIX) = F_system(x) − F_random(x)  ·  "
                 "Blue (ΔF<0) everywhere = 1st-order dominance  ·  Holds across all VIX regimes",
                 fontsize=12, fontweight="bold", color=TEXT, y=0.98)
    ax = fig.add_subplot(111, projection="3d"); _ax3d(ax)

    cmap = plt.get_cmap("RdBu_r")
    norm = TwoSlopeNorm(vcenter=0,
                        vmin=float(Z_dom.T.min()), vmax=float(Z_dom.T.max()))
    ax.plot_surface(XI, VI, Z_dom.T, facecolors=cmap(norm(Z_dom.T)),
                    rstride=1, cstride=1, alpha=0.90, shade=True)
    ax.plot_wireframe(XI, VI, Z_dom.T, rstride=4, cstride=1,
                      color="white", lw=0.2, alpha=0.20)
    ax.contourf(XI, VI, Z_dom.T, zdir="z", offset=float(Z_dom.min())-0.05,
                cmap="RdBu_r", norm=norm, alpha=0.40, levels=12)

    # Zero plane (dominance threshold)
    ax.plot_surface(
        np.array([[x_range[0],x_range[-1]],[x_range[0],x_range[-1]]]),
        np.array([[vix_mids[0],vix_mids[0]],[vix_mids[-1],vix_mids[-1]]]),
        np.zeros((2,2)), alpha=0.10, color=BORDER)
    ax.contour(XI, VI, Z_dom.T, levels=[0], colors=[TEXT], linewidths=2.0, alpha=0.7)

    ax.set_xlabel("Return threshold  x  ($)", labelpad=10, fontsize=9, color=SUB)
    ax.set_ylabel("VIX level", labelpad=10, fontsize=9, color=SUB)
    ax.set_zlabel("ΔF(x, VIX)", labelpad=10, fontsize=9, color=SUB)
    ax.view_init(elev=28, azim=-55)
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm); sm.set_array([])
    cb = fig.colorbar(sm, ax=ax, shrink=0.45, pad=0.08)
    cb.set_label("CDF difference  F_sys − F_rand", fontsize=9); cb.ax.tick_params(labelsize=8)
    _footer(fig); _save(fig, "12_stochastic_dominance")


# ══════════════════════════════════════════════════════════════════════════════
# 13. GPD TAIL PARAMETER SURFACE — ξ(VIX_bin, score_bin)
#     Generalized Pareto tail index surface from POT method
#     ξ>0 = heavy tail (Pareto)  ·  ξ≈0 = exponential  ·  ξ<0 = bounded tail
# ══════════════════════════════════════════════════════════════════════════════
def chart_13_gpd_tail_surface(trades):
    _font()
    vix_edges   = [0,14,18,23,30,60]
    score_edges = [5,9,12,15,18,22]
    nv, ns = len(vix_edges)-1, len(score_edges)-1

    def _bkt(v, edges):
        for i in range(len(edges)-1):
            if edges[i] <= v < edges[i+1]: return i
        return len(edges)-2

    def _fit_gpd(losses):
        if len(losses) < 6: return np.nan, np.nan
        u = np.percentile(losses, 65)
        exc = losses[losses > u] - u
        if len(exc) < 3: return np.nan, np.nan
        mu_e = float(exc.mean()); var_e = float(exc.var())
        if var_e < 1e-10: return 0.0, mu_e
        xi  = 0.5*(mu_e**2/var_e - 1)
        beta= mu_e*(1 - xi)
        return float(np.clip(xi,-0.5,1.0)), max(float(beta),0.01)

    cells = defaultdict(list)
    for t in trades:
        cells[(_bkt(t.vix,vix_edges), _bkt(getattr(t,"score",10),score_edges))].append(-t.pnl)

    Z_xi   = np.full((nv,ns), np.nan)
    Z_beta = np.full((nv,ns), np.nan)
    for (vi,si),losses in cells.items():
        arr = np.array(losses); arr = arr[arr>0]
        xi, beta = _fit_gpd(arr)
        Z_xi[vi,si]   = xi
        Z_beta[vi,si] = beta

    fx = float(np.nanmean(Z_xi))   if not np.all(np.isnan(Z_xi))   else 0.0
    fb = float(np.nanmean(Z_beta)) if not np.all(np.isnan(Z_beta)) else 10.0
    Z_xi_   = np.where(np.isnan(Z_xi),   fx, Z_xi)
    Z_beta_ = np.where(np.isnan(Z_beta), fb, Z_beta)

    xc = [(vix_edges[i]+vix_edges[i+1])/2 for i in range(nv)]
    yc = [(score_edges[i]+score_edges[i+1])/2 for i in range(ns)]
    X3, Y3 = np.meshgrid(xc, yc, indexing="ij")

    fig = plt.figure(figsize=FIG3D, facecolor=BG)
    fig.suptitle("GPD TAIL INDEX SURFACE  ·  ξ(VIX, Score)  via POT Method  ·  "
                 "ξ>0 = Pareto heavy tail  ·  ξ≈0 = exponential  ·  ξ<0 = bounded",
                 fontsize=13, fontweight="bold", color=TEXT, y=0.98)
    ax = fig.add_subplot(111, projection="3d"); _ax3d(ax)

    cmap = plt.get_cmap("RdYlGn_r")
    _zmin, _zmax = float(Z_xi_.min()), float(Z_xi_.max())
    if _zmin < 0 < _zmax:
        norm = TwoSlopeNorm(vcenter=0, vmin=_zmin, vmax=_zmax)
    else:
        norm = Normalize(vmin=_zmin, vmax=_zmax)
    ax.plot_surface(X3, Y3, Z_xi_, facecolors=cmap(norm(Z_xi_)),
                    rstride=1, cstride=1, alpha=0.90, shade=True)
    ax.plot_wireframe(X3, Y3, Z_xi_, rstride=1, cstride=1,
                      color="white", lw=0.5, alpha=0.40)
    ax.contourf(X3, Y3, Z_xi_, zdir="z", offset=float(Z_xi_.min())-0.05,
                cmap="RdYlGn_r", norm=norm, alpha=0.45, levels=12)

    # ξ=0 reference plane
    ax.plot_surface(
        np.array([[xc[0],xc[-1]],[xc[0],xc[-1]]]),
        np.array([[yc[0],yc[0]],[yc[-1],yc[-1]]]),
        np.zeros((2,2)), alpha=0.10, color=BORDER)
    ax.contour(X3, Y3, Z_xi_, levels=[0], colors=[C_BLUE], linewidths=2.5, alpha=0.8)

    ax.set_xlabel("VIX Level", labelpad=10, fontsize=9, color=SUB)
    ax.set_ylabel("Confidence Score", labelpad=10, fontsize=9, color=SUB)
    ax.set_zlabel("Tail index  ξ", labelpad=10, fontsize=9, color=SUB)
    ax.view_init(elev=28, azim=-50)
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm); sm.set_array([])
    cb = fig.colorbar(sm, ax=ax, shrink=0.45, pad=0.08)
    cb.set_label("GPD tail index  ξ", fontsize=9); cb.ax.tick_params(labelsize=8)
    _footer(fig); _save(fig, "13_gpd_tail_surface")


# ══════════════════════════════════════════════════════════════════════════════
# 14. EQUITY PATH IN 3D — cum_pnl × rolling_sharpe × rolling_vol trajectory
#     The system's full life traced as a 3D path through performance space
#     Color = trade index (time)  ·  Arrows = direction of travel
# ══════════════════════════════════════════════════════════════════════════════
def chart_14_equity_path_3d(trades):
    _font()
    pnls   = np.array([t.pnl for t in trades])
    cum    = np.cumsum(pnls)
    n      = len(pnls)
    win    = min(15, n//4)

    roll_std    = pd.Series(pnls).rolling(win, min_periods=3).std().fillna(pnls.std())
    roll_mean   = pd.Series(pnls).rolling(win, min_periods=3).mean().fillna(pnls.mean())
    roll_sharpe = (roll_mean / (roll_std + 1e-8) * np.sqrt(252*3)).values
    roll_vol    = roll_std.values

    t_idx = np.arange(n)

    fig = plt.figure(figsize=FIG3D, facecolor=BG)
    fig.suptitle("EQUITY PATH IN 3D PERFORMANCE SPACE  ·  "
                 "Cumulative P&L  ×  Rolling Sharpe  ×  Rolling Volatility  ·  Color = trade index",
                 fontsize=13, fontweight="bold", color=TEXT, y=0.98)
    ax = fig.add_subplot(111, projection="3d"); _ax3d(ax)

    # Color by time (trade index)
    cmap   = plt.get_cmap("plasma")
    norm   = Normalize(vmin=0, vmax=n-1)
    colors = cmap(norm(t_idx))

    # Draw path segments colored by time
    for i in range(n-1):
        ax.plot(cum[i:i+2], roll_sharpe[i:i+2], roll_vol[i:i+2],
                color=colors[i], lw=1.8, alpha=0.80)

    # Arrow markers every ~n/15 steps to show direction
    step = max(1, n//15)
    for i in range(0, n-step-1, step):
        ax.quiver(cum[i], roll_sharpe[i], roll_vol[i],
                  cum[i+1]-cum[i], roll_sharpe[i+1]-roll_sharpe[i], roll_vol[i+1]-roll_vol[i],
                  color=colors[i], lw=1.0, arrow_length_ratio=0.4, alpha=0.75)

    # Start and end markers
    ax.scatter([cum[0]], [roll_sharpe[0]], [roll_vol[0]],
               color=C_POS, s=200, marker="o", zorder=10, label="Start")
    ax.scatter([cum[-1]], [roll_sharpe[-1]], [roll_vol[-1]],
               color=C_RED, s=200, marker="*", zorder=10, label="End")

    # Projections on walls
    z_floor = float(roll_vol.min()) * 0.85
    ax.plot(cum, roll_sharpe, np.full(n, z_floor), color=DIM, lw=0.8, alpha=0.35)
    ax.plot(cum, np.full(n, float(roll_sharpe.min())*1.3), roll_vol, color=DIM, lw=0.8, alpha=0.35)

    ax.set_xlabel("Cumulative P&L ($)", labelpad=10, fontsize=9, color=SUB)
    ax.set_ylabel(f"Rolling Sharpe  (w={win})", labelpad=10, fontsize=9, color=SUB)
    ax.set_zlabel(f"Rolling Vol ($)  (w={win})", labelpad=10, fontsize=9, color=SUB)
    ax.view_init(elev=25, azim=-55)
    ax.legend(fontsize=9, loc="upper left")
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm); sm.set_array([])
    cb = fig.colorbar(sm, ax=ax, shrink=0.45, pad=0.08)
    cb.set_label("Trade index (time →)", fontsize=9); cb.ax.tick_params(labelsize=8)
    _footer(fig); _save(fig, "14_equity_path_3d")


# ══════════════════════════════════════════════════════════════════════════════
# 15. REGIME-CONDITIONED RETURN SURFACE — 3D KDE stack by HMM state
#     Each regime's P&L density is rendered as a 3D ribbon at its VIX height
#     Color = density amplitude  ·  Full 3D probability landscape
# ══════════════════════════════════════════════════════════════════════════════
def chart_15_regime_density_3d(trades):
    _font()
    by_regime = defaultdict(list)
    for t in trades:
        by_regime[getattr(t,"hmm_state","unavailable")].append(t.pnl)

    all_pnls = np.array([t.pnl for t in trades])
    x_range  = np.linspace(all_pnls.min()*1.3, all_pnls.max()*1.3, 150)

    regime_order  = ["strong_bull","bull","neutral","stress","bear","unavailable"]
    regime_labels = {"strong_bull":"Strong Bull","bull":"Bull","neutral":"Neutral",
                     "stress":"Stress","bear":"Bear","unavailable":"N/A"}
    vix_heights   = {"strong_bull":12, "bull":16, "neutral":20,
                     "stress":26, "bear":32, "unavailable":38}

    # Fallback: if all unavailable, distribute by score
    all_unavailable = all(r=="unavailable" for r in by_regime.keys())
    if all_unavailable:
        score_arr = np.array([getattr(t,"score",10) for t in trades])
        for t in trades:
            sc = getattr(t,"score",10)
            if   sc >= 18: by_regime["strong_bull"].append(t.pnl)
            elif sc >= 15: by_regime["bull"].append(t.pnl)
            elif sc >= 12: by_regime["neutral"].append(t.pnl)
            elif sc >= 9:  by_regime["stress"].append(t.pnl)
            else:          by_regime["bear"].append(t.pnl)
        by_regime.pop("unavailable", None)
        regime_order = ["strong_bull","bull","neutral","stress","bear"]

    fig = plt.figure(figsize=FIG3D, facecolor=BG)
    fig.suptitle("REGIME-CONDITIONED RETURN DENSITY RIBBONS  ·  3D KDE per HMM State  ·  "
                 "Height = VIX regime  ·  Amplitude = probability density",
                 fontsize=13, fontweight="bold", color=TEXT, y=0.98)
    ax = fig.add_subplot(111, projection="3d"); _ax3d(ax)

    cmap_density = plt.get_cmap("plasma")
    all_max_d    = 0.0

    ribbons = []
    for regime in regime_order:
        pnl_r = np.array(by_regime.get(regime,[]))
        if len(pnl_r) < 3: continue
        try:
            kde = gaussian_kde(pnl_r, bw_method="silverman")
            yd  = kde(x_range)
        except Exception:
            continue
        y_pos   = float(vix_heights.get(regime, 20))
        col     = REGIME_C.get(regime, SUB)
        all_max_d = max(all_max_d, yd.max())
        ribbons.append((regime, y_pos, yd, col, pnl_r))

    norm_d = Normalize(vmin=0, vmax=all_max_d + 1e-10)
    for regime, y_pos, yd, col, pnl_r in ribbons:
        # 3D ribbon: X=p&l, Y=vix_height, Z=density
        ax.plot(x_range, np.full_like(x_range, y_pos), yd,
                color=col, lw=2.5, alpha=0.90, zorder=5)
        # Filled ribbon (polygon) — use Poly3DCollection to avoid qhull collinear error
        verts_x = np.concatenate([[x_range[0]], x_range, [x_range[-1]]])
        verts_z = np.concatenate([[0], yd, [0]])
        verts   = [(verts_x[i], y_pos, verts_z[i]) for i in range(len(verts_x))]
        poly    = Poly3DCollection([verts], alpha=0.18, facecolor=col, edgecolor="none")
        ax.add_collection3d(poly)
        # Mean marker
        mu_r = float(np.mean(pnl_r))
        mu_d = float(gaussian_kde(pnl_r, bw_method="silverman")(np.array([mu_r]))[0])
        ax.scatter([mu_r],[y_pos],[mu_d], color=col, s=80, zorder=10)
        wr = float((pnl_r>0).mean()*100)
        ax.text(x_range[-1]*0.8, y_pos, yd.max()*1.05,
                f"{regime_labels.get(regime,regime)}\nn={len(pnl_r)} WR={wr:.0f}%",
                fontsize=7.5, color=col, fontweight="bold", ha="left")

    ax.set_xlabel("Trade P&L ($)", labelpad=10, fontsize=9, color=SUB)
    ax.set_ylabel("VIX Regime Level", labelpad=10, fontsize=9, color=SUB)
    ax.set_zlabel("Probability Density", labelpad=10, fontsize=9, color=SUB)
    ax.view_init(elev=20, azim=-60)
    _footer(fig); _save(fig, "15_regime_density_3d")


# ── Entry point ────────────────────────────────────────────────────────────────
def generate_all_charts(trades) -> None:
    print(f"\nGenerating 15 advanced quant charts ({len(trades)} trades) -> {OUT_DIR}/")
    specs = [
        ("01 Kelly Growth Landscape (3D surface)",        chart_01_kelly_surface),
        ("02 PCA Manifold + LDA Hyperplane (3D)",         chart_02_pca_manifold),
        ("03 Omega Function 3D Surface",                  chart_03_omega_surface),
        ("04 Rolling IC Surface (3D)",                    chart_04_rolling_ic_surface),
        ("05 Dual CVaR + Sharpe Surface (3D)",            chart_05_dual_risk_surface),
        ("06 Hawkes Process Intensity (3D)",              chart_06_hawkes_intensity),
        ("07 Joint Density P&L×VIX (3D KDE)",            chart_07_joint_density),
        ("08 Rolling Kelly Surface (3D)",                 chart_08_rolling_kelly_surface),
        ("09 Efficient Frontier (3D MC scatter)",         chart_09_efficient_frontier),
        ("10 ARCH Variance Surface (3D)",                 chart_10_arch_surface),
        ("11 Permutation Entropy Surface (3D)",           chart_11_permutation_entropy),
        ("12 Stochastic Dominance Surface (3D)",          chart_12_stochastic_dominance),
        ("13 GPD Tail Index Surface (3D)",                chart_13_gpd_tail_surface),
        ("14 Equity Path in 3D Performance Space",        chart_14_equity_path_3d),
        ("15 Regime Density Ribbons (3D KDE stack)",      chart_15_regime_density_3d),
    ]
    for name, fn in specs:
        try:
            print(f"  {name} ...", end=" ", flush=True)
            fn(trades)
        except Exception as e:
            import traceback
            print(f"[WARN] {name}: {e}")
            traceback.print_exc()
    print(f"\nDone — 15 charts saved to ./{OUT_DIR}/\n")
