"""
SQLite connection + additive schema migrations.

Migrations here only ever ADD things (a nullable column, a new table, indexes),
so they are safe to run on every startup against an existing users.db: no
existing row or column is altered or dropped.

`MYMILE_DB_PATH` overrides the file location (used by the automated tests so
they never touch the real backend/data/users.db).
"""
import os
import sqlite3
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "users.db"
DB_PATH = Path(os.environ.get("MYMILE_DB_PATH") or DEFAULT_DB_PATH)


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    # timeout: wait for a competing writer instead of failing straight away.
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _column_names(conn: sqlite3.Connection, table: str) -> set:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def migrate(conn: sqlite3.Connection) -> None:
    """Bring an existing (or brand new) database up to the current schema."""
    # users.premium_until: ISO-8601 UTC timestamp when paid Premium ends.
    # NULL means "no paid pass". The demo account keeps plan='premium' with
    # premium_until NULL, i.e. it stays Premium exactly as before.
    if "premium_until" not in _column_names(conn, "users"):
        conn.execute("ALTER TABLE users ADD COLUMN premium_until TEXT")

    # One row per PayPal order this backend created. `order_id` is UNIQUE so
    # an order can only ever be recorded (and granted) once; `capture_id` is
    # UNIQUE so one PayPal capture can never grant Premium to two orders.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS payments (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id     TEXT NOT NULL UNIQUE,
            user_id      TEXT NOT NULL REFERENCES users(id),
            amount       TEXT NOT NULL,
            currency     TEXT NOT NULL,
            status       TEXT NOT NULL,
            capture_id   TEXT UNIQUE,
            created_at   TEXT NOT NULL,
            completed_at TEXT
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_payments_user_id ON payments(user_id)")

    # payments.last_capture_result: what the LAST capture request for this
    # order ended with, recorded the moment the answer (or failure) arrives:
    #   NULL              no recorded result (never sent, sent but the process
    #                     crashed before recording, or a retry is in flight)
    #   TRANSPORT_ERROR   timeout / connection failure: outcome unknown
    #   HTTP_5XX          PayPal server error: outcome unknown
    #   HTTP_2XX          PayPal answered the capture
    #   HTTP_<4xx>:<ISSUE> definite rejection (e.g. HTTP_422:COMPLIANCE_VIOLATION)
    # Only TRANSPORT_ERROR / HTTP_5XX ever allow a same-key capture retry.
    # Existing rows get NULL, i.e. read-only lookups only.
    if "last_capture_result" not in _column_names(conn, "payments"):
        conn.execute("ALTER TABLE payments ADD COLUMN last_capture_result TEXT")

    # At most one in-flight PayPal create-order attempt per user. The row is
    # written BEFORE calling PayPal and holds the PayPal-Request-Id, so a retry
    # after a lost response (timeout, crash) re-sends the SAME key and PayPal
    # returns the order it already created instead of making a new one. It is
    # deleted in the same transaction that records the order in `payments`.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS payment_create_attempts (
            user_id    TEXT PRIMARY KEY REFERENCES users(id),
            request_id TEXT NOT NULL UNIQUE,
            terms      TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
