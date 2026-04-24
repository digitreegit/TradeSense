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
                supabase_user_id TEXT UNIQUE,
                alpaca_key_enc BLOB,
                alpaca_secret_enc BLOB,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        # Lightweight migration for existing DBs created before supabase_user_id
        cols = conn.execute("PRAGMA table_info(users)").fetchall()
        col_names = {str(c[1]) for c in cols}
        if "supabase_user_id" not in col_names:
            conn.execute("ALTER TABLE users ADD COLUMN supabase_user_id TEXT")
        if "alpaca_paper_trading" not in col_names:
            conn.execute(
                "ALTER TABLE users ADD COLUMN alpaca_paper_trading INTEGER NOT NULL DEFAULT 1"
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


def get_user_by_supabase_id(supabase_user_id: str) -> Optional[dict[str, Any]]:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE supabase_user_id = ?",
            (supabase_user_id,),
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


def ensure_user_for_supabase(
    email: str,
    supabase_user_id: str,
) -> dict[str, Any]:
    """
    Map Supabase-authenticated identity to local user row.
    - Prefer direct supabase_user_id match
    - Else match by email and bind supabase_user_id
    - Else create new user row (password_hash kept empty for OAuth users)
    """
    user_row = get_user_by_supabase_id(supabase_user_id)
    if user_row:
        return user_row

    existing = get_user_by_email(email)
    conn = get_connection()
    try:
        if existing:
            conn.execute(
                "UPDATE users SET supabase_user_id = ? WHERE id = ?",
                (supabase_user_id, int(existing["id"])),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM users WHERE id = ?", (int(existing["id"]),)).fetchone()
            return dict(row)
        cur = conn.execute(
            "INSERT INTO users (email, password_hash, supabase_user_id) VALUES (?, ?, ?)",
            (email.strip().lower(), "", supabase_user_id),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM users WHERE id = ?", (int(cur.lastrowid),)).fetchone()
        return dict(row)
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


def get_alpaca_paper_trading(user_id: int) -> bool:
    """True = paper API endpoint; False = live trading API."""
    row = get_user_by_id(user_id)
    if not row:
        return True
    v = row.get("alpaca_paper_trading")
    if v is None:
        return True
    return bool(int(v))


def set_alpaca_paper_trading(user_id: int, paper: bool) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE users SET alpaca_paper_trading = ? WHERE id = ?",
            (1 if paper else 0, user_id),
        )
        conn.commit()
    finally:
        conn.close()


def clear_user_alpaca_encrypted(user_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE users SET alpaca_key_enc = NULL, alpaca_secret_enc = NULL WHERE id = ?",
            (user_id,),
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
