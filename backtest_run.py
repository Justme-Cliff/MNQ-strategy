"""
Run the backtest. Execute: python backtest_run.py

Modes:
  default  — 60 days at 5m (high fidelity, current evaluation window)
  --long   — 24 months at 1h (approximate, multi-regime validation)
  --both   — run both and compare
"""
import sys
from backtest.engine import run_backtest
from backtest.results_analyzer import analyze

if __name__ == "__main__":
    args = sys.argv[1:]
    run_long  = "--long" in args or "--both" in args
    run_short = "--long" not in args or "--both" in args

    if run_short:
        print("\n" + "=" * 60)
        print("  60-DAY BACKTEST  |  5-minute bars  |  High fidelity")
        print("=" * 60)
        result_5m = run_backtest(interval="5m", period="60d")
        stats_5m  = analyze(result_5m)

        if stats_5m:
            print(f"\nDone (5m). {stats_5m['total_trades']} trades found.")
            if not stats_5m["would_pass_challenge"]:
                print("Not yet at $1,500 target — review breakdown above.")
            else:
                print("Passes historical test. Review before going live.")

    if run_long:
        print("\n" + "=" * 60)
        print("  24-MONTH BACKTEST  |  1-hour bars  |  Approximate")
        print("  (1h resolution: less precise but multi-regime validated)")
        print("=" * 60)
        result_1h = run_backtest(interval="1h", period="730d")
        stats_1h  = analyze(result_1h)

        if stats_1h:
            print(f"\nDone (1h). {stats_1h['total_trades']} trades found across ~24 months.")
            wr = stats_1h["win_rate_pct"]
            if wr >= 65:
                print(f"Strong multi-regime win rate: {wr}% — strategy is robust.")
            elif wr >= 50:
                print(f"Acceptable multi-regime win rate: {wr}% — review breakdown for weak spots.")
            else:
                print(f"Below 50% over 24 months ({wr}%) — needs filter tuning.")
