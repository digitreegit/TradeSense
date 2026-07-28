"""State persistence: position metadata (stops/sleeves), pending orders,
equity curve, trade log, and key-value state (drawdown peak, regime, etc.).

Three backends behind one interface, picked automatically:
- Postgres     when DATABASE_URL is set (needs psycopg installed)
- Vercel Blob  when BLOB_READ_WRITE_TOKEN is set (default on Vercel — the
               serverless filesystem is ephemeral; one small JSON document)
- SQLite       otherwise (local dev / single-box Docker)
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from .config import settings

log = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS pos_meta (
    symbol TEXT PRIMARY KEY,
    sleeve TEXT NOT NULL,
    stop_level DOUBLE PRECISION,
    stop_mult DOUBLE PRECISION,
    entry_date TEXT,
    held_days INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS pending_orders (
    id {autoinc},
    symbol TEXT NOT NULL,
    sleeve TEXT NOT NULL,
    side TEXT NOT NULL,
    slot_weight DOUBLE PRECISION DEFAULT 0,
    stop_mult DOUBLE PRECISION DEFAULT 0,
    reason TEXT DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS equity_curve (
    ts TEXT PRIMARY KEY,
    equity DOUBLE PRECISION NOT NULL,
    cash DOUBLE PRECISION,
    regime TEXT
);
CREATE TABLE IF NOT EXISTS trades (
    id {autoinc},
    ts TEXT NOT NULL,
    symbol TEXT NOT NULL,
    sleeve TEXT,
    side TEXT NOT NULL,
    notional DOUBLE PRECISION,
    reason TEXT,
    detail TEXT
);
CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


class Store:
    def __init__(self, sqlite_path: str | None = None) -> None:
        self.pg = bool(settings.database_url)
        self.ephemeral = False
        self._lock = threading.Lock()
        if self.pg:
            import psycopg

            self._conn = psycopg.connect(settings.database_url, autocommit=True)
            schema = _SCHEMA.format(autoinc="BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY")
            with self._lock, self._conn.cursor() as cur:
                cur.execute(schema)
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
            schema = _SCHEMA.format(autoinc="INTEGER PRIMARY KEY AUTOINCREMENT")
            with self._lock:
                self._conn.executescript(schema)
                self._conn.commit()

    # -- backend-agnostic helpers ------------------------------------------
    def _exec(self, sql: str, params: tuple = ()) -> None:
        with self._lock:
            if self.pg:
                with self._conn.cursor() as cur:
                    cur.execute(sql.replace("?", "%s"), params)
            else:
                self._conn.execute(sql, params)
                self._conn.commit()

    def _query(self, sql: str, params: tuple = ()) -> list[dict]:
        with self._lock:
            if self.pg:
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
    def pending_replace(self, orders: list) -> None:
        self._exec("DELETE FROM pending_orders")
        for o in orders:
            self._exec(
                "INSERT INTO pending_orders(symbol,sleeve,side,slot_weight,stop_mult,reason,created_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (o.symbol, o.sleeve, o.side, o.slot_weight, o.stop_mult, o.reason,
                 datetime.now(timezone.utc).isoformat()),
            )

    def pending_all(self) -> list[dict]:
        return self._query("SELECT * FROM pending_orders ORDER BY id")

    def pending_clear(self) -> None:
        self._exec("DELETE FROM pending_orders")

    # -- logs -------------------------------------------------------------
    def log_equity(self, equity: float, cash: float, reg: str) -> None:
        self._exec(
            "INSERT INTO equity_curve(ts,equity,cash,regime) VALUES(?,?,?,?) "
            "ON CONFLICT(ts) DO UPDATE SET equity=excluded.equity",
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
        try:
            self.set("_heartbeat", datetime.now(timezone.utc).isoformat())
            return {"ok": True, "backend": "postgres" if self.pg else "sqlite",
                    "ephemeral": self.ephemeral}
        except Exception as exc:
            return {"ok": False, "backend": "postgres" if self.pg else "sqlite",
                    "error": str(exc)}

    # -- Alpaca credentials (kept apart from trading state) -----------------
    def config_get(self) -> dict:
        return self.get("alpaca_config", {}) or {}

    def config_set(self, cfg: dict) -> None:
        self.set("alpaca_config", cfg)


class BlobStore:
    """Whole state as one JSON document in Vercel Blob.

    Volumes are tiny (a few writes per day), and jobs never overlap in time,
    so read-modify-write on a single document is safe. A short TTL cache
    keeps the dashboard cheap while staying fresh across lambda instances.
    """

    PATH = "state/tradesense.json"
    # Credentials live in their OWN document. The main state doc is rewritten
    # by every cron tick; if a download transiently returns empty, that
    # rewrite used to wipe the saved live keys. A separate doc that only the
    # settings endpoints write can never be clobbered by trading-state saves.
    CONFIG_PATH = "state/alpaca_config.json"
    API = "https://blob.vercel-storage.com"
    API_VERSION = "12"
    TTL_SECONDS = 10
    EMPTY = {"kv": {}, "pos_meta": {}, "pending": [], "equity_curve": [], "trades": []}

    def __init__(self) -> None:
        self._state: dict | None = None
        self._loaded_at = 0.0
        self._url: str | None = None
        self._lock = threading.Lock()
        self._load_ok = False
        self._config: dict | None = None
        self._config_at = 0.0
        self._config_url: str | None = None

    # -- transport (Blob REST API, mirrors @vercel/blob headers) -----------
    def _token(self) -> str:
        # Prefer the long-lived RW token. OIDC alone is short-lived and not
        # always present in Python serverless; RW token works for list/put/get.
        return (
            os.environ.get("BLOB_READ_WRITE_TOKEN")
            or os.environ.get("VERCEL_OIDC_TOKEN")
            or ""
        )

    def _headers(self, **extra: str) -> dict:
        return {
            "authorization": f"Bearer {self._token()}",
            "x-api-version": self.API_VERSION,
            **extra,
        }

    def _get_private(self, url: str) -> "httpx.Response":
        """GET a private blob URL, re-attaching Authorization on every hop.

        httpx drops Authorization when following cross-host redirects. Private
        blob CDN URLs redirect to origin, so a naive follow_redirects=True
        yields a silent 403 and the bot can never persist state/orders."""
        import httpx

        # Only Authorization — x-api-version is for the Blob API host, not CDN.
        headers = {"authorization": f"Bearer {self._token()}"}
        # Bypass CDN so overwrite-after-write is immediately visible.
        fetch_url = url
        if "cache=" not in url:
            sep = "&" if "?" in url else "?"
            fetch_url = f"{url}{sep}cache=0"

        current = fetch_url
        for _ in range(5):
            resp = httpx.get(current, headers=headers, timeout=15, follow_redirects=False)
            if resp.status_code in (301, 302, 303, 307, 308):
                loc = resp.headers.get("location")
                if not loc:
                    resp.raise_for_status()
                current = str(httpx.URL(current).join(loc))
                continue
            return resp
        return resp  # type: ignore[name-defined]

    def _download_doc(self, path: str, url: str | None) -> tuple[bytes | None, str | None]:
        """Fetch one JSON document. Retries once when the listing comes back
        empty or the cached URL 404s — transient blips here must not be
        mistaken for 'document does not exist'."""
        import httpx

        for attempt in (0, 1):
            if url is None:
                resp = httpx.get(
                    f"{self.API}/?prefix={path}&limit=1",
                    headers=self._headers(), timeout=15,
                )
                resp.raise_for_status()
                blobs = resp.json().get("blobs", [])
                url = blobs[0]["url"] if blobs else None
            if url is None:
                if attempt == 0:
                    time.sleep(1)
                    continue
                return None, None
            resp = self._get_private(url)
            if resp.status_code == 404:
                url = None
                if attempt == 0:
                    continue
                return None, None
            resp.raise_for_status()
            return resp.content, url
        return None, None

    def _download(self) -> bytes | None:
        raw, self._url = self._download_doc(self.PATH, self._url)
        return raw

    def _load(self, force: bool = False) -> dict:
        with self._lock:
            fresh = self._state is not None and (time.time() - self._loaded_at) < self.TTL_SECONDS
            if fresh and not force:
                return self._state
            try:
                raw = self._download()
                self._state = json.loads(raw) if raw else json.loads(json.dumps(self.EMPTY))
                self._load_ok = True
            except Exception as exc:
                log.error("blob state load failed: %s", exc)
                self._load_ok = False
                if self._state is None:
                    self._state = json.loads(json.dumps(self.EMPTY))
            self._loaded_at = time.time()
            return self._state

    def _save(self) -> None:
        import httpx

        # Never persist an EMPTY fallback produced after a failed download —
        # that is how live keys / trading_mode get wiped back to env paper.
        if not self._load_ok:
            log.error("blob state save skipped: last load failed")
            return
        try:
            resp = httpx.put(
                f"{self.API}/?pathname={self.PATH}",
                headers=self._headers(**{
                    "x-vercel-blob-access": "private",
                    "x-allow-overwrite": "1",
                    "x-add-random-suffix": "0",
                    "x-cache-control-max-age": "0",
                    "x-content-type": "application/json",
                }),
                content=json.dumps(self._state).encode(),
                timeout=15,
            )
            resp.raise_for_status()
            self._url = resp.json().get("url", self._url)
        except Exception as exc:
            log.error("blob state save failed: %s", exc)

    # -- kv -----------------------------------------------------------------
    def get(self, key: str, default=None):
        return self._load().get("kv", {}).get(key, default)

    def set(self, key: str, value) -> None:
        # Always re-read before write to reduce lost-update races with cron.
        st = self._load(force=True)
        st.setdefault("kv", {})[key] = value
        self._save()

    # -- position metadata ---------------------------------------------------
    def pos_meta_all(self) -> dict[str, dict]:
        return dict(self._load().get("pos_meta", {}))

    def pos_meta_upsert(self, symbol: str, sleeve: str, stop_level: float | None,
                        stop_mult: float, entry_date: str, held_days: int = 0) -> None:
        st = self._load(force=True)
        st.setdefault("pos_meta", {})[symbol] = {
            "symbol": symbol, "sleeve": sleeve, "stop_level": stop_level,
            "stop_mult": stop_mult, "entry_date": entry_date, "held_days": held_days,
        }
        self._save()

    def pos_meta_update_stop(self, symbol: str, stop_level: float, held_days: int) -> None:
        st = self._load(force=True)
        meta = st.get("pos_meta", {}).get(symbol)
        if meta:
            meta["stop_level"] = stop_level
            meta["held_days"] = held_days
            self._save()

    def pos_meta_delete(self, symbol: str) -> None:
        st = self._load(force=True)
        if st.get("pos_meta", {}).pop(symbol, None) is not None:
            self._save()

    # -- pending orders ---------------------------------------------------------
    def pending_replace(self, orders: list) -> None:
        st = self._load(force=True)
        st["pending"] = [
            {"id": i + 1, "symbol": o.symbol, "sleeve": o.sleeve, "side": o.side,
             "slot_weight": o.slot_weight, "stop_mult": o.stop_mult, "reason": o.reason,
             "created_at": datetime.now(timezone.utc).isoformat()}
            for i, o in enumerate(orders)
        ]
        self._save()

    def pending_all(self) -> list[dict]:
        return list(self._load().get("pending", []))

    def pending_clear(self) -> None:
        st = self._load(force=True)
        if st.get("pending"):
            st["pending"] = []
            self._save()

    # -- logs ----------------------------------------------------------------
    def log_equity(self, equity: float, cash: float, reg: str) -> None:
        st = self._load(force=True)
        st.setdefault("equity_curve", []).append(
            {"ts": datetime.now(timezone.utc).isoformat(), "equity": equity,
             "cash": cash, "regime": reg})
        st["equity_curve"] = st["equity_curve"][-5000:]
        self._save()

    def log_trade(self, symbol: str, sleeve: str, side: str, notional: float,
                  reason: str, detail: str = "") -> None:
        st = self._load(force=True)
        trades = st.setdefault("trades", [])
        trades.append({"id": len(trades) + 1,
                       "ts": datetime.now(timezone.utc).isoformat(),
                       "symbol": symbol, "sleeve": sleeve, "side": side,
                       "notional": notional, "reason": reason, "detail": detail})
        st["trades"] = trades[-2000:]
        self._save()

    def equity_curve(self, limit: int = 5000) -> list[dict]:
        return self._load().get("equity_curve", [])[-limit:]

    def recent_trades(self, limit: int = 200) -> list[dict]:
        return list(reversed(self._load().get("trades", [])[-limit:]))

    def storage_health(self) -> dict:
        """Probe whether the blob backend can read/write. Surfaces billing
        suspensions that otherwise look like a silent 'idle' bot."""
        import httpx

        try:
            probe = {
                "kv": {"_heartbeat": datetime.now(timezone.utc).isoformat()},
                "pos_meta": {}, "pending": [], "equity_curve": [], "trades": [],
            }
            resp = httpx.put(
                f"{self.API}/?pathname={self.PATH}",
                headers=self._headers(**{
                    "x-vercel-blob-access": "private",
                    "x-allow-overwrite": "1",
                    "x-add-random-suffix": "0",
                    "x-cache-control-max-age": "0",
                    "x-content-type": "application/json",
                }),
                content=json.dumps(probe).encode(),
                timeout=15,
            )
            if resp.status_code >= 400:
                body = (resp.text or "")[:300]
                return {
                    "ok": False, "backend": "blob",
                    "error": f"Vercel Blob write failed ({resp.status_code}): {body}",
                }
            self._url = resp.json().get("url", self._url)
            self._state = probe
            self._load_ok = True
            self._loaded_at = time.time()
            # Confirm we can read it back
            raw, self._url = self._download_doc(self.PATH, self._url)
            if raw is None:
                return {"ok": False, "backend": "blob",
                        "error": "Vercel Blob write ok but read returned empty"}
            return {"ok": True, "backend": "blob"}
        except Exception as exc:
            msg = str(exc)
            return {"ok": False, "backend": "blob", "error": msg}
        with self._lock:
            fresh = self._config is not None and (time.time() - self._config_at) < self.TTL_SECONDS
            if fresh:
                return dict(self._config)
            try:
                raw, self._config_url = self._download_doc(self.CONFIG_PATH, self._config_url)
                self._config = json.loads(raw) if raw else {}
            except Exception as exc:
                log.error("alpaca config load failed: %s", exc)
                if self._config is None:
                    self._config = {}
            self._config_at = time.time()
            return dict(self._config)

    def config_set(self, cfg: dict) -> None:
        import httpx

        with self._lock:
            resp = httpx.put(
                f"{self.API}/?pathname={self.CONFIG_PATH}",
                headers=self._headers(**{
                    "x-vercel-blob-access": "private",
                    "x-allow-overwrite": "1",
                    "x-add-random-suffix": "0",
                    "x-cache-control-max-age": "0",
                    "x-content-type": "application/json",
                }),
                content=json.dumps(cfg).encode(),
                timeout=15,
            )
            resp.raise_for_status()
            self._config = dict(cfg)
            self._config_at = time.time()
            self._config_url = resp.json().get("url", self._config_url)


def _make_store():
    if settings.database_url:
        return Store()
    if os.environ.get("BLOB_READ_WRITE_TOKEN"):
        return BlobStore()
    return Store()


store = _make_store()
