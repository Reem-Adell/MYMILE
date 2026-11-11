"""
PayPal Premium pass: create order -> buyer approves in PayPal -> capture.

Business rules (backend-owned; nothing here is taken from the client):
  * Price, currency and duration come only from settings
    (PREMIUM_PRICE / PREMIUM_CURRENCY / PREMIUM_DURATION_DAYS).
  * One-time payment, no renewal.
  * Premium is granted ONLY after PayPal returns order status COMPLETED with a
    COMPLETED capture whose amount, currency and custom_id (our user id) match
    the payment row we stored when the order was created.
  * A payment row can move to COMPLETED exactly once (conditional UPDATE in a
    single transaction), so duplicate/concurrent captures cannot grant twice.
  * One PayPal-Request-Id per order (`mymile-capture-{order_id}`), never rotated.
  * A decline confirmed by the capture endpoint is FINAL for that order: it is
    never captured again. The buyer retries with a NEW order (new approval).
  * A PayPal order lookup (get_order) may only move a payment forward (towards
    evidence that money moved). It never downgrades an in-flight capture to a
    state that would allow a new order: a missing capture in a lookup is not
    proof that the capture was never processed.
  * Ambiguous or inconsistent PayPal data -> NEEDS_REVIEW: blocking, no grant,
    no further PayPal calls for that order.

Logging: only order ids, statuses and HTTP codes. Never tokens, credentials,
payer names/emails, or raw PayPal bodies.
"""
import json
import logging
import re
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from apimatic_core.exceptions.auth_validation_exception import AuthValidationException
from paypalserversdk.exceptions.api_exception import ApiException
from paypalserversdk.models.amount_with_breakdown import AmountWithBreakdown
from paypalserversdk.models.capture_status import CaptureStatus
from paypalserversdk.models.checkout_payment_intent import CheckoutPaymentIntent
from paypalserversdk.models.order_request import OrderRequest
from paypalserversdk.models.order_status import OrderStatus
from paypalserversdk.models.purchase_unit_request import PurchaseUnitRequest

from app.core import database, premium
from app.core.config import settings
from app.core.paypal_client import PayPalNotConfiguredError, get_paypal_client

log = logging.getLogger(__name__)

PREMIUM_REFERENCE_ID = "mymile-premium-pass"
ORDER_ID_RE = re.compile(r"^[A-Za-z0-9-]{1,64}$")
CENTS = Decimal("0.01")

# Local payment statuses
ST_CREATED = "CREATED"        # order created at PayPal, not captured yet
ST_COMPLETED = "COMPLETED"    # verified + Premium granted (terminal)
ST_PENDING = "PENDING"        # PayPal capture is PENDING (e.g. under review)
ST_DECLINED = "DECLINED"      # capture endpoint confirmed a decline; FINAL for this order
ST_UNCERTAIN = "UNCERTAIN"    # network/5xx during capture; outcome unknown
ST_REJECTED = "REJECTED"      # legacy: verification failed (now NEEDS_REVIEW); terminal
ST_EXPIRED = "EXPIRED"        # PayPal CONFIRMED the order no longer exists / was voided
ST_NEEDS_REVIEW = "NEEDS_REVIEW"  # ambiguous/inconsistent PayPal data: blocking, no grant
# Response-only status (never stored): another capture request for the same
# order is still running at PayPal; the caller should check again shortly.
ST_IN_PROGRESS = "IN_PROGRESS"

# Recovery / duplicate-order rules.
# BLOCKING: money may have moved -> no new order until this one is resolved.
#   (A capture attempt marks the order UNCERTAIN *before* calling PayPal, so a
#   crash mid-capture can never leave it looking like an untouched CREATED order.)
# RESUMABLE: provably not charged (approval alone never moves money; only a
#   capture does) -> the same order may be continued.
# DECLINED / EXPIRED / REJECTED are terminal for their order and do not block:
#   the buyer may start a NEW order.
BLOCKING_STATUSES = (ST_PENDING, ST_UNCERTAIN, ST_NEEDS_REVIEW)
RESUMABLE_STATUSES = (ST_CREATED,)
# Statuses in which a capture call may be (or may have been) in flight. Outcome
# writes are conditional on the row still being in one of these, so a late or
# concurrent answer can never overwrite a more advanced state.
IN_FLIGHT_STATUSES = (ST_UNCERTAIN, ST_PENDING)
# Terminal statuses: answered locally, PayPal is never called again.
TERMINAL_STATUSES = (ST_COMPLETED, ST_DECLINED, ST_EXPIRED, ST_REJECTED, ST_NEEDS_REVIEW)
REUSE_WINDOW = timedelta(minutes=30)
# PayPal answers that suggest the order is gone. Never trusted alone: expiry is
# only recorded after get_order CONFIRMS it (404 or VOIDED).
EXPIRY_HINT_ISSUES = ("RESOURCE_NOT_FOUND", "INVALID_RESOURCE_ID", "ORDER_EXPIRED")
# Capture-endpoint answers that are documented declines of THAT request (no
# capture happened). Any other 4xx stays inconclusive and is reconciled.
CAPTURE_DECLINE_ISSUES = ("INSTRUMENT_DECLINED", "TRANSACTION_REFUSED", "COMPLIANCE_VIOLATION")
# payments.last_capture_result values that prove the previous capture request
# ended with an UNKNOWN outcome. Only these allow a same-key capture retry.
# Anything else (NULL = nothing recorded, e.g. a crash before recording; or a
# definite HTTP 4xx such as HTTP_422:COMPLIANCE_VIOLATION) allows read-only
# lookups only, forever.
RETRYABLE_CAPTURE_RESULTS = ("TRANSPORT_ERROR", "HTTP_5XX")
# Even then, a status check re-sends at most once per this many seconds per order.
CAPTURE_RESEND_COOLDOWN_SECONDS = 15


# ------------------------------------------------------ response codes ---
# Machine-readable `code` on EVERY payment response (success and error). The
# frontend must branch on `code`, never on the HTTP status alone: e.g. 409 is
# used both for "not approved yet" (safe to continue in PayPal) and for
# conflicts that must stop the checkout.
CODE_COMPLETED = "PAYMENT_COMPLETED"
CODE_PENDING = "PAYMENT_PENDING"
CODE_UNCERTAIN = "PAYMENT_UNCERTAIN"
CODE_CAPTURE_IN_PROGRESS = "CAPTURE_IN_PROGRESS"
CODE_DECLINED = "PAYMENT_DECLINED"
CODE_NOT_APPROVED = "ORDER_NOT_APPROVED"         # 409: buyer has not approved yet; nothing charged
CODE_REJECTED = "PAYMENT_REJECTED"               # 409: verification failed; Premium not granted
CODE_CAPTURE_ID_CONFLICT = "CAPTURE_ID_CONFLICT"  # 409: PayPal capture id already used by another payment
CODE_NEEDS_REVIEW = "PAYMENT_NEEDS_REVIEW"       # 409: unverifiable result; blocked, contact support
CODE_EXPIRED = "ORDER_EXPIRED"
CODE_NOT_FOUND = "ORDER_NOT_FOUND"
CODE_UNRESOLVED = "UNRESOLVED_PAYMENT"           # 409 on create: resolve THIS order first
CODE_CREATE_IN_PROGRESS = "CREATE_IN_PROGRESS"   # 409 on create: another create is running
CODE_ALREADY_PROCESSED = "ORDER_ALREADY_PROCESSED"
CODE_CREATE_UNCONFIRMED = "CREATE_UNCONFIRMED"   # 502: PayPal may have created the order; retry is safe
CODE_PAYPAL_ERROR = "PAYPAL_ERROR"
CODE_UNAVAILABLE = "PAYMENTS_UNAVAILABLE"
CODE_PRICING = "PRICING_MISCONFIGURED"

_STATUS_CODES = {
    "COMPLETED": CODE_COMPLETED,
    "PENDING": CODE_PENDING,
    "UNCERTAIN": CODE_UNCERTAIN,
    "IN_PROGRESS": CODE_CAPTURE_IN_PROGRESS,
    "DECLINED": CODE_DECLINED,
    "CREATED": CODE_NOT_APPROVED,
    "REJECTED": CODE_REJECTED,
    "EXPIRED": CODE_EXPIRED,
    "NEEDS_REVIEW": CODE_NEEDS_REVIEW,
}


# ----------------------------------------------------------------- errors ---
class PaymentError(Exception):
    """Error with an HTTP status, a machine-readable code and a client-safe message."""

    def __init__(self, http_status: int, message: str, extra: Optional[dict] = None,
                 code: str = CODE_PAYPAL_ERROR):
        super().__init__(message)
        self.http_status = http_status
        self.message = message
        self.code = code
        self.extra = extra or {}  # client-safe fields (e.g. the blocking order_id)


@dataclass
class CaptureOutcome:
    http_status: int
    status: str
    message: str
    premium_until: Optional[str] = None
    already_processed: bool = False
    extra: dict = field(default_factory=dict)

    @property
    def code(self) -> str:
        return _STATUS_CODES[self.status]

    def as_dict(self, order_id: str) -> dict:
        body = {
            "order_id": order_id,
            "status": self.status,
            "code": self.code,
            "message": self.message,
            "premium_granted": self.status == ST_COMPLETED,
            "premium_until": self.premium_until,
            "already_processed": self.already_processed,
        }
        body.update(self.extra)
        return body


# --------------------------------------------------------------- helpers ---
def _now() -> datetime:
    # Same clock as the Premium status rule, so tests can freeze both at once.
    return premium.utc_now()


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _to_money(value: Any) -> Optional[Decimal]:
    try:
        return Decimal(str(value)).quantize(CENTS)
    except (InvalidOperation, TypeError, ValueError):
        return None


def premium_terms() -> dict:
    """The Premium offer, derived only from backend settings."""
    price = _to_money(settings.PREMIUM_PRICE)
    currency = (settings.PREMIUM_CURRENCY or "").strip().upper()
    days = settings.PREMIUM_DURATION_DAYS
    if price is None or price <= 0 or len(currency) != 3 or days <= 0:
        # Misconfiguration: refuse to sell rather than charge a wrong amount.
        raise PaymentError(503, "Premium pricing is not configured correctly.", code=CODE_PRICING)
    return {"price": format(price, "f"), "currency": currency, "duration_days": days}


def _paypal_client():
    try:
        return get_paypal_client()
    except PayPalNotConfiguredError:
        log.warning("PayPal payment requested but PayPal is not configured")
        raise PaymentError(503, "Payments are temporarily unavailable.", code=CODE_UNAVAILABLE)


def _error_issue(exc: ApiException) -> Optional[str]:
    """First `details[].issue` from a typed PayPal error, if any (no body logging)."""
    details = getattr(exc, "details", None) or []
    for d in details:
        issue = getattr(d, "issue", None)
        if issue:
            return issue
    return None


def _clip(value: Any, limit: int = 200) -> str:
    text = str(value)
    return text if len(text) <= limit else text[:limit] + "..."


def describe_paypal_error(exc: ApiException) -> dict:
    """Client-safe summary of a PayPal error response for logs and support.

    Contains only PayPal's own error fields (name, message, debug_id, every
    details[] entry: issue, description, field, value, location) plus the HTTP
    status. Never request headers, tokens, credentials or payer data: those are
    not part of PayPal's error body and are not read here.
    """
    info: dict = {"http": getattr(exc, "response_code", None)}
    for key in ("name", "message", "debug_id"):
        value = getattr(exc, key, None)
        if value:
            info[key] = _clip(value)
    if "debug_id" not in info:  # also sent as a response header
        headers = getattr(getattr(exc, "response", None), "headers", None) or {}
        for header, value in dict(headers).items():
            if str(header).lower() == "paypal-debug-id" and value:
                info["debug_id"] = _clip(value, 64)
    details = []
    for d in getattr(exc, "details", None) or []:
        entry = {}
        for key in ("issue", "description", "field", "value", "location"):
            value = getattr(d, key, None)
            if value not in (None, ""):
                entry[key] = _clip(value, 100 if key == "value" else 200)
        if entry:
            details.append(entry)
    info["details"] = details
    return info


def _log_paypal_error(operation: str, order_id: Optional[str], exc: ApiException) -> None:
    log.warning("PayPal %s error: order_id=%s paypal_error=%s",
                operation, order_id, json.dumps(describe_paypal_error(exc), sort_keys=True))


def _get_payment(conn: sqlite3.Connection, order_id: str) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM payments WHERE order_id = ?", (order_id,)).fetchone()


def _placeholders(values: tuple) -> str:
    return ", ".join("?" for _ in values)


def _set_status(order_id: str, user_id: str, status: str,
                from_statuses: tuple = IN_FLIGHT_STATUSES) -> bool:
    """Conditional transition: only applies while the row is still in one of
    `from_statuses`, so a late/concurrent answer never overwrites a more
    advanced state (COMPLETED, DECLINED, NEEDS_REVIEW, ...). Returns True if applied."""
    with database.connect() as conn:
        cur = conn.execute(
            f"UPDATE payments SET status = ? WHERE order_id = ? AND user_id = ? "
            f"AND status IN ({_placeholders(from_statuses)})",
            (status, order_id, user_id, *from_statuses),
        )
        return cur.rowcount == 1


def _mark_capture_attempt(order_id: str, user_id: str) -> bool:
    """First capture: CREATED -> UNCERTAIN (no recorded result) just before the
    call. Atomic: of several simultaneous requests only one wins. True if marked."""
    with database.connect() as conn:
        cur = conn.execute(
            "UPDATE payments SET status = ?, last_capture_result = NULL "
            "WHERE order_id = ? AND user_id = ? AND status = ?",
            (ST_UNCERTAIN, order_id, user_id, ST_CREATED))
        return cur.rowcount == 1


def _claim_capture_retry(order_id: str, user_id: str) -> bool:
    """Retry: allowed ONLY for an UNCERTAIN row whose last capture result is
    recorded as retryable (TRANSPORT_ERROR / HTTP_5XX). Atomically clears the
    result, so (a) only one request can claim the retry, and (b) a crash after
    this point leaves NULL = "nothing recorded" -> read-only lookups only."""
    with database.connect() as conn:
        cur = conn.execute(
            f"UPDATE payments SET last_capture_result = NULL "
            f"WHERE order_id = ? AND user_id = ? AND status = ? "
            f"AND last_capture_result IN ({_placeholders(RETRYABLE_CAPTURE_RESULTS)})",
            (order_id, user_id, ST_UNCERTAIN, *RETRYABLE_CAPTURE_RESULTS))
        return cur.rowcount == 1


def _record_capture_result(order_id: str, user_id: str, result: str) -> None:
    """Persist how the capture request ended, as soon as the answer arrives."""
    with database.connect() as conn:
        conn.execute("UPDATE payments SET last_capture_result = ? WHERE order_id = ? AND user_id = ?",
                     (result, order_id, user_id))


def _recorded_decline_issue(payment: sqlite3.Row) -> Optional[str]:
    """The decline issue if last_capture_result records a definite capture-endpoint
    decline (HTTP_4xx:<ISSUE in CAPTURE_DECLINE_ISSUES>), else None."""
    result = payment["last_capture_result"] or ""
    head, _, issue = result.partition(":")
    if head.startswith("HTTP_4") and issue in CAPTURE_DECLINE_ISSUES:
        return issue
    return None


def _finish_recorded_decline(order_id: str, user_id: str, payment: sqlite3.Row) -> Optional[CaptureOutcome]:
    """A crash after RECORDING a definite decline but before storing DECLINED:
    the recorded answer already proves it, so finish the transition locally
    (no PayPal call). Returns None if there is no such recorded decline."""
    issue = _recorded_decline_issue(payment)
    if issue is None or payment["status"] != ST_UNCERTAIN:
        return None
    if _set_status(order_id, user_id, ST_DECLINED, from_statuses=(ST_UNCERTAIN,)):
        log.info("Recorded %s decline finalized locally: order_id=%s", issue, order_id)
        outcome = _current_outcome(order_id, user_id)
        outcome.extra["decline_issue"] = issue
        return outcome
    return _current_outcome(order_id, user_id)


def _restore_unsent(order_id: str, user_id: str, status: str, result: Optional[str]) -> None:
    """Undo the mark/claim for a request that provably was NOT sent."""
    with database.connect() as conn:
        conn.execute(
            "UPDATE payments SET status = ?, last_capture_result = ? WHERE order_id = ? AND user_id = ? "
            "AND status = ? AND last_capture_result IS NULL",
            (status, result, order_id, user_id, ST_UNCERTAIN))


def _is_recent(created_at: Optional[str]) -> bool:
    created = premium.parse_utc(created_at)
    return created is not None and _now() - created < REUSE_WINDOW


def _public_order(row: sqlite3.Row) -> dict:
    """Client-safe view of a payment row (no capture id, no PayPal payloads)."""
    status = row["status"]
    return {
        "order_id": row["order_id"],
        "status": status,
        "amount": row["amount"],
        "currency": row["currency"],
        "created_at": row["created_at"],
        "completed_at": row["completed_at"],
        # Must be resolved (retry capture on this SAME order) before any new purchase.
        "blocking": status in BLOCKING_STATUSES,
        # Not charged and recent: the same order can be continued in PayPal.
        "resumable": status in RESUMABLE_STATUSES and _is_recent(row["created_at"]),
    }


def get_order_status(user_id: str, order_id: str) -> dict:
    """Owner-only, local status of one order. Never calls PayPal."""
    if not ORDER_ID_RE.match(order_id or ""):
        raise PaymentError(404, "Order not found.", code=CODE_NOT_FOUND)
    with database.connect() as conn:
        row = _get_payment(conn, order_id)
    if row is None or row["user_id"] != user_id:
        raise PaymentError(404, "Order not found.", code=CODE_NOT_FOUND)  # same answer for "not yours"
    data = _public_order(row)
    data["premium_until"] = get_premium_until(user_id) if row["status"] == ST_COMPLETED else None
    return data


def _find_unresolved(conn: sqlite3.Connection, user_id: str) -> Optional[sqlite3.Row]:
    """Newest BLOCKING order, else the newest recent RESUMABLE order, else None."""
    row = conn.execute(
        f"SELECT * FROM payments WHERE user_id = ? AND status IN ({_placeholders(BLOCKING_STATUSES)}) "
        "ORDER BY id DESC LIMIT 1",
        (user_id, *BLOCKING_STATUSES),
    ).fetchone()
    if row is not None:
        return row
    row = conn.execute(
        f"SELECT * FROM payments WHERE user_id = ? AND status IN ({_placeholders(RESUMABLE_STATUSES)}) "
        "ORDER BY id DESC LIMIT 1",
        (user_id, *RESUMABLE_STATUSES),
    ).fetchone()
    return row if row is not None and _is_recent(row["created_at"]) else None


def get_unresolved_order(user_id: str) -> dict:
    with database.connect() as conn:
        row = _find_unresolved(conn, user_id)
    return {"order": _public_order(row) if row is not None else None}


def get_premium_until(user_id: str) -> Optional[str]:
    with database.connect() as conn:
        row = conn.execute("SELECT premium_until FROM users WHERE id = ?", (user_id,)).fetchone()
    return row["premium_until"] if row else None


# ----------------------------------------------------------- create order ---
# Duplicate-order protection has three layers:
#
# 1. Per-user threading lock (below) around "check -> create at PayPal ->
#    store". Two simultaneous requests for one user in THIS process are
#    serialized; the second then reuses the first one's CREATED row.
#    SCOPE: PROCESS-LOCAL. It does not coordinate several worker processes
#    (`uvicorn --workers N`) or hosts. The supported deployment
#    (start-backend.bat / README: one `uvicorn --reload` process) is single
#    process, so this lock is sufficient there.
#
# 2. Database reservation (`payment_create_attempts`, BEGIN IMMEDIATE): the
#    "is there already an order?" check and the reservation of a create attempt
#    happen in one SQLite write transaction, and the order is recorded + the
#    attempt removed in another. Combined with (3) this also covers several
#    processes sharing the SAME SQLite file. It does not help across hosts
#    (SQLite cannot be shared that way).
#
# 3. PayPal-Request-Id idempotency on create-order. The attempt row (with its
#    request id) is committed BEFORE PayPal is called. If PayPal creates the
#    order but the response is lost (timeout, connection reset, crash before we
#    store the order id), the next create for this user re-sends the SAME
#    request id and PayPal answers with the order it already created (HTTP 200)
#    instead of creating another. PayPal keeps request ids for 6 hours; we
#    reuse a key only for CREATE_KEY_WINDOW (30 min) and only for identical
#    terms, because the request body must be identical for a replay.
#    LIMITATION: if the user does not retry within that window, the lost order
#    is left orphaned at PayPal. It cannot be charged: nobody ever received
#    its id, so nobody can approve it, and PayPal lets it expire.
CREATE_KEY_WINDOW = REUSE_WINDOW
_create_locks: dict = {}               # user_id -> [threading.Lock, active users]
_create_locks_guard = threading.Lock()


@contextmanager
def _user_create_lock(user_id: str):
    with _create_locks_guard:
        entry = _create_locks.setdefault(user_id, [threading.Lock(), 0])
        entry[1] += 1
    try:
        # Bounded wait: the holder is at most one PayPal call (client timeout).
        if not entry[0].acquire(timeout=settings.PAYPAL_TIMEOUT_SECONDS + 15):
            raise PaymentError(409, "A payment is already being started for your account. "
                                    "Please wait a moment and try again; do not pay twice.",
                               code=CODE_CREATE_IN_PROGRESS)
        try:
            yield
        finally:
            entry[0].release()
    finally:
        with _create_locks_guard:
            entry[1] -= 1
            if entry[1] == 0:
                _create_locks.pop(user_id, None)  # no per-user lock leak


@contextmanager
def _write_txn():
    """One SQLite write transaction (BEGIN IMMEDIATE: writers are serialized,
    across processes too). Commits on success, rolls back on any exception."""
    conn = database.connect()
    try:
        conn.isolation_level = None
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def _terms_key(terms: dict) -> str:
    return f"{terms['price']}|{terms['currency']}|{terms['duration_days']}"


def _order_response(order_id: str, status: str, amount: str, currency: str, terms: dict,
                    reused: bool, approve_url: Optional[str] = None) -> dict:
    return {
        "order_id": order_id,
        "status": status,
        "code": "ORDER_REUSED" if reused else "ORDER_CREATED",
        "approve_url": approve_url,
        "amount": amount,
        "currency": currency,
        "duration_days": terms["duration_days"],
        "one_time": True,
        "reused": reused,
    }


def _blocking_error(row: sqlite3.Row) -> PaymentError:
    # A previous payment might have succeeded: never start a replacement.
    return PaymentError(
        409, "You have a payment that is still being confirmed. Please finish confirming it; do not pay again.",
        extra={"order_id": row["order_id"], "status": row["status"]}, code=CODE_UNRESOLVED)


def _reserve_creation(user_id: str, terms: dict) -> tuple:
    """Atomically decide what a create request does.

    Returns ("reuse", payment_row) or ("create", (request_id, created_at)).
    Raises the 409 UNRESOLVED_PAYMENT error when a blocking order exists.
    """
    with _write_txn() as conn:
        existing = _find_unresolved(conn, user_id)
        if existing is not None and existing["status"] in BLOCKING_STATUSES:
            raise _blocking_error(existing)
        if (existing is not None and existing["status"] == ST_CREATED
                and existing["amount"] == terms["price"] and existing["currency"] == terms["currency"]):
            return "reuse", existing  # recent, uncharged, same terms (popup closed, second tab)

        attempt = conn.execute(
            "SELECT request_id, terms, created_at FROM payment_create_attempts WHERE user_id = ?",
            (user_id,)).fetchone()
        if attempt is not None and attempt["terms"] == _terms_key(terms):
            created = premium.parse_utc(attempt["created_at"])
            if created is not None and _now() - created < CREATE_KEY_WINDOW:
                # An earlier create's outcome is unknown: re-send the SAME key so
                # PayPal returns that order instead of creating another.
                log.info("Retrying an unconfirmed PayPal order creation with the same request id")
                return "create", (attempt["request_id"], attempt["created_at"])
        request_id = f"mymile-create-{uuid.uuid4().hex}"
        created_at = _iso(_now())
        conn.execute(
            "INSERT OR REPLACE INTO payment_create_attempts (user_id, request_id, terms, created_at) "
            "VALUES (?, ?, ?, ?)",
            (user_id, request_id, _terms_key(terms), created_at))
        return "create", (request_id, created_at)


def _clear_create_attempt(user_id: str, request_id: str) -> None:
    """Forget a create attempt that PayPal DEFINITELY did not turn into an order."""
    with database.connect() as conn:
        conn.execute("DELETE FROM payment_create_attempts WHERE user_id = ? AND request_id = ?",
                     (user_id, request_id))


def _record_created_order(user_id: str, order_id: str, terms: dict, request_id: str,
                          created_at: str) -> Optional[sqlite3.Row]:
    """Store the PayPal order and drop the attempt, in one transaction.

    Returns None when newly recorded, or the existing row when this order was
    already recorded (a replayed response another request stored first).
    """
    with _write_txn() as conn:
        row = _get_payment(conn, order_id)
        if row is None:
            # created_at = when the attempt started, i.e. no later than PayPal's
            # own creation time, so the 30-minute reuse window stays conservative.
            conn.execute(
                "INSERT INTO payments (order_id, user_id, amount, currency, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (order_id, user_id, terms["price"], terms["currency"], ST_CREATED, created_at),
            )
        elif row["user_id"] != user_id:
            log.error("PayPal create_order returned an order id owned by another user: order_id=%s", order_id)
            raise PaymentError(502, "PayPal returned an unexpected response. Please try again.")
        conn.execute("DELETE FROM payment_create_attempts WHERE user_id = ? AND request_id = ?",
                     (user_id, request_id))
        return row


def create_premium_order(user_id: str) -> dict:
    terms = premium_terms()
    with _user_create_lock(user_id):
        return _create_premium_order_locked(user_id, terms)


def _create_premium_order_locked(user_id: str, terms: dict) -> dict:
    action, value = _reserve_creation(user_id, terms)
    if action == "reuse":
        log.info("Reusing PayPal order: order_id=%s", value["order_id"])
        return _order_response(value["order_id"], ST_CREATED, value["amount"], value["currency"],
                               terms, reused=True)
    request_id, created_at = value

    try:
        client = _paypal_client()
    except PaymentError:
        _clear_create_attempt(user_id, request_id)  # nothing was sent to PayPal
        raise

    body = OrderRequest(
        intent=CheckoutPaymentIntent.CAPTURE,
        purchase_units=[
            PurchaseUnitRequest(
                amount=AmountWithBreakdown(currency_code=terms["currency"], value=terms["price"]),
                reference_id=PREMIUM_REFERENCE_ID,
                custom_id=user_id,  # echoed back by PayPal; checked again at capture
                description=f"MYMILE Premium pass - {terms['duration_days']} days (one-time, no renewal)",
            )
        ],
    )

    try:
        result = client.orders.create_order({
            "body": body,
            "paypal_request_id": request_id,  # stable for this logical attempt (see above)
            "prefer": "return=minimal",
        })
    except ApiException as exc:
        issue = _error_issue(exc)
        code = exc.response_code
        log.warning("PayPal create_order failed: http=%s issue=%s", code, issue)
        _log_paypal_error("create_order", None, exc)
        if issue == "PREVIOUS_REQUEST_IN_PROGRESS":
            # Same request id still being processed by PayPal: keep the attempt.
            raise PaymentError(409, "A payment is already being started for your account. "
                                    "Please wait a moment and try again; do not pay twice.",
                               code=CODE_CREATE_IN_PROGRESS)
        if code is not None and 400 <= code < 500:
            # Definitive refusal: PayPal created nothing, so a fresh key is fine next time.
            _clear_create_attempt(user_id, request_id)
            raise PaymentError(502, "Could not start the PayPal payment. Please try again.")
        # 5xx: PayPal may or may not have created the order. Keep the key.
        raise PaymentError(502, "Could not confirm with PayPal whether the checkout started. "
                                "Please try again; you have not been charged.", code=CODE_CREATE_UNCONFIRMED)
    except AuthValidationException:
        # Raised before the request is sent: nothing was created.
        _clear_create_attempt(user_id, request_id)
        log.error("PayPal create_order: authentication with PayPal failed")
        raise PaymentError(503, "Payments are temporarily unavailable.", code=CODE_UNAVAILABLE)
    except Exception as exc:
        # Network / timeout: PayPal may have created the order and the response
        # was lost. Keep the attempt so a retry re-sends the same request id.
        log.warning("PayPal create_order transport error: %s", type(exc).__name__)
        raise PaymentError(502, "Could not confirm with PayPal whether the checkout started. "
                                "Please try again; you have not been charged.", code=CODE_CREATE_UNCONFIRMED)

    order = result.body
    order_id = getattr(order, "id", None)
    order_status = getattr(order, "status", None)
    if not order_id or not ORDER_ID_RE.match(order_id) or order_status not in (
        OrderStatus.CREATED, OrderStatus.PAYER_ACTION_REQUIRED
    ):
        log.warning("PayPal create_order returned unexpected status=%s", order_status)
        raise PaymentError(502, "PayPal returned an unexpected response. Please try again.")

    existing = _record_created_order(user_id, order_id, terms, request_id, created_at)
    if existing is not None:
        # Another request already stored this (replayed) order.
        if existing["status"] in BLOCKING_STATUSES:
            raise _blocking_error(existing)
        if existing["status"] != ST_CREATED:
            raise PaymentError(409, "This checkout was already processed. Please reload your payment status.",
                               extra={"order_id": order_id, "status": existing["status"]},
                               code=CODE_ALREADY_PROCESSED)
        return _order_response(order_id, ST_CREATED, existing["amount"], existing["currency"],
                               terms, reused=True)
    log.info("PayPal order created: order_id=%s", order_id)

    approve_url = None
    for link in getattr(order, "links", None) or []:
        if getattr(link, "rel", None) in ("approve", "payer-action"):
            approve_url = getattr(link, "href", None)
            break

    return _order_response(order_id, order_status, terms["price"], terms["currency"], terms,
                           reused=False, approve_url=approve_url)


# ---------------------------------------------------------- capture order ---
def _verify(order: Any, order_id: str, payment: sqlite3.Row) -> tuple:
    """
    Inspect a PayPal order (from the capture response or from get_order).
    Returns (local_status, capture_id_or_None, reason). Only ST_COMPLETED means
    "safe to grant". Anything inconsistent, or a possible payment that cannot be
    fully verified, is ST_NEEDS_REVIEW (blocking, never granted).

    Rules:
      * order id, exactly one purchase unit, unit custom_id == our user id,
        unit reference_id / amount (when present) == what we created;
      * every capture: non-empty unique id, currency == stored currency,
        custom_id (when present) == our user id;
      * captures are classified by status: exactly one COMPLETED (any number
        of DECLINED/FAILED alongside) -> verify it and grant; two COMPLETED,
        COMPLETED+PENDING, several PENDING, refunds or unknown statuses ->
        NEEDS_REVIEW.
    """
    if getattr(order, "id", None) != order_id:
        return ST_NEEDS_REVIEW, None, "order id mismatch"

    units = getattr(order, "purchase_units", None) or []
    if len(units) != 1:
        return ST_NEEDS_REVIEW, None, "unexpected purchase units"
    unit = units[0]
    if getattr(unit, "custom_id", None) != payment["user_id"]:
        return ST_NEEDS_REVIEW, None, "order belongs to a different user"
    reference_id = getattr(unit, "reference_id", None)
    if reference_id is not None and reference_id != PREMIUM_REFERENCE_ID:
        return ST_NEEDS_REVIEW, None, "unexpected purchase unit"
    unit_amount = getattr(unit, "amount", None)
    if unit_amount is not None:
        if _to_money(getattr(unit_amount, "value", None)) != _to_money(payment["amount"]):
            return ST_NEEDS_REVIEW, None, "amount mismatch"
        if (getattr(unit_amount, "currency_code", None) or "").upper() != payment["currency"]:
            return ST_NEEDS_REVIEW, None, "currency mismatch"

    payments_obj = getattr(unit, "payments", None)
    captures = (getattr(payments_obj, "captures", None) or []) if payments_obj is not None else []
    order_status = getattr(order, "status", None)

    if not captures:
        if order_status == OrderStatus.COMPLETED:
            return ST_NEEDS_REVIEW, None, "completed order without capture"
        if order_status in (OrderStatus.CREATED, OrderStatus.SAVED, OrderStatus.PAYER_ACTION_REQUIRED):
            return ST_CREATED, None, f"order not approved ({order_status})"
        if order_status == OrderStatus.VOIDED:
            return ST_EXPIRED, None, "order voided"
        return ST_UNCERTAIN, None, f"order status {order_status}"  # e.g. APPROVED: retry capture

    completed, pending, failed, other = [], [], [], []
    seen_ids = set()
    for capture in captures:
        capture_id = getattr(capture, "id", None)
        if not capture_id or capture_id in seen_ids:
            return ST_NEEDS_REVIEW, None, "missing or duplicate capture id"
        seen_ids.add(capture_id)
        amount = getattr(capture, "amount", None)
        if (getattr(amount, "currency_code", None) or "").upper() != payment["currency"]:
            return ST_NEEDS_REVIEW, None, "currency mismatch"
        capture_custom_id = getattr(capture, "custom_id", None)
        if capture_custom_id is not None and capture_custom_id != payment["user_id"]:
            return ST_NEEDS_REVIEW, None, "capture belongs to a different user"
        status = getattr(capture, "status", None)
        if status == CaptureStatus.COMPLETED:
            completed.append(capture)
        elif status == CaptureStatus.PENDING:
            pending.append(capture)
        elif status in (CaptureStatus.DECLINED, CaptureStatus.FAILED):
            failed.append(capture)
        else:
            other.append(capture)  # REFUNDED, PARTIALLY_REFUNDED, unknown

    if other:
        return ST_NEEDS_REVIEW, None, "refunded or unknown capture status"
    if len(completed) > 1:
        return ST_NEEDS_REVIEW, None, "more than one completed capture"
    if completed and pending:
        return ST_NEEDS_REVIEW, None, "completed and pending captures"
    if len(pending) > 1:
        return ST_NEEDS_REVIEW, None, "more than one pending capture"
    if pending:
        return ST_PENDING, None, "capture pending"
    if not completed:
        return ST_DECLINED, None, "capture declined/failed"

    capture = completed[0]
    if order_status != OrderStatus.COMPLETED:
        return ST_NEEDS_REVIEW, None, f"completed capture but order {order_status}"
    paid_value = _to_money(getattr(getattr(capture, "amount", None), "value", None))
    if paid_value is None or paid_value != _to_money(payment["amount"]):
        return ST_NEEDS_REVIEW, None, "amount mismatch"
    # final_capture is not checked: the SDK maps both "absent" and false to
    # False (CapturedPayment.from_dictionary), so it cannot be relied on.
    return ST_COMPLETED, getattr(capture, "id"), "verified"


def _grant(order_id: str, user_id: str, capture_id: str) -> tuple:
    """
    Atomically mark the payment COMPLETED and extend Premium.
    Returns (premium_until, granted_now). Safe under concurrent calls.
    """
    conn = database.connect()
    try:
        conn.isolation_level = None
        conn.execute("BEGIN IMMEDIATE")  # serialize writers
        now = _now()
        try:
            cur = conn.execute(
                "UPDATE payments SET status = ?, capture_id = ?, completed_at = ? "
                "WHERE order_id = ? AND user_id = ? AND status != ?",
                (ST_COMPLETED, capture_id, _iso(now), order_id, user_id, ST_COMPLETED),
            )
        except sqlite3.IntegrityError:
            # capture_id already used by another payment row: never grant twice.
            conn.execute("ROLLBACK")
            log.error("Capture id reused across orders; refusing grant for order_id=%s", order_id)
            # Block the order for manual review: no replacement order, and no
            # further PayPal calls for it (NEEDS_REVIEW is terminal + blocking).
            conn.execute(
                "UPDATE payments SET status = ? WHERE order_id = ? AND user_id = ? AND status != ?",
                (ST_NEEDS_REVIEW, order_id, user_id, ST_COMPLETED))
            raise PaymentError(409, "This payment could not be verified because its PayPal capture is "
                                    "already linked to another payment. Premium was not activated. "
                                    "Please do not pay again; contact support with your order reference.",
                               code=CODE_CAPTURE_ID_CONFLICT)

        user = conn.execute("SELECT plan, premium_until FROM users WHERE id = ?", (user_id,)).fetchone()
        if cur.rowcount != 1:
            conn.execute("COMMIT")
            return (user["premium_until"] if user else None), False

        if user_id == premium.DEMO_USER_ID:
            # Only the designated demo account has permanent Premium: record the
            # payment but leave its (open-ended) expiry exactly as it is.
            new_until = None
        else:
            # Renewal stacks only on Premium that is ACTIVE right now (per the
            # single authoritative rule). Expired, missing, unparseable, or a
            # stored plan of 'free' all start the new period from now.
            active = user is not None and premium.is_premium_active(
                user_id, user["plan"], user["premium_until"], now)
            start = premium.parse_utc(user["premium_until"]) if active else now
            try:
                new_until = _iso(start + timedelta(days=settings.PREMIUM_DURATION_DAYS))
            except OverflowError:
                # Existing expiry too close to datetime.max to extend (only
                # possible via manual DB edits): treat it as invalid and start
                # the new period from now instead of failing the grant.
                new_until = _iso(now + timedelta(days=settings.PREMIUM_DURATION_DAYS))
        conn.execute(
            "UPDATE users SET plan = 'premium', premium_until = COALESCE(?, premium_until) WHERE id = ?",
            (new_until, user_id),
        )
        conn.execute("COMMIT")
        return new_until, True
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def _expired_outcome() -> CaptureOutcome:
    return CaptureOutcome(410, ST_EXPIRED,
                          "This PayPal order has expired and was not charged. Please start a new payment.")


def _outcome_for_status(status: str, user_id: str) -> CaptureOutcome:
    """Client answer for a payment in `status` (no PayPal call, no write)."""
    if status == ST_COMPLETED:
        return CaptureOutcome(200, ST_COMPLETED, "Payment was already confirmed.",
                              premium_until=get_premium_until(user_id), already_processed=True)
    if status == ST_PENDING:
        return CaptureOutcome(202, ST_PENDING,
                              "PayPal is still processing this payment. Premium will activate once it completes. "
                              "Please do not pay again.")
    if status == ST_DECLINED:
        # Final for this order: the buyer retries with a NEW order (new approval).
        return CaptureOutcome(402, ST_DECLINED,
                              "The payment was declined, so you have not been charged. To try again, "
                              "start a new checkout and choose another payment method.",
                              extra={"next_step": "new_order"})
    if status == ST_CREATED:
        return CaptureOutcome(409, ST_CREATED,
                              "The order has not been approved in PayPal yet. You have not been charged.")
    if status == ST_EXPIRED:
        return _expired_outcome()
    if status == ST_NEEDS_REVIEW:
        return CaptureOutcome(409, ST_NEEDS_REVIEW,
                              "We could not automatically verify this payment, so Premium was not activated. "
                              "Please do not pay again; contact support with your order reference.")
    if status == ST_REJECTED:
        return CaptureOutcome(409, ST_REJECTED, "The payment could not be verified. Premium was not activated.")
    return CaptureOutcome(202, ST_UNCERTAIN,
                          "We could not confirm the payment yet. Please do not pay again; try confirming shortly.",
                          extra={"retryable": True})


def _current_outcome(order_id: str, user_id: str) -> CaptureOutcome:
    """Answer from the row's CURRENT stored status (it may have been advanced
    by a concurrent request in the meantime)."""
    with database.connect() as conn:
        row = _get_payment(conn, order_id)
    return _outcome_for_status(row["status"] if row is not None else ST_UNCERTAIN, user_id)


def _outcome_for(order: Any, order_id: str, payment: sqlite3.Row, user_id: str,
                 source: str = "capture") -> CaptureOutcome:
    """Apply a PayPal order representation.

    source="capture": the capture endpoint's own response for our request.
    source="lookup":  a get_order lookup. It can be stale and only ever moves a
    payment FORWARD: a missing capture is never proof that our capture was not
    processed, so it cannot produce CREATED, and a decline seen in a lookup is
    only accepted for a capture we already knew existed (row was PENDING).
    """
    status, capture_id, reason = _verify(order, order_id, payment)
    if status == ST_COMPLETED:
        premium_until, granted_now = _grant(order_id, user_id, capture_id)
        log.info("Premium %s for order_id=%s", "granted" if granted_now else "already granted", order_id)
        return CaptureOutcome(
            200, ST_COMPLETED,
            "Payment confirmed. Premium is active." if granted_now else "Payment was already confirmed.",
            premium_until=premium_until, already_processed=not granted_now,
        )

    if source == "lookup":
        if status == ST_CREATED:
            status = ST_UNCERTAIN
        elif status == ST_DECLINED and payment["status"] != ST_PENDING:
            status = ST_UNCERTAIN

    if status != ST_UNCERTAIN:  # UNCERTAIN: leave the row as it is (UNCERTAIN or PENDING)
        # CREATED / EXPIRED are only possible from UNCERTAIN (never "un-pend" a capture).
        allowed = (ST_UNCERTAIN,) if status in (ST_CREATED, ST_EXPIRED) else IN_FLIGHT_STATUSES
        if not _set_status(order_id, user_id, status, from_statuses=allowed):
            log.info("Payment state already advanced; not overwritten: order_id=%s", order_id)
    log.warning("PayPal capture not granted: order_id=%s status=%s reason=%s source=%s",
                order_id, status, reason, source)
    return _current_outcome(order_id, user_id)


def _reconcile(client: Any, order_id: str, payment: sqlite3.Row, user_id: str,
               missing_means_expired: bool = False) -> CaptureOutcome:
    """Look the order up at PayPal to resolve an unknown capture outcome.

    Expiry is recorded ONLY when PayPal confirms it: get_order says 404 (and the
    capture already hinted the order is gone) or the order is VOIDED. A failed
    lookup changes nothing: the payment stays UNCERTAIN (or PENDING), blocking.
    """
    try:
        result = client.orders.get_order({"id": order_id})
    except ApiException as exc:
        if missing_means_expired and exc.response_code == 404:
            if _set_status(order_id, user_id, ST_EXPIRED, from_statuses=(ST_UNCERTAIN,)):
                log.warning("PayPal order confirmed expired/missing: order_id=%s", order_id)
            return _current_outcome(order_id, user_id)
        log.warning("PayPal get_order failed while reconciling order_id=%s: http=%s", order_id, exc.response_code)
        _log_paypal_error("get_order", order_id, exc)
        return _current_outcome(order_id, user_id)
    except Exception as exc:
        log.warning("PayPal get_order failed while reconciling order_id=%s: %s",
                    order_id, getattr(exc, "response_code", type(exc).__name__))
        return _current_outcome(order_id, user_id)
    return _outcome_for(result.body, order_id, payment, user_id, source="lookup")


def capture_premium_order(user_id: str, order_id: str) -> CaptureOutcome:
    if not ORDER_ID_RE.match(order_id or ""):
        raise PaymentError(404, "Order not found.", code=CODE_NOT_FOUND)

    with database.connect() as conn:
        payment = _get_payment(conn, order_id)
    # Unknown order and someone else's order look identical to the caller.
    if payment is None or payment["user_id"] != user_id:
        raise PaymentError(404, "Order not found.", code=CODE_NOT_FOUND)

    if payment["status"] in TERMINAL_STATUSES:
        # COMPLETED / DECLINED (final) / EXPIRED / NEEDS_REVIEW / REJECTED:
        # answered locally, PayPal is never called again for this order.
        return _outcome_for_status(payment["status"], user_id)

    finished = _finish_recorded_decline(order_id, user_id, payment)
    if finished is not None:
        return finished

    client = _paypal_client()
    # Decide whether a capture request may be sent at all. Crash safety: the row
    # says UNCERTAIN with NO recorded result before the request leaves, so a
    # crash at any later point allows read-only lookups only.
    if payment["status"] == ST_CREATED:
        if not _mark_capture_attempt(order_id, user_id):
            # Another request started capturing this order a moment ago.
            with database.connect() as conn:
                current = _get_payment(conn, order_id)
            if current is not None and current["status"] in TERMINAL_STATUSES:
                return _outcome_for_status(current["status"], user_id)
            return CaptureOutcome(202, ST_IN_PROGRESS,
                                  "This payment is already being confirmed. Please wait a few seconds. "
                                  "Do not pay again.", extra={"retryable": True})
        restore = (ST_CREATED, None)
    elif _claim_capture_retry(order_id, user_id):
        previous = payment["last_capture_result"]
        restore = (ST_UNCERTAIN, previous if previous in RETRYABLE_CAPTURE_RESULTS else "TRANSPORT_ERROR")
        log.info("Retrying capture after a recorded unknown outcome (same PayPal-Request-Id): order_id=%s",
                 order_id)
    else:
        # UNCERTAIN without a recorded retryable result (a definite 4xx such as
        # COMPLIANCE_VIOLATION, nothing recorded, or a retry already in flight),
        # or PENDING: never capture again; read-only lookup only.
        log.info("No capture re-send (last result %s, status %s); read-only lookup: order_id=%s",
                 payment["last_capture_result"], payment["status"], order_id)
        return _reconcile(client, order_id, payment, user_id)
    _note_capture_sent(order_id)
    try:
        # Same PayPal-Request-Id for every attempt on this order (never rotated):
        # PayPal returns the latest status of that request instead of capturing twice.
        result = client.orders.capture_order({
            "id": order_id,
            "paypal_request_id": f"mymile-capture-{order_id}",
            "prefer": "return=representation",
        })
    except ApiException as exc:
        issue = _error_issue(exc)
        code = exc.response_code
        log.warning("PayPal capture_order error: order_id=%s http=%s issue=%s", order_id, code, issue)
        _log_paypal_error("capture_order", order_id, exc)
        if issue != "PREVIOUS_REQUEST_IN_PROGRESS":
            # Recorded first. 5xx = unknown (retryable); every 4xx is a definite
            # answer and never retryable. PREVIOUS_REQUEST_IN_PROGRESS is not our
            # outcome (the in-flight request records its own), so nothing is
            # recorded and the row stays "nothing recorded" -> lookups only.
            _record_capture_result(order_id, user_id, "HTTP_5XX" if code is not None and code >= 500
                                   else f"HTTP_{code}:{issue or 'NO_ISSUE'}")
        if issue == "PREVIOUS_REQUEST_IN_PROGRESS":
            # A concurrent request with the same PayPal-Request-Id is still
            # running. Grant nothing and write nothing (the in-flight request
            # records its own outcome); if it already finished, report that.
            with database.connect() as conn:
                current = _get_payment(conn, order_id)
            if current is not None and current["status"] in TERMINAL_STATUSES:
                return _outcome_for_status(current["status"], user_id)
            return CaptureOutcome(202, ST_IN_PROGRESS,
                                  "This payment is still being confirmed. Please wait a few seconds and "
                                  "check again. Do not pay again.",
                                  extra={"retryable": True})
        if issue == "ORDER_ALREADY_CAPTURED" or (code is not None and code >= 500):
            # ORDER_ALREADY_CAPTURED is evidence that a capture happened: the
            # lookup may grant it, but can never turn it into "not charged".
            return _reconcile(client, order_id, payment, user_id)
        if issue in CAPTURE_DECLINE_ISSUES:
            # The capture endpoint itself declined this request: final for this
            # order (it is never captured again; the buyer may start a new order).
            # COMPLIANCE_VIOLATION is documented by PayPal as "Transaction is
            # declined due to compliance violation" (an account-side refusal).
            if _set_status(order_id, user_id, ST_DECLINED):
                outcome = _current_outcome(order_id, user_id)
                outcome.extra["decline_issue"] = issue
                return outcome
            return _current_outcome(order_id, user_id)
        if issue == "ORDER_NOT_APPROVED":
            # Definitive: PayPal refused to capture, so nothing was charged.
            if _set_status(order_id, user_id, ST_CREATED, from_statuses=(ST_UNCERTAIN,)):
                raise PaymentError(409, "The order has not been approved in PayPal yet. You have not been charged.",
                                   extra={"order_id": order_id, "status": ST_CREATED}, code=CODE_NOT_APPROVED)
            return _current_outcome(order_id, user_id)
        if code == 404 or issue in EXPIRY_HINT_ISSUES:
            # Looks gone, but only get_order may CONFIRM expiry.
            return _reconcile(client, order_id, payment, user_id, missing_means_expired=True)
        # Any other PayPal error is inconclusive: let the order's real state decide.
        return _reconcile(client, order_id, payment, user_id)
    except AuthValidationException:
        # Raised while the SDK builds the request (apimatic request_builder.apply_auth),
        # i.e. before it is handed to the HTTP client: the capture was not sent.
        _restore_unsent(order_id, user_id, *restore)
        log.error("PayPal capture_order: authentication with PayPal failed")
        raise PaymentError(503, "Payments are temporarily unavailable.", code=CODE_UNAVAILABLE)
    except Exception as exc:
        # Timeout / connection reset: PayPal may or may not have captured. The
        # row stays UNCERTAIN (or PENDING) until PayPal gives a definitive answer.
        log.warning("PayPal capture_order transport error: order_id=%s err=%s", order_id, type(exc).__name__)
        _record_capture_result(order_id, user_id, "TRANSPORT_ERROR")
        return _reconcile(client, order_id, payment, user_id)

    _record_capture_result(order_id, user_id, "HTTP_2XX")
    return _outcome_for(result.body, order_id, payment, user_id, source="capture")


# ----------------------------------------------------- payment status check ---
# "Check payment status" for an unfinished payment. Unlike the capture call, it
# LOOKS THE ORDER UP first (get_order, read-only) and never blindly re-captures:
#   * completed capture  -> verified + granted once;  pending -> PENDING;
#   * voided             -> EXPIRED;  inconsistent -> NEEDS_REVIEW;
#   * APPROVED but no capture while our row is UNCERTAIN -> the capture is
#     re-sent (SAME PayPal-Request-Id, at most once per
#     CAPTURE_RESEND_COOLDOWN_SECONDS) ONLY if last_capture_result records a
#     retryable unknown outcome (TRANSPORT_ERROR / HTTP_5XX). A definite 4xx
#     (e.g. COMPLIANCE_VIOLATION) or nothing recorded -> lookup only, forever;
#   * anything else (lookup failed, no capture yet) -> unchanged, still blocking.
# One status check per order at a time (process-local; single-process demo).
_status_locks: dict = {}
_status_locks_guard = threading.Lock()
_last_capture_sent: dict = {}  # order_id -> time.monotonic() of the last capture request


def _note_capture_sent(order_id: str) -> None:
    _last_capture_sent[order_id] = time.monotonic()


def _capture_resend_allowed(order_id: str) -> bool:
    last = _last_capture_sent.get(order_id)
    return last is None or time.monotonic() - last >= CAPTURE_RESEND_COOLDOWN_SECONDS


def _status_lock(order_id: str) -> threading.Lock:
    with _status_locks_guard:
        return _status_locks.setdefault(order_id, threading.Lock())


def _approved_without_capture(order: Any) -> bool:
    if getattr(order, "status", None) != OrderStatus.APPROVED:
        return False
    for unit in getattr(order, "purchase_units", None) or []:
        payments_obj = getattr(unit, "payments", None)
        if payments_obj is not None and (getattr(payments_obj, "captures", None) or []):
            return False
    return True


def refresh_order_status(user_id: str, order_id: str) -> CaptureOutcome:
    if not ORDER_ID_RE.match(order_id or ""):
        raise PaymentError(404, "Order not found.", code=CODE_NOT_FOUND)
    with database.connect() as conn:
        payment = _get_payment(conn, order_id)
    if payment is None or payment["user_id"] != user_id:
        raise PaymentError(404, "Order not found.", code=CODE_NOT_FOUND)
    if payment["status"] in TERMINAL_STATUSES or payment["status"] == ST_CREATED:
        # Final, or not approved/captured yet: nothing to look up.
        return _outcome_for_status(payment["status"], user_id)
    finished = _finish_recorded_decline(order_id, user_id, payment)
    if finished is not None:
        return finished

    lock = _status_lock(order_id)
    if not lock.acquire(blocking=False):
        return CaptureOutcome(202, ST_IN_PROGRESS,
                              "This payment is already being checked. Please wait a few seconds. Do not pay again.",
                              extra={"retryable": True})
    try:
        client = _paypal_client()
        try:
            result = client.orders.get_order({"id": order_id})
        except ApiException as exc:
            log.warning("PayPal get_order failed during status check: order_id=%s http=%s",
                        order_id, exc.response_code)
            _log_paypal_error("get_order", order_id, exc)
            return _current_outcome(order_id, user_id)
        except Exception as exc:
            log.warning("PayPal get_order failed during status check: order_id=%s err=%s",
                        order_id, type(exc).__name__)
            return _current_outcome(order_id, user_id)

        with database.connect() as conn:
            payment = _get_payment(conn, order_id)  # may have advanced meanwhile
        if payment["status"] in TERMINAL_STATUSES:
            return _outcome_for_status(payment["status"], user_id)

        order = result.body
        verified, _, _ = _verify(order, order_id, payment)
        if (verified == ST_UNCERTAIN and payment["status"] == ST_UNCERTAIN
                and _approved_without_capture(order)):
            if payment["last_capture_result"] not in RETRYABLE_CAPTURE_RESULTS:
                # No recorded proof that the last capture ended with an unknown
                # outcome (definite 4xx, or nothing recorded): lookup only.
                log.info("Order approved but not captured; no capture re-send (last result %s): order_id=%s",
                         payment["last_capture_result"], order_id)
                return _current_outcome(order_id, user_id)
            if _capture_resend_allowed(order_id):
                log.info("Order approved but not captured after %s; re-sending capture with the same "
                         "PayPal-Request-Id: order_id=%s", payment["last_capture_result"], order_id)
                return capture_premium_order(user_id, order_id)
            log.info("Order approved but not captured; capture re-send is cooling down: order_id=%s", order_id)
            return _current_outcome(order_id, user_id)
        return _outcome_for(order, order_id, payment, user_id, source="lookup")
    finally:
        lock.release()
