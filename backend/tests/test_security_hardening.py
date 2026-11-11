"""
Phase 3.2.1: Channel3 purchase-link enforcement + authentication hardening.

Run from backend/:
    venv\\Scripts\\python -m unittest discover -s tests -v

Everything goes through the real HTTP routes and the real auth / plan
dependencies (nothing in app.api.routes.auth is mocked). External providers are
deterministic: the weather HTTP client fails fast (offline fallback), LLM and
hotel-pricing keys are cleared, and Channel3 uses either its built-in catalog
or a fake HTTP client returning a fixed payload. Time is frozen via
app.core.premium.utc_now. The shared tests/_env.py temp DB is used.
"""
# Shared isolated environment (temp DB + random SECRET_KEY). Must be imported
# BEFORE any `app.*` module; it raises if the real users.db would be used.
from tests import _env  # noqa: F401

import base64
import httpx
import json
import sqlite3
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest import mock

from fastapi.testclient import TestClient
from jose import jwt

from app.core import database, premium
from app.core.config import settings
from app.main import app
from app.services import channel3_service, weather_service

FROZEN = datetime(2026, 11, 9, 12, 0, 0, tzinfo=timezone.utc)
PREMIUM_DETAIL = "This feature requires an active MYMILE Premium pass."
PRODUCT_QUERY = {"query": "packable rain jacket", "limit": 4}
HOTEL_QUERY = {"destination": "Cairo", "check_in": "2026-12-01", "check_out": "2026-12-05", "nights": 4}
TRIP_BODY = {"destination": "Cairo", "departure_date": "2026-12-01", "return_date": "2026-12-05",
             "travelers": 2, "purpose": "Tourism", "total_budget": 3000}
BUDGET_BODY = {"destination": "Cairo", "duration_days": 5, "travelers": 2, "total_budget": 3000}


def iso(dt):
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


class _NoNetworkClient:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        raise ConnectionError("network disabled in tests")

    async def __aexit__(self, *exc):
        return False


# Documented Channel3 POST /v1/search response shape (https://channel3.ai/docs).
CHANNEL3_PAYLOAD = {"next_page_token": None, "products": [
    {"id": "c3-live-1", "title": "Packable Rain Jacket", "description": "Light shell",
     "brands": [{"id": "b1", "name": "Acme"}],
     "images": [{"url": "https://img.example/1.jpg", "is_main_image": True}],
     "offers": [{"url": "https://merchant.example/p/live-1", "domain": "merchant.example",
                 "price": {"price": 79.0, "compare_at_price": None, "currency": "USD"},
                 "availability": "InStock"}]},
    {"id": "c3-live-2", "title": "Insulated Bottle",
     "brands": [], "images": [{"url": "https://img.example/2.jpg"}],
     "offers": [{"url": "https://shop.example/bottle", "domain": "shop.example",
                 "price": {"price": 25.0, "currency": "USD"}, "availability": "InStock"}]},
]}


_RealAsyncClient = httpx.AsyncClient  # captured before tests patch httpx.AsyncClient globally


def _fake_channel3_client():
    return _RealAsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, json=CHANNEL3_PAYLOAD)))


class _Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _env.ensure_isolated_db()  # explicit, also under python -O

    def setUp(self):
        for p in (mock.patch.object(premium, "utc_now", lambda: FROZEN),
                  mock.patch.object(weather_service.httpx, "AsyncClient", _NoNetworkClient),
                  mock.patch.object(settings, "CHANNEL3_API_KEY", "test-channel3-key"),
                  mock.patch.object(channel3_service, "_make_client", side_effect=_fake_channel3_client),
                  mock.patch.object(settings, "HOTEL_API_KEY", None),
                  mock.patch.object(settings, "GEMINI_API_KEY", None),
                  mock.patch.object(settings, "OPENAI_API_KEY", None)):
            p.start()
            self.addCleanup(p.stop)
        self.api = TestClient(app)

    # -- accounts --
    def register(self, email=None, plan=None, until=None):
        email = email or f"sh-{uuid.uuid4().hex[:8]}@test.example"
        r = self.api.post("/api/auth/register", json={"name": "SH", "email": email, "password": "password123"})
        self.assertEqual(r.status_code, 201, r.text)
        body = r.json()
        if plan is not None:
            with database.connect() as conn:
                conn.execute("UPDATE users SET plan = ?, premium_until = ? WHERE id = ?",
                             (plan, until, body["user"]["id"]))
        return {"email": email, "id": body["user"]["id"], "token": body["access_token"]}

    def premium_account(self, email=None):
        return self.register(email, "premium", iso(FROZEN + timedelta(days=10)))

    @staticmethod
    def bearer(token):
        return {"Authorization": f"Bearer {token}"}

    # -- endpoint probes --
    def products(self, headers=None, **extra):
        r = self.api.get("/api/products/search", params={**PRODUCT_QUERY, **extra}, headers=headers or {})
        self.assertEqual(r.status_code, 200, r.text)
        products = r.json()["products"]
        self.assertTrue(products, "product discovery must stay available")
        return products

    def hotel_links(self, headers=None):
        r = self.api.get("/api/hotels/search", params=HOTEL_QUERY, headers=headers or {})
        self.assertEqual(r.status_code, 200, r.text)
        return sum(1 for h in r.json()["hotels"] if h.get("booking_link"))

    def assert_no_purchase_urls(self, products):
        self.assertTrue(all("purchase_url" in p for p in products), "field must stay in the contract")
        self.assertTrue(all(p["purchase_url"] is None for p in products), "purchase URL leaked")

    def assert_purchase_urls(self, products):
        self.assertTrue(all(isinstance(p["purchase_url"], str) and p["purchase_url"].startswith("https://")
                            for p in products), "Premium purchase URLs missing")

    def assert_treated_as_guest(self, headers):
        """Token must not authenticate: /me 401, and no Premium features anywhere."""
        self.assertEqual(self.api.get("/api/auth/me", headers=headers).status_code, 401)
        self.assert_no_purchase_urls(self.products(headers))
        self.assertEqual(self.hotel_links(headers), 0)
        r = self.api.post("/api/budget/optimize", json=BUDGET_BODY, headers=headers)
        self.assertEqual((r.status_code, r.json()["detail"]), (403, PREMIUM_DETAIL))


# ==========================================================================
# Authentication hardening
# ==========================================================================
class TokenHardeningTest(_Base):

    def _jwt(self, claims, key=None, alg="HS256"):
        claims = {"exp": FROZEN + timedelta(days=365 * 10), **claims}
        return self.bearer(jwt.encode(claims, key or settings.SECRET_KEY, algorithm=alg))

    def test_valid_token_carries_matching_uid(self):
        acct = self.premium_account()
        claims = jwt.get_unverified_claims(acct["token"])
        self.assertEqual((claims["sub"], claims["uid"]), (acct["email"], acct["id"]))
        me = self.api.get("/api/auth/me", headers=self.bearer(acct["token"])).json()
        self.assertEqual((me["id"], me["plan"]), (acct["id"], "premium"))

    def test_forged_alg_none_token_is_rejected(self):
        acct = self.premium_account()
        enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
        forged = f"{enc({'alg': 'none', 'typ': 'JWT'})}.{enc({'sub': acct['email'], 'uid': acct['id'], 'exp': 4102444800})}."
        self.assert_treated_as_guest(self.bearer(forged))

    def test_token_signed_with_wrong_key_is_rejected(self):
        acct = self.premium_account()
        self.assert_treated_as_guest(self._jwt({"sub": acct["email"], "uid": acct["id"]}, key="w" * 48))

    def test_hs512_token_is_rejected(self):
        acct = self.premium_account()
        self.assert_treated_as_guest(self._jwt({"sub": acct["email"], "uid": acct["id"]}, alg="HS512"))

    def test_token_without_uid_is_rejected(self):
        acct = self.premium_account()
        self.assert_treated_as_guest(self._jwt({"sub": acct["email"]}))  # legacy email-only token

    def test_token_with_invalid_uid_is_rejected(self):
        acct = self.premium_account()
        for bad_uid in ("", 123, None, ["usr-x"]):
            self.assert_treated_as_guest(self._jwt({"sub": acct["email"], "uid": bad_uid}))

    def test_token_with_mismatched_uid_is_rejected(self):
        a, b = self.premium_account(), self.premium_account()
        self.assert_treated_as_guest(self._jwt({"sub": a["email"], "uid": b["id"]}))

    def test_token_for_nonexistent_user_is_rejected(self):
        self.assert_treated_as_guest(self._jwt({"sub": "ghost@test.example", "uid": "usr-ghost000"}))

    def test_deleted_then_reregistered_email_does_not_inherit_identity(self):
        old = self.premium_account()
        old_headers = self.bearer(old["token"])
        self.assertEqual(self.api.get("/api/auth/me", headers=old_headers).status_code, 200)

        with database.connect() as conn:  # account deleted
            conn.execute("DELETE FROM users WHERE id = ?", (old["id"],))
        self.assert_treated_as_guest(old_headers)

        new = self.premium_account(email=old["email"])  # same email, new Premium account
        self.assertNotEqual(new["id"], old["id"])
        self.assert_treated_as_guest(old_headers)  # old token must NOT become the new account
        me = self.api.get("/api/auth/me", headers=self.bearer(new["token"])).json()
        self.assertEqual((me["id"], me["plan"]), (new["id"], "premium"))

    def test_stored_free_with_future_expiry_is_free_at_every_endpoint(self):
        acct = self.register(plan="free", until=iso(FROZEN + timedelta(days=30)))
        h = self.bearer(acct["token"])
        self.assertEqual(self.api.get("/api/auth/me", headers=h).json()["plan"], "free")
        self.assert_no_purchase_urls(self.products(h))
        self.assertEqual(self.hotel_links(h), 0)
        self.assertEqual(self.api.post("/api/budget/optimize", json=BUDGET_BODY, headers=h).status_code, 403)
        trip = self.api.post("/api/trips/plan", json=TRIP_BODY, headers=h).json()
        self.assertEqual(trip["plan_tier"], "free")


class ErrorPropagationTest(_Base):
    """A broken DB / unexpected error during optional auth must be a 500, never guest access."""

    def setUp(self):
        super().setUp()
        self.acct = self.premium_account()
        self.headers = self.bearer(self.acct["token"])
        self.raw = TestClient(app, raise_server_exceptions=False)  # real HTTP 500 instead of re-raise

    def _with_db_failure(self, exc):
        return mock.patch.object(database, "connect", side_effect=exc)  # DB layer, not auth logic

    def _assert_500_not_guest(self, exc):
        with self._with_db_failure(exc):
            for method, path, kw in (("get", "/api/products/search", {"params": PRODUCT_QUERY}),
                                     ("get", "/api/hotels/search", {"params": HOTEL_QUERY}),
                                     ("post", "/api/budget/optimize", {"json": BUDGET_BODY})):
                r = getattr(self.raw, method)(path, headers=self.headers, **kw)
                self.assertEqual(r.status_code, 500, f"{path}: {r.status_code} {r.text[:200]}")
                self.assertNotIn("products", r.text)
                self.assertNotIn("hotels", r.text)
                self.assertNotIn(PREMIUM_DETAIL, r.text, "must not be downgraded to a guest denial")

    def test_database_error_returns_500_not_guest_access(self):
        self._assert_500_not_guest(sqlite3.OperationalError("database is locked"))

    def test_unexpected_runtime_error_returns_500_not_guest_access(self):
        self._assert_500_not_guest(RuntimeError("unexpected failure"))

    def test_guest_requests_still_work_while_db_is_down(self):
        # Guests never touch the DB in optional auth, so Free discovery keeps working.
        with self._with_db_failure(sqlite3.OperationalError("down")):
            r = self.raw.get("/api/products/search", params=PRODUCT_QUERY)
        self.assertEqual(r.status_code, 200)
        self.assert_no_purchase_urls(r.json()["products"])


# ==========================================================================
# Channel3 purchase-link enforcement
# ==========================================================================
class Channel3PurchaseLinkTest(_Base):

    def _strip(self, products):
        return [{**{k: v for k, v in p.items() if k not in ("purchase_url", "offers")},
                 "offers": [{k: v for k, v in o.items() if k != "url"} for o in p["offers"]]} for p in products]

    def assert_no_offer_urls(self, products):
        self.assertTrue(all(o["url"] is None for p in products for o in p["offers"]), "offer URL leaked")

    def test_guest_sees_products_without_purchase_urls(self):
        products = self.products()
        self.assert_no_purchase_urls(products)
        self.assert_no_offer_urls(products)
        for p in products:  # genuine product details are NOT hidden
            for field in ("id", "name", "price", "currency", "image_url", "retailer"):
                self.assertTrue(p[field] not in (None, ""), field)

    def test_free_user_sees_products_without_purchase_urls(self):
        products = self.products(self.bearer(self.register()["token"]))
        self.assert_no_purchase_urls(products)
        self.assert_no_offer_urls(products)

    def test_expired_premium_user_gets_no_purchase_urls(self):
        acct = self.register(plan="premium", until=iso(FROZEN - timedelta(seconds=1)))
        self.assert_no_purchase_urls(self.products(self.bearer(acct["token"])))

    def test_active_premium_and_demo_get_channel3_purchase_urls(self):
        demo = self.api.post("/api/auth/login", json={"email": "alex@example.com", "password": "password123"}).json()
        for token in (self.premium_account()["token"], demo["access_token"]):
            products = self.products(self.bearer(token))
            self.assertEqual([p["purchase_url"] for p in products],
                             ["https://merchant.example/p/live-1", "https://shop.example/bottle"])
            self.assertEqual(products[0]["offers"][0]["url"], "https://merchant.example/p/live-1")

    def test_details_identical_across_plans_only_urls_differ(self):
        guest = self.products()
        prem = self.products(self.bearer(self.premium_account()["token"]))
        self.assertEqual(self._strip(guest), self._strip(prem))

    def test_plan_query_parameter_cannot_unlock_purchase_urls(self):
        self.assert_no_purchase_urls(self.products(None, plan="premium"))
        self.assert_no_purchase_urls(self.products(self.bearer(self.register()["token"]), plan="premium"))

    def test_cached_results_are_never_mutated_by_the_policy(self):
        self.assert_no_purchase_urls(self.products())                       # guest first
        self.assert_purchase_urls(self.products(self.bearer(self.premium_account()["token"])))
        self.assert_no_purchase_urls(self.products())

    def _plan_with_products(self, headers):
        from tests._fake_gemini import FakeGemini, calls, text
        plan = {"summary": "s", "why_recommended": "w", "recommended_hotel_id": None,
                "itinerary": [{"day_number": n, "theme": "t", "activities": [{"time": "09:00 AM", "title": "x"}]}
                              for n in range(1, 5)],
                "essentials": [{"product_id": "c3-live-1", "reason": "Rain is likely."}]}
        fake = FakeGemini([calls(("find_travel_products", {"queries": ["packable rain jacket"]})), text(plan)])
        with fake.patch():
            r = self.api.post("/api/trips/plan", json={**TRIP_BODY, "departure_date": "2026-12-01",
                                                       "destination": f"Cairo {uuid.uuid4().hex[:6]}"},
                              headers=headers)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_trip_travel_essentials_hide_urls_for_guest_and_free(self):
        for headers in ({}, self.bearer(self.register()["token"])):
            trip = self._plan_with_products(headers)
            self.assertEqual([p["id"] for p in trip["travel_essentials"]], ["c3-live-1"])
            self.assert_no_purchase_urls(trip["travel_essentials"])
            self.assert_no_offer_urls(trip["travel_essentials"])

    def test_trip_travel_essentials_keep_urls_for_premium(self):
        trip = self._plan_with_products(self.bearer(self.premium_account()["token"]))
        self.assertEqual(trip["plan_tier"], "premium")
        self.assertEqual(trip["travel_essentials"][0]["purchase_url"], "https://merchant.example/p/live-1")
        self.assertEqual(trip["travel_essentials"][0]["reason"], "Rain is likely.")

    def test_service_is_closed_by_default(self):
        import asyncio
        res = asyncio.run(channel3_service.search_products_response("packable rain jacket"))  # no plan passed
        self.assertTrue(res.products)
        self.assertTrue(all(p.purchase_url is None and all(o.url is None for o in p.offers) for p in res.products))


if __name__ == "__main__":
    unittest.main()
