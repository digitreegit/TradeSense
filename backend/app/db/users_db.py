"""SQLite schema and helpers for TradeSense users."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any, Optional

from app.core.config import settings


def _db_path() -> Path:
    raw = os.getenv("TRADESENSE_DB_PATH", "")
    if raw:
        return Path(raw).expanduser().resolve()
    # Default: project root / data / tradesense.db
    here = Path(__file__).resolve().parent.parent.parent.parent
    d = here / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d / "tradesense.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path()), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_connection()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                alpaca_key_enc BLOB,
                alpaca_secret_enc BLOB,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def create_user(email: str, password_hash: str) -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO users (email, password_hash) VALUES (?, ?)",
            (email.strip().lower(), password_hash),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def get_user_by_email(email: str) -> Optional[dict[str, Any]]:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE email = ? COLLATE NOCASE",
            (email.strip().lower(),),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_user_by_id(user_id: int) -> Optional[dict[str, Any]]:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def set_user_alpaca_encrypted(
    user_id: int, key_enc: bytes, secret_enc: bytes
) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE users SET alpaca_key_enc = ?, alpaca_secret_enc = ? WHERE id = ?",
            (key_enc, secret_enc, user_id),
        )
        conn.commit()
    finally:
        conn.close()


def list_user_ids_with_alpaca() -> list[int]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id FROM users WHERE alpaca_key_enc IS NOT NULL "
            "AND alpaca_secret_enc IS NOT NULL"
        ).fetchall()
        return [int(r[0]) for r in rows]
    finally:
        conn.close()
