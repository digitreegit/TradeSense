"""State persistence: position metadata (stops/sleeves), pending orders,
equity curve, trade log, and key-value state (drawdown peak, regime, etc.).

Two backends behind one interface, picked automatically:
- Postgres  when DATABASE_URL is set (Supabase — required on Vercel)
- SQLite    otherwise (local dev / single-box Docker)

The old Vercel Blob backend was removed: its health probe could overwrite
the live state document, and the store itself got suspended. On Vercel
without DATABASE_URL the app boots on ephemeral /tmp SQLite and the
dashboard shows a loud storage error instead of silently losing state.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from .config import settings

log = logging.getLogger(__name__)

_TABLES = (
    """
CREATE TABLE IF NOT EXISTS pos_meta (
    symbol TEXT PRIMARY KEY,
    sleeve TEXT NOT NULL,
    stop_level DOUBLE PRECISION,
    stop_mult DOUBLE PRECISION,
    entry_date TEXT,
    held_days INTEGER DEFAULT 0
)
""",
    """
CREATE TABLE IF NOT EXISTS pending_orders (
    id {autoinc},
    symbol TEXT NOT NULL,
    sleeve TEXT NOT NULL,
    side TEXT NOT NULL,
    slot_weight DOUBLE PRECISION DEFAULT 0,
    stop_mult DOUBLE PRECISION DEFAULT 0,
    reason TEXT DEFAULT '',
    created_at TEXT NOT NULL
)
""",
    """
CREATE TABLE IF NOT EXISTS equity_curve (
    ts TEXT PRIMARY KEY,
    equity DOUBLE PRECISION NOT NULL,
    cash DOUBLE PRECISION,
    regime TEXT
)
""",
    """
CREATE TABLE IF NOT EXISTS trades (
    id {autoinc},
    ts TEXT NOT NULL,
    symbol TEXT NOT NULL,
    sleeve TEXT,
    side TEXT NOT NULL,
    notional DOUBLE PRECISION,
    reason TEXT,
    detail TEXT
)
""",
    """
CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY,
    value TEXT
)
""",
    """
CREATE TABLE IF NOT EXISTS job_claims (
    key TEXT PRIMARY KEY,
    claimed_at DOUBLE PRECISION NOT NULL
)
""",
)

_APP_TABLES = (
    "pos_meta",
    "pending_orders",
    "equity_curve",
    "trades",
    "kv",
    "job_claims",
)

# Tables were created by the Vercel pooler role, which is not the SQL-editor
# `postgres` user. That role also does not bypass RLS, so ENABLE RLS with no
# matching policy blocked cron writes. Disable RLS here (as the table owner)
# and revoke API roles so PostgREST still cannot read the tables.


class Store:
    def __init__(self, sqlite_path: str | None = None) -> None:
        self.pg = bool(settings.database_url)
        self.ephemeral = False
        self._lock = threading.Lock()
        self._conn = None
        if self.pg:
            self._pg_connect()
            self._pg_migrate()
        else:
            if settings.on_vercel:
                # no DATABASE_URL on Vercel: fall back to ephemeral /tmp so the
                # app still boots; state will NOT survive across invocations
                sqlite_path = "/tmp/tradesense.db"
                self.ephemeral = True
            db_path = Path(sqlite_path or settings.db_path)
            db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            schema = ";\n".join(
                t.format(autoinc="INTEGER PRIMARY KEY AUTOINCREMENT") for t in _TABLES
            )
            with self._lock:
                self._conn.executescript(schema)
                self._conn.commit()

    def _pg_connect(self) -> None:
        import psycopg

        # prepare_threshold=None is required for Supabase transaction pooler
        # (port 6543); prepared statements are not supported across clients.
        url = settings.database_url
        if "sslmode=" not in url:
            url += ("&" if "?" in url else "?") + "sslmode=require"
        self._conn = psycopg.connect(url, autocommit=True, prepare_threshold=None)

    def _pg_migrate(self) -> None:
        autoinc = "BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY"
        with self._lock:
            with self._conn.cursor() as cur:
                for stmt in _TABLES:
                    cur.execute(stmt.format(autoinc=autoinc))
                for name in _APP_TABLES:
                    try:
                        cur.execute(
                            f"ALTER TABLE {name} DISABLE ROW LEVEL SECURITY"
                        )
                    except Exception as exc:
                        log.debug("rls disable skipped for %s: %s", name, exc)
                    try:
                        cur.execute(
                            f"REVOKE ALL ON TABLE {name} FROM PUBLIC, anon, authenticated"
                        )
                    except Exception as exc:
                        log.debug("revoke skipped for %s: %s", name, exc)

    def _pg_ensure(self) -> None:
        """Reconnect if the pooled connection was closed between lambda invokes."""
        try:
            if self._conn is None or self._conn.closed:
                self._pg_connect()
                return
            self._conn.execute("SELECT 1")
        except Exception:
            log.warning("postgres connection stale; reconnecting")
            try:
                if self._conn is not None and not self._conn.closed:
                    self._conn.close()
            except Exception:
                pass
            self._pg_connect()

    # -- backend-agnostic helpers ------------------------------------------
    def _exec(self, sql: str, params: tuple = ()) -> None:
        with self._lock:
            if self.pg:
                self._pg_ensure()
                with self._conn.cursor() as cur:
                    cur.execute(sql.replace("?", "%s"), params)
            else:
                self._conn.execute(sql, params)
                self._conn.commit()

    def _query(self, sql: str, params: tuple = ()) -> list[dict]:
        with self._lock:
            if self.pg:
                self._pg_ensure()
                with self._conn.cursor() as cur:
                    cur.execute(sql.replace("?", "%s"), params)
                    cols = [d.name for d in cur.description]
                    return [dict(zip(cols, row)) for row in cur.fetchall()]
            cur = self._conn.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]

    # -- kv -------------------------------------------------------------
    def get(self, key: str, default=None):
        rows = self._query("SELECT value FROM kv WHERE key=?", (key,))
        return json.loads(rows[0]["value"]) if rows else default

    def set(self, key: str, value) -> None:
        self._exec(
            "INSERT INTO kv(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value)),
        )

    def try_job_claim(self, key: str, stale_after: float = 600.0) -> bool:
        """Atomically claim one cron execution window across server instances."""
        now = time.time()
        with self._lock:
            if self.pg:
                self._pg_ensure()
                with self._conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM job_claims WHERE claimed_at < %s",
                        (now - 7 * 86400,),
                    )
                    cur.execute(
                        "DELETE FROM job_claims WHERE key=%s AND claimed_at < %s",
                        (key, now - stale_after),
                    )
                    cur.execute(
                        "INSERT INTO job_claims(key,claimed_at) VALUES(%s,%s) "
                        "ON CONFLICT(key) DO NOTHING RETURNING key",
                        (key, now),
                    )
                    return cur.fetchone() is not None
            self._conn.execute(
                "DELETE FROM job_claims WHERE claimed_at < ?",
                (now - 7 * 86400,),
            )
            self._conn.execute(
                "DELETE FROM job_claims WHERE key=? AND claimed_at < ?",
                (key, now - stale_after),
            )
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO job_claims(key,claimed_at) VALUES(?,?)",
                (key, now),
            )
            self._conn.commit()
            return cur.rowcount == 1

    def release_job_claim(self, key: str) -> None:
        self._exec("DELETE FROM job_claims WHERE key=?", (key,))

    # -- position metadata ----------------------------------------------
    def pos_meta_all(self) -> dict[str, dict]:
        return {r["symbol"]: r for r in self._query("SELECT * FROM pos_meta")}

    def pos_meta_upsert(self, symbol: str, sleeve: str, stop_level: float | None,
                        stop_mult: float, entry_date: str, held_days: int = 0) -> None:
        self._exec(
            "INSERT INTO pos_meta(symbol,sleeve,stop_level,stop_mult,entry_date,held_days) "
            "VALUES(?,?,?,?,?,?) ON CONFLICT(symbol) DO UPDATE SET "
            "sleeve=excluded.sleeve, stop_level=excluded.stop_level, "
            "stop_mult=excluded.stop_mult, held_days=excluded.held_days",
            (symbol, sleeve, stop_level, stop_mult, entry_date, held_days),
        )

    def pos_meta_update_stop(self, symbol: str, stop_level: float, held_days: int) -> None:
        self._exec("UPDATE pos_meta SET stop_level=?, held_days=? WHERE symbol=?",
                   (stop_level, held_days, symbol))

    def pos_meta_delete(self, symbol: str) -> None:
        self._exec("DELETE FROM pos_meta WHERE symbol=?", (symbol,))

    # -- pending orders ---------------------------------------------------
    def _replace_pending_rows(self, rows: list[tuple]) -> None:
        sql = (
            "INSERT INTO pending_orders"
            "(symbol,sleeve,side,slot_weight,stop_mult,reason,created_at) "
            "VALUES(?,?,?,?,?,?,?)"
        )
        # DELETE + INSERT must be one transaction. A serverless timeout between
        # the old per-row autocommit calls could erase the entire next-open queue.
        with self._lock:
            if self.pg:
                self._pg_ensure()
                with self._conn.transaction():
                    with self._conn.cursor() as cur:
                        cur.execute("DELETE FROM pending_orders")
                        if rows:
                            cur.executemany(sql.replace("?", "%s"), rows)
                return
            self._conn.execute("DELETE FROM pending_orders")
            if rows:
                self._conn.executemany(sql, rows)
            self._conn.commit()

    def pending_replace(self, orders: list) -> None:
        created_at = datetime.now(timezone.utc).isoformat()
        self._replace_pending_rows([
            (o.symbol, o.sleeve, o.side, o.slot_weight, o.stop_mult, o.reason, created_at)
            for o in orders
        ])

    def pending_replace_dicts(self, orders: list[dict]) -> None:
        """Rewrite the pending queue from row dicts (used to keep only the
        orders that failed to execute at the open, so they retry next tick)."""
        self._replace_pending_rows([
                (o["symbol"], o["sleeve"], o["side"], o.get("slot_weight", 0),
                 o.get("stop_mult", 0), o.get("reason", ""),
                 o.get("created_at") or datetime.now(timezone.utc).isoformat())
                for o in orders
        ])

    def pending_all(self) -> list[dict]:
        return self._query("SELECT * FROM pending_orders ORDER BY id")

    def pending_clear(self) -> None:
        self._exec("DELETE FROM pending_orders")

    # -- logs -------------------------------------------------------------
    def log_equity(self, equity: float, cash: float, reg: str) -> None:
        self._exec(
            "INSERT INTO equity_curve(ts,equity,cash,regime) VALUES(?,?,?,?) "
            "ON CONFLICT(ts) DO UPDATE SET equity=excluded.equity, "
            "cash=excluded.cash, regime=excluded.regime",
            (datetime.now(timezone.utc).isoformat(), equity, cash, reg),
        )

    def log_trade(self, symbol: str, sleeve: str, side: str, notional: float,
                  reason: str, detail: str = "") -> None:
        self._exec(
            "INSERT INTO trades(ts,symbol,sleeve,side,notional,reason,detail) VALUES(?,?,?,?,?,?,?)",
            (datetime.now(timezone.utc).isoformat(), symbol, sleeve, side, notional, reason, detail),
        )

    def equity_curve(self, limit: int = 5000) -> list[dict]:
        rows = self._query("SELECT * FROM equity_curve ORDER BY ts DESC LIMIT ?", (limit,))
        return list(reversed(rows))

    def recent_trades(self, limit: int = 200) -> list[dict]:
        return self._query("SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,))

    def reset_trading_state(self) -> None:
        """Wipe account-specific state (drawdown peak, regime, positions,
        pending orders, equity curve, trades). Keeps Alpaca keys + activity log."""
        self._exec("DELETE FROM pos_meta")
        self._exec("DELETE FROM pending_orders")
        self._exec("DELETE FROM equity_curve")
        self._exec("DELETE FROM trades")
        self._exec("DELETE FROM kv WHERE key IN ('brake','regime') OR key LIKE 'job_ran:%'")

    def storage_health(self) -> dict:
        backend = "postgres" if self.pg else "sqlite"
        if self.ephemeral:
            # /tmp SQLite on Vercel: works within one invocation but state is
            # lost between lambdas. Treat as broken so the dashboard screams.
            return {"ok": False, "backend": backend, "ephemeral": True,
                    "error": "DATABASE_URL 미설정 — 상태가 요청 간에 유지되지 않습니다."}
        try:
            self.set("_heartbeat", datetime.now(timezone.utc).isoformat())
            return {"ok": True, "backend": backend, "ephemeral": False}
        except Exception as exc:
            return {"ok": False, "backend": backend, "error": str(exc)}

    # -- Alpaca credentials (kept apart from trading state) -----------------
    def config_get(self) -> dict:
        return self.get("alpaca_config", {}) or {}

    def config_set(self, cfg: dict) -> None:
        self.set("alpaca_config", cfg)


store = Store()
