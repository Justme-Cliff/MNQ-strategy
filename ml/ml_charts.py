"""
ML model interpretability — 3D visualizations that answer "what did the
model actually learn?" in a way you can SEE rather than read off a metrics
table. Three charts, each a different angle on the same question:

  01  DECISION SURFACE     — the literal P(win) landscape the model carved
                             out of its two most important signals, with real
                             trades scattered on it (green=won, red=lost) so
                             you can see whether reality matches the shape.
  02  FEATURE IMPORTANCE   — which signals the model leans on most, per
                             strategy (taller bar = the model "looks at" that
                             feature more when deciding).
  03  VALIDATION GATE      — why some models are trusted live and others
                             aren't: AUC × WFE landscape with the two pass/
                             fail walls from `ml.inference.ml_gate_enabled`.

Run with:
    python3 -m ml.ml_charts
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import lightgbm as lgb
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401  (registers 3d projection)
import warnings
warnings.filterwarnings("ignore")

from ml.features import ALL_FEATURES, CATEGORICAL_FEATURES

MODEL_DIR = Path("ml/saved_models")
DATA_PATH = Path("ml/data/candidates_10yr.parquet")
OUT_DIR   = "ml_charts"

FIG3D = (16.05, 10.04)
BG, PANEL, GRID, BORDER = "#FFFFFF", "#F8F9FA", "#E9ECEF", "#CED4DA"
TEXT, SUB, DIM = "#212529", "#6C757D", "#ADB5BD"
C_WIN, C_LOSS, C_BLUE, C_PUR = "#2E7D32", "#C62828", "#1565C0", "#6A1B9A"
STRAT_PAL = ["#1565C0", "#C62828", "#2E7D32", "#E65100", "#6A1B9A", "#00695C"]
PWIN_CMAP = LinearSegmentedColormap.from_list("pwin", ["#C62828", "#FBC02D", "#2E7D32"])


def _font():
    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 10,
        "axes.titlesize": 13, "axes.labelsize": 10,
        "xtick.labelsize": 9, "ytick.labelsize": 9,
        "legend.fontsize": 9, "figure.dpi": 150,
        "axes.spines.top": False, "axes.spines.right": False,
    })


def _ax3d(ax):
    ax.set_facecolor(BG); ax.patch.set_facecolor(BG)
    ax.tick_params(colors=SUB, labelsize=7); ax.grid(False)
    ax.xaxis.pane.fill = ax.yaxis.pane.fill = ax.zaxis.pane.fill = False
    for pane in [ax.xaxis.pane, ax.yaxis.pane, ax.zaxis.pane]:
        pane.set_edgecolor(BORDER); pane.set_alpha(0.3)


def _save(fig, name):
    Path(OUT_DIR).mkdir(exist_ok=True)
    path = f"{OUT_DIR}/{name}.png"
    fig.savefig(path, dpi=150, facecolor=BG)
    plt.close(fig)
    print(f"  saved -> {path}")


def _footer(fig, note):
    fig.text(0.5, 0.004, note, ha="center", va="bottom", color=DIM,
             fontsize=7, style="italic")


def _title(fig, title, subtitle):
    fig.text(0.5, 0.985, title, ha="center", va="top", fontsize=14, fontweight="bold", color=TEXT)
    fig.text(0.5, 0.935, subtitle, ha="center", va="top", fontsize=8.3, color=SUB, linespacing=1.6)


def _load_model(strategy):
    booster = lgb.Booster(model_file=str(MODEL_DIR / f"meta_{strategy}.txt"))
    meta = json.loads((MODEL_DIR / f"meta_{strategy}.json").read_text())
    return booster, meta


def _predict(booster, sub):
    X = sub[ALL_FEATURES].copy()
    for c in CATEGORICAL_FEATURES:
        X[c] = X[c].astype("category")
    return booster.predict(X)


# ══════════════════════════════════════════════════════════════════════════════
# 01. DECISION SURFACE — the P(win) landscape the model learned, in 3D, with
#     real trades scattered on it so you can eyeball "does reality match?"
# ══════════════════════════════════════════════════════════════════════════════
def chart_01_decision_surface(strategy="vwap_bounce", feat_x="lambda_val", feat_y="lambda_zscore"):
    _font()
    booster, meta = _load_model(strategy)
    df = pd.read_parquet(DATA_PATH)
    sub = df[df["strategy"] == strategy].reset_index(drop=True)

    # Build a smooth grid over the two most important continuous features;
    # every OTHER feature is frozen at its median/mode (the model's "typical day").
    xs = np.linspace(sub[feat_x].quantile(0.02), sub[feat_x].quantile(0.98), 60)
    ys = np.linspace(sub[feat_y].quantile(0.02), sub[feat_y].quantile(0.98), 60)
    XX, YY = np.meshgrid(xs, ys)

    base = {}
    for f in ALL_FEATURES:
        base[f] = sub[f].mode().iloc[0] if f in CATEGORICAL_FEATURES else sub[f].median()
    grid = pd.DataFrame({f: np.full(XX.size, base[f]) for f in ALL_FEATURES})
    grid[feat_x] = XX.ravel()
    grid[feat_y] = YY.ravel()
    for c in CATEGORICAL_FEATURES:
        grid[c] = grid[c].astype("category")
    ZZ = booster.predict(grid).reshape(XX.shape)

    # Real trades: plotted at the model's ACTUAL prediction for that exact
    # trade (using its true feature row, not the frozen grid) — so the dots
    # show what the model really said about real setups, colored by what
    # really happened.
    proba_real = _predict(booster, sub)
    won  = sub["label"] == 1
    lost = ~won

    fig = plt.figure(figsize=FIG3D, facecolor=BG)
    ax = fig.add_axes([0.04, 0.05, 0.92, 0.80], projection="3d")
    _ax3d(ax)
    ax.set_box_aspect((1.3, 1.0, 0.65), zoom=1.35)
    ax.plot_surface(XX, YY, ZZ, cmap=PWIN_CMAP, alpha=0.6, rstride=1, cstride=1,
                    linewidth=0, antialiased=True, vmin=0, vmax=1)
    ax.contourf(XX, YY, ZZ, zdir="z", offset=-0.05, cmap=PWIN_CMAP, alpha=0.35, levels=20)

    ax.scatter(sub.loc[won, feat_x], sub.loc[won, feat_y], proba_real[won],
               c=C_WIN, s=24, alpha=0.85, edgecolor="white", linewidth=0.4,
               depthshade=False, label=f"WON  (n={int(won.sum())})")
    ax.scatter(sub.loc[lost, feat_x], sub.loc[lost, feat_y], proba_real[lost],
               c=C_LOSS, s=24, alpha=0.85, edgecolor="white", linewidth=0.4,
               depthshade=False, label=f"LOST (n={int(lost.sum())})")

    thr = 0.55
    ax.plot_surface(XX, YY, np.full_like(ZZ, thr), color="#37474F", alpha=0.10,
                    linewidth=0, shade=False)

    ax.set_xlabel(feat_x, labelpad=10); ax.set_ylabel(feat_y, labelpad=10)
    ax.set_zlabel("P(win)  —  model's confidence", labelpad=10)
    ax.set_zlim(-0.05, 1.0)
    ax.view_init(elev=22, azim=-52)
    ax.legend(loc="upper left", bbox_to_anchor=(0.0, 0.98), framealpha=0.9,
              facecolor=PANEL, edgecolor=BORDER)

    _title(fig,
           f"ML DECISION SURFACE  ·  {strategy}  ·  P(win) = f({feat_x}, {feat_y})",
           f"This is the literal shape LightGBM learned from {len(sub)} historical setups (OOS AUC={meta.get('avg_oos_auc', float('nan')):.2f})\n"
           f"green ridge = model says TAKE  ·  red valley = model says SKIP  ·  grey plane = the {thr:.2f} live gate threshold\n"
           f"dots = real trades plotted at the model's actual prediction for them, colored by what really happened — green dots sitting high on the ridge means the model's confidence matched reality")
    _footer(fig, "ISOGENY ALPHA SYSTEM  |  ML META-LABELING — DECISION SURFACE  |  For Internal Use Only")
    _save(fig, "ml_01_decision_surface")


# ══════════════════════════════════════════════════════════════════════════════
# 02. FEATURE IMPORTANCE LANDSCAPE — what the model "looks at" most, per
#     strategy, as a 3D bar landscape (taller = more influence on the decision)
# ══════════════════════════════════════════════════════════════════════════════
def chart_02_feature_importance(strategies=("orb", "vwap_bounce", "vwap_bounce_pm"), top_n=6):
    _font()
    fig = plt.figure(figsize=FIG3D, facecolor=BG)
    ax = fig.add_axes([0.04, 0.05, 0.92, 0.80], projection="3d")
    _ax3d(ax)
    ax.set_box_aspect((1.5, 1.0, 0.7), zoom=1.35)

    dx, dy = 0.7, 0.7
    for si, strat in enumerate(strategies):
        shap_path = MODEL_DIR / f"shap_{strat}.csv"
        rank = pd.read_csv(shap_path).head(top_n).reset_index(drop=True)
        for fi, row in rank.iterrows():
            feat, imp, corr = row["feature"], row["mean_abs_shap"], row["corr_with_shap"]
            color = C_WIN if (corr == corr and corr > 0) else (C_LOSS if corr == corr and corr < 0 else SUB)
            x0, y0 = fi * 1.0, si * 1.3
            ax.bar3d(x0, y0, 0, dx, dy, imp, color=color, alpha=0.88,
                     edgecolor="white", linewidth=0.7, shade=True)
            # stagger label height by rank so adjacent bars' labels don't collide
            ax.text(x0 + dx / 2, y0 + dy / 2, imp + 0.06 + (fi % 2) * 0.07, feat,
                    fontsize=7.2, color=TEXT, ha="center", va="bottom")

    ax.set_xlabel("rank (most -> least important)", labelpad=12)
    ax.set_yticks([si * 1.3 + dy / 2 for si in range(len(strategies))])
    ax.set_yticklabels(strategies)
    ax.set_zlabel("mean |SHAP|  —  influence on the model's decision", labelpad=10)
    ax.set_xticks([fi * 1.0 + dx / 2 for fi in range(top_n)])
    ax.set_xticklabels([f"#{i+1}" for i in range(top_n)])
    ax.view_init(elev=24, azim=-60)

    handles = [plt.Rectangle((0, 0), 1, 1, color=C_WIN, alpha=0.88),
               plt.Rectangle((0, 0), 1, 1, color=C_LOSS, alpha=0.88)]
    ax.legend(handles, ["high value -> pushes toward WIN", "high value -> pushes toward LOSS"],
              loc="upper left", bbox_to_anchor=(0.0, 0.98), framealpha=0.9,
              facecolor=PANEL, edgecolor=BORDER)

    _title(fig,
           "SHAP FEATURE IMPORTANCE LANDSCAPE  ·  What Each Model Pays Attention To",
           "Every bar is a signal the model weighs before deciding; height = how much it swings the prediction\n"
           "color = which way it pushes (green = toward a win, red = toward a loss)\n"
           "notice Kyle's-lambda order-flow features (lambda_aligned, lambda_val, bd_lambda) dominate all three — a real, causal microstructure signal, not noise")
    _footer(fig, "ISOGENY ALPHA SYSTEM  |  ML META-LABELING — SHAP INTERPRETABILITY  |  For Internal Use Only")
    _save(fig, "ml_02_feature_importance")


# ══════════════════════════════════════════════════════════════════════════════
# 03. VALIDATION GATE LANDSCAPE — why 4 models are trusted live and 1 isn't:
#     AUC x WFE plane with the two pass/fail walls from ml_gate_enabled()
# ══════════════════════════════════════════════════════════════════════════════
def chart_03_validation_gate():
    _font()
    metas = {}
    for p in sorted(MODEL_DIR.glob("meta_*.json")):
        if p.name == "training_summary.json":
            continue
        d = json.loads(p.read_text())
        strat = p.stem.replace("meta_", "")
        metas[strat] = d

    AUC_BAR, WFE_BAR = 0.55, 50.0
    fig = plt.figure(figsize=FIG3D, facecolor=BG)
    ax = fig.add_axes([0.04, 0.05, 0.92, 0.78], projection="3d")
    _ax3d(ax)
    ax.set_box_aspect((1.3, 1.0, 0.6), zoom=1.35)

    aucs = [d.get("avg_oos_auc", 0.0) for d in metas.values()]
    wfes = [d.get("wfe_avg") or 0.0 for d in metas.values()]
    x_max, y_max = max(max(aucs) * 1.12, AUC_BAR * 1.3), max(max(wfes) * 1.12, WFE_BAR * 1.6)
    z_top = 1.0

    # Floor: grey everywhere, green tint only in the pass quadrant (AUC>bar AND WFE>=bar)
    xx, yy = np.meshgrid(np.linspace(0.45, x_max, 2), np.linspace(0, y_max, 2))
    ax.plot_surface(xx, yy, np.zeros_like(xx), color="#ECEFF1", alpha=0.6, linewidth=0, shade=False)
    xx2, yy2 = np.meshgrid(np.linspace(AUC_BAR, x_max, 2), np.linspace(WFE_BAR, y_max, 2))
    ax.plot_surface(xx2, yy2, np.zeros_like(xx2), color=C_WIN, alpha=0.20, linewidth=0, shade=False)

    # The two "walls" the model must clear — AUC bar (plane at x=0.55) and WFE bar (at y=50)
    zw = np.linspace(0, z_top, 2)
    yw = np.linspace(0, y_max, 2)
    YW, ZW = np.meshgrid(yw, zw)
    ax.plot_surface(np.full_like(YW, AUC_BAR), YW, ZW, color=C_BLUE, alpha=0.12, linewidth=0, shade=False)
    xw = np.linspace(0.45, x_max, 2)
    XW, ZW2 = np.meshgrid(xw, zw)
    ax.plot_surface(XW, np.full_like(XW, WFE_BAR), ZW2, color=C_PUR, alpha=0.12, linewidth=0, shade=False)

    # Sort by AUC so labels can be staggered in z without guessing collisions
    items = sorted(metas.items(), key=lambda kv: kv[1].get("avg_oos_auc", 0.0))
    for i, (strat, d) in enumerate(items):
        auc = d.get("avg_oos_auc", 0.0)
        wfe = d.get("wfe_avg") or 0.0
        passed = auc > AUC_BAR and wfe >= WFE_BAR
        color = C_WIN if passed else C_LOSS
        stem_h = 0.26 + i * 0.16          # stagger stem heights so labels never overlap
        ax.plot([auc, auc], [wfe, wfe], [0, stem_h], color=color, lw=2.0, alpha=0.8)
        ax.scatter([auc], [wfe], [stem_h], c=color, s=150, edgecolor="white",
                   linewidth=1.3, depthshade=False, zorder=10)
        verdict = "LIVE-ELIGIBLE" if passed else "SHADOW ONLY"
        label = f"{strat} — AUC {auc:.2f} · WFE {wfe:.0f}%  ({verdict})"
        ax.text(auc, wfe, stem_h + 0.045, label, fontsize=8, color=color,
                ha="left", va="bottom", fontweight="bold")

    ax.set_xlabel("Purged-CV OOS AUC  (does it have a real edge?)", labelpad=12)
    ax.set_ylabel("Walk-Forward Efficiency %  (does that edge survive retrain-and-deploy?)", labelpad=12)
    ax.set_zlabel("")
    ax.set_zticks([])
    ax.set_xlim(0.45, x_max); ax.set_ylim(0, y_max); ax.set_zlim(0, z_top)
    ax.view_init(elev=15, azim=-35)

    handles = [plt.Line2D([0], [0], marker="o", color="w", markerfacecolor=C_WIN, markersize=11,
                          label="PASSED both bars -> live-gate-eligible"),
               plt.Line2D([0], [0], marker="o", color="w", markerfacecolor=C_LOSS, markersize=11,
                          label="FAILED -> shadow-mode only (curve-fit risk)"),
               plt.Rectangle((0, 0), 1, 1, color=C_BLUE, alpha=0.35, label=f"AUC wall = {AUC_BAR:.2f}"),
               plt.Rectangle((0, 0), 1, 1, color=C_PUR, alpha=0.35, label=f"WFE wall = {WFE_BAR:.0f}%"),
               plt.Rectangle((0, 0), 1, 1, color=C_WIN, alpha=0.20, label="pass quadrant (clears both walls)")]
    ax.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.0, 0.99), framealpha=0.9,
              facecolor=PANEL, edgecolor=BORDER, fontsize=8.5)

    _title(fig,
           "VALIDATION GATE LANDSCAPE  ·  Why Some Models Are Trusted Live and Others Aren't",
           "Two walls, BOTH must be cleared before a model earns live authority: AUC > 0.55 (a real predictive edge, not noise)\n"
           "AND Walk-Forward Efficiency >= 50% (that edge survives an actual retrain-and-deploy cycle, not just one lucky CV split)\n"
           "va_rule cleared the AUC wall (0.63) but crashed through the WFE wall (48%) — exactly the curve-fitting that AUC alone would have missed")
    _footer(fig, "ISOGENY ALPHA SYSTEM  |  ML META-LABELING — DEPLOYABILITY GATE  |  For Internal Use Only")
    _save(fig, "ml_03_validation_gate")


def generate_all():
    print(f"\n{'='*72}\n  Generating ML interpretability charts -> {OUT_DIR}/\n{'='*72}")
    chart_01_decision_surface()
    chart_02_feature_importance()
    chart_03_validation_gate()
    print(f"{'='*72}\n  Done — 3 charts saved to {OUT_DIR}/\n{'='*72}")


if __name__ == "__main__":
    generate_all()
