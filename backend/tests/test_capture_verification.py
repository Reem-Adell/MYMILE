"""
Sandbox-checkout completion: final declines (retry = new order), lookups that
never downgrade an in-flight capture, multi-capture verification, blocking
NEEDS_REVIEW, conditional status writes, crash recovery and concurrency.

Run from backend/:
    venv\\Scripts\\python -m unittest discover -s tests -v

Same fake-PayPal transport as test_paypal_payments (real SDK, fake HTTP adapter).
"""
from tests import _env  # noqa: F401  (must precede any app.* import)

import threading
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import requests

from tests import test_paypal_payments as base
from app.services import paypal_service

order_body, paypal_error = base.order_body, base.paypal_error
CAPTURE = "/capture"
CREATE = "/v2/checkout/orders"


def multi_capture_body(order_id, user_id, captures, *, order_status="COMPLETED",
                       reference_id="mymile-premium-pass", unit_value="9.00", currency="USD"):
    """Order with several captures: `captures` = [(id, status, value, currency, custom_id?, final?)]."""
    caps = []
    for c in captures:
        cid, status, value, cur = c[:4]
        cap = {"id": cid, "status": status, "amount": {"currency_code": cur, "value": value}}
        if len(c) > 4 and c[4] is not None:
            cap["custom_id"] = c[4]
        if len(c) > 5:
            cap["final_capture"] = c[5]
        caps.append(cap)
    return {"id": order_id, "status": order_status, "intent": "CAPTURE",
            "purchase_units": [{"reference_id": reference_id, "custom_id": user_id,
                                "amount": {"currency_code": currency, "value": unit_value},
                                "payments": {"captures": caps}}]}


def approved_no_capture(order_id, user_id, status="CREATED"):
    return {"id": order_id, "status": status, "purchase_units": [
        {"reference_id": "mymile-premium-pass", "custom_id": user_id,
         "amount": {"currency_code": "USD", "value": "9.00"}}]}


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

    @classmethod
    def setUpClass(cls):
        _env.ensure_isolated_db()

    def _post_order(self, user):
        return self.api.post("/api/payments/paypal/orders", headers=user["headers"])

    def _unresolved(self, user):
        return self.api.get("/api/payments/paypal/orders/unresolved", headers=user["headers"]).json()["order"]

    def _captures(self):
        return self.fake.count("POST", CAPTURE)

    def _timeout(self, o, req):
        raise requests.exceptions.ReadTimeout("simulated")


# ------------------------------------------------------- end-to-end flow ---
class SandboxFlowTest(_Base):

    def test_full_flow_create_approve_capture_premium(self):
        r = self._post_order(self.user_a)
        self.assertEqual((r.status_code, r.json()["code"]), (201, "ORDER_CREATED"))
        oid = r.json()["order_id"]
        self.assertTrue(r.json()["approve_url"])
        self._capture_returns(lambda o, req: (201, order_body(o, self.user_a["id"])))
        before = datetime.now(timezone.utc)
        c = self._capture(self.user_a, oid)
        self.assertEqual((c.status_code, c.json()["code"], c.json()["premium_granted"]), (200, "PAYMENT_COMPLETED", True))
        until = datetime.fromisoformat(c.json()["premium_until"])
        self.assertAlmostEqual((until - before).total_seconds(), timedelta(days=30).total_seconds(), delta=120)
        me = self.api.get("/api/auth/me", headers=self.user_a["headers"]).json()
        self.assertEqual(me["plan"], "premium")
        self.assertIsNone(self._unresolved(self.user_a))


# -------------------------------------------------------- final declines ---
class DeclineIsFinalTest(_Base):

    def _assert_final_decline(self, oid):
        self.assertEqual(self._payment(oid)["status"], "DECLINED")
        calls = self._captures()
        again = self._capture(self.user_a, oid)
        self.assertEqual((again.status_code, again.json()["code"], again.json()["next_step"]),
                         (402, "PAYMENT_DECLINED", "new_order"))
        self.assertEqual(self._captures(), calls, "a declined order is never captured again")
        self.assertIsNone(self._unresolved(self.user_a), "a declined order is not resumable")
        self._assert_not_premium(self.user_a)

    def test_instrument_declined_is_final_and_retry_uses_a_new_order(self):
        oid = self._create(self.user_a)
        self._capture_returns(lambda o, req: paypal_error(422, "INSTRUMENT_DECLINED"))
        r = self._capture(self.user_a, oid)
        self.assertEqual((r.status_code, r.json()["code"], r.json()["status"]), (402, "PAYMENT_DECLINED", "DECLINED"))
        self._assert_final_decline(oid)
        # Retry: a NEW order (new approval), then a successful capture of it.
        new = self._post_order(self.user_a)
        self.assertEqual((new.status_code, new.json()["code"]), (201, "ORDER_CREATED"))
        self.assertNotEqual(new.json()["order_id"], oid)
        self._capture_returns(lambda o, req: (201, order_body(o, self.user_a["id"])))
        ok = self._capture(self.user_a, new.json()["order_id"])
        self.assertEqual((ok.status_code, ok.json()["premium_granted"]), (200, True))
        keys = {h.get("PayPal-Request-Id") for m, p, h, _ in self.fake.calls if p.endswith(CAPTURE)}
        self.assertEqual(keys, {f"mymile-capture-{oid}", f"mymile-capture-{new.json()['order_id']}"},
                         "one stable capture key per order, never rotated")

    def test_declined_capture_in_capture_response_is_final(self):
        oid = self._create(self.user_a)
        self._capture_returns(lambda o, req: (201, order_body(o, self.user_a["id"],
                                                              order_status="COMPLETED", capture_status="DECLINED")))
        self.assertEqual(self._capture(self.user_a, oid).status_code, 402)
        self._assert_final_decline(oid)

    def test_legacy_declined_row_is_not_captured_again(self):
        oid = self._create(self.user_a)
        paypal_service._set_status(oid, self.user_a["id"], "DECLINED", from_statuses=("CREATED",))
        self._assert_final_decline(oid)

    def test_crash_after_decline_before_storing_recovers_with_same_key(self):
        oid = self._create(self.user_a)
        self._capture_returns(lambda o, req: paypal_error(422, "INSTRUMENT_DECLINED"))
        real = paypal_service._set_status
        calls = [0]

        def crash_on_decline(order_id, user_id, status, from_statuses=paypal_service.IN_FLIGHT_STATUSES):
            if status == "DECLINED" and calls[0] == 0:
                calls[0] += 1
                raise RuntimeError("process died before storing the decline")
            return real(order_id, user_id, status, from_statuses)
        with mock.patch.object(paypal_service, "_set_status", crash_on_decline):
            with self.assertRaises(RuntimeError):
                paypal_service.capture_premium_order(self.user_a["id"], oid)
        self.assertEqual(self._payment(oid)["status"], "UNCERTAIN")
        self.assertEqual(self._post_order(self.user_a).status_code, 409, "blocked until resolved")
        self.assertEqual(self._payment(oid)["last_capture_result"], "HTTP_422:INSTRUMENT_DECLINED",
                         "the definite answer was recorded before the crash")
        calls = self._captures()
        r = self._capture(self.user_a, oid)  # after "restart": finished from the recorded answer
        self.assertEqual((r.status_code, r.json()["decline_issue"]), (402, "INSTRUMENT_DECLINED"))
        self.assertEqual(self._payment(oid)["status"], "DECLINED")
        self.assertEqual(self._captures(), calls, "no PayPal call: the recorded decline is final")

    def test_concurrent_captures_of_a_declining_order(self):
        oid = self._create(self.user_a)
        n = 5
        barrier = threading.Barrier(n)
        self._capture_returns(lambda o, req: paypal_error(422, "INSTRUMENT_DECLINED"))
        results = [None] * n

        def worker(i):
            barrier.wait(timeout=10)
            results[i] = self._capture(self.user_a, oid)
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
        [t.start() for t in threads]
        [t.join(timeout=60) for t in threads]
        self.assertTrue(all(r is not None and r.status_code in (402, 202) for r in results),
                        [r and r.text for r in results])
        self.assertEqual(self._payment(oid)["status"], "DECLINED")
        self._assert_not_premium(self.user_a)


# -------------------------------------------- lookups never downgrade ---
class LookupNeverDowngradesTest(_Base):

    def test_order_already_captured_but_lookup_shows_no_capture_stays_blocked(self):
        oid = self._create(self.user_a)
        self._capture_returns(lambda o, req: paypal_error(422, "ORDER_ALREADY_CAPTURED"))
        self.fake.get_handler = lambda o: (200, approved_no_capture(o, self.user_a["id"], "APPROVED"))
        r = self._capture(self.user_a, oid)
        self.assertEqual((r.status_code, r.json()["status"]), (202, "UNCERTAIN"))
        self.assertEqual(self._post_order(self.user_a).status_code, 409)
        self.fake.get_handler = lambda o: (200, approved_no_capture(o, self.user_a["id"], "CREATED"))
        r = self._capture(self.user_a, oid)
        self.assertEqual((r.status_code, r.json()["status"]), (202, "UNCERTAIN"),
                         "ORDER_ALREADY_CAPTURED is never turned into 'not charged'")
        self._assert_not_premium(self.user_a)

    def test_order_already_captured_and_lookup_shows_completed_grants_once(self):
        oid = self._create(self.user_a)
        self._capture_returns(lambda o, req: paypal_error(422, "ORDER_ALREADY_CAPTURED"))
        self.fake.get_handler = lambda o: (200, order_body(o, self.user_a["id"]))
        first = self._capture(self.user_a, oid)
        second = self._capture(self.user_a, oid)
        self.assertEqual((first.status_code, first.json()["already_processed"]), (200, False))
        self.assertEqual((second.status_code, second.json()["already_processed"]), (200, True))

    def test_timeout_then_lookup_shows_only_a_decline_stays_uncertain(self):
        oid = self._create(self.user_a)
        self._capture_returns(self._timeout)
        self.fake.get_handler = lambda o: (200, order_body(o, self.user_a["id"], capture_status="DECLINED"))
        r = self._capture(self.user_a, oid)
        self.assertEqual((r.status_code, r.json()["status"]), (202, "UNCERTAIN"))
        self.assertEqual(self._payment(oid)["status"], "UNCERTAIN")
        # Recovery: the capture endpoint's own answer for the same key decides.
        self._capture_returns(lambda o, req: paypal_error(422, "INSTRUMENT_DECLINED"))
        self.assertEqual(self._capture(self.user_a, oid).status_code, 402)
        self.assertEqual(self._payment(oid)["status"], "DECLINED")

    def test_pending_capture_later_declined_in_lookup_is_final(self):
        oid = self._create(self.user_a)
        self._capture_returns(lambda o, req: (201, order_body(o, self.user_a["id"], capture_status="PENDING")))
        self.assertEqual(self._capture(self.user_a, oid).status_code, 202)
        self._capture_returns(lambda o, req: paypal_error(422, "ORDER_ALREADY_CAPTURED"))
        self.fake.get_handler = lambda o: (200, order_body(o, self.user_a["id"], capture_status="DECLINED"))
        self.assertEqual(self._capture(self.user_a, oid).status_code, 402)
        self.assertEqual(self._payment(oid)["status"], "DECLINED")

    def test_pending_row_is_not_changed_by_a_lookup_without_capture(self):
        oid = self._create(self.user_a)
        self._capture_returns(lambda o, req: (201, order_body(o, self.user_a["id"], capture_status="PENDING")))
        self._capture(self.user_a, oid)
        self._capture_returns(self._timeout)
        self.fake.get_handler = lambda o: (200, approved_no_capture(o, self.user_a["id"]))
        r = self._capture(self.user_a, oid)
        self.assertEqual((r.status_code, r.json()["status"]), (202, "PENDING"))
        self.assertEqual(self._payment(oid)["status"], "PENDING")

    def test_late_decline_never_overwrites_a_completed_payment(self):
        oid = self._create(self.user_a)

        def granted_meanwhile_then_declined(o, req):
            paypal_service._grant(o, self.user_a["id"], f"CAP{o}")  # a concurrent request finished first
            return paypal_error(422, "INSTRUMENT_DECLINED")
        self._capture_returns(granted_meanwhile_then_declined)
        r = self._capture(self.user_a, oid)
        self.assertEqual((r.status_code, r.json()["status"]), (200, "COMPLETED"))
        self.assertEqual(self._payment(oid)["status"], "COMPLETED")


# --------------------------------------------- multi-capture verification ---
class MultiCaptureVerificationTest(_Base):

    def _capture_with(self, body_fn):
        oid = self._create(self.user_a)
        self._capture_returns(lambda o, req: (201, body_fn(o)))
        return oid, self._capture(self.user_a, oid)

    def _assert_review(self, oid, r):
        self.assertEqual((r.status_code, r.json()["code"], r.json()["status"]),
                         (409, "PAYMENT_NEEDS_REVIEW", "NEEDS_REVIEW"), r.text)
        self.assertEqual(self._payment(oid)["status"], "NEEDS_REVIEW")
        self._assert_not_premium(self.user_a)

    def test_completed_after_declined_capture_grants_with_the_completed_capture(self):
        u = self.user_a["id"]
        oid, r = self._capture_with(lambda o: multi_capture_body(o, u, [
            ("CAP-DECL-" + o, "DECLINED", "9.00", "USD"), ("CAP-OK-" + o, "COMPLETED", "9.00", "USD")]))
        self.assertEqual((r.status_code, r.json()["premium_granted"]), (200, True))
        self.assertEqual(self._payment(oid)["capture_id"], "CAP-OK-" + oid)

    def test_completed_with_failed_captures_grants(self):
        u = self.user_a["id"]
        oid, r = self._capture_with(lambda o: multi_capture_body(o, u, [
            ("F1-" + o, "FAILED", "9.00", "USD"), ("F2-" + o, "FAILED", "9.00", "USD"),
            ("OK-" + o, "COMPLETED", "9.00", "USD", u, True)]))
        self.assertEqual(r.status_code, 200)

    def test_two_completed_captures_need_review(self):
        u = self.user_a["id"]
        oid, r = self._capture_with(lambda o: multi_capture_body(o, u, [
            ("A-" + o, "COMPLETED", "9.00", "USD"), ("B-" + o, "COMPLETED", "9.00", "USD")]))
        self._assert_review(oid, r)

    def test_completed_and_pending_need_review(self):
        u = self.user_a["id"]
        oid, r = self._capture_with(lambda o: multi_capture_body(o, u, [
            ("A-" + o, "COMPLETED", "9.00", "USD"), ("B-" + o, "PENDING", "9.00", "USD")]))
        self._assert_review(oid, r)

    def test_refunded_capture_needs_review(self):
        u = self.user_a["id"]
        oid, r = self._capture_with(lambda o: multi_capture_body(o, u, [("A-" + o, "REFUNDED", "9.00", "USD")]))
        self._assert_review(oid, r)

    def test_duplicate_capture_id_in_order_needs_review(self):
        u = self.user_a["id"]
        oid, r = self._capture_with(lambda o: multi_capture_body(o, u, [
            ("SAME-" + o, "DECLINED", "9.00", "USD"), ("SAME-" + o, "COMPLETED", "9.00", "USD")]))
        self._assert_review(oid, r)

    def test_declined_capture_in_another_currency_needs_review(self):
        u = self.user_a["id"]
        oid, r = self._capture_with(lambda o: multi_capture_body(o, u, [
            ("D-" + o, "DECLINED", "9.00", "EUR"), ("OK-" + o, "COMPLETED", "9.00", "USD")]))
        self._assert_review(oid, r)

    def test_wrong_purchase_unit_reference_needs_review(self):
        u = self.user_a["id"]
        oid, r = self._capture_with(lambda o: multi_capture_body(
            o, u, [("OK-" + o, "COMPLETED", "9.00", "USD")], reference_id="something-else"))
        self._assert_review(oid, r)

    def test_wrong_purchase_unit_amount_needs_review(self):
        u = self.user_a["id"]
        oid, r = self._capture_with(lambda o: multi_capture_body(
            o, u, [("OK-" + o, "COMPLETED", "9.00", "USD")], unit_value="1.00"))
        self._assert_review(oid, r)

    def test_completed_capture_with_wrong_amount_needs_review(self):
        u = self.user_a["id"]
        oid, r = self._capture_with(lambda o: multi_capture_body(o, u, [("OK-" + o, "COMPLETED", "8.99", "USD")]))
        self._assert_review(oid, r)

    def test_capture_of_another_user_needs_review(self):
        u, other = self.user_a["id"], self.user_b["id"]
        oid, r = self._capture_with(lambda o: multi_capture_body(o, u, [("OK-" + o, "COMPLETED", "9.00", "USD", other)]))
        self._assert_review(oid, r)

    def test_completed_capture_but_order_not_completed_needs_review(self):
        u = self.user_a["id"]
        oid, r = self._capture_with(lambda o: multi_capture_body(
            o, u, [("OK-" + o, "COMPLETED", "9.00", "USD")], order_status="APPROVED"))
        self._assert_review(oid, r)

    def test_completed_order_without_capture_needs_review(self):
        u = self.user_a["id"]
        oid, r = self._capture_with(lambda o: multi_capture_body(o, u, []))
        self._assert_review(oid, r)

    def test_order_id_mismatch_needs_review(self):
        u = self.user_a["id"]
        oid, r = self._capture_with(lambda o: multi_capture_body("OTHERORDER123", u, [("OK", "COMPLETED", "9.00", "USD")]))
        self._assert_review(oid, r)


# ----------------------------------------------------- NEEDS_REVIEW blocks ---
class NeedsReviewBlocksTest(_Base):

    def test_needs_review_blocks_new_orders_and_further_captures(self):
        oid = self._create(self.user_a)
        u = self.user_a["id"]
        self._capture_returns(lambda o, req: (201, multi_capture_body(o, u, [
            ("A-" + o, "COMPLETED", "9.00", "USD"), ("B-" + o, "COMPLETED", "9.00", "USD")])))
        self.assertEqual(self._capture(self.user_a, oid).status_code, 409)
        calls = self._captures()
        again = self._capture(self.user_a, oid)
        self.assertEqual((again.status_code, again.json()["code"]), (409, "PAYMENT_NEEDS_REVIEW"))
        self.assertEqual(self._captures(), calls, "no further PayPal calls for a review order")
        creates = self.fake.count("POST", CREATE)
        blocked = self._post_order(self.user_a)
        self.assertEqual((blocked.status_code, blocked.json()["code"], blocked.json()["status"]),
                         (409, "UNRESOLVED_PAYMENT", "NEEDS_REVIEW"))
        self.assertEqual(self.fake.count("POST", CREATE), creates)
        u = self._unresolved(self.user_a)
        self.assertEqual((u["order_id"], u["status"], u["blocking"], u["resumable"]),
                         (oid, "NEEDS_REVIEW", True, False))
        self._assert_not_premium(self.user_a)

    def test_capture_id_conflict_puts_order_in_review(self):
        o1 = self._create(self.user_a)
        shared = f"CAP-REVIEW-{self.user_a['id']}"
        self._capture_returns(lambda o, req: (201, order_body(o, self.user_a["id"], capture_id=shared)))
        self.assertEqual(self._capture(self.user_a, o1).status_code, 200)
        o2 = self._create(self.user_a)
        r = self._capture(self.user_a, o2)
        self.assertEqual((r.status_code, r.json()["code"]), (409, "CAPTURE_ID_CONFLICT"))
        self.assertEqual(self._payment(o2)["status"], "NEEDS_REVIEW")
        calls = self._captures()
        self.assertEqual(self._capture(self.user_a, o2).json()["code"], "PAYMENT_NEEDS_REVIEW")
        self.assertEqual(self._captures(), calls)


if __name__ == "__main__":
    unittest.main()
