"""JWT + bcrypt auth."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import bcrypt
import jwt

from app.db import users_db

JWT_ALG = "HS256"


def _jwt_secret() -> str:
    s = os.getenv("JWT_SECRET", "").strip()
    if not s:
        raise RuntimeError("JWT_SECRET is not set in environment.")
    return s


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def create_access_token(user_id: int, email: str) -> str:
    exp_min = int(os.getenv("JWT_EXPIRE_MINUTES", "10080"))  # 7 days default
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "email": email,
        "exp": now + timedelta(minutes=exp_min),
        "iat": now,
    }
    return jwt.encode(payload, _jwt_secret(), algorithm=JWT_ALG)


def decode_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, _jwt_secret(), algorithms=[JWT_ALG])


def register_user(email: str, password: str) -> dict[str, Any]:
    users_db.init_db()
    if users_db.get_user_by_email(email):
        raise ValueError("Email already registered")
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters")
    uid = users_db.create_user(email, hash_password(password))
    row = users_db.get_user_by_id(uid)
    token = create_access_token(uid, row["email"])
    return {"user_id": uid, "email": row["email"], "access_token": token}


def login_user(email: str, password: str) -> dict[str, Any]:
    users_db.init_db()
    row = users_db.get_user_by_email(email)
    if not row or not verify_password(password, row["password_hash"]):
        raise ValueError("Invalid email or password")
    token = create_access_token(int(row["id"]), row["email"])
    return {"user_id": int(row["id"]), "email": row["email"], "access_token": token}
