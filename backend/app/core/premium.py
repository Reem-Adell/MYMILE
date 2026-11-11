"""
The ONE authoritative rule for whether a user currently has Premium.

Every place that needs a user's effective plan must call `effective_plan()`
(or `is_premium_active()`); do not re-implement the comparison elsewhere.

Rules:
  1. The designated demo account (DEMO_USER_ID) always has Premium.
  2. Everyone else is Premium only if ALL of these hold:
       - stored plan is 'premium'
       - premium_until is present and parseable
       - premium_until is strictly later than the current UTC time
  3. Anything else (expired, equal to now, missing, unparseable, or stored
     plan 'free') is 'free'. An empty premium_until never means "permanent"
     for anyone except the demo account.

Stored timestamps are ISO-8601 strings, written by the payment service as
UTC with an explicit offset (e.g. "2026-12-09T16:21:01+00:00"). A trailing
"Z" is accepted, and a value without an offset is read as UTC.

Nothing here writes to the database: expiry is evaluated when the user is
read, so no stored values change.
"""
from datetime import datetime, timezone
from typing import Optional

DEMO_USER_ID = "usr-demo-01"
PLAN_PREMIUM = "premium"
PLAN_FREE = "free"


def utc_now() -> datetime:
    """Current time, timezone-aware UTC. Tests patch this to freeze time."""
    return datetime.now(timezone.utc)


def parse_utc(value: Optional[str]) -> Optional[datetime]:
    """Parse a stored timestamp to an aware UTC datetime.

    Returns None if absent, malformed, or not representable in UTC (e.g. year
    9999 with a negative offset raises OverflowError on conversion). None means
    "no valid expiry", which the rules below treat as Free.
    """
    if not value or not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None


def is_premium_active(user_id: Optional[str], stored_plan: Optional[str],
                      premium_until: Optional[str], now: Optional[datetime] = None) -> bool:
    if user_id == DEMO_USER_ID:
        return True
    if (stored_plan or "").strip().lower() != PLAN_PREMIUM:
        return False
    until = parse_utc(premium_until)
    if until is None:
        return False
    current = now if now is not None else utc_now()
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return until > current


def effective_plan(user_id: Optional[str], stored_plan: Optional[str],
                   premium_until: Optional[str], now: Optional[datetime] = None) -> str:
    return PLAN_PREMIUM if is_premium_active(user_id, stored_plan, premium_until, now) else PLAN_FREE
