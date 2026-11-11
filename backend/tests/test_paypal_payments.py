"""
PayPal Premium pass tests (no network, no real PayPal, no real users.db).

Run from backend/:
    venv\\Scripts\\python -m unittest discover -s tests -v

PayPal is faked BELOW the SDK: a real PaypalServersdkClient is built with a
requests.Session whose adapter answers the OAuth token, create, capture and
get-order endpoints. So the SDK's own serialization and error mapping run.
"""
import json
import logging
import os
import sqlite3
import subprocess
import sys
import threading
import time
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

# Shared isolated environment (temp DB + random SECRET_KEY). Must be imported
# BEFORE any `app.*` module; it raises if the real users.db would be used.
from tests import _env  # noqa: E402

_TMP = _env.TMP_DIR

import requests  # noqa: E402
from pydantic import SecretStr  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from paypalserversdk.configuration import Environment  # noqa: E402
from paypalserversdk.http.auth.o_auth_2 import ClientCredentialsAuthCredentials  # noqa: E402
from paypalserversdk.paypal_serversdk_client import PaypalServersdkClient  # noqa: E402

from app.core import database  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.main import app  # noqa: E402
from app.services import paypal_service  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parents[1]
TEST_CLIENT_ID = "test-client-id"
TEST_SECRET = "test-secret-MUST-NOT-LEAK"
TEST_ACCESS_TOKEN = "access-token-MUST-NOT-LEAK"


# ------------------------------------------------------------ fake PayPal ---
class FakePayPal(requests.adapters.HTTPAdapter):
    """Routes by path. Handlers return (status, body_dict) or raise."""

    def __init__(self):
        super().__init__()
        self.calls = []
        self._n = 0                   # number of distinct orders created
        self.create_replays = {}      # PayPal-Request-Id -> created order body
        self._create_guard = threading.Lock()
        self.capture_handler = None   # fn(order_id, request) -> (status, body)
        self.get_handler = None       # fn(order_id) -> (status, body)

    def send(self, request, **kwargs):
        path = requests.utils.urlparse(request.url).path
        self.calls.append((request.method, path, dict(request.headers), request.body))
        if path == "/v1/oauth2/token":
            return self._resp(request, 200, {"access_token": TEST_ACCESS_TOKEN,
                                             "token_type": "Bearer", "expires_in": 3600})
        if request.method == "POST" and path == "/v2/checkout/orders":
            # Models PayPal-Request-Id idempotency: a repeated key returns the
            # order already created for it (HTTP 200) instead of a new one.
            key = request.headers.get("PayPal-Request-Id")
            with self._create_guard:
                if key and key in self.create_replays:
                    return self._resp(request, 200, self.create_replays[key])
                self._n += 1
                oid = f"TESTORDER{self._n:04d}{uuid.uuid4().hex[:6].upper()}"
                body = {"id": oid, "status": "CREATED",
                        "links": [{"href": f"https://www.sandbox.paypal.com/checkoutnow?token={oid}",
                                   "rel": "approve", "method": "GET"}]}
                if key:
                    self.create_replays[key] = body
            return self._resp(request, 201, body)
        if request.method == "POST" and path.endswith("/capture"):
            oid = path.split("/")[-2]
            status, body = self.capture_handler(oid, request)
            return self._resp(request, status, body)
        if request.method == "GET" and path.startswith("/v2/checkout/orders/"):
            oid = path.split("/")[-1]
            status, body = self.get_handler(oid)
            return self._resp(request, status, body)
        return self._resp(request, 404, {"name": "RESOURCE_NOT_FOUND"})

    @staticmethod
    def _resp(request, status, body):
        r = requests.Response()
        r.status_code = status
        r._content = json.dumps(body).encode()
        r.headers["Content-Type"] = "application/json"
        r.request = request
        r.url = request.url
        return r

    def count(self, method, suffix):
        return sum(1 for m, p, _, _ in self.calls if m == method and p.endswith(suffix))


def order_body(order_id, user_id, *, order_status="COMPLETED", capture_status="COMPLETED",
               value="9.00", currency="USD", capture_id=None, unit_custom_id=None):
    capture = {"id": capture_id or f"CAP{order_id}", "status": capture_status,
               "amount": {"currency_code": currency, "value": value},
               "custom_id": user_id, "final_capture": True}
    return {"id": order_id, "status": order_status, "intent": "CAPTURE",
            "purchase_units": [{"reference_id": "mymile-premium-pass",
                                "custom_id": unit_custom_id or user_id,
                                "amount": {"currency_code": currency, "value": value},
                                "payments": {"captures": [capture]}}]}


def paypal_error(status, issue):
    return status, {"name": "UNPROCESSABLE_ENTITY", "message": "fail", "debug_id": "dbg123",
                    "details": [{"issue": issue, "description": "x"}]}


# ------------------------------------------------------------------ tests ---
class PayPalPaymentsTest(unittest.TestCase):

    def setUp(self):
        self.fake = FakePayPal()
        session = requests.Session()
        session.mount("https://", self.fake)
        self.paypal = PaypalServersdkClient(
            environment=Environment.SANDBOX,
            client_credentials_auth_credentials=ClientCredentialsAuthCredentials(
                o_auth_client_id=TEST_CLIENT_ID, o_auth_client_secret=TEST_SECRET),
            http_client_instance=session,
            max_retries=0,
        )
        patches = [
            mock.patch.object(paypal_service, "get_paypal_client", lambda: self.paypal),
            mock.patch.object(settings, "PAYPAL_CLIENT_ID", TEST_CLIENT_ID),
            mock.patch.object(settings, "PAYPAL_CLIENT_SECRET", SecretStr(TEST_SECRET)),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.api = TestClient(app)
        self.user_a = self._register("a")
        self.user_b = self._register("b")

    # -- helpers --
    def _register(self, tag):
        email = f"{tag}-{uuid.uuid4().hex[:8]}@test.example"
        r = self.api.post("/api/auth/register", json={"name": tag, "email": email, "password": "password123"})
        self.assertEqual(r.status_code, 201, r.text)
        data = r.json()
        return {"id": data["user"]["id"], "email": email,
                "headers": {"Authorization": f"Bearer {data['access_token']}"}}

    def _create(self, user, json_body=None):
        r = self.api.post("/api/payments/paypal/orders", headers=user["headers"], json=json_body)
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()["order_id"]

    def _capture(self, user, order_id):
        return self.api.post(f"/api/payments/paypal/orders/{order_id}/capture", headers=user["headers"])

    def _db(self, sql, *args):
        with database.connect() as conn:
            return conn.execute(sql, args).fetchone()

    def _user_row(self, user):
        return self._db("SELECT plan, premium_until FROM users WHERE id = ?", user["id"])

    def _payment(self, order_id):
        return self._db("SELECT * FROM payments WHERE order_id = ?", order_id)

    def _assert_not_premium(self, user):
        row = self._user_row(user)
        self.assertEqual(row["plan"], "free")
        self.assertIsNone(row["premium_until"])

    def _capture_returns(self, fn):
        self.fake.capture_handler = fn

    # -- authentication --
    def test_endpoints_require_authentication(self):
        for method, path in [("get", "/api/payments/paypal/config"),
                             ("post", "/api/payments/paypal/orders"),
                             ("post", "/api/payments/paypal/orders/ABC123/capture")]:
            self.assertEqual(getattr(self.api, method)(path).status_code, 401, f"guest {path}")
            bad = {"Authorization": "Bearer not-a-real-token"}
            self.assertEqual(getattr(self.api, method)(path, headers=bad).status_code, 401, f"bad token {path}")
        self.assertEqual(self.fake.calls, [], "PayPal must not be called for unauthenticated requests")

    def test_config_exposes_no_secret(self):
        r = self.api.get("/api/payments/paypal/config", headers=self.user_a["headers"])
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["client_id"], TEST_CLIENT_ID)
        self.assertEqual((body["price"], body["currency"], body["duration_days"]), ("9.00", "USD", 30))
        self.assertTrue(body["one_time"])
        self.assertFalse(body["auto_renew"])
        self.assertEqual(body["environment"], "sandbox")
        self.assertNotIn(TEST_SECRET, r.text)
        self.assertNotIn("secret", r.text.lower())

    # -- create order --
    def test_create_order_uses_backend_values_only(self):
        tampered = {"amount": "0.01", "price": "0.01", "currency": "EUR", "user_id": self.user_b["id"],
                    "plan": "lifetime", "duration_days": 9999}
        order_id = self._create(self.user_a, json_body=tampered)
        _, _, _, sent = next(c for c in self.fake.calls if c[1] == "/v2/checkout/orders")
        unit = json.loads(sent)["purchase_units"][0]
        self.assertEqual(json.loads(sent)["intent"], "CAPTURE")
        self.assertEqual(unit["amount"], {"currency_code": "USD", "value": "9.00"})
        self.assertEqual(unit["custom_id"], self.user_a["id"])
        p = self._payment(order_id)
        self.assertEqual((p["user_id"], p["amount"], p["currency"], p["status"]),
                         (self.user_a["id"], "9.00", "USD", "CREATED"))
        self._assert_not_premium(self.user_a)  # creating an order grants nothing

    # -- capture: success + duplicates --
    def test_successful_capture_grants_30_days(self):
        order_id = self._create(self.user_a)
        self._capture_returns(lambda oid, req: (201, order_body(oid, self.user_a["id"])))
        before = datetime.now(timezone.utc)
        r = self._capture(self.user_a, order_id)
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["status"], "COMPLETED")
        self.assertTrue(body["premium_granted"])
        until = datetime.fromisoformat(body["premium_until"])
        self.assertAlmostEqual((until - before).total_seconds(), timedelta(days=30).total_seconds(), delta=120)
        row = self._user_row(self.user_a)
        self.assertEqual((row["plan"], row["premium_until"]), ("premium", body["premium_until"]))
        p = self._payment(order_id)
        self.assertEqual(p["status"], "COMPLETED")
        self.assertEqual(p["capture_id"], f"CAP{order_id}")
        self.assertIsNotNone(p["completed_at"])
        me = self.api.get("/api/auth/me", headers=self.user_a["headers"]).json()
        self.assertEqual(me["plan"], "premium")

    def test_duplicate_capture_grants_once(self):
        order_id = self._create(self.user_a)
        self._capture_returns(lambda oid, req: (201, order_body(oid, self.user_a["id"])))
        first = self._capture(self.user_a, order_id).json()
        second = self._capture(self.user_a, order_id)
        self.assertEqual(second.status_code, 200)
        self.assertTrue(second.json()["already_processed"])
        self.assertEqual(second.json()["premium_until"], first["premium_until"])
        self.assertEqual(self._user_row(self.user_a)["premium_until"], first["premium_until"])
        self.assertEqual(self.fake.count("POST", "/capture"), 1, "second request must not hit PayPal")

    def test_grant_is_idempotent_at_db_level(self):
        order_id = self._create(self.user_a)
        until1, granted1 = paypal_service._grant(order_id, self.user_a["id"], "CAP-X")
        until2, granted2 = paypal_service._grant(order_id, self.user_a["id"], "CAP-X")
        self.assertTrue(granted1)
        self.assertFalse(granted2)
        self.assertEqual(until1, until2)

    def test_same_capture_id_cannot_grant_two_orders(self):
        o1 = self._create(self.user_a)
        # Age o1 past the 30-minute reuse window so a second, distinct order is created.
        with database.connect() as conn:
            conn.execute("UPDATE payments SET created_at = '2000-01-01T00:00:00+00:00' WHERE order_id = ?", (o1,))
        o2 = self._create(self.user_a)
        self.assertNotEqual(o1, o2)
        paypal_service._grant(o1, self.user_a["id"], "CAP-SHARED")
        until = self._user_row(self.user_a)["premium_until"]
        with self.assertRaises(paypal_service.PaymentError) as ctx:
            paypal_service._grant(o2, self.user_a["id"], "CAP-SHARED")
        self.assertEqual(ctx.exception.http_status, 409)
        self.assertEqual(self._user_row(self.user_a)["premium_until"], until)
        # The conflicting order is blocked for manual review (no replacement order).
        self.assertEqual(self._payment(o2)["status"], "NEEDS_REVIEW")

    def test_already_captured_at_paypal_is_reconciled_once(self):
        order_id = self._create(self.user_a)
        self._capture_returns(lambda oid, req: paypal_error(422, "ORDER_ALREADY_CAPTURED"))
        self.fake.get_handler = lambda oid: (200, order_body(oid, self.user_a["id"]))
        r = self._capture(self.user_a, order_id)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["premium_granted"])

    def test_capture_uses_stable_paypal_request_id(self):
        order_id = self._create(self.user_a)

        def timeout(oid, req):
            raise requests.exceptions.ReadTimeout("simulated")
        self._capture_returns(timeout)                    # unknown outcome, recorded as TRANSPORT_ERROR
        self.fake.get_handler = lambda oid: (503, {})
        self._capture(self.user_a, order_id)
        self._capture_returns(lambda oid, req: (201, order_body(oid, self.user_a["id"])))
        self._capture(self.user_a, order_id)              # the recorded retryable result allows one retry
        ids = [h.get("PayPal-Request-Id") for m, p, h, _ in self.fake.calls if p.endswith("/capture")]
        self.assertEqual(len(ids), 2)
        self.assertEqual(ids[0], ids[1])
        self.assertEqual(ids[0], f"mymile-capture-{order_id}")

    def test_stacked_purchase_extends_from_current_expiry(self):
        self._capture_returns(lambda oid, req: (201, order_body(oid, self.user_a["id"])))
        first = self._capture(self.user_a, self._create(self.user_a)).json()["premium_until"]
        second = self._capture(self.user_a, self._create(self.user_a)).json()["premium_until"]
        delta = datetime.fromisoformat(second) - datetime.fromisoformat(first)
        self.assertEqual(delta, timedelta(days=30))

    # -- ownership --
    def test_other_user_cannot_capture_order(self):
        order_id = self._create(self.user_a)
        self._capture_returns(lambda oid, req: (201, order_body(oid, self.user_b["id"])))
        r = self._capture(self.user_b, order_id)
        self.assertEqual(r.status_code, 404)
        self.assertEqual(self.fake.count("POST", "/capture"), 0)
        self._assert_not_premium(self.user_a)
        self._assert_not_premium(self.user_b)
        self.assertEqual(self._payment(order_id)["status"], "CREATED")

    def test_unknown_or_malformed_order_is_404(self):
        self.assertEqual(self._capture(self.user_a, "NOTOURORDER123").status_code, 404)
        self.assertEqual(self._capture(self.user_a, "bad$id").status_code, 404)
        self.assertEqual(self.fake.count("POST", "/capture"), 0)

    def test_paypal_custom_id_mismatch_needs_review(self):
        order_id = self._create(self.user_a)
        self._capture_returns(lambda oid, req: (201, order_body(oid, self.user_a["id"],
                                                                unit_custom_id=self.user_b["id"])))
        r = self._capture(self.user_a, order_id)
        self.assertEqual((r.status_code, r.json()["status"]), (409, "NEEDS_REVIEW"))
        self._assert_not_premium(self.user_a)
        self.assertEqual(self._payment(order_id)["status"], "NEEDS_REVIEW")

    # -- verification failures --
    def test_amount_mismatch_needs_review(self):
        order_id = self._create(self.user_a)
        self._capture_returns(lambda oid, req: (201, order_body(oid, self.user_a["id"], value="1.00")))
        r = self._capture(self.user_a, order_id)
        self.assertEqual((r.status_code, r.json()["status"]), (409, "NEEDS_REVIEW"))
        self.assertFalse(r.json()["premium_granted"])
        self._assert_not_premium(self.user_a)
        self.assertEqual(self._payment(order_id)["status"], "NEEDS_REVIEW")

    def test_amount_compared_as_decimal(self):
        order_id = self._create(self.user_a)
        self._capture_returns(lambda oid, req: (201, order_body(oid, self.user_a["id"], value="9.0")))
        self.assertEqual(self._capture(self.user_a, order_id).status_code, 200)

    def test_currency_mismatch_is_rejected(self):
        order_id = self._create(self.user_a)
        self._capture_returns(lambda oid, req: (201, order_body(oid, self.user_a["id"], currency="EUR")))
        r = self._capture(self.user_a, order_id)
        self.assertEqual(r.status_code, 409)
        self._assert_not_premium(self.user_a)

    def test_pending_capture_does_not_grant(self):
        order_id = self._create(self.user_a)
        self._capture_returns(lambda oid, req: (201, order_body(oid, self.user_a["id"], capture_status="PENDING")))
        r = self._capture(self.user_a, order_id)
        self.assertEqual(r.status_code, 202)
        self.assertEqual(r.json()["status"], "PENDING")
        self._assert_not_premium(self.user_a)
        self.assertEqual(self._payment(order_id)["status"], "PENDING")

    def test_declined_capture_does_not_grant(self):
        order_id = self._create(self.user_a)
        self._capture_returns(lambda oid, req: (201, order_body(oid, self.user_a["id"], order_status="COMPLETED",
                                                                capture_status="DECLINED")))
        r = self._capture(self.user_a, order_id)
        self.assertEqual(r.status_code, 402)
        self._assert_not_premium(self.user_a)
        self.assertEqual(self._payment(order_id)["status"], "DECLINED")

    def test_instrument_declined_error_does_not_grant(self):
        order_id = self._create(self.user_a)
        self._capture_returns(lambda oid, req: paypal_error(422, "INSTRUMENT_DECLINED"))
        r = self._capture(self.user_a, order_id)
        self.assertEqual(r.status_code, 402)
        self._assert_not_premium(self.user_a)

    def test_order_not_approved_does_not_grant(self):
        order_id = self._create(self.user_a)
        self._capture_returns(lambda oid, req: paypal_error(422, "ORDER_NOT_APPROVED"))
        self.assertEqual(self._capture(self.user_a, order_id).status_code, 409)
        self._assert_not_premium(self.user_a)

    # -- uncertain outcomes --
    def test_timeout_then_unknown_does_not_grant_then_retry_grants(self):
        order_id = self._create(self.user_a)

        def timeout(oid, req):
            raise requests.exceptions.ReadTimeout("simulated")
        self._capture_returns(timeout)
        self.fake.get_handler = lambda oid: (503, {"name": "SERVICE_UNAVAILABLE"})
        r = self._capture(self.user_a, order_id)
        self.assertEqual(r.status_code, 202, r.text)
        self.assertEqual(r.json()["status"], "UNCERTAIN")
        self.assertTrue(r.json()["retryable"])
        self._assert_not_premium(self.user_a)
        self.assertEqual(self._payment(order_id)["status"], "UNCERTAIN")

        # Retry: PayPal says it was in fact captured -> verified and granted once.
        self._capture_returns(lambda oid, req: paypal_error(422, "ORDER_ALREADY_CAPTURED"))
        self.fake.get_handler = lambda oid: (200, order_body(oid, self.user_a["id"]))
        r2 = self._capture(self.user_a, order_id)
        self.assertEqual(r2.status_code, 200, r2.text)
        self.assertTrue(r2.json()["premium_granted"])
        self.assertEqual(self._user_row(self.user_a)["plan"], "premium")

    def test_timeout_reconciled_immediately_when_paypal_shows_completed(self):
        order_id = self._create(self.user_a)

        def conn_reset(oid, req):
            raise requests.exceptions.ConnectionError("simulated reset")
        self._capture_returns(conn_reset)
        self.fake.get_handler = lambda oid: (200, order_body(oid, self.user_a["id"]))
        r = self._capture(self.user_a, order_id)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["premium_granted"])

    def test_timeout_reconcile_shows_pending_does_not_grant(self):
        order_id = self._create(self.user_a)

        def timeout(oid, req):
            raise requests.exceptions.ReadTimeout("simulated")
        self._capture_returns(timeout)
        self.fake.get_handler = lambda oid: (200, order_body(oid, self.user_a["id"], order_status="COMPLETED",
                                                             capture_status="PENDING"))
        r = self._capture(self.user_a, order_id)
        self.assertEqual(r.status_code, 202)
        self._assert_not_premium(self.user_a)

    def test_paypal_5xx_on_capture_is_reconciled(self):
        order_id = self._create(self.user_a)
        self._capture_returns(lambda oid, req: (500, {"name": "INTERNAL_SERVER_ERROR", "message": "x"}))
        self.fake.get_handler = lambda oid: (200, order_body(oid, self.user_a["id"], order_status="APPROVED",
                                                             capture_status="PENDING") | {"purchase_units": [
            {"reference_id": "mymile-premium-pass", "custom_id": self.user_a["id"],
             "amount": {"currency_code": "USD", "value": "9.00"}}]})
        r = self._capture(self.user_a, order_id)
        self.assertEqual(r.status_code, 202)
        self.assertEqual(r.json()["status"], "UNCERTAIN")
        self._assert_not_premium(self.user_a)

    # -- concurrent request still running at PayPal --
    def test_previous_request_in_progress_returns_202_without_grant(self):
        order_id = self._create(self.user_a)
        self._capture_returns(lambda oid, req: paypal_error(422, "PREVIOUS_REQUEST_IN_PROGRESS"))
        self.fake.get_handler = lambda oid: self.fail("must not reconcile while PayPal is still processing")
        r = self._capture(self.user_a, order_id)
        self.assertEqual(r.status_code, 202, r.text)
        body = r.json()
        self.assertEqual(body["status"], "IN_PROGRESS")
        self.assertTrue(body["retryable"])
        self.assertFalse(body["premium_granted"])
        self.assertIsNone(body["premium_until"])
        self.assertIn("Do not pay again", body["message"])
        self._assert_not_premium(self.user_a)
        p = self._payment(order_id)
        # A capture was attempted, so the order is UNCERTAIN (crash-safe) until
        # resolved; it must never be COMPLETED here.
        self.assertEqual(p["status"], "UNCERTAIN")
        self.assertIsNone(p["capture_id"])
        self.assertIsNone(p["completed_at"])

    def test_previous_request_in_progress_with_409_status(self):
        order_id = self._create(self.user_a)
        self._capture_returns(lambda oid, req: paypal_error(409, "PREVIOUS_REQUEST_IN_PROGRESS"))
        r = self._capture(self.user_a, order_id)
        self.assertEqual(r.status_code, 202, r.text)
        self.assertEqual(r.json()["status"], "IN_PROGRESS")
        self._assert_not_premium(self.user_a)

    def test_previous_request_in_progress_keeps_existing_status(self):
        order_id = self._create(self.user_a)
        self._capture_returns(lambda oid, req: (201, order_body(oid, self.user_a["id"], capture_status="PENDING")))
        self._capture(self.user_a, order_id)
        self.assertEqual(self._payment(order_id)["status"], "PENDING")
        self._capture_returns(lambda oid, req: paypal_error(422, "PREVIOUS_REQUEST_IN_PROGRESS"))
        self.assertEqual(self._capture(self.user_a, order_id).status_code, 202)
        self.assertEqual(self._payment(order_id)["status"], "PENDING")
        self._assert_not_premium(self.user_a)

    def test_previous_request_in_progress_then_lookup_grants_once(self):
        order_id = self._create(self.user_a)
        self._capture_returns(lambda oid, req: paypal_error(422, "PREVIOUS_REQUEST_IN_PROGRESS"))
        self.assertEqual(self._capture(self.user_a, order_id).status_code, 202)
        # Nothing recorded for this request -> no re-capture; a read-only lookup
        # finds the capture the in-flight request completed.
        self._capture_returns(lambda oid, req: (201, order_body(oid, self.user_a["id"])))
        self.fake.get_handler = lambda oid: (200, order_body(oid, self.user_a["id"]))
        r = self._capture(self.user_a, order_id)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["premium_granted"])
        self.assertFalse(r.json()["already_processed"])
        until = r.json()["premium_until"]
        third = self._capture(self.user_a, order_id)
        self.assertTrue(third.json()["already_processed"])
        self.assertEqual(third.json()["premium_until"], until)
        ids = [h.get("PayPal-Request-Id") for m, p, h, _ in self.fake.calls if p.endswith("/capture")]
        self.assertEqual(ids, [f"mymile-capture-{order_id}"], "never re-captured; 3rd call skips PayPal")

    def test_previous_request_in_progress_after_concurrent_completion(self):
        order_id = self._create(self.user_a)

        def in_progress_but_other_request_finished(oid, req):
            # The concurrent in-flight request completes and grants first.
            paypal_service._grant(oid, self.user_a["id"], f"CAP{oid}")
            return paypal_error(422, "PREVIOUS_REQUEST_IN_PROGRESS")
        self._capture_returns(in_progress_but_other_request_finished)
        r = self._capture(self.user_a, order_id)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["already_processed"])
        self.assertEqual(r.json()["premium_until"], self._user_row(self.user_a)["premium_until"])
        self.assertEqual(self._db("SELECT COUNT(*) AS n FROM payments WHERE order_id = ? AND status = 'COMPLETED'",
                                  order_id)["n"], 1)

    # -- concurrent order creation (per-user lock, process-local) --
    def _hook_create(self, before_create):
        """Run `before_create(request)` on each PayPal create-order call; if it
        returns a response, that is sent instead of the fake's normal answer."""
        original = self.fake.send

        def send(request, **kwargs):
            if request.method == "POST" and requests.utils.urlparse(request.url).path == "/v2/checkout/orders":
                replacement = before_create(request)
                if replacement is not None:
                    return replacement
            return original(request, **kwargs)
        self.fake.send = send

    def _post_orders_concurrently(self, users):
        barrier = threading.Barrier(len(users))
        results = [None] * len(users)

        def worker(i, user):
            barrier.wait(timeout=10)
            results[i] = self.api.post("/api/payments/paypal/orders", headers=user["headers"])
        threads = [threading.Thread(target=worker, args=(i, u)) for i, u in enumerate(users)]
        [t.start() for t in threads]
        [t.join(timeout=60) for t in threads]
        return results

    def test_concurrent_order_creation_same_user_creates_one_paypal_order(self):
        in_create, max_in_create, guard = [0], [0], threading.Lock()

        def slow_create(request):
            with guard:
                in_create[0] += 1
                max_in_create[0] = max(max_in_create[0], in_create[0])
            time.sleep(0.3)  # widen the race window; correctness does not depend on it
            with guard:
                in_create[0] -= 1
            return None
        self._hook_create(slow_create)

        results = self._post_orders_concurrently([self.user_a] * 5)
        codes = sorted(r.status_code for r in results)
        self.assertEqual(codes, [200, 200, 200, 200, 201], [r.text for r in results])
        self.assertEqual(self.fake.count("POST", "/v2/checkout/orders"), 1, "exactly one PayPal order")
        self.assertEqual(max_in_create[0], 1)
        order_ids = {r.json()["order_id"] for r in results}
        self.assertEqual(len(order_ids), 1, "every request got the same order")
        self.assertEqual(sum(r.json()["reused"] for r in results), 4)
        rows = self._db("SELECT COUNT(*) AS n FROM payments WHERE user_id = ?", self.user_a["id"])["n"]
        self.assertEqual(rows, 1)
        self.assertEqual(paypal_service._create_locks, {}, "per-user locks are cleaned up")

    def test_concurrent_order_creation_different_users_is_not_serialized(self):
        # Rendezvous: the first create waits for the second to arrive. If the
        # lock were global, the second could never arrive while the first waits.
        both_inside = threading.Barrier(2)
        overlapped = []

        def rendezvous(request):
            try:
                both_inside.wait(timeout=5)  # breaks if the other never gets in
                overlapped.append(True)
            except threading.BrokenBarrierError:
                overlapped.append(False)
            return None
        self._hook_create(rendezvous)

        results = self._post_orders_concurrently([self.user_a, self.user_b])
        self.assertEqual(sorted(r.status_code for r in results), [201, 201], [r.text for r in results])
        self.assertEqual(self.fake.count("POST", "/v2/checkout/orders"), 2)
        self.assertNotEqual(results[0].json()["order_id"], results[1].json()["order_id"])
        self.assertTrue(all(overlapped) and len(overlapped) == 2, "different users ran in parallel")

    def test_order_creation_lock_released_after_paypal_failure(self):
        calls = [0]

        def fail_first(request):
            calls[0] += 1
            return FakePayPal._resp(request, 500, {"name": "INTERNAL_SERVER_ERROR"}) if calls[0] == 1 else None
        self._hook_create(fail_first)

        first = self.api.post("/api/payments/paypal/orders", headers=self.user_a["headers"])
        self.assertEqual(first.status_code, 502, first.text)
        self.assertEqual(paypal_service._create_locks, {})
        second = self.api.post("/api/payments/paypal/orders", headers=self.user_a["headers"])
        self.assertEqual(second.status_code, 201, second.text)
        self.assertFalse(second.json()["reused"])

    def test_order_creation_lock_wait_is_bounded(self):
        # Hold the user's lock, then a create for that user must give up with a
        # clear 409 (never a second PayPal order) once the bounded wait expires.
        with mock.patch.object(settings, "PAYPAL_TIMEOUT_SECONDS", -14.9):  # wait = 0.1 s
            with paypal_service._user_create_lock(self.user_a["id"]):
                with self.assertRaises(paypal_service.PaymentError) as ctx:
                    paypal_service.create_premium_order(self.user_a["id"])
        self.assertEqual(ctx.exception.http_status, 409)
        self.assertIn("do not pay twice", ctx.exception.message)
        self.assertEqual(self.fake.count("POST", "/v2/checkout/orders"), 0)
        self.assertEqual(paypal_service._create_locks, {})

    # -- logging --
    def test_no_secrets_in_logs(self):
        order_id = self._create(self.user_a)
        self._capture_returns(lambda oid, req: (201, order_body(oid, self.user_a["id"], value="1.00")))
        with self.assertLogs("app.services.paypal_service", level="DEBUG") as logs:
            self._capture(self.user_a, order_id)
        text = "\n".join(logs.output)
        for secret in (TEST_SECRET, TEST_ACCESS_TOKEN, self.user_a["email"],
                       self.user_a["headers"]["Authorization"].split()[1]):
            self.assertNotIn(secret, text)

    # -- demo account / persistence --
    def test_demo_account_still_premium(self):
        row = self._db("SELECT plan, premium_until FROM users WHERE email = 'alex@example.com'")
        self.assertEqual(row["plan"], "premium")
        self.assertIsNone(row["premium_until"])

    def test_premium_persists_after_backend_restart(self):
        order_id = self._create(self.user_a)
        self._capture_returns(lambda oid, req: (201, order_body(oid, self.user_a["id"])))
        until = self._capture(self.user_a, order_id).json()["premium_until"]

        # A brand-new Python process = a backend restart against the same DB file.
        script = (
            "import json\n"
            "from fastapi.testclient import TestClient\n"
            "from app.main import app\n"
            "from app.core import database\n"
            "c = TestClient(app)\n"
            f"t = c.post('/api/auth/login', json={{'email': {self.user_a['email']!r}, 'password': 'password123'}}).json()\n"
            "me = c.get('/api/auth/me', headers={'Authorization': 'Bearer ' + t['access_token']}).json()\n"
            "with database.connect() as conn:\n"
            f"    row = conn.execute('SELECT premium_until FROM users WHERE id = ?', ({self.user_a['id']!r},)).fetchone()\n"
            f"    pay = conn.execute('SELECT status FROM payments WHERE order_id = ?', ({order_id!r},)).fetchone()\n"
            "print(json.dumps({'plan': me['plan'], 'premium_until': row[0], 'payment': pay[0]}))\n"
        )
        # The exact file the app under test is using (shared by every module).
        db_path = str(database.DB_PATH)
        _env.ensure_not_real_db(db_path)
        env = dict(os.environ, MYMILE_DB_PATH=db_path, PYTHONDONTWRITEBYTECODE="1")
        out = subprocess.run([sys.executable, "-c", script], cwd=BACKEND_DIR, env=env,
                             capture_output=True, text=True, timeout=120)
        self.assertEqual(out.returncode, 0, out.stderr)
        result = json.loads(out.stdout.strip().splitlines()[-1])
        self.assertEqual(result, {"plan": "premium", "premium_until": until, "payment": "COMPLETED"})


class MigrationTest(unittest.TestCase):
    """The migration must keep every existing row of a pre-Phase-2 database."""

    def test_migrates_legacy_database_without_data_loss(self):
        path = os.path.join(_TMP, "legacy.db")
        conn = sqlite3.connect(path)
        conn.execute("""CREATE TABLE users (id TEXT PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE,
                        hashed_password TEXT NOT NULL, plan TEXT NOT NULL DEFAULT 'free', created_at TEXT NOT NULL)""")
        rows = [("usr-demo-01", "Alex Morgan", "alex@example.com", "h1", "premium", "2026-01-15T10:00:00Z"),
                ("usr-1", "Old User", "old@example.com", "h2", "free", "2026-02-01T00:00:00Z")]
        conn.executemany("INSERT INTO users VALUES (?,?,?,?,?,?)", rows)
        conn.commit()
        for _ in range(2):  # running twice must be harmless
            database.migrate(conn)
            conn.commit()
        cols = [r[1] for r in conn.execute("PRAGMA table_info(users)")]
        self.assertIn("premium_until", cols)
        kept = conn.execute("SELECT id,name,email,hashed_password,plan,created_at FROM users ORDER BY id").fetchall()
        self.assertEqual(sorted(kept), sorted(rows))
        self.assertIsNotNone(conn.execute("SELECT 1 FROM sqlite_master WHERE name='payments'").fetchone())
        conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    unittest.main()
