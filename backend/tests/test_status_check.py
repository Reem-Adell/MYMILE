"""
COMPLIANCE_VIOLATION handling, full (sanitized) PayPal error logging, and the
"Check payment status" endpoint (lookup first, never a blind re-capture).

Run from backend/:
    venv\\Scripts\\python -m unittest discover -s tests -v
"""
from tests import _env  # noqa: F401  (must precede any app.* import)

import json
import threading
import time
import unittest
from unittest import mock

import requests

from tests import test_paypal_payments as base
from app.services import paypal_service

order_body = base.order_body
CAPTURE = "/capture"


def compliance_violation(_oid=None, _req=None):
    """A complete PayPal 422 body for COMPLIANCE_VIOLATION (shape per the SDK's ErrorException)."""
    return 422, {
        "name": "UNPROCESSABLE_ENTITY",
        "message": "The requested action could not be performed, semantically incorrect, or failed business validation.",
        "debug_id": "dbgcompliance42",
        "details": [{"issue": "COMPLIANCE_VIOLATION",
                     "description": "Transaction is declined due to compliance violation.",
                     "field": "/purchase_units/0", "value": "mymile-premium-pass", "location": "body"}],
        "links": [{"href": "https://developer.paypal.com/docs/api/orders/v2/#error-COMPLIANCE_VIOLATION",
                   "rel": "information_link", "method": "GET"}],
    }


def approved(order_id, user_id):
    return {"id": order_id, "status": "APPROVED", "purchase_units": [
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

    def _refresh(self, user, order_id):
        return self.api.post(f"/api/payments/paypal/orders/{order_id}/refresh", headers=user["headers"])

    def _post_order(self, user):
        return self.api.post("/api/payments/paypal/orders", headers=user["headers"])

    def _captures(self):
        return self.fake.count("POST", CAPTURE)

    def _lookups(self, oid):
        return self.fake.count("GET", oid)

    def _allow_resend(self, oid):
        paypal_service._last_capture_sent.pop(oid, None)  # as if the cooldown elapsed

    def _make_uncertain_approved(self):
        """The real incident's state: buyer approved, capture answer inconclusive,
        lookup shows APPROVED without a capture -> UNCERTAIN."""
        oid = self._create(self.user_a)
        self._capture_returns(lambda o, req: base.paypal_error(422, "SOMETHING_INCONCLUSIVE"))
        self.fake.get_handler = lambda o: (200, approved(o, self.user_a["id"]))
        r = self._capture(self.user_a, oid)
        self.assertEqual((r.status_code, r.json()["status"]), (202, "UNCERTAIN"))
        return oid


# ------------------------------------------------- error parsing & logging ---
class PayPalErrorDetailsTest(_Base):

    def test_full_422_error_is_logged_without_secrets(self):
        oid = self._create(self.user_a)
        self._capture_returns(compliance_violation)
        with self.assertLogs("app.services.paypal_service", level="WARNING") as logs:
            self._capture(self.user_a, oid)
        line = next(l for l in logs.output if "paypal_error=" in l)
        info = json.loads(line.split("paypal_error=", 1)[1])
        self.assertEqual(info["http"], 422)
        self.assertEqual(info["name"], "UNPROCESSABLE_ENTITY")
        self.assertEqual(info["debug_id"], "dbgcompliance42")
        self.assertEqual(info["details"], [{
            "issue": "COMPLIANCE_VIOLATION", "description": "Transaction is declined due to compliance violation.",
            "field": "/purchase_units/0", "value": "mymile-premium-pass", "location": "body"}])
        joined = "\n".join(logs.output)
        for secret in (base.TEST_SECRET, base.TEST_ACCESS_TOKEN, "Bearer", "Authorization"):
            self.assertNotIn(secret, joined)

    def test_describe_handles_missing_fields_and_long_values(self):
        class Detail:
            issue, description, field, location = "X", None, None, None
            value = "v" * 500

        class Err(Exception):
            response_code, name, message, debug_id = 422, None, None, None
            details = [Detail()]

            class response:  # noqa: N801  (mimics the SDK attribute)
                headers = {"Paypal-Debug-Id": "hdr-debug-1", "Authorization": "Bearer should-not-appear"}
        info = paypal_service.describe_paypal_error(Err())
        self.assertEqual(info["debug_id"], "hdr-debug-1")
        self.assertEqual(info["details"][0]["issue"], "X")
        self.assertLessEqual(len(info["details"][0]["value"]), 103)
        self.assertNotIn("should-not-appear", json.dumps(info))


# ------------------------------------------------------ COMPLIANCE_VIOLATION ---
class ComplianceViolationTest(_Base):

    def test_compliance_violation_on_capture_is_a_final_decline(self):
        oid = self._create(self.user_a)
        self._capture_returns(compliance_violation)
        r = self._capture(self.user_a, oid)
        body = r.json()
        self.assertEqual((r.status_code, body["code"], body["status"], body["decline_issue"]),
                         (402, "PAYMENT_DECLINED", "DECLINED", "COMPLIANCE_VIOLATION"))
        self.assertFalse(body["premium_granted"])
        self.assertEqual(self._payment(oid)["status"], "DECLINED")
        self._assert_not_premium(self.user_a)
        calls = self._captures()
        self.assertEqual(self._capture(self.user_a, oid).status_code, 402)
        self.assertEqual(self._refresh(self.user_a, oid).status_code, 402)
        self.assertEqual(self._captures(), calls, "a declined order is never captured again")
        new = self._post_order(self.user_a)
        self.assertEqual(new.status_code, 201, "a new attempt is allowed after a confirmed decline")
        self.assertNotEqual(new.json()["order_id"], oid)

    def test_other_unknown_422_is_not_treated_as_a_decline(self):
        oid = self._make_uncertain_approved()
        self.assertEqual(self._payment(oid)["status"], "UNCERTAIN")
        self.assertEqual(self._post_order(self.user_a).status_code, 409, "still blocks new orders")


# ---------------------------------------------------- "Check payment status" ---
class StatusCheckTest(_Base):

    def test_status_check_looks_up_and_does_not_recapture_during_cooldown(self):
        oid = self._make_uncertain_approved()
        captures, lookups = self._captures(), self._lookups(oid)
        for _ in range(3):  # repeated clicks right after the failed capture
            r = self._refresh(self.user_a, oid)
            self.assertEqual((r.status_code, r.json()["status"]), (202, "UNCERTAIN"))
        self.assertEqual(self._captures(), captures, "no capture re-sent while cooling down")
        self.assertEqual(self._lookups(oid), lookups + 3, "each click is a lookup")
        self.assertEqual(self._post_order(self.user_a).status_code, 409)
        self._assert_not_premium(self.user_a)

    def test_recorded_transport_error_allows_one_same_key_retry(self):
        # Unknown outcome RECORDED (timeout): the status check may re-send once.
        oid = self._create(self.user_a)

        def timeout(o, req):
            raise requests.exceptions.ReadTimeout("simulated")
        self._capture_returns(timeout)
        self.fake.get_handler = lambda o: (200, approved(o, self.user_a["id"]))
        self.assertEqual(self._capture(self.user_a, oid).json()["status"], "UNCERTAIN")
        self.assertEqual(self._payment(oid)["last_capture_result"], "TRANSPORT_ERROR")
        self._allow_resend(oid)
        self._capture_returns(compliance_violation)
        r = self._refresh(self.user_a, oid)
        self.assertEqual((r.status_code, r.json()["status"], r.json()["decline_issue"]),
                         (402, "DECLINED", "COMPLIANCE_VIOLATION"))
        keys = {h.get("PayPal-Request-Id") for m, p, h, _ in self.fake.calls if p.endswith(CAPTURE)}
        self.assertEqual(keys, {f"mymile-capture-{oid}"}, "same idempotency key, never a new one")
        self._assert_not_premium(self.user_a)

    def test_status_check_grants_only_a_verified_completed_capture(self):
        oid = self._make_uncertain_approved()
        self.fake.get_handler = lambda o: (200, order_body(o, self.user_a["id"]))
        captures = self._captures()
        r = self._refresh(self.user_a, oid)
        self.assertEqual((r.status_code, r.json()["premium_granted"]), (200, True))
        self.assertEqual(self._captures(), captures, "granted from the lookup, no new capture")
        lookups = self._lookups(oid)
        again = self._refresh(self.user_a, oid)
        self.assertEqual((again.status_code, again.json()["already_processed"]), (200, True))
        self.assertEqual(self._lookups(oid), lookups, "completed orders are answered locally")

    def test_approved_order_is_never_treated_as_paid(self):
        oid = self._make_uncertain_approved()
        self._allow_resend(oid)
        self._capture_returns(lambda o, req: base.paypal_error(422, "SOMETHING_INCONCLUSIVE"))
        r = self._refresh(self.user_a, oid)
        self.assertEqual((r.status_code, r.json()["status"]), (202, "UNCERTAIN"))
        self._assert_not_premium(self.user_a)

    def test_failed_lookup_changes_nothing(self):
        oid = self._make_uncertain_approved()
        self.fake.get_handler = lambda o: (503, {"name": "SERVICE_UNAVAILABLE"})
        captures = self._captures()
        r = self._refresh(self.user_a, oid)
        self.assertEqual((r.status_code, r.json()["status"]), (202, "UNCERTAIN"))
        self.assertEqual(self._captures(), captures)

    def test_pending_payment_is_not_recaptured(self):
        oid = self._create(self.user_a)
        self._capture_returns(lambda o, req: (201, order_body(o, self.user_a["id"], capture_status="PENDING")))
        self._capture(self.user_a, oid)
        self._allow_resend(oid)
        self.fake.get_handler = lambda o: (200, approved(o, self.user_a["id"]))
        captures = self._captures()
        r = self._refresh(self.user_a, oid)
        self.assertEqual((r.status_code, r.json()["status"]), (202, "PENDING"))
        self.assertEqual(self._captures(), captures)

    def test_created_and_terminal_orders_make_no_paypal_call(self):
        oid = self._create(self.user_a)
        calls = len(self.fake.calls)
        r = self._refresh(self.user_a, oid)
        self.assertEqual((r.status_code, r.json()["code"]), (409, "ORDER_NOT_APPROVED"))
        self.assertEqual(len(self.fake.calls), calls)

    def test_status_check_is_owner_only_and_authenticated(self):
        oid = self._create(self.user_a)
        self.assertEqual(self._refresh(self.user_b, oid).status_code, 404)
        self.assertEqual(self.api.post(f"/api/payments/paypal/orders/{oid}/refresh").status_code, 401)

    def test_concurrent_status_checks_make_a_single_lookup(self):
        oid = self._make_uncertain_approved()
        lookups = self._lookups(oid)

        def slow_lookup(o):
            time.sleep(0.5)
            return 200, approved(o, self.user_a["id"])
        self.fake.get_handler = slow_lookup
        n = 4
        barrier = threading.Barrier(n)
        results = [None] * n

        def worker(i):
            barrier.wait(timeout=10)
            results[i] = self._refresh(self.user_a, oid)
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
        [t.start() for t in threads]
        [t.join(timeout=60) for t in threads]
        statuses = sorted(r.json()["status"] for r in results)
        self.assertEqual(self._lookups(oid), lookups + 1, "one PayPal lookup for simultaneous clicks")
        self.assertEqual(statuses.count("IN_PROGRESS"), n - 1, statuses)
        self.assertEqual(self._payment(oid)["status"], "UNCERTAIN")


if __name__ == "__main__":
    unittest.main()
