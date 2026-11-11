"""
Capture-retry gate + reconciliation command.

  * A capture is re-sent ONLY when payments.last_capture_result records a
    retryable unknown outcome (TRANSPORT_ERROR / HTTP_5XX).
  * Definite 4xx answers (incl. COMPLIANCE_VIOLATION) and "nothing recorded"
    (legacy rows, crashes before recording) allow read-only lookups only,
    including after a backend restart.
  * app.tools.reconcile_declined is conditional and makes no capture call.

Run from backend/:
    venv\\Scripts\\python -m unittest discover -s tests -v
"""
from tests import _env  # noqa: F401  (must precede any app.* import)

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import requests

from tests import test_paypal_payments as base
from app.core import database
from app.services import paypal_service
from app.tools import reconcile_declined as tool

order_body, paypal_error = base.order_body, base.paypal_error
CAPTURE = "/capture"


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

    def _refresh(self, user, oid):
        return self.api.post(f"/api/payments/paypal/orders/{oid}/refresh", headers=user["headers"])

    def _post_order(self, user):
        return self.api.post("/api/payments/paypal/orders", headers=user["headers"])

    def _captures(self):
        return self.fake.count("POST", CAPTURE)

    def _simulate_restart(self):
        # In-memory state is lost on restart; only the database survives.
        paypal_service._last_capture_sent.clear()
        paypal_service._status_locks.clear()

    def _legacy_uncertain_order(self):
        """Exactly the real incident's row: approved order, capture declined
        with COMPLIANCE_VIOLATION by the OLD code, stored only as UNCERTAIN
        (no recorded result: the migration adds the column as NULL)."""
        oid = self._create(self.user_a)
        with database.connect() as conn:
            conn.execute("UPDATE payments SET status = 'UNCERTAIN', last_capture_result = NULL WHERE order_id = ?",
                         (oid,))
        self.fake.get_handler = lambda o: (200, approved(o, self.user_a["id"]))
        self._capture_returns(lambda o, req: self.fail("a capture must never be sent for this order"))
        return oid

    def _fresh_user(self):
        # A user whose earlier order is UNCERTAIN is (correctly) blocked from new orders.
        self.user_a = self._register("loop")

    def _assert_never_captured_again(self, oid):
        before = self._captures()
        for _ in range(3):
            r = self._refresh(self.user_a, oid)
            self.assertEqual((r.status_code, r.json()["status"]), (202, "UNCERTAIN"), r.text)
            r = self._capture(self.user_a, oid)
            self.assertEqual((r.status_code, r.json()["status"]), (202, "UNCERTAIN"), r.text)
        self.assertEqual(self._captures(), before, "no further capture request")
        self.assertEqual(self._post_order(self.user_a).status_code, 409, "still blocks new orders")
        self._assert_not_premium(self.user_a)


# --------------------------------------------------------- existing order ---
class ExistingOrderNeverRecapturedTest(_Base):

    def test_existing_uncertain_order_cannot_trigger_another_capture(self):
        oid = self._legacy_uncertain_order()
        self._assert_never_captured_again(oid)
        self.assertGreater(self.fake.count("GET", oid), 0, "status checks are read-only lookups")

    def test_still_true_after_a_backend_restart(self):
        oid = self._legacy_uncertain_order()
        self._refresh(self.user_a, oid)
        self._simulate_restart()                     # cooldown memory gone
        self._assert_never_captured_again(oid)
        self._simulate_restart()
        self._assert_never_captured_again(oid)


# -------------------------------------------------------- definite 4xx ---
class DefiniteRejectionsNeverRetriedTest(_Base):

    def _assert_no_retry_after(self, status, issue, expect_final_decline=False):
        self._fresh_user()
        oid = self._create(self.user_a)
        self._capture_returns(lambda o, req: paypal_error(status, issue))
        self.fake.get_handler = lambda o: (200, approved(o, self.user_a["id"]))
        self._capture(self.user_a, oid)
        row = self._payment(oid)
        self.assertEqual(row["last_capture_result"], f"HTTP_{status}:{issue}")
        if expect_final_decline:
            self.assertEqual(row["status"], "DECLINED")
        calls = self._captures()
        for _ in range(2):
            self._simulate_restart()
            self._refresh(self.user_a, oid)
            self._capture(self.user_a, oid)
        self.assertEqual(self._captures(), calls, f"{status} {issue} must never trigger another capture")
        self._assert_not_premium(self.user_a)

    def test_compliance_violation_is_permanently_non_retryable(self):
        self._assert_no_retry_after(422, "COMPLIANCE_VIOLATION", expect_final_decline=True)

    def test_instrument_declined_is_non_retryable(self):
        self._assert_no_retry_after(422, "INSTRUMENT_DECLINED", expect_final_decline=True)

    def test_unknown_422_is_non_retryable(self):
        self._assert_no_retry_after(422, "SOMETHING_UNEXPECTED")

    def test_400_and_403_are_non_retryable(self):
        self._assert_no_retry_after(400, "INVALID_REQUEST")
        self._assert_no_retry_after(403, "PERMISSION_DENIED")

    def test_crash_after_recording_compliance_violation_finishes_as_declined_locally(self):
        oid = self._create(self.user_a)
        self._capture_returns(lambda o, req: paypal_error(422, "COMPLIANCE_VIOLATION"))
        real = paypal_service._set_status

        def crash_on_decline(order_id, user_id, status, from_statuses=paypal_service.IN_FLIGHT_STATUSES):
            if status == "DECLINED":
                raise RuntimeError("process died before storing the decline")
            return real(order_id, user_id, status, from_statuses)
        with mock.patch.object(paypal_service, "_set_status", crash_on_decline):
            with self.assertRaises(RuntimeError):
                paypal_service.capture_premium_order(self.user_a["id"], oid)
        self._simulate_restart()
        calls = self._captures()
        r = self._refresh(self.user_a, oid)
        self.assertEqual((r.status_code, r.json()["status"], r.json()["decline_issue"]),
                         (402, "DECLINED", "COMPLIANCE_VIOLATION"))
        self.assertEqual(self._captures(), calls)


# ------------------------------------------------- recorded unknown outcomes ---
class RecordedUnknownOutcomesTest(_Base):

    def _uncertain_after(self, handler):
        oid = self._create(self.user_a)
        self._capture_returns(handler)
        self.fake.get_handler = lambda o: (200, approved(o, self.user_a["id"]))
        self.assertEqual(self._capture(self.user_a, oid).json()["status"], "UNCERTAIN")
        return oid

    def _timeout(self, o, req):
        raise requests.exceptions.ReadTimeout("simulated")

    def test_recorded_5xx_allows_exactly_one_retry(self):
        oid = self._uncertain_after(lambda o, req: (500, {"name": "INTERNAL_SERVER_ERROR"}))
        self.assertEqual(self._payment(oid)["last_capture_result"], "HTTP_5XX")
        self._simulate_restart()
        self._capture_returns(lambda o, req: (201, order_body(o, self.user_a["id"])))
        r = self._refresh(self.user_a, oid)
        self.assertEqual((r.status_code, r.json()["premium_granted"]), (200, True))
        self.assertEqual(self._captures(), 2)

    def test_recorded_transport_error_allows_a_retry_via_capture_too(self):
        oid = self._uncertain_after(self._timeout)
        self.assertEqual(self._payment(oid)["last_capture_result"], "TRANSPORT_ERROR")
        self._capture_returns(lambda o, req: (201, order_body(o, self.user_a["id"])))
        self.assertEqual(self._capture(self.user_a, oid).status_code, 200)

    def test_crash_before_recording_the_first_result_allows_lookup_only(self):
        oid = self._create(self.user_a)
        self._capture_returns(self._timeout)
        with mock.patch.object(paypal_service, "_record_capture_result",
                               side_effect=RuntimeError("process died before recording")):
            with self.assertRaises(RuntimeError):
                paypal_service.capture_premium_order(self.user_a["id"], oid)
        row = self._payment(oid)
        self.assertEqual((row["status"], row["last_capture_result"]), ("UNCERTAIN", None))
        self.fake.get_handler = lambda o: (200, approved(o, self.user_a["id"]))
        self._capture_returns(lambda o, req: self.fail("no capture without a recorded retryable result"))
        self._simulate_restart()
        self._assert_never_captured_again(oid)

    def test_crash_during_a_retry_before_recording_allows_lookup_only(self):
        oid = self._uncertain_after(self._timeout)
        self._simulate_restart()
        with mock.patch.object(paypal_service, "_record_capture_result",
                               side_effect=RuntimeError("process died during the retry")):
            with self.assertRaises(RuntimeError):
                paypal_service.capture_premium_order(self.user_a["id"], oid)
        self.assertIsNone(self._payment(oid)["last_capture_result"], "the claim cleared it before sending")
        calls = self._captures()
        self._capture_returns(lambda o, req: self.fail("no second retry without a new recorded result"))
        self._simulate_restart()
        self._refresh(self.user_a, oid)
        self._capture(self.user_a, oid)
        self.assertEqual(self._captures(), calls)

    def test_auth_failure_restores_the_retryable_record(self):
        from apimatic_core.exceptions.auth_validation_exception import AuthValidationException
        oid = self._uncertain_after(self._timeout)
        with mock.patch.object(self.paypal.orders, "capture_order", side_effect=AuthValidationException("t")):
            self.assertEqual(self._capture(self.user_a, oid).status_code, 503)
        row = self._payment(oid)
        self.assertEqual((row["status"], row["last_capture_result"]), ("UNCERTAIN", "TRANSPORT_ERROR"))


# --------------------------------------------------------------- migration ---
class MigrationTest(unittest.TestCase):

    def test_old_payments_table_gets_a_null_last_capture_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "old.db"
            conn = sqlite3.connect(db)
            conn.row_factory = sqlite3.Row
            conn.execute("CREATE TABLE users (id TEXT PRIMARY KEY, name TEXT, email TEXT, hashed_password TEXT, "
                         "plan TEXT, created_at TEXT)")
            conn.execute("CREATE TABLE payments (id INTEGER PRIMARY KEY AUTOINCREMENT, order_id TEXT NOT NULL UNIQUE, "
                         "user_id TEXT NOT NULL, amount TEXT NOT NULL, currency TEXT NOT NULL, status TEXT NOT NULL, "
                         "capture_id TEXT UNIQUE, created_at TEXT NOT NULL, completed_at TEXT)")
            conn.execute("INSERT INTO payments (order_id, user_id, amount, currency, status, created_at) "
                         "VALUES ('OLD1', 'u', '9.00', 'USD', 'UNCERTAIN', '2026-01-01T00:00:00+00:00')")
            database.migrate(conn)
            database.migrate(conn)  # idempotent
            row = conn.execute("SELECT status, last_capture_result FROM payments WHERE order_id = 'OLD1'").fetchone()
            conn.close()
        self.assertEqual((row["status"], row["last_capture_result"]), ("UNCERTAIN", None))


# ------------------------------------------------------ reconciliation tool ---
class ReconcileCommandTest(_Base):

    def _no_paypal_client(self):
        return mock.patch("app.core.paypal_client.get_paypal_client",
                          side_effect=AssertionError("no PayPal call by default"))

    def test_reconciles_the_legacy_order_without_any_paypal_call(self):
        oid = self._legacy_uncertain_order()
        calls_before = len(self.fake.calls)
        with self._no_paypal_client():
            ok, msg = tool.reconcile_compliance_decline(oid, "COMPLIANCE_VIOLATION")
        self.assertTrue(ok, msg)
        self.assertEqual(len(self.fake.calls), calls_before, "no PayPal request at all")
        row = self._payment(oid)
        self.assertEqual((row["status"], row["last_capture_result"]), ("DECLINED", "HTTP_422:COMPLIANCE_VIOLATION"))
        # Afterwards: answered locally, never captured, and a new payment may start.
        self.assertEqual(self._refresh(self.user_a, oid).status_code, 402)
        self.assertEqual(self._capture(self.user_a, oid).status_code, 402)
        self.assertEqual(self._captures(), 0)
        self.assertEqual(self._post_order(self.user_a).status_code, 201)
        ok, msg = tool.reconcile_compliance_decline(oid, "COMPLIANCE_VIOLATION")
        self.assertFalse(ok, "running it twice changes nothing")

    def test_refuses_any_other_issue(self):
        oid = self._legacy_uncertain_order()
        for issue in ("INSTRUMENT_DECLINED", "compliance_violation", "", "HTTP_422:COMPLIANCE_VIOLATION"):
            ok, _ = tool.reconcile_compliance_decline(oid, issue)
            self.assertFalse(ok, issue)
        self.assertEqual(self._payment(oid)["status"], "UNCERTAIN")

    def test_refuses_completed_captured_or_changed_payments(self):
        cases = {
            "COMPLETED": "UPDATE payments SET status='COMPLETED', capture_id='CAP-X-{o}', completed_at='2026-01-01' "
                         "WHERE order_id=?",
            "captured": "UPDATE payments SET capture_id='CAP-Y-{o}' WHERE order_id=?",
            "completed_at": "UPDATE payments SET completed_at='2026-01-01' WHERE order_id=?",
            "PENDING": "UPDATE payments SET status='PENDING' WHERE order_id=?",
            "CREATED": "UPDATE payments SET status='CREATED' WHERE order_id=?",
            "NEEDS_REVIEW": "UPDATE payments SET status='NEEDS_REVIEW' WHERE order_id=?",
        }
        for name, sql in cases.items():
            self._fresh_user()
            oid = self._legacy_uncertain_order()
            with database.connect() as conn:
                conn.execute(sql.format(o=oid), (oid,))
            before = dict(self._payment(oid))
            ok, msg = tool.reconcile_compliance_decline(oid, "COMPLIANCE_VIOLATION")
            self.assertFalse(ok, f"{name}: {msg}")
            self.assertEqual(dict(self._payment(oid)), before, f"{name}: row unchanged")
        self.assertFalse(tool.reconcile_compliance_decline("NOSUCHORDER1", "COMPLIANCE_VIOLATION")[0])

    def test_refuses_if_the_payment_changes_during_reconciliation(self):
        oid = self._legacy_uncertain_order()

        def lookup_while_another_request_completes(o):
            paypal_service._grant(o, self.user_a["id"], f"CAP-RACE-{o}")  # changed meanwhile
            return 200, approved(o, self.user_a["id"])
        self.fake.get_handler = lookup_while_another_request_completes
        ok, msg = tool.reconcile_compliance_decline(oid, "COMPLIANCE_VIOLATION", verify=True, client=self.paypal)
        self.assertFalse(ok, msg)
        self.assertEqual(self._payment(oid)["status"], "COMPLETED", "a completed payment is never overwritten")

    def test_verify_does_one_read_only_lookup_and_accepts_approved_without_capture(self):
        oid = self._legacy_uncertain_order()
        ok, msg = tool.reconcile_compliance_decline(oid, "COMPLIANCE_VIOLATION", verify=True, client=self.paypal)
        self.assertTrue(ok, msg)
        self.assertEqual(self.fake.count("GET", oid), 1)
        self.assertEqual(self._captures(), 0)

    def test_verify_refuses_if_paypal_reports_any_capture_or_other_status(self):
        u = self.user_a["id"]
        bodies = {
            "completed capture": lambda o: order_body(o, u),
            "declined capture": lambda o: order_body(o, u, order_status="APPROVED", capture_status="DECLINED"),
            "pending capture": lambda o: order_body(o, u, order_status="APPROVED", capture_status="PENDING"),
            "status COMPLETED": lambda o: {**approved(o, u), "status": "COMPLETED"},
            "status VOIDED": lambda o: {**approved(o, u), "status": "VOIDED"},
            "status CREATED": lambda o: {**approved(o, u), "status": "CREATED"},
            "other order id": lambda o: approved("SOMEOTHERORDER", u),
        }
        for name, body in bodies.items():
            self._fresh_user()
            oid = self._legacy_uncertain_order()
            self.fake.get_handler = lambda o, body=body: (200, body(o))
            ok, msg = tool.reconcile_compliance_decline(oid, "COMPLIANCE_VIOLATION", verify=True, client=self.paypal)
            self.assertFalse(ok, f"{name}: {msg}")
            self.assertEqual(self._payment(oid)["status"], "UNCERTAIN", name)
        self.assertEqual(self._captures(), 0)

    def test_verify_refuses_when_the_lookup_fails(self):
        oid = self._legacy_uncertain_order()
        self.fake.get_handler = lambda o: (503, {"name": "SERVICE_UNAVAILABLE"})
        ok, _ = tool.reconcile_compliance_decline(oid, "COMPLIANCE_VIOLATION", verify=True, client=self.paypal)
        self.assertFalse(ok)

        def down(o):
            raise requests.exceptions.ConnectionError("down")
        self.fake.get_handler = down
        ok, _ = tool.reconcile_compliance_decline(oid, "COMPLIANCE_VIOLATION", verify=True, client=self.paypal)
        self.assertFalse(ok)
        self.assertEqual(self._payment(oid)["status"], "UNCERTAIN")

    def test_command_line_exit_codes(self):
        oid = self._legacy_uncertain_order()
        with self._no_paypal_client(), mock.patch("builtins.print"):
            self.assertEqual(tool.main([oid, "--issue", "INSTRUMENT_DECLINED"]), 2)
            self.assertEqual(tool.main([oid, "--issue", "COMPLIANCE_VIOLATION"]), 0)
            self.assertEqual(tool.main([oid, "--issue", "COMPLIANCE_VIOLATION"]), 2)


if __name__ == "__main__":
    unittest.main()
