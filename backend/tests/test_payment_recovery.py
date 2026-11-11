"""
Phase 3.3-A: payment recovery, duplicate-order protection, confirmed expiry,
public pricing, removed fake upgrade, CORS.

Run from backend/:
    venv\\Scripts\\python -m unittest discover -s tests -v

Reuses the fake-PayPal transport and helpers of test_paypal_payments (the real
SDK client runs; only the HTTP adapter is fake). Referenced through the module
so its test classes are not collected twice.
"""
from tests import _env  # noqa: F401  (must precede any app.* import)

import unittest
from datetime import timedelta
from unittest import mock

import requests

from tests import test_paypal_payments as base
from app.core import database, premium
from app.core.config import settings
from app.services import paypal_service

order_body, paypal_error = base.order_body, base.paypal_error


class PaymentRecoveryTest(unittest.TestCase):
    # Same isolated setup + helpers as the existing PayPal tests.
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

    # -- helpers --
    def _post_order(self, user):
        return self.api.post("/api/payments/paypal/orders", headers=user["headers"])

    def _status(self, user, order_id):
        return self.api.get(f"/api/payments/paypal/orders/{order_id}", headers=user["headers"])

    def _unresolved(self, user):
        r = self.api.get("/api/payments/paypal/orders/unresolved", headers=user["headers"])
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["order"]

    def _creates(self):
        return self.fake.count("POST", "/v2/checkout/orders")

    def _timeout_then_unknown(self):
        def timeout(oid, req):
            raise requests.exceptions.ReadTimeout("simulated")
        self._capture_returns(timeout)
        self.fake.get_handler = lambda oid: (503, {"name": "SERVICE_UNAVAILABLE"})

    def _age(self, order_id, minutes):
        old = premium.utc_now() - timedelta(minutes=minutes)
        with database.connect() as conn:
            conn.execute("UPDATE payments SET created_at = ? WHERE order_id = ?",
                         (old.isoformat(timespec="seconds"), order_id))

    # ---------------------------------------------------------- status ---
    def test_status_endpoint_is_owner_only(self):
        oid = self._create(self.user_a)
        r = self._status(self.user_a, oid)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual((body["order_id"], body["status"], body["amount"], body["currency"]),
                         (oid, "CREATED", "9.00", "USD"))
        self.assertEqual((body["blocking"], body["resumable"]), (False, True))
        self.assertNotIn("capture_id", body)
        self.assertEqual(self._status(self.user_b, oid).status_code, 404)       # not yours
        self.assertEqual(self._status(self.user_a, "NOPE123").status_code, 404)  # unknown
        self.assertEqual(self.api.get(f"/api/payments/paypal/orders/{oid}").status_code, 401)
        self.assertEqual(self.fake.count("GET", oid), 0, "status must not call PayPal")

    def test_status_after_completion_includes_premium_until(self):
        oid = self._create(self.user_a)
        self._capture_returns(lambda o, req: (201, order_body(o, self.user_a["id"])))
        until = self._capture(self.user_a, oid).json()["premium_until"]
        body = self._status(self.user_a, oid).json()
        self.assertEqual((body["status"], body["premium_until"], body["blocking"]), ("COMPLETED", until, False))

    # ------------------------------------------------------- unresolved ---
    def test_unresolved_endpoint(self):
        self.assertIsNone(self._unresolved(self.user_a))
        oid = self._create(self.user_a)
        u = self._unresolved(self.user_a)
        self.assertEqual((u["order_id"], u["status"], u["blocking"], u["resumable"]), (oid, "CREATED", False, True))
        self._timeout_then_unknown()
        self._capture(self.user_a, oid)
        u = self._unresolved(self.user_a)
        self.assertEqual((u["order_id"], u["status"], u["blocking"]), (oid, "UNCERTAIN", True))
        self.assertIsNone(self._unresolved(self.user_b), "never another user's order")
        self.assertEqual(self.api.get("/api/payments/paypal/orders/unresolved").status_code, 401)

    def test_old_created_order_is_not_unresolved(self):
        oid = self._create(self.user_a)
        self._age(oid, 31)
        self.assertIsNone(self._unresolved(self.user_a))

    # ------------------------------------------------ duplicate orders ---
    def test_recent_created_order_is_reused(self):
        first = self._post_order(self.user_a)
        second = self._post_order(self.user_a)
        self.assertEqual((first.status_code, second.status_code), (201, 200))
        self.assertEqual(first.json()["order_id"], second.json()["order_id"])
        self.assertEqual((first.json()["reused"], second.json()["reused"]), (False, True))
        self.assertEqual(self._creates(), 1, "PayPal create must be called once")

    def test_created_order_older_than_30_minutes_is_not_reused(self):
        first = self._post_order(self.user_a).json()["order_id"]
        self._age(first, 31)
        second = self._post_order(self.user_a)
        self.assertEqual(second.status_code, 201)
        self.assertNotEqual(second.json()["order_id"], first)
        self.assertEqual(self._creates(), 2)

    def test_reuse_is_per_user(self):
        a = self._post_order(self.user_a).json()["order_id"]
        b = self._post_order(self.user_b).json()["order_id"]
        self.assertNotEqual(a, b)

    def test_uncertain_order_blocks_new_orders(self):
        oid = self._create(self.user_a)
        self._timeout_then_unknown()
        self._capture(self.user_a, oid)
        r = self._post_order(self.user_a)
        self.assertEqual(r.status_code, 409, r.text)
        body = r.json()
        self.assertEqual((body["order_id"], body["status"]), (oid, "UNCERTAIN"))
        self.assertIn("do not pay again", body["detail"].lower())
        self.assertEqual(self._creates(), 1, "no replacement order may be created")

    def test_pending_order_blocks_new_orders(self):
        oid = self._create(self.user_a)
        self._capture_returns(lambda o, req: (201, order_body(o, self.user_a["id"], capture_status="PENDING")))
        self._capture(self.user_a, oid)
        r = self._post_order(self.user_a)
        self.assertEqual((r.status_code, r.json()["order_id"], r.json()["status"]), (409, oid, "PENDING"))
        self.assertEqual(self._creates(), 1)

    def test_blocking_order_blocks_even_when_old(self):
        oid = self._create(self.user_a)
        self._timeout_then_unknown()
        self._capture(self.user_a, oid)
        self._age(oid, 60 * 24)
        self.assertEqual(self._post_order(self.user_a).status_code, 409)

    def test_declined_order_does_not_block(self):
        oid = self._create(self.user_a)
        self._capture_returns(lambda o, req: paypal_error(422, "INSTRUMENT_DECLINED"))
        self.assertEqual(self._capture(self.user_a, oid).status_code, 402)
        r = self._post_order(self.user_a)
        self.assertIn(r.status_code, (200, 201))

    # -------------------------------------------------------- recovery ---
    def test_capture_attempt_marks_uncertain_before_calling_paypal(self):
        oid = self._create(self.user_a)
        seen = {}

        def capture(o, req):
            seen["status_during_capture"] = self._payment(o)["status"]
            raise requests.exceptions.ConnectionError("process died / network lost")
        self._capture_returns(capture)
        self.fake.get_handler = lambda o: (503, {})
        self._capture(self.user_a, oid)
        self.assertEqual(seen["status_during_capture"], "UNCERTAIN")
        self.assertEqual(self._payment(oid)["status"], "UNCERTAIN")
        self._assert_not_premium(self.user_a)

    def test_uncertain_payment_recovers_on_the_same_order(self):
        oid = self._create(self.user_a)
        self._timeout_then_unknown()
        self.assertEqual(self._capture(self.user_a, oid).json()["status"], "UNCERTAIN")
        # Later retry of the SAME order: PayPal had captured it.
        self._capture_returns(lambda o, req: paypal_error(422, "ORDER_ALREADY_CAPTURED"))
        self.fake.get_handler = lambda o: (200, order_body(o, self.user_a["id"]))
        r = self._capture(self.user_a, oid)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["premium_granted"])
        self.assertEqual(self._creates(), 1, "recovery never creates another order")
        ids = {h.get("PayPal-Request-Id") for m, p, h, _ in self.fake.calls if p.endswith("/capture")}
        self.assertEqual(ids, {f"mymile-capture-{oid}"})
        self.assertIsNone(self._unresolved(self.user_a))

    def test_order_not_approved_returns_to_created_and_is_resumable(self):
        oid = self._create(self.user_a)
        self._capture_returns(lambda o, req: paypal_error(422, "ORDER_NOT_APPROVED"))
        self.assertEqual(self._capture(self.user_a, oid).status_code, 409)
        self.assertEqual(self._payment(oid)["status"], "CREATED")
        r = self._post_order(self.user_a)
        self.assertEqual((r.status_code, r.json()["order_id"]), (200, oid))  # same order continued

    def test_auth_failure_before_sending_undoes_the_mark(self):
        from apimatic_core.exceptions.auth_validation_exception import AuthValidationException
        oid = self._create(self.user_a)
        with mock.patch.object(self.paypal.orders, "capture_order",
                               side_effect=AuthValidationException("token")):
            self.assertEqual(self._capture(self.user_a, oid).status_code, 503)
        self.assertEqual(self._payment(oid)["status"], "CREATED")

    def test_generic_paypal_error_then_lookup_without_capture_stays_uncertain(self):
        oid = self._create(self.user_a)
        self._capture_returns(lambda o, req: paypal_error(422, "SOMETHING_UNEXPECTED"))
        self.fake.get_handler = lambda o: (200, {"id": o, "status": "CREATED", "purchase_units": [
            {"reference_id": "mymile-premium-pass", "custom_id": self.user_a["id"],
             "amount": {"currency_code": "USD", "value": "9.00"}}]})
        r = self._capture(self.user_a, oid)
        # A lookup without a capture is not proof the capture was never processed.
        self.assertEqual((r.status_code, r.json()["status"]), (202, "UNCERTAIN"))
        self.assertEqual(self._payment(oid)["status"], "UNCERTAIN")
        self.assertEqual(self._post_order(self.user_a).status_code, 409, "still blocks new orders")
        self._assert_not_premium(self.user_a)

    # ------------------------------------------------- confirmed expiry ---
    def _gone(self, o, req):
        return 404, {"name": "RESOURCE_NOT_FOUND", "message": "x", "details": [{"issue": "INVALID_RESOURCE_ID"}]}

    def test_expiry_is_recorded_only_when_paypal_confirms_it(self):
        oid = self._create(self.user_a)
        self._capture_returns(self._gone)
        self.fake.get_handler = lambda o: (404, {"name": "RESOURCE_NOT_FOUND"})
        r = self._capture(self.user_a, oid)
        self.assertEqual((r.status_code, r.json()["status"]), (410, "EXPIRED"))
        self.assertEqual(self._payment(oid)["status"], "EXPIRED")
        self._assert_not_premium(self.user_a)
        # Further captures don't call PayPal; a new order is allowed (not reused).
        calls = self.fake.count("POST", "/capture")
        self.assertEqual(self._capture(self.user_a, oid).status_code, 410)
        self.assertEqual(self.fake.count("POST", "/capture"), calls)
        new = self._post_order(self.user_a)
        self.assertEqual(new.status_code, 201)
        self.assertNotEqual(new.json()["order_id"], oid)

    def test_not_found_on_capture_but_lookup_fails_is_not_expiry(self):
        oid = self._create(self.user_a)
        self._capture_returns(self._gone)

        def lookup_down(o):
            raise requests.exceptions.ReadTimeout("simulated")
        self.fake.get_handler = lookup_down
        r = self._capture(self.user_a, oid)
        self.assertEqual((r.status_code, r.json()["status"]), (202, "UNCERTAIN"))
        self.assertEqual(self._payment(oid)["status"], "UNCERTAIN")
        self.assertEqual(self._post_order(self.user_a).status_code, 409, "still blocks new orders")

    def test_not_found_on_capture_but_order_was_captured_grants(self):
        oid = self._create(self.user_a)
        self._capture_returns(self._gone)
        self.fake.get_handler = lambda o: (200, order_body(o, self.user_a["id"]))
        r = self._capture(self.user_a, oid)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["premium_granted"])

    def test_lookup_404_without_expiry_hint_is_not_expiry(self):
        oid = self._create(self.user_a)
        self._capture_returns(lambda o, req: (500, {"name": "INTERNAL_SERVER_ERROR"}))
        self.fake.get_handler = lambda o: (404, {"name": "RESOURCE_NOT_FOUND"})
        r = self._capture(self.user_a, oid)
        self.assertEqual((r.status_code, r.json()["status"]), (202, "UNCERTAIN"))

    def test_voided_order_is_confirmed_expired(self):
        oid = self._create(self.user_a)
        self._capture_returns(lambda o, req: paypal_error(422, "ORDER_CANNOT_BE_CAPTURED"))
        self.fake.get_handler = lambda o: (200, {"id": o, "status": "VOIDED", "purchase_units": [
            {"reference_id": "mymile-premium-pass", "custom_id": self.user_a["id"],
             "amount": {"currency_code": "USD", "value": "9.00"}}]})
        r = self._capture(self.user_a, oid)
        self.assertEqual((r.status_code, r.json()["status"]), (410, "EXPIRED"))


class PublicApiChangesTest(unittest.TestCase):
    setUp = base.PayPalPaymentsTest.setUp
    _register = base.PayPalPaymentsTest._register

    @classmethod
    def setUpClass(cls):
        _env.ensure_isolated_db()

    def test_public_pricing_comes_from_settings(self):
        r = self.api.get("/api/subscriptions/plans")  # no auth
        self.assertEqual(r.status_code, 200)
        p = r.json()["premium"]
        self.assertEqual((p["price"], p["currency"], p["duration_days"], p["billing"], p["one_time"], p["auto_renew"]),
                         ("9.00", "USD", 30, "one-time", True, False))
        self.assertNotIn("per month", r.text)
        with mock.patch.object(settings, "PREMIUM_PRICE", "12.50"), \
             mock.patch.object(settings, "PREMIUM_DURATION_DAYS", 45):
            p = self.api.get("/api/subscriptions/plans").json()["premium"]
        self.assertEqual((p["price"], p["duration_days"]), ("12.50", 45))

    # -- payment availability (what decides whether the PayPal button is shown) --
    def test_configured_paypal_is_reported_without_exposing_secrets(self):
        health = self.api.get("/api/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["payments"], {"paypal_configured": True, "paypal_environment": "sandbox"})
        cfg = self.api.get("/api/payments/paypal/config", headers=self.user_a["headers"]).json()
        self.assertEqual((cfg["enabled"], cfg["client_id"], cfg["environment"]), (True, base.TEST_CLIENT_ID, "sandbox"))
        for text in (health.text, str(cfg)):
            self.assertNotIn(base.TEST_SECRET, text)
        self.assertNotIn(base.TEST_CLIENT_ID, health.text, "health never shows the client id")

    def test_missing_credentials_keep_payments_unavailable(self):
        for client_id, secret in ((None, base.SecretStr(base.TEST_SECRET)), (base.TEST_CLIENT_ID, None),
                                  ("   ", base.SecretStr(base.TEST_SECRET)), (base.TEST_CLIENT_ID, base.SecretStr(" "))):
            with mock.patch.object(settings, "PAYPAL_CLIENT_ID", client_id), \
                 mock.patch.object(settings, "PAYPAL_CLIENT_SECRET", secret):
                self.assertFalse(self.api.get("/api/health").json()["payments"]["paypal_configured"])
                cfg = self.api.get("/api/payments/paypal/config", headers=self.user_a["headers"]).json()
                self.assertEqual((cfg["enabled"], cfg["client_id"]), (False, None))

    def test_start_script_restarts_backend_when_env_changes(self):
        script = (_env.BACKEND_DIR.parent / "start-backend.bat").read_text(encoding="utf-8")
        self.assertIn("--reload-include .env", script)

    def test_fake_upgrade_is_gone(self):
        for headers in ({}, self.user_a["headers"]):
            r = self.api.post("/api/subscriptions/upgrade", json={"plan": "premium"}, headers=headers)
            self.assertEqual(r.status_code, 410)
        me = self.api.get("/api/auth/me", headers=self.user_a["headers"]).json()
        self.assertEqual(me["plan"], "free")

    def test_cors_allows_only_the_vite_dev_origins(self):
        def preflight(origin):
            return self.api.options("/api/health", headers={
                "Origin": origin, "Access-Control-Request-Method": "GET"})
        for origin in ("http://localhost:5173", "http://127.0.0.1:5173"):
            self.assertEqual(preflight(origin).headers.get("access-control-allow-origin"), origin)
        for origin in ("http://evil.example", "http://localhost:3000", "null"):
            self.assertIsNone(preflight(origin).headers.get("access-control-allow-origin"), origin)
        simple = self.api.get("/api/health", headers={"Origin": "http://evil.example"})
        self.assertIsNone(simple.headers.get("access-control-allow-origin"))
        self.assertNotIn("*", settings.BACKEND_CORS_ORIGINS)


if __name__ == "__main__":
    unittest.main()
