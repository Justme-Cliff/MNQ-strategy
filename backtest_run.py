"""
Run the backtest. Execute: python backtest_run.py
Pulls last 60 days of NQ futures data (MNQ proxy) and simulates the strategy.
"""
from backtest.engine import run_backtest
from backtest.results_analyzer import analyze

if __name__ == "__main__":
    result = run_backtest(interval="5m", period="60d")
    stats = analyze(result)

    if stats:
        print(f"\nDone. {stats['total_trades']} trades found.")
        if not stats["would_pass_challenge"]:
            print("Strategy needs tuning before going live.")
        else:
            print("Strategy passes historical test. Review results above before trading.")
