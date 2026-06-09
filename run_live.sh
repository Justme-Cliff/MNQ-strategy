#!/usr/bin/env bash
# Launch monitor.py on the v8 hybrid engine with the ML meta-labeling gate.
#
#   ./run_live.sh            -> ML_GATE=live   (gate actively vetoes low-confidence signals)
#   ./run_live.sh shadow     -> ML_GATE=shadow (ML scores shown, never vetoes — build trust first)
#   ./run_live.sh off        -> ML_GATE=off    (rules-only hybrid engine, no ML opinion)
#
# Plain `python3 monitor.py` defaults to ISOGENY_ENGINE=quant — the old, far more
# conservative v7.0 engine (~43 signals / 623 days). This script always runs the
# validated v8 hybrid engine (283 signals / 80.9% WR with the gate live).

set -euo pipefail
cd "$(dirname "$0")"

MODE="${1:-live}"
case "$MODE" in
  live|shadow|off) ;;
  *) echo "Usage: ./run_live.sh [live|shadow|off]" >&2; exit 1 ;;
esac

ISOGENY_ENGINE=hybrid ISOGENY_ML_GATE="$MODE" python3 monitor.py
