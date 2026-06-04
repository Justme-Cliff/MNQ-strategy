"""
Video generator — 15 rotating 3D chart animations + 1 combined video.

Requirements: ffmpeg  (brew install ffmpeg)

Run:  python3 generate_videos.py        # yfinance data (fast, ~5 min)
      python3 generate_videos.py /2y    # Databento 2-year data (~8 min)

Output:
  backtest_videos/01_kelly_surface.mp4
  backtest_videos/02_pca_manifold.mp4
  ...
  backtest_videos/15_regime_density_3d.mp4
  backtest_videos/ISOGENY_ALPHA_SHOWCASE.mp4   ← combined
"""
from __future__ import annotations
import os, sys, shutil, subprocess
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ── Config ────────────────────────────────────────────────────────────────────
VIDEO_DIR  = Path("backtest_videos")
FRAMES_DIR = VIDEO_DIR / "_frames"
N_FRAMES   = 120      # 120 frames @ 24 fps = 5 s per chart
FPS        = 24
VIDEO_DPI  = 100      # ~1605 × 1004 px per frame
BG         = "#FFFFFF"
ELEV       = 25       # fixed elevation during rotation

CHARTS = [
    ("01_kelly_surface",         "chart_01_kelly_surface",         "01 — Kelly Growth Landscape"),
    ("02_pca_manifold",          "chart_02_pca_manifold",          "02 — PCA Manifold + LDA Hyperplane"),
    ("03_omega_surface",         "chart_03_omega_surface",         "03 — Omega Function 3D Surface"),
    ("04_rolling_ic_surface",    "chart_04_rolling_ic_surface",    "04 — Rolling IC Surface"),
    ("05_dual_risk_surface",     "chart_05_dual_risk_surface",     "05 — Dual CVaR + Sharpe Surface"),
    ("06_hawkes_intensity",      "chart_06_hawkes_intensity",      "06 — Hawkes Process Intensity"),
    ("07_joint_density",         "chart_07_joint_density",         "07 — Joint Density P&L × VIX"),
    ("08_rolling_kelly_surface", "chart_08_rolling_kelly_surface", "08 — Rolling Kelly Surface"),
    ("09_efficient_frontier",    "chart_09_efficient_frontier",    "09 — 3D Efficient Frontier"),
    ("10_arch_surface",          "chart_10_arch_surface",          "10 — ARCH Variance Surface"),
    ("11_permutation_entropy",   "chart_11_permutation_entropy",   "11 — Permutation Entropy Surface"),
    ("12_stochastic_dominance",  "chart_12_stochastic_dominance",  "12 — Stochastic Dominance Surface"),
    ("13_gpd_tail_surface",      "chart_13_gpd_tail_surface",      "13 — GPD Tail Index Surface"),
    ("14_equity_path_3d",        "chart_14_equity_path_3d",        "14 — Equity Path 3D"),
    ("15_regime_density_3d",     "chart_15_regime_density_3d",     "15 — Regime Density Ribbons"),
]


# ── Load trades ───────────────────────────────────────────────────────────────
def load_trades():
    arg = next((a for a in sys.argv[1:] if a.startswith("/")), "")
    period = arg.lstrip("/") or "60d"
    use_db = period in ("2y", "3y", "5y", "10y")

    if use_db:
        print(f"  Loading {period} Databento data ...")
        from backtest.databento_loader import load_nq_databento
        years = int(period.replace("y", ""))
        df = load_nq_databento(years=years)
        from backtest.hybrid_engine import run_hybrid_backtest
        print("  Running hybrid backtest ...")
        trades = run_hybrid_backtest(df=df)
    else:
        print(f"  Loading {period} yfinance data ...")
        from backtest.hybrid_engine import run_hybrid_backtest
        trades = run_hybrid_backtest(interval="5m", period=period)

    print(f"  {len(trades)} trades loaded.\n")
    return trades


# ── Monkey-patch _save to capture figure without closing ──────────────────────
import backtest.quant_charts as qc

_captured: dict = {}

def _intercept_save(fig, name):
    _captured["fig"]  = fig
    _captured["name"] = name
    # Do NOT close — we need it for animation


# ── Render one rotating video ─────────────────────────────────────────────────
def render_video(slug: str, fn_name: str, title: str, trades: list) -> Path | None:
    print(f"  Rendering {title} ...")

    # Build figure via chart function
    _captured.clear()
    original_save = qc._save
    qc._save = _intercept_save
    try:
        getattr(qc, fn_name)(trades)
    except Exception as e:
        print(f"    [WARN] chart function failed: {e}")
        qc._save = original_save
        return None
    finally:
        qc._save = original_save

    fig = _captured.get("fig")
    if fig is None:
        print("    [WARN] no figure captured, skipping.")
        return None

    # Find all 3D axes
    axes_3d = [ax for ax in fig.get_axes() if hasattr(ax, "get_zlim")]
    if not axes_3d:
        print("    [WARN] no 3D axes found, skipping.")
        plt.close(fig)
        return None

    # Render frames
    frames_dir = FRAMES_DIR / slug
    frames_dir.mkdir(parents=True, exist_ok=True)

    start_azim = axes_3d[0].azim
    azimuths   = np.linspace(start_azim, start_azim + 360, N_FRAMES, endpoint=False)

    for i, azim in enumerate(azimuths):
        for ax in axes_3d:
            ax.view_init(elev=ELEV, azim=float(azim))
        frame_path = frames_dir / f"frame_{i:04d}.png"
        fig.savefig(frame_path, dpi=VIDEO_DPI, facecolor=BG)
        if i % 30 == 0:
            print(f"    frame {i+1}/{N_FRAMES}")

    plt.close(fig)

    # Stitch frames → MP4
    out_path = VIDEO_DIR / f"{slug}.mp4"
    cmd = [
        "ffmpeg", "-y",
        "-r", str(FPS),
        "-i", str(frames_dir / "frame_%04d.png"),
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
        str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"    [WARN] ffmpeg error: {result.stderr[-300:]}")
        shutil.rmtree(frames_dir, ignore_errors=True)
        return None

    shutil.rmtree(frames_dir, ignore_errors=True)
    size_mb = out_path.stat().st_size / 1_048_576
    print(f"    saved -> {out_path}  ({size_mb:.1f} MB)")
    return out_path


# ── Combine all videos ────────────────────────────────────────────────────────
def combine_videos(video_paths: list[Path]) -> None:
    valid = [p for p in video_paths if p and p.exists()]
    if not valid:
        print("  No videos to combine.")
        return

    concat_file = VIDEO_DIR / "concat.txt"
    with open(concat_file, "w") as f:
        for p in valid:
            f.write(f"file '{p.resolve()}'\n")

    out = VIDEO_DIR / "ISOGENY_ALPHA_SHOWCASE.mp4"
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(concat_file),
        "-c", "copy",
        str(out),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    concat_file.unlink(missing_ok=True)

    if result.returncode == 0:
        size_mb = out.stat().st_size / 1_048_576
        print(f"\n  Combined -> {out}  ({size_mb:.1f} MB)")
    else:
        print(f"  [WARN] combine failed: {result.stderr[-300:]}")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    if not shutil.which("ffmpeg"):
        print("ERROR: ffmpeg not found. Run: brew install ffmpeg")
        sys.exit(1)

    VIDEO_DIR.mkdir(exist_ok=True)
    FRAMES_DIR.mkdir(exist_ok=True)

    trades = load_trades()
    if not trades:
        print("ERROR: no trades loaded.")
        sys.exit(1)

    print(f"Generating {len(CHARTS)} videos ({N_FRAMES} frames each @ {FPS}fps = {N_FRAMES//FPS}s/chart)\n")

    video_paths = []
    for slug, fn_name, title in CHARTS:
        path = render_video(slug, fn_name, title, trades)
        video_paths.append(path)

    print("\nCombining into showcase video ...")
    combine_videos(video_paths)

    n_ok = sum(1 for p in video_paths if p and p.exists())
    print(f"\nDone — {n_ok}/15 individual videos + 1 combined in ./{VIDEO_DIR}/\n")


if __name__ == "__main__":
    main()
