import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status

from app.core.security import (
    create_access_token,
    decode_access_token,
    get_password_hash,
    verify_password,
)
from app.schemas.auth_schema import Token, UserLogin, UserOut, UserRegister

router = APIRouter(prefix="/auth", tags=["Authentication"])

# Users are stored in a small SQLite file so accounts survive server restarts.
DB_PATH = Path(__file__).resolve().parents[3] / "data" / "users.db"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD_LENGTH = 8


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


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


_init_db()


def _get_user_by_email(email: str) -> Optional[sqlite3.Row]:
    with _connect() as conn:
        return conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()


def _to_user_out(row: sqlite3.Row) -> UserOut:
    return UserOut(
        id=row["id"],
        name=row["name"],
        email=row["email"],
        plan=row["plan"],
        created_at=row["created_at"],
    )


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _user_from_token(authorization: Optional[str]) -> Optional[UserOut]:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    payload = decode_access_token(authorization.split(" ", 1)[1])
    if not payload or "sub" not in payload:
        raise HTTPException(status_code=401, detail="Invalid or expired session. Please log in again.")
    row = _get_user_by_email(payload["sub"])
    if not row:
        raise HTTPException(status_code=401, detail="Account no longer exists. Please log in again.")
    return _to_user_out(row)


def require_user(authorization: Optional[str] = Header(None)) -> UserOut:
    """Dependency for endpoints that need a logged-in user."""
    user = _user_from_token(authorization)
    if user is None:
        raise HTTPException(status_code=401, detail="Not logged in")
    return user


def get_current_user(authorization: Optional[str] = Header(None)) -> UserOut:
    """Logged-in user if a token is sent, otherwise the demo user (keeps guest demos working)."""
    user = _user_from_token(authorization)
    if user is not None:
        return user
    return _to_user_out(_get_user_by_email("alex@example.com"))


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
    return Token(access_token=create_access_token(subject=email), user=_to_user_out(row))


@router.post("/login", response_model=Token)
async def login(req: UserLogin):
    email = _normalize_email(req.email)
    row = _get_user_by_email(email)
    # Same message for unknown email and wrong password, so accounts can't be probed.
    if not row or not verify_password(req.password, row["hashed_password"]):
        raise HTTPException(status_code=401, detail="Incorrect email or password.")
    return Token(access_token=create_access_token(subject=email), user=_to_user_out(row))


@router.get("/me", response_model=UserOut)
async def me(current_user: UserOut = Depends(require_user)):
    return current_user
