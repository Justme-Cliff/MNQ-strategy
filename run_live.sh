#!/usr/bin/env bash
# Launch monitor.py on the v8 hybrid engine with the ML meta-labeling gate.
#
#   ./run_live.sh            -> ML_GATE=shadow (ML score shown, NEVER vetoes — most signals)
#   ./run_live.sh live       -> ML_GATE=live   (gate actively vetoes low-confidence signals)
#   ./run_live.sh off        -> ML_GATE=off    (rules-only hybrid engine, no ML opinion)
#
# Default is SHADOW: you see the model's P(win) on every signal but it never
# suppresses one — maximizes signal count while you build trust in the model
# (the documented shadow-first path). Switch to `live` only after you've watched
# the shadow scores track real outcomes for a few weeks.
#
# Plain `python3 monitor.py` also defaults to the hybrid engine + shadow gate;
# this script just makes the engine/gate explicit.

set -euo pipefail
cd "$(dirname "$0")"

MODE="${1:-shadow}"
case "$MODE" in
  live|shadow|off) ;;
  *) echo "Usage: ./run_live.sh [live|shadow|off]" >&2; exit 1 ;;
esac

ISOGENY_ENGINE=hybrid ISOGENY_ML_GATE="$MODE" python3 monitor.py
