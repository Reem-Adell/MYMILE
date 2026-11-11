"""
Phase 3.1: effective Premium status, auth responses, and grant/renewal rules.

Run from backend/:
    venv\\Scripts\\python -m unittest discover -s tests -v

Time is frozen by patching app.core.premium.utc_now (the single clock used by
both the status rule and the payment service), so nothing depends on sleeps.
A throwaway SQLite file is used; the real backend/data/users.db is never opened.
"""
import os
import subprocess
import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

# Shared isolated environment (temp DB + random SECRET_KEY). Must be imported
# BEFORE any `app.*` module; it raises if the real users.db would be used.
from tests import _env  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app.core import database, premium  # noqa: E402
from app.core.premium import DEMO_USER_ID, effective_plan, is_premium_active  # noqa: E402
from app.main import app  # noqa: E402
from app.services import paypal_service  # noqa: E402

FROZEN = datetime(2026, 11, 9, 12, 0, 0, tzinfo=timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def frozen_at(moment: datetime):
    return mock.patch.object(premium, "utc_now", lambda: moment)


class _DbSafety(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Explicit check (not `assert`): still enforced under `python -O`.
        _env.ensure_isolated_db()


# --------------------------------------------------------------------------
# 1. The authoritative rule (pure function, injected time)
# --------------------------------------------------------------------------
class EffectivePlanRuleTest(_DbSafety):

    def test_demo_with_null_expiry_is_premium(self):
        self.assertEqual(effective_plan(DEMO_USER_ID, "premium", None, FROZEN), "premium")

    def test_demo_is_premium_regardless_of_expiry_or_stored_plan(self):
        for stored_plan, until in [("premium", iso(FROZEN - timedelta(days=400))),
                                   ("premium", iso(FROZEN)),
                                   ("premium", "not-a-date"),
                                   ("free", None),
                                   ("free", iso(FROZEN - timedelta(days=1)))]:
            self.assertEqual(effective_plan(DEMO_USER_ID, stored_plan, until, FROZEN), "premium",
                             (stored_plan, until))

    def test_regular_user_with_future_expiry_is_premium(self):
        self.assertEqual(effective_plan("usr-x", "premium", iso(FROZEN + timedelta(seconds=1)), FROZEN), "premium")

    def test_regular_user_with_past_expiry_is_free(self):
        self.assertEqual(effective_plan("usr-x", "premium", iso(FROZEN - timedelta(seconds=1)), FROZEN), "free")

    def test_regular_user_with_expiry_equal_to_now_is_free(self):
        self.assertEqual(effective_plan("usr-x", "premium", iso(FROZEN), FROZEN), "free")

    def test_regular_user_with_null_or_empty_expiry_is_free(self):
        for until in (None, "", "   "):
            self.assertEqual(effective_plan("usr-x", "premium", until, FROZEN), "free", repr(until))

    def test_stored_free_with_future_expiry_is_free(self):
        self.assertEqual(effective_plan("usr-x", "free", iso(FROZEN + timedelta(days=10)), FROZEN), "free")

    def test_unparseable_expiry_is_free(self):
        self.assertEqual(effective_plan("usr-x", "premium", "tomorrow-ish", FROZEN), "free")

    def test_timestamp_formats_are_compared_in_utc(self):
        # "Z" suffix, naive (read as UTC), and a non-UTC offset equal to FROZEN.
        self.assertTrue(is_premium_active("u", "premium", "2026-11-09T12:00:01Z", FROZEN))
        self.assertTrue(is_premium_active("u", "premium", "2026-11-09T12:00:01", FROZEN))
        self.assertFalse(is_premium_active("u", "premium", "2026-11-09T14:00:00+02:00", FROZEN))
        self.assertTrue(is_premium_active("u", "premium", "2026-11-09T14:00:01+02:00", FROZEN))

    def test_default_clock_is_the_injectable_utc_clock(self):
        until = iso(FROZEN + timedelta(hours=1))
        with frozen_at(FROZEN):
            self.assertEqual(effective_plan("u", "premium", until), "premium")
        with frozen_at(FROZEN + timedelta(hours=1)):
            self.assertEqual(effective_plan("u", "premium", until), "free")

    def test_unrepresentable_expiry_is_free_not_an_error(self):
        for until in ("9999-12-31T23:59:59-05:00", "0001-01-01T00:00:00+05:00"):
            self.assertIsNone(premium.parse_utc(until), until)
            self.assertEqual(effective_plan("usr-x", "premium", until, FROZEN), "free", until)

    def test_demo_never_loses_premium_through_expiration_check(self):
        far_future = datetime(2100, 1, 1, tzinfo=timezone.utc)
        self.assertEqual(effective_plan(DEMO_USER_ID, "premium", None, far_future), "premium")
        with frozen_at(far_future):
            self.assertEqual(effective_plan(DEMO_USER_ID, "premium", None), "premium")


# --------------------------------------------------------------------------
# 2. Auth responses expose the effective plan + premium_until
# --------------------------------------------------------------------------
class AuthResponseTest(_DbSafety):

    def setUp(self):
        self.api = TestClient(app)
        p = frozen_at(FROZEN)
        p.start()
        self.addCleanup(p.stop)

    def _register(self):
        email = f"p-{uuid.uuid4().hex[:8]}@test.example"
        r = self.api.post("/api/auth/register", json={"name": "P", "email": email, "password": "password123"})
        self.assertEqual(r.status_code, 201, r.text)
        return email, r.json()

    def _set(self, user_id, plan, until):
        with database.connect() as conn:
            conn.execute("UPDATE users SET plan = ?, premium_until = ? WHERE id = ?", (plan, until, user_id))

    def _login(self, email):
        r = self.api.post("/api/auth/login", json={"email": email, "password": "password123"})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_register_returns_effective_plan(self):
        _, body = self._register()
        user = body["user"]
        self.assertEqual(user["plan"], "free")
        self.assertIsNone(user["premium_until"])
        self.assertEqual(set(user), {"id", "name", "email", "plan", "created_at", "premium_until"})
        self.assertEqual(body["token_type"], "bearer")
        self.assertTrue(body["access_token"])

    def test_login_returns_effective_plan(self):
        email, body = self._register()
        uid = body["user"]["id"]
        future = iso(FROZEN + timedelta(days=1))
        self._set(uid, "premium", future)
        user = self._login(email)["user"]
        self.assertEqual((user["plan"], user["premium_until"]), ("premium", future))

        past = iso(FROZEN - timedelta(seconds=1))
        self._set(uid, "premium", past)
        user = self._login(email)["user"]
        self.assertEqual((user["plan"], user["premium_until"]), ("free", past))

    def test_me_returns_effective_plan_and_premium_until(self):
        email, body = self._register()
        uid, token = body["user"]["id"], body["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        until = iso(FROZEN + timedelta(hours=2))
        self._set(uid, "premium", until)

        me = self.api.get("/api/auth/me", headers=headers).json()
        self.assertEqual((me["plan"], me["premium_until"]), ("premium", until))

        # Same token, clock moves to exactly the expiry moment -> free.
        with frozen_at(FROZEN + timedelta(hours=2)):
            me = self.api.get("/api/auth/me", headers=headers).json()
        self.assertEqual((me["plan"], me["premium_until"]), ("free", until))

    def test_me_stored_free_with_future_expiry_is_free(self):
        email, body = self._register()
        self._set(body["user"]["id"], "free", iso(FROZEN + timedelta(days=5)))
        self.assertEqual(self._login(email)["user"]["plan"], "free")

    def test_me_premium_with_null_expiry_is_free_for_regular_user(self):
        email, body = self._register()
        self._set(body["user"]["id"], "premium", None)
        self.assertEqual(self._login(email)["user"]["plan"], "free")

    def test_me_with_unrepresentable_expiry_returns_free_not_500(self):
        email, body = self._register()
        self._set(body["user"]["id"], "premium", "9999-12-31T23:59:59-05:00")
        r = self.api.get("/api/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["plan"], "free")
        self.assertEqual(self._login(email)["user"]["plan"], "free")

    def test_demo_login_and_me_are_premium(self):
        body = self.api.post("/api/auth/login",
                             json={"email": "alex@example.com", "password": "password123"}).json()
        self.assertEqual(body["user"]["id"], DEMO_USER_ID)
        self.assertEqual((body["user"]["plan"], body["user"]["premium_until"]), ("premium", None))
        me = self.api.get("/api/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"}).json()
        self.assertEqual(me["plan"], "premium")

    def test_responses_never_include_sensitive_fields(self):
        email, body = self._register()
        login = self._login(email)
        me = self.api.get("/api/auth/me", headers={"Authorization": f"Bearer {login['access_token']}"}).json()
        for payload in (body["user"], login["user"], me):
            for forbidden in ("hashed_password", "password", "capture_id", "order_id"):
                self.assertNotIn(forbidden, payload)


# --------------------------------------------------------------------------
# 3. Grant / renewal (frozen clock, payment rows inserted directly)
# --------------------------------------------------------------------------
class GrantRenewalTest(_DbSafety):

    def setUp(self):
        p = frozen_at(FROZEN)
        p.start()
        self.addCleanup(p.stop)

    def _user(self, plan="free", until=None):
        uid = f"usr-t{uuid.uuid4().hex[:8]}"
        with database.connect() as conn:
            conn.execute(
                "INSERT INTO users (id, name, email, hashed_password, plan, created_at, premium_until) "
                "VALUES (?, 'T', ?, 'x', ?, ?, ?)",
                (uid, f"{uid}@test.example", plan, iso(FROZEN), until))
        return uid

    def _order(self, uid):
        oid = f"T{uuid.uuid4().hex[:15].upper()}"
        with database.connect() as conn:
            conn.execute(
                "INSERT INTO payments (order_id, user_id, amount, currency, status, created_at) "
                "VALUES (?, ?, '9.00', 'USD', 'CREATED', ?)", (oid, uid, iso(FROZEN)))
        return oid

    def _row(self, uid):
        with database.connect() as conn:
            return conn.execute("SELECT plan, premium_until FROM users WHERE id = ?", (uid,)).fetchone()

    def _grant(self, uid):
        oid = self._order(uid)
        return paypal_service._grant(oid, uid, f"CAP-{oid}")

    def test_new_purchase_grants_exactly_30_days_from_now(self):
        uid = self._user()
        until, granted = self._grant(uid)
        self.assertTrue(granted)
        self.assertEqual(until, iso(FROZEN + timedelta(days=30)))
        self.assertEqual(tuple(self._row(uid)), ("premium", until))

    def test_renewal_extends_active_premium_by_30_days(self):
        uid = self._user("premium", iso(FROZEN + timedelta(days=10)))
        until, _ = self._grant(uid)
        self.assertEqual(until, iso(FROZEN + timedelta(days=40)))

    def test_expired_premium_renewal_starts_from_now(self):
        uid = self._user("premium", iso(FROZEN - timedelta(days=5)))
        until, _ = self._grant(uid)
        self.assertEqual(until, iso(FROZEN + timedelta(days=30)))

    def test_expiry_equal_to_now_renewal_starts_from_now(self):
        uid = self._user("premium", iso(FROZEN))
        until, _ = self._grant(uid)
        self.assertEqual(until, iso(FROZEN + timedelta(days=30)))

    def test_stored_free_with_future_expiry_renewal_starts_from_now(self):
        uid = self._user("free", iso(FROZEN + timedelta(days=10)))
        until, _ = self._grant(uid)
        self.assertEqual(until, iso(FROZEN + timedelta(days=30)))

    def test_regular_user_with_null_expiry_never_gets_permanent_premium(self):
        uid = self._user("premium", None)
        until, granted = self._grant(uid)
        self.assertTrue(granted)
        self.assertEqual(until, iso(FROZEN + timedelta(days=30)))
        self.assertIsNotNone(self._row(uid)["premium_until"])

    def test_repeated_grant_for_same_order_does_not_extend_twice(self):
        uid = self._user()
        oid = self._order(uid)
        until1, granted1 = paypal_service._grant(oid, uid, f"CAP-{oid}")
        with frozen_at(FROZEN + timedelta(days=3)):
            until2, granted2 = paypal_service._grant(oid, uid, f"CAP-{oid}")
        self.assertTrue(granted1)
        self.assertFalse(granted2)
        self.assertEqual(until1, until2)
        self.assertEqual(self._row(uid)["premium_until"], until1)

    def test_grant_with_unrepresentable_existing_expiry_starts_from_now(self):
        uid = self._user("premium", "9999-12-31T23:59:59-05:00")
        until, granted = self._grant(uid)
        self.assertTrue(granted)
        self.assertEqual(until, iso(FROZEN + timedelta(days=30)))

    def test_grant_with_expiry_too_late_to_extend_starts_from_now(self):
        # Valid and active, but +30 days would overflow datetime.max.
        uid = self._user("premium", "9999-12-31T23:59:59+00:00")
        until, granted = self._grant(uid)
        self.assertTrue(granted)
        self.assertEqual(until, iso(FROZEN + timedelta(days=30)))
        self.assertEqual(tuple(self._row(uid)), ("premium", until))

    def test_demo_purchase_keeps_permanent_premium(self):
        before = self._row(DEMO_USER_ID)
        until, granted = self._grant(DEMO_USER_ID)
        self.assertTrue(granted)
        self.assertIsNone(until)
        self.assertEqual(tuple(self._row(DEMO_USER_ID)), tuple(before))
        self.assertEqual(effective_plan(DEMO_USER_ID, before["plan"], before["premium_until"]), "premium")


# --------------------------------------------------------------------------
# 4. Test-database safety guard (shared tests/_env.py)
# --------------------------------------------------------------------------
class TestDatabaseSafetyTest(unittest.TestCase):

    def test_app_uses_the_shared_temporary_database(self):
        db = Path(database.DB_PATH).resolve()
        self.assertEqual(db, Path(_env.TEST_DB).resolve())
        self.assertNotEqual(db, _env.REAL_DB_PATH)

    def test_real_database_path_is_rejected(self):
        with self.assertRaises(_env.UnsafeTestDatabaseError):
            _env.ensure_not_real_db(_env.REAL_DB_PATH)

    def _run_optimized(self, code):
        env = {k: v for k, v in os.environ.items()
               if k not in ("MYMILE_TEST_ENV_OWNER_PID", "MYMILE_TEST_DB_PATH")}
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        return subprocess.run([sys.executable, "-O", "-c", code], cwd=_env.BACKEND_DIR, env=env,
                              capture_output=True, text=True, timeout=120)

    def test_guard_still_raises_under_python_O(self):
        # Simulate the dangerous case: app.core.database imported first while
        # pointing at the real file. Importing it only computes a path; it never
        # opens the database. The guard must refuse even with asserts disabled.
        code = (
            "import os\n"
            f"os.environ['MYMILE_DB_PATH'] = {str(_env.REAL_DB_PATH)!r}\n"
            "assert False, 'asserts are active'\n"  # skipped under -O
            "import app.core.database\n"
            "from tests import _env\n"
        )
        out = self._run_optimized(code)
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("UnsafeTestDatabaseError", out.stderr)
        self.assertNotIn("asserts are active", out.stderr, "must really run with -O")

    def test_guard_allows_isolated_database_under_python_O(self):
        code = ("from tests import _env\n"
                "import app.core.database as d\n"
                "print(__debug__, d.DB_PATH.resolve() == _env.REAL_DB_PATH)\n")
        out = self._run_optimized(code)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.split(), ["False", "False"])


if __name__ == "__main__":
    unittest.main()
