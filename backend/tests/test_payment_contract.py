"""
Phase B review fixes:
  1. Machine-readable `code` on payment responses (409 is ambiguous on its own).
  2. Create-order idempotency (PayPal-Request-Id persisted before the call).
  3. Create coordination that does not rely on the process-local lock alone.
  4. Real concurrent capture requests (not only a simulated
     PREVIOUS_REQUEST_IN_PROGRESS answer).

Run from backend/:
    venv\\Scripts\\python -m unittest discover -s tests -v

Same fake-PayPal transport as test_paypal_payments (real SDK, fake HTTP
adapter). The fake models PayPal-Request-Id replay for create-order.
"""
from tests import _env  # noqa: F401  (must precede any app.* import)

import sqlite3
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import requests

from tests import test_paypal_payments as base
from app.core import database, premium
from app.core.config import settings
from app.core.paypal_client import PayPalNotConfiguredError
from app.services import paypal_service

order_body, paypal_error, FakePayPal = base.order_body, base.paypal_error, base.FakePayPal
CREATE_PATH = "/v2/checkout/orders"


class _Base(unittest.TestCase):
    setUp = base.PayPalPaymentsTest.setUp
    _register = base.PayPalPaymentsTest._register
    _create = base.PayPalPaymentsTest._create
    _capture = base.PayPalPaymentsTest._capture
    _db = base.PayPalPaymentsTest._db
    _payment = base.PayPalPaymentsTest._payment
    _user_row = base.PayPalPaymentsTest._user_row
    _assert_not_premium = base.PayPalPaymentsTest._assert_not_premium
    _capture_returns = base.PayPalPaymentsTest._capture_returns
    _hook_create = base.PayPalPaymentsTest._hook_create

    @classmethod
    def setUpClass(cls):
        _env.ensure_isolated_db()

    def _post_order(self, user):
        return self.api.post("/api/payments/paypal/orders", headers=user["headers"])

    def _attempt(self, user):
        return self._db("SELECT * FROM payment_create_attempts WHERE user_id = ?", user["id"])

    def _create_keys(self):
        return [h.get("PayPal-Request-Id") for m, p, h, _ in self.fake.calls if m == "POST" and p == CREATE_PATH]

    def _reply(self, request, status, body):
        """Hook-supplied PayPal answer, recorded like the fake's own calls."""
        self.fake.calls.append((request.method, CREATE_PATH, dict(request.headers), request.body))
        return FakePayPal._resp(request, status, body)

    def _payment_rows(self, user):
        return self._db("SELECT COUNT(*) AS n FROM payments WHERE user_id = ?", user["id"])["n"]


# ---------------------------------------------------------------- issue 1 ---
class ErrorCodeContractTest(_Base):

    def test_order_not_approved_has_explicit_code(self):
        oid = self._create(self.user_a)
        self._capture_returns(lambda o, req: paypal_error(422, "ORDER_NOT_APPROVED"))
        r = self._capture(self.user_a, oid)
        self.assertEqual(r.status_code, 409)
        body = r.json()
        self.assertEqual((body["code"], body["status"], body["order_id"]), ("ORDER_NOT_APPROVED", "CREATED", oid))
        self.assertIsInstance(body["detail"], str)
        self._assert_not_premium(self.user_a)

    def test_lookup_showing_unapproved_order_does_not_downgrade(self):
        # Inconclusive capture error, then get_order shows CREATED: stays UNCERTAIN.
        oid = self._create(self.user_a)
        self._capture_returns(lambda o, req: paypal_error(422, "SOMETHING_UNEXPECTED"))
        self.fake.get_handler = lambda o: (200, {"id": o, "status": "CREATED", "purchase_units": [
            {"reference_id": "mymile-premium-pass", "custom_id": self.user_a["id"],
             "amount": {"currency_code": "USD", "value": "9.00"}}]})
        r = self._capture(self.user_a, oid)
        self.assertEqual((r.status_code, r.json()["code"], r.json()["status"]), (202, "PAYMENT_UNCERTAIN", "UNCERTAIN"))

    def test_capture_id_conflict_is_a_distinct_409_and_stays_blocking(self):
        o1 = self._create(self.user_a)
        shared = f"CAP-CONFLICT-{self.user_a['id']}"  # unique per test run (DB is shared across tests)
        self._capture_returns(lambda o, req: (201, order_body(o, self.user_a["id"], capture_id=shared)))
        self.assertEqual(self._capture(self.user_a, o1).status_code, 200)
        until = self._user_row(self.user_a)["premium_until"]

        o2 = self._create(self.user_a)   # o1 is COMPLETED, so a new order is allowed
        r = self._capture(self.user_a, o2)  # PayPal (wrongly) reports the same capture id
        self.assertEqual(r.status_code, 409, r.text)
        body = r.json()
        self.assertEqual(body["code"], "CAPTURE_ID_CONFLICT")
        self.assertNotEqual(body.get("status"), "CREATED", "must not look like 'not approved'")
        self.assertIn("do not pay again", body["detail"].lower())
        # Never granted twice; the order stays blocking, so no replacement order.
        self.assertEqual(self._user_row(self.user_a)["premium_until"], until)
        self.assertEqual(self._payment(o2)["status"], "NEEDS_REVIEW")
        creates = self.fake.count("POST", CREATE_PATH)
        blocked = self._post_order(self.user_a)
        self.assertEqual((blocked.status_code, blocked.json()["code"], blocked.json()["order_id"]),
                         (409, "UNRESOLVED_PAYMENT", o2))
        self.assertEqual(self.fake.count("POST", CREATE_PATH), creates, "no replacement order")

    def test_unverifiable_payment_has_needs_review_code(self):
        oid = self._create(self.user_a)
        self._capture_returns(lambda o, req: (201, order_body(o, self.user_a["id"], value="1.00")))
        r = self._capture(self.user_a, oid)
        self.assertEqual((r.status_code, r.json()["code"], r.json()["status"]),
                         (409, "PAYMENT_NEEDS_REVIEW", "NEEDS_REVIEW"))
        self._assert_not_premium(self.user_a)

    def test_every_capture_answer_carries_a_code(self):
        cases = [
            (lambda o, req: (201, order_body(o, self.user_a["id"], capture_status="PENDING")), 202, "PAYMENT_PENDING"),
            (lambda o, req: paypal_error(422, "INSTRUMENT_DECLINED"), 402, "PAYMENT_DECLINED"),
            (lambda o, req: paypal_error(422, "PREVIOUS_REQUEST_IN_PROGRESS"), 202, "CAPTURE_IN_PROGRESS"),
            (lambda o, req: (201, order_body(o, self.user_a["id"])), 200, "PAYMENT_COMPLETED"),
        ]
        for handler, status, code in cases:
            with database.connect() as conn:  # fresh order each time
                conn.execute("DELETE FROM payments WHERE user_id = ?", (self.user_a["id"],))
            oid = self._create(self.user_a)
            self._capture_returns(handler)
            r = self._capture(self.user_a, oid)
            self.assertEqual((r.status_code, r.json()["code"]), (status, code), r.text)
        r = self._capture(self.user_a, "NOPE123")
        self.assertEqual((r.status_code, r.json()["code"]), (404, "ORDER_NOT_FOUND"))

    def test_uncertain_and_expired_codes(self):
        oid = self._create(self.user_a)

        def timeout(o, req):
            raise requests.exceptions.ReadTimeout("simulated")
        self._capture_returns(timeout)
        self.fake.get_handler = lambda o: (503, {})
        r = self._capture(self.user_a, oid)
        self.assertEqual((r.status_code, r.json()["code"]), (202, "PAYMENT_UNCERTAIN"))
        self._capture_returns(lambda o, req: (404, {"name": "RESOURCE_NOT_FOUND",
                                                    "details": [{"issue": "INVALID_RESOURCE_ID"}]}))
        self.fake.get_handler = lambda o: (404, {"name": "RESOURCE_NOT_FOUND"})
        r = self._capture(self.user_a, oid)
        self.assertEqual((r.status_code, r.json()["code"]), (410, "ORDER_EXPIRED"))

    def test_capture_error_bodies_match_the_frontend_contract(self):
        # frontend/src/services/paymentOutcome.ts requires these exact shapes.
        from apimatic_core.exceptions.auth_validation_exception import AuthValidationException
        r = self._capture(self.user_a, "NOPE123")
        self.assertEqual((r.status_code, r.json()["code"]), (404, "ORDER_NOT_FOUND"))
        self.assertNotIn("status", r.json())
        oid = self._create(self.user_a)
        with mock.patch.object(self.paypal.orders, "capture_order", side_effect=AuthValidationException("t")):
            r = self._capture(self.user_a, oid)
        self.assertEqual((r.status_code, r.json()["code"]), (503, "PAYMENTS_UNAVAILABLE"))
        self.assertNotIn("status", r.json())
        self._capture_returns(lambda o, req: paypal_error(422, "INSTRUMENT_DECLINED"))
        r = self._capture(self.user_a, oid)
        self.assertEqual((r.status_code, r.json()["code"], r.json()["status"]), (402, "PAYMENT_DECLINED", "DECLINED"))

    def test_create_answers_carry_codes(self):
        first = self._post_order(self.user_a)
        second = self._post_order(self.user_a)
        self.assertEqual((first.json()["code"], second.json()["code"]), ("ORDER_CREATED", "ORDER_REUSED"))
        with mock.patch.object(settings, "PAYPAL_TIMEOUT_SECONDS", -14.9):  # lock wait = 0.1 s
            with paypal_service._user_create_lock(self.user_a["id"]):
                r = self._post_order(self.user_a)
        self.assertEqual((r.status_code, r.json()["code"]), (409, "CREATE_IN_PROGRESS"))
        self.assertNotIn("order_id", r.json())

    def test_unconfigured_paypal_has_code_and_leaves_no_attempt(self):
        def not_configured():
            raise PayPalNotConfiguredError("x")
        with mock.patch.object(paypal_service, "get_paypal_client", not_configured):
            r = self._post_order(self.user_a)
        self.assertEqual((r.status_code, r.json()["code"]), (503, "PAYMENTS_UNAVAILABLE"))
        self.assertIsNone(self._attempt(self.user_a))


# ---------------------------------------------------------------- issue 2 ---
class CreateIdempotencyTest(_Base):

    def _lose_first_response(self, exc=None):
        """PayPal really creates the order on the first call, then the response
        is lost on the way back (timeout). Later calls behave normally."""
        original = FakePayPal.send.__get__(self.fake)
        state = {"n": 0, "order_id": None}

        def before_create(request):
            state["n"] += 1
            if state["n"] == 1:
                resp = original(request)  # order created + stored under its request id
                state["order_id"] = resp.json()["id"]
                raise exc or requests.exceptions.ReadTimeout("response lost")
            return None
        self._hook_create(before_create)
        return state

    def test_create_sends_a_request_id_and_clears_it_on_success(self):
        r = self._post_order(self.user_a)
        self.assertEqual(r.status_code, 201)
        keys = self._create_keys()
        self.assertEqual(len(keys), 1)
        self.assertTrue(keys[0] and keys[0].startswith("mymile-create-"))
        self.assertIsNone(self._attempt(self.user_a))

    def test_timeout_after_remote_create_recovers_the_same_order(self):
        state = self._lose_first_response()
        r1 = self._post_order(self.user_a)
        self.assertEqual((r1.status_code, r1.json()["code"]), (502, "CREATE_UNCONFIRMED"), r1.text)
        self.assertEqual(self.fake._n, 1, "PayPal did create an order")
        self.assertEqual(self._payment_rows(self.user_a), 0, "its id never reached the backend")
        self.assertIsNotNone(self._attempt(self.user_a), "attempt kept for a safe retry")

        r2 = self._post_order(self.user_a)
        self.assertEqual(r2.status_code, 201, r2.text)
        self.assertEqual(r2.json()["order_id"], state["order_id"], "the SAME PayPal order is recovered")
        self.assertEqual(self.fake._n, 1, "no second PayPal order was created")
        keys = self._create_keys()
        self.assertEqual(len(keys), 2)
        self.assertEqual(keys[0], keys[1], "retry re-sent the same PayPal-Request-Id")
        self.assertEqual(self._payment(state["order_id"])["status"], "CREATED")
        self.assertIsNone(self._attempt(self.user_a))

        r3 = self._post_order(self.user_a)  # normal reuse afterwards, no PayPal call
        self.assertEqual((r3.status_code, r3.json()["order_id"]), (200, state["order_id"]))
        self.assertEqual(len(self._create_keys()), 2)
        self._assert_not_premium(self.user_a)

    def test_connection_reset_after_remote_create_recovers_the_same_order(self):
        state = self._lose_first_response(requests.exceptions.ConnectionError("reset"))
        self.assertEqual(self._post_order(self.user_a).status_code, 502)
        self.assertEqual(self._post_order(self.user_a).json()["order_id"], state["order_id"])
        self.assertEqual(self.fake._n, 1)

    def test_crash_after_response_before_persisting_recovers_the_same_order(self):
        # PayPal answered, but the backend failed before storing the order id.
        real = paypal_service._record_created_order
        calls = [0]

        def fail_once(*args, **kwargs):
            calls[0] += 1
            if calls[0] == 1:
                raise sqlite3.OperationalError("disk I/O error (simulated)")
            return real(*args, **kwargs)
        with mock.patch.object(paypal_service, "_record_created_order", fail_once):
            with self.assertRaises(sqlite3.OperationalError):
                paypal_service.create_premium_order(self.user_a["id"])
            lost = self.fake.create_replays[self._create_keys()[0]]["id"]
            self.assertEqual(self._payment_rows(self.user_a), 0)
            result = paypal_service.create_premium_order(self.user_a["id"])
        self.assertEqual(result["order_id"], lost)
        self.assertEqual(self.fake._n, 1)
        self.assertEqual(self._payment_rows(self.user_a), 1)

    def test_paypal_5xx_keeps_the_request_id(self):
        calls = [0]

        def fail_first(request):
            calls[0] += 1
            return self._reply(request, 500, {"name": "INTERNAL_SERVER_ERROR"}) if calls[0] == 1 else None
        self._hook_create(fail_first)
        r = self._post_order(self.user_a)
        self.assertEqual((r.status_code, r.json()["code"]), (502, "CREATE_UNCONFIRMED"))
        self.assertEqual(self._post_order(self.user_a).status_code, 201)
        keys = self._create_keys()
        self.assertEqual(keys[0], keys[1])

    def test_definitive_4xx_clears_the_request_id(self):
        calls = [0]

        def reject_first(request):
            calls[0] += 1
            return self._reply(request, 400, {"name": "INVALID_REQUEST"}) if calls[0] == 1 else None
        self._hook_create(reject_first)
        r = self._post_order(self.user_a)
        self.assertEqual((r.status_code, r.json()["code"]), (502, "PAYPAL_ERROR"))
        self.assertIsNone(self._attempt(self.user_a))
        self.assertEqual(self._post_order(self.user_a).status_code, 201)
        keys = self._create_keys()
        self.assertNotEqual(keys[0], keys[1])

    def test_previous_request_in_progress_on_create_keeps_the_key(self):
        calls = [0]

        def busy_first(request):
            calls[0] += 1
            return self._reply(request, *paypal_error(422, "PREVIOUS_REQUEST_IN_PROGRESS")) \
                if calls[0] == 1 else None
        self._hook_create(busy_first)
        r = self._post_order(self.user_a)
        self.assertEqual((r.status_code, r.json()["code"]), (409, "CREATE_IN_PROGRESS"))
        self.assertIsNotNone(self._attempt(self.user_a))
        self.assertEqual(self._post_order(self.user_a).status_code, 201)
        keys = self._create_keys()
        self.assertEqual(keys[0], keys[1])

    def test_stale_attempt_uses_a_new_key(self):
        # Documented limitation: after CREATE_KEY_WINDOW the lost order is
        # abandoned (never shown to anyone, so it cannot be approved/charged).
        state = self._lose_first_response()
        self._post_order(self.user_a)
        old = (premium.utc_now() - timedelta(minutes=31)).isoformat(timespec="seconds")
        with database.connect() as conn:
            conn.execute("UPDATE payment_create_attempts SET created_at = ? WHERE user_id = ?",
                         (old, self.user_a["id"]))
        r = self._post_order(self.user_a)
        self.assertEqual(r.status_code, 201)
        self.assertNotEqual(r.json()["order_id"], state["order_id"])
        keys = self._create_keys()
        self.assertNotEqual(keys[0], keys[1])

    def test_changed_terms_use_a_new_key(self):
        self._lose_first_response()
        self._post_order(self.user_a)
        with mock.patch.object(settings, "PREMIUM_PRICE", "12.00"):
            r = self._post_order(self.user_a)
        self.assertEqual((r.status_code, r.json()["amount"]), (201, "12.00"))
        keys = self._create_keys()
        self.assertNotEqual(keys[0], keys[1], "a different body must not reuse the old key")

    def test_unresolved_capture_still_blocks_a_pending_create_retry(self):
        # A blocking order always wins over a remembered create attempt.
        oid = self._create(self.user_a)

        def timeout(o, req):
            raise requests.exceptions.ReadTimeout("simulated")
        self._capture_returns(timeout)
        self.fake.get_handler = lambda o: (503, {})
        self._capture(self.user_a, oid)
        with database.connect() as conn:
            conn.execute("INSERT INTO payment_create_attempts (user_id, request_id, terms, created_at) "
                         "VALUES (?, 'mymile-create-x', '9.00|USD|30', ?)",
                         (self.user_a["id"], premium.utc_now().isoformat(timespec="seconds")))
        creates = self.fake.count("POST", CREATE_PATH)
        r = self._post_order(self.user_a)
        self.assertEqual((r.status_code, r.json()["code"]), (409, "UNRESOLVED_PAYMENT"))
        self.assertEqual(self.fake.count("POST", CREATE_PATH), creates)


# ---------------------------------------------------------------- issue 3 ---
class CreateWithoutProcessLockTest(_Base):
    """Simulates two worker processes: the per-user threading lock is bypassed
    and only the SQLite reservation + PayPal-Request-Id coordinate. This is an
    in-process simulation, not a real multi-process run."""

    def test_two_unlocked_creates_produce_one_paypal_order(self):
        original = FakePayPal.send.__get__(self.fake)
        inflight, guard = set(), threading.Lock()

        def paypal_like(request):
            key = request.headers.get("PayPal-Request-Id")
            with guard:
                if key in inflight:  # PayPal: same key still processing
                    return FakePayPal._resp(request, *paypal_error(422, "PREVIOUS_REQUEST_IN_PROGRESS"))
                inflight.add(key)
            try:
                time.sleep(0.3)  # widen the window
                return original(request)
            finally:
                with guard:
                    inflight.discard(key)
        self._hook_create(paypal_like)

        terms = paypal_service.premium_terms()
        barrier = threading.Barrier(2)
        results = [None, None]

        def worker(i):
            barrier.wait(timeout=10)
            try:
                results[i] = paypal_service._create_premium_order_locked(self.user_a["id"], terms)
            except paypal_service.PaymentError as exc:
                results[i] = exc
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
        [t.start() for t in threads]
        [t.join(timeout=60) for t in threads]

        self.assertEqual(self.fake._n, 1, "exactly one PayPal order")
        self.assertEqual(self._payment_rows(self.user_a), 1)
        ids = {r["order_id"] for r in results if isinstance(r, dict)}
        self.assertEqual(len(ids), 1, results)
        for r in results:
            if isinstance(r, paypal_service.PaymentError):
                self.assertEqual(r.code, "CREATE_IN_PROGRESS")


# ---------------------------------------------------------------- issue 4 ---
class ConcurrentCaptureTest(_Base):
    """Real simultaneous HTTP capture requests for one order."""

    def _capture_concurrently(self, order_id, n):
        barrier = threading.Barrier(n)
        results = [None] * n

        def worker(i):
            barrier.wait(timeout=10)
            results[i] = self._capture(self.user_a, order_id)
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
        [t.start() for t in threads]
        [t.join(timeout=60) for t in threads]
        self.assertTrue(all(r is not None for r in results), "a request hung")
        return results

    def _assert_granted_once(self, order_id, before):
        until = datetime.fromisoformat(self._user_row(self.user_a)["premium_until"])
        self.assertAlmostEqual((until - before).total_seconds(), timedelta(days=30).total_seconds(), delta=120,
                               msg="Premium extended exactly once (30 days, not 60)")
        row = self._payment(order_id)
        self.assertEqual((row["status"], row["capture_id"]), ("COMPLETED", f"CAP{order_id}"))
        n = self._db("SELECT COUNT(*) AS n FROM payments WHERE user_id = ? AND status = 'COMPLETED'",
                     self.user_a["id"])["n"]
        self.assertEqual(n, 1)

    def _concurrent_capture_scenario(self, lookup_body):
        oid = self._create(self.user_a)

        def slow_capture(o, req):
            time.sleep(0.4)
            return 201, order_body(o, self.user_a["id"])
        self._capture_returns(slow_capture)
        self.fake.get_handler = lambda o: (200, lookup_body(o))
        before = datetime.now(timezone.utc)
        results = self._capture_concurrently(oid, 5)
        self.assertEqual(self.fake.count("POST", "/capture"), 1,
                         "simultaneous captures reach PayPal exactly once (the others never re-capture)")
        self.assertTrue(all(r.status_code in (200, 202) for r in results), [r.text for r in results])
        fresh = [r for r in results if r.status_code == 200 and not r.json()["already_processed"]]
        self.assertEqual(len(fresh), 1, "exactly one grant")
        self._assert_granted_once(oid, before)
        return oid, results

    def test_concurrent_captures_losers_resolve_by_lookup(self):
        # Requests that lost the race see the completed capture via a read-only lookup.
        self._concurrent_capture_scenario(lambda o: order_body(o, self.user_a["id"]))

    def test_concurrent_captures_losers_never_recapture_while_uncertain(self):
        # Lookup still shows APPROVED without a capture: losers answer "in progress /
        # uncertain" instead of sending another capture.
        oid, results = self._concurrent_capture_scenario(lambda o: {
            "id": o, "status": "APPROVED", "purchase_units": [
                {"reference_id": "mymile-premium-pass", "custom_id": self.user_a["id"],
                 "amount": {"currency_code": "USD", "value": "9.00"}}]})
        statuses = {r.json()["status"] for r in results if r.status_code == 202}
        self.assertTrue(statuses <= {"IN_PROGRESS", "UNCERTAIN"}, statuses)
        calls = self.fake.count("POST", "/capture")
        again = self._capture(self.user_a, oid)
        self.assertEqual((again.status_code, again.json()["already_processed"]), (200, True))
        self.assertEqual(self.fake.count("POST", "/capture"), calls)

if __name__ == "__main__":
    unittest.main()
