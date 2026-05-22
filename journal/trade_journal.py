"""
SQLite-backed trade journal.
Every trade is logged — entries, exits, scores, drawdown state.
"""
from __future__ import annotations
import sqlite3
import json
from datetime import datetime, date
from pathlib import Path

DB_PATH = Path(__file__).parent / "trades.db"


class TradeJournal:
    def __init__(self, db_path: Path = DB_PATH):
        self._db = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp           TEXT    NOT NULL,
                    direction           TEXT    NOT NULL,
                    entry_price         REAL    NOT NULL,
                    stop_price          REAL    NOT NULL,
                    tp1_price           REAL,
                    tp2_price           REAL,
                    exit_price          REAL,
                    contracts           INTEGER NOT NULL,
                    risk_dollars        REAL,
                    pnl_dollars         REAL,
                    score               INTEGER,
                    score_breakdown     TEXT,
                    outcome             TEXT,
                    status              TEXT    DEFAULT 'OPEN',
                    drawdown_remaining  REAL,
                    daily_pnl           REAL,
                    total_pnl           REAL,
                    consistency_pct     REAL,
                    tradovate_order_id  TEXT,
                    asia_high           REAL,
                    asia_low            REAL,
                    vwap                REAL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS daily_summary (
                    date            TEXT PRIMARY KEY,
                    trades_count    INTEGER DEFAULT 0,
                    wins            INTEGER DEFAULT 0,
                    losses          INTEGER DEFAULT 0,
                    daily_pnl       REAL    DEFAULT 0,
                    ending_balance  REAL
                )
            """)

    def log_trade(self, data: dict) -> int:
        """Insert a new trade record. Returns the new row ID."""
        ts = data.get("timestamp", datetime.utcnow().isoformat())
        with self._connect() as conn:
            cur = conn.execute("""
                INSERT INTO trades (
                    timestamp, direction, entry_price, stop_price, tp1_price, tp2_price,
                    contracts, risk_dollars, score, score_breakdown, status,
                    drawdown_remaining, daily_pnl, total_pnl, tradovate_order_id,
                    asia_high, asia_low, vwap
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                ts,
                data.get("direction"),
                data.get("entry_price"),
                data.get("stop_price"),
                data.get("tp1_price"),
                data.get("tp2_price"),
                data.get("contracts"),
                data.get("risk_dollars"),
                data.get("score"),
                data.get("score_reason") or data.get("score_breakdown"),
                data.get("status", "OPEN"),
                data.get("drawdown_remaining"),
                data.get("daily_pnl"),
                data.get("total_pnl"),
                data.get("tradovate_order_id"),
                data.get("asia_high"),
                data.get("asia_low"),
                data.get("vwap"),
            ))
            return cur.lastrowid

    def update_trade(self, trade_id: int, data: dict) -> None:
        """Update an existing trade with exit info."""
        fields = {k: v for k, v in data.items() if k in {
            "exit_price", "pnl_dollars", "outcome", "status",
            "daily_pnl", "total_pnl", "drawdown_remaining", "consistency_pct"
        }}
        if not fields:
            return
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        with self._connect() as conn:
            conn.execute(
                f"UPDATE trades SET {set_clause} WHERE id = ?",
                list(fields.values()) + [trade_id]
            )

    def get_today_trades(self) -> list[dict]:
        today = date.today().isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM trades WHERE date(timestamp) = ?", (today,)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_all_trades(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM trades ORDER BY id").fetchall()
        return [dict(r) for r in rows]

    def get_stats(self) -> dict:
        with self._connect() as conn:
            all_rows = conn.execute("SELECT * FROM trades WHERE status = 'CLOSED'").fetchall()
        trades = [dict(r) for r in all_rows]
        if not trades:
            return {"total_trades": 0, "wins": 0, "losses": 0, "win_rate": 0, "total_pnl": 0}
        wins = [t for t in trades if (t["pnl_dollars"] or 0) > 0]
        losses = [t for t in trades if (t["pnl_dollars"] or 0) <= 0]
        return {
            "total_trades": len(trades),
            "wins":         len(wins),
            "losses":       len(losses),
            "win_rate":     round(len(wins) / len(trades) * 100, 1),
            "total_pnl":    round(sum(t["pnl_dollars"] or 0 for t in trades), 2),
            "avg_win":      round(sum(t["pnl_dollars"] or 0 for t in wins) / len(wins), 2) if wins else 0,
            "avg_loss":     round(sum(t["pnl_dollars"] or 0 for t in losses) / len(losses), 2) if losses else 0,
        }
