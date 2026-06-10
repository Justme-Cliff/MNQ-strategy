"""
Accuracy logger for the ^NDX-tightened price feed.

Runs the composite feed live and prints, every few seconds:
  RAW   = the old NQ 1-min anchor (laggy)
  NDX   = real-time ^NDX index
  PROXY = anchor + ^NDX delta (the tightened price)
  synced = whether the delta was actually applied

Watch this next to TradingView during the cash session (9:30-16:00 ET):
compare PROXY vs your chart's live NQ. PROXY should sit much closer than RAW.
If PROXY tracks within a few points and beats RAW, the tightening works — wire
it in with confidence. Ctrl+C to stop; writes _ndx_accuracy.csv.

Run: python3 _ndx_accuracy.py
"""
import csv
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from fast_feed import FastPriceFeed

EST = ZoneInfo("America/New_York")

if __name__ == "__main__":
    feed = FastPriceFeed(interval=10.0)
    print("warming up feed (need an NQ bar + ^NDX prints) ...")
    time.sleep(8)
    print(f"{'time':<10} {'RAW':>10} {'NDX':>10} {'PROXY':>10} {'PROXY-RAW':>10}  synced")
    rows = []
    try:
        while True:
            now   = datetime.now(tz=EST)
            raw   = feed.raw_price
            proxy = feed.price
            synced = feed.synced
            ndx   = feed._ndx.ndx if feed._ndx else None
            if raw is not None and proxy is not None:
                diff = proxy - raw
                print(f"{now.strftime('%H:%M:%S'):<10} {raw:>10.2f} "
                      f"{(ndx if ndx else 0):>10.2f} {proxy:>10.2f} {diff:>+10.2f}  "
                      f"{'YES' if synced else 'no'}")
                rows.append([now.isoformat(), raw, ndx, proxy, diff, synced])
            time.sleep(3)
    except KeyboardInterrupt:
        with open("_ndx_accuracy.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["time", "raw_nq", "ndx", "proxy_nq", "proxy_minus_raw", "synced"])
            w.writerows(rows)
        print(f"\nwrote _ndx_accuracy.csv ({len(rows)} rows)")
