import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status

from app.core import database
from app.core.premium import PLAN_FREE, PLAN_PREMIUM, effective_plan
from app.core.security import (
    create_access_token,
    decode_access_token,
    get_password_hash,
    verify_password,
)
from app.schemas.auth_schema import Token, UserLogin, UserOut, UserRegister

router = APIRouter(prefix="/auth", tags=["Authentication"])

# Users are stored in a small SQLite file so accounts survive server restarts.
# The location and connection settings live in app/core/database.py.
DB_PATH = database.DB_PATH
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD_LENGTH = 8


def _connect() -> sqlite3.Connection:
    return database.connect()


def _init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                hashed_password TEXT NOT NULL,
                plan TEXT NOT NULL DEFAULT 'free',
                created_at TEXT NOT NULL
            )
            """
        )
        # Demo account so the app can be tried without signing up.
        conn.execute(
            """
            INSERT OR IGNORE INTO users (id, name, email, hashed_password, plan, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "usr-demo-01",
                "Alex Morgan",
                "alex@example.com",
                get_password_hash("password123"),
                "premium",
                "2026-01-15T10:00:00Z",
            ),
        )
        # Additive migrations (premium_until column, payments table).
        database.migrate(conn)


_init_db()


def _get_user_by_email(email: str) -> Optional[sqlite3.Row]:
    with _connect() as conn:
        return conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()


def _to_user_out(row: sqlite3.Row) -> UserOut:
    premium_until = row["premium_until"] if "premium_until" in row.keys() else None
    return UserOut(
        id=row["id"],
        name=row["name"],
        email=row["email"],
        # Effective plan (expiry-aware), never the raw stored value.
        plan=effective_plan(row["id"], row["plan"], premium_until),
        created_at=row["created_at"],
        premium_until=premium_until,
    )


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _user_from_token(authorization: Optional[str]) -> Optional[UserOut]:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    payload = decode_access_token(authorization.split(" ", 1)[1])
    sub = payload.get("sub") if payload else None
    uid = payload.get("uid") if payload else None
    # Both claims are required. Tokens issued before `uid` existed are rejected
    # (no email-only fallback), so users simply log in again.
    if not isinstance(sub, str) or not sub or not isinstance(uid, str) or not uid:
        raise HTTPException(status_code=401, detail="Invalid or expired session. Please log in again.")
    row = _get_user_by_email(sub)
    # The account found by email must be the SAME account the token was issued
    # to: a deleted account's token can never authenticate a later account that
    # re-registered with the same email.
    if not row or row["id"] != uid:
        raise HTTPException(status_code=401, detail="Account no longer exists. Please log in again.")
    return _to_user_out(row)


def require_user(authorization: Optional[str] = Header(None)) -> UserOut:
    """Dependency for endpoints that need a logged-in user."""
    user = _user_from_token(authorization)
    if user is None:
        raise HTTPException(status_code=401, detail="Not logged in")
    return user


def get_optional_user(authorization: Optional[str] = Header(None)) -> Optional[UserOut]:
    """Logged-in user, or None for a guest. Never substitutes another account.

    For endpoints that guests may use. A missing, malformed, invalid or expired
    token is treated as a guest (Free): this can only ever LOWER access, never
    grant it, and keeps Free features working for a browser holding a stale
    token. Endpoints that need a real login use `require_user` (401) instead.
    """
    try:
        return _user_from_token(authorization)
    except HTTPException:
        return None


def get_effective_plan(user: Optional[UserOut] = Depends(get_optional_user)) -> str:
    """The caller's server-verified plan: 'free' for guests, otherwise the
    effective plan computed by app.core.premium (see `_to_user_out`). Never
    read from query parameters, request bodies or frontend state."""
    return PLAN_PREMIUM if user is not None and user.plan == PLAN_PREMIUM else PLAN_FREE


PREMIUM_REQUIRED_DETAIL = "This feature requires an active MYMILE Premium pass."


def require_premium(plan: str = Depends(get_effective_plan)) -> str:
    """Dependency for Premium-only endpoints: 403 for guests and Free users."""
    if plan != PLAN_PREMIUM:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=PREMIUM_REQUIRED_DETAIL)
    return plan


@router.post("/register", response_model=Token, status_code=status.HTTP_201_CREATED)
async def register(req: UserRegister):
    name = req.name.strip()
    email = _normalize_email(req.email)

    if not name:
        raise HTTPException(status_code=400, detail="Please enter your name.")
    if not EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="Please enter a valid email address.")
    if len(req.password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Password must be at least {MIN_PASSWORD_LENGTH} characters.",
        )
    if _get_user_by_email(email):
        raise HTTPException(status_code=409, detail="An account with this email already exists.")

    user_id = f"usr-{uuid.uuid4().hex[:8]}"
    created_at = datetime.now(timezone.utc).isoformat()
    try:
        with _connect() as conn:
            conn.execute(
                "INSERT INTO users (id, name, email, hashed_password, plan, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, name, email, get_password_hash(req.password), "free", created_at),
            )
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="An account with this email already exists.")

    row = _get_user_by_email(email)
    return Token(access_token=create_access_token(subject=email, uid=row["id"]), user=_to_user_out(row))


@router.post("/login", response_model=Token)
async def login(req: UserLogin):
    email = _normalize_email(req.email)
    row = _get_user_by_email(email)
    # Same message for unknown email and wrong password, so accounts can't be probed.
    if not row or not verify_password(req.password, row["hashed_password"]):
        raise HTTPException(status_code=401, detail="Incorrect email or password.")
    return Token(access_token=create_access_token(subject=email, uid=row["id"]), user=_to_user_out(row))


@router.get("/me", response_model=UserOut)
async def me(current_user: UserOut = Depends(require_user)):
    return current_user
