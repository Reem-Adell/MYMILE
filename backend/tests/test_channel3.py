"""
Channel3 product search: documented request/response handling, no invented data,
errors, cache and limits, the Gemini product tool, and trip essentials.

Run from backend/:
    venv\\Scripts\\python -m unittest tests.test_channel3 -v
No real Channel3 or Gemini requests: HTTP is served by httpx.MockTransport.
"""
from tests import _env  # noqa: F401  (must precede any app.* import)

import asyncio
import json
import time
import unittest
from contextlib import closing
from unittest import mock

import httpx

from app.agents import tools as agent_tools, travel_agent
from app.agents.tools import AgentToolbox, TripContext
from app.core.config import settings
from app.services import channel3_service
from tests._fake_gemini import FakeGemini, calls, text
from tests.test_explore_trip import _Api, run
from tests.test_gemini_agent import clear_plan_cache, live_weather

KEY = "c3-test-SECRET-key"


def product(pid, title="Packable Rain Jacket", **over):
    p = {"id": pid, "title": title, "description": "Light shell", "brands": [{"id": "b", "name": "Acme"}],
         "images": [{"url": f"https://img.example/{pid}-alt.jpg", "is_main_image": False},
                    {"url": f"https://img.example/{pid}.jpg", "is_main_image": True}],
         "category": {"slug": "jackets", "title": "Rain Jackets", "path": [], "has_children": False},
         "ratings": {"value": 4.6, "count": 210, "source_count": 2},
         "variants": {"options": [{"name": "Size", "values": [{"label": "S", "available": True},
                                                              {"label": "M", "available": False},
                                                              {"label": "L", "available": True}]}]},
         "offers": [{"url": f"https://shop-b.example/{pid}", "domain": "shop-b.example",
                     "price": {"price": 99.0, "compare_at_price": None, "currency": "USD"}, "availability": "InStock"},
                    {"url": f"https://shop-a.example/{pid}", "domain": "shop-a.example",
                     "price": {"price": 79.0, "compare_at_price": 110.0, "currency": "USD"},
                     "availability": "InStock"},
                    {"url": f"https://shop-c.example/{pid}", "domain": "shop-c.example",
                     "price": {"price": 50.0, "currency": "USD"}, "availability": "OutOfStock"}]}
    p.update(over)
    return p


class FakeChannel3:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        item = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(item, Exception):
            raise item
        status, body = item
        return httpx.Response(status, json=body) if not isinstance(body, str) else httpx.Response(status, text=body)

    def client(self):
        return httpx.AsyncClient(transport=httpx.MockTransport(self))

    def bodies(self):
        return [json.loads(r.content) for r in self.requests]


def ok(*products):
    return (200, {"products": list(products), "next_page_token": None})


class _C3Case(unittest.TestCase):
    def setUp(self):
        super().setUp()
        channel3_service.reset_inflight()
        with closing(channel3_service._db()) as conn:
            conn.execute("DELETE FROM channel3_cache")
            conn.commit()
        for p in (mock.patch.object(settings, "CHANNEL3_API_KEY", KEY),
                  mock.patch.object(settings, "CHANNEL3_BASE_URL", "https://api.trychannel3.com"),
                  mock.patch.object(settings, "CHANNEL3_RESULTS_PER_QUERY", 4),
                  mock.patch.object(settings, "CHANNEL3_MAX_QUERIES_PER_TRIP", 3),
                  mock.patch.object(settings, "CHANNEL3_CACHE_TTL_HOURS", 24.0)):
            p.start()
            self.addCleanup(p.stop)

    def serve(self, fake):
        p = mock.patch.object(channel3_service, "_make_client", side_effect=fake.client)
        p.start()
        self.addCleanup(p.stop)
        return fake


# ------------------------------------------------------------ request/response ---
class RequestResponseTest(_C3Case):

    def test_documented_endpoint_auth_and_body(self):
        fake = self.serve(FakeChannel3(ok(product("p1"))))
        run(channel3_service.search("  packable   rain jacket "))
        req = fake.requests[0]
        self.assertEqual((req.method, str(req.url)), ("POST", "https://api.trychannel3.com/v1/search"))
        self.assertEqual(req.headers["x-api-key"], KEY)
        self.assertNotIn("authorization", {k.lower() for k in req.headers})
        self.assertEqual(fake.bodies()[0], {"query": "packable rain jacket", "limit": 4,
                                            "config": {"currency": "USD", "country": "US"}})

    def test_legacy_guessed_base_url_is_replaced(self):
        fake = self.serve(FakeChannel3(ok(product("p1"))))
        with mock.patch.object(settings, "CHANNEL3_BASE_URL", "https://api.channel3.ai/v1"):
            run(channel3_service.search("rain jacket"))
        self.assertEqual(str(fake.requests[0].url), "https://api.trychannel3.com/v1/search")

    def test_genuine_fields_are_preserved(self):
        self.serve(FakeChannel3(ok(product("p1"))))
        p = run(channel3_service.search("rain jacket"))["products"][0]
        self.assertEqual((p["id"], p["name"], p["brand"], p["category"]), ("p1", "Packable Rain Jacket", "Acme", "Rain Jackets"))
        self.assertEqual(p["image_url"], "https://img.example/p1.jpg", "main image")
        self.assertEqual((p["rating"], p["rating_count"]), (4.6, 210))
        self.assertEqual(p["variants"], ["Size: S, L"], "unavailable variants left out")
        # main offer = cheapest in-stock offer
        self.assertEqual((p["retailer"], p["price"], p["compare_at_price"], p["currency"], p["in_stock"]),
                         ("shop-a.example", 79.0, 110.0, "USD", True))
        self.assertEqual(p["purchase_url"], "https://shop-a.example/p1")
        self.assertEqual([o["retailer"] for o in p["offers"]], ["shop-b.example", "shop-a.example", "shop-c.example"])

    def test_missing_optional_fields_are_never_invented(self):
        bare = {"id": "p2", "title": "Travel Adapter", "brands": [], "images": [], "offers": []}
        self.serve(FakeChannel3(ok(bare, {"title": "no id"}, {"id": "x"})))
        found = run(channel3_service.search("adapter"))["products"]
        self.assertEqual([p["id"] for p in found], ["p2"], "entries without id/title are dropped")
        p = found[0]
        for field in ("price", "currency", "image_url", "rating", "purchase_url", "retailer", "in_stock", "brand"):
            self.assertIsNone(p[field], field)

    def test_unsafe_urls_are_dropped(self):
        evil = product("p3", images=[{"url": "javascript:alert(1)"}],
                       offers=[{"url": "javascript:alert(1)", "domain": "x.example",
                                "price": {"price": 5, "currency": "USD"}, "availability": "InStock"}])
        self.serve(FakeChannel3(ok(evil)))
        p = run(channel3_service.search("travel pouch"))["products"][0]
        self.assertIsNone(p["image_url"])
        self.assertIsNone(p["purchase_url"])


# ---------------------------------------------------------------------- errors ---
class ErrorTest(_C3Case):

    def test_documented_errors_are_reported(self):
        for status, code in ((401, "INVALID_API_KEY"), (402, "CREDITS_EXHAUSTED"), (422, "INVALID_REQUEST"),
                             (429, "RATE_LIMITED"), (500, "SERVICE_ERROR"), (504, "TIMEOUT")):
            channel3_service.reset_inflight()
            with mock.patch.object(channel3_service, "_make_client",
                                   side_effect=FakeChannel3((status, {"detail": "x"})).client):
                with self.assertRaises(channel3_service.Channel3Error) as ctx:
                    run(channel3_service.search(f"query {status}"))
            self.assertEqual(ctx.exception.code, code)

    def test_timeout_network_and_bad_json(self):
        for item, code in ((httpx.ReadTimeout("slow"), "TIMEOUT"), (httpx.ConnectError("down"), "NETWORK"),
                           ((200, "not json"), "INVALID_RESPONSE"), ((200, [1, 2]), "INVALID_RESPONSE")):
            channel3_service.reset_inflight()
            with mock.patch.object(channel3_service, "_make_client", side_effect=FakeChannel3(item).client):
                with self.assertRaises(channel3_service.Channel3Error) as ctx:
                    run(channel3_service.search(f"q {code}"))
            self.assertEqual(ctx.exception.code, code)

    def test_missing_key_sends_nothing(self):
        fake = self.serve(FakeChannel3(ok(product("p1"))))
        with mock.patch.object(settings, "CHANNEL3_API_KEY", ""):
            res = run(channel3_service.search_products_response("rain jacket"))
        self.assertEqual((res.status, res.products), ("not_configured", []))
        self.assertEqual(fake.requests, [])

    def test_key_never_appears_in_errors(self):
        self.serve(FakeChannel3((401, {"detail": f"bad key {KEY}"})))
        res = run(channel3_service.search_products_response("rain jacket"))
        self.assertEqual(res.status, "unavailable")
        self.assertNotIn(KEY, res.model_dump_json())


# ------------------------------------------------------------------- cache/limits ---
class CacheAndLimitsTest(_C3Case):

    def test_cache_hit_spends_no_credit(self):
        fake = self.serve(FakeChannel3(ok(product("p1"))))
        run(channel3_service.search("Rain Jacket"))
        run(channel3_service.search("rain   jacket"))
        self.assertEqual(len(fake.requests), 1)

    def test_cache_expires_and_failed_refresh_serves_stale(self):
        fake = self.serve(FakeChannel3(ok(product("p1")), (500, {"detail": "x"})))
        run(channel3_service.search("rain jacket"))
        real = time.time
        with mock.patch.object(channel3_service.time, "time", side_effect=lambda: real() + 25 * 3600):
            res = run(channel3_service.search("rain jacket"))
        self.assertEqual((len(fake.requests), res["stale"], res["products"][0]["id"]), (2, True, "p1"))

    def test_identical_searches_in_flight_share_one_request(self):
        calls_made = []

        async def handler(request):
            calls_made.append(request)
            await asyncio.sleep(0.05)
            return httpx.Response(200, json={"products": [product("p1")]})

        async def go():
            with mock.patch.object(channel3_service, "_make_client",
                                   side_effect=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))):
                return await asyncio.gather(*[channel3_service.search("rain jacket") for _ in range(4)])
        run(go())
        self.assertEqual(len(calls_made), 1)

    def test_results_per_query_is_capped(self):
        fake = self.serve(FakeChannel3(ok(*[product(f"p{i}") for i in range(12)])))
        with mock.patch.object(settings, "CHANNEL3_RESULTS_PER_QUERY", 50):
            found = run(channel3_service.search("rain jacket"))["products"]
        self.assertEqual(fake.bodies()[0]["limit"], channel3_service.MAX_RESULTS_PER_QUERY)
        self.assertEqual(len(found), channel3_service.MAX_RESULTS_PER_QUERY)


# -------------------------------------------------------------------- Gemini tool ---
def ctx():
    return TripContext(destination="Lisbon, Portugal", city="Lisbon", country="Portugal", check_in="2026-12-01",
                       check_out="2026-12-04", nights=3, travelers=2, purpose="Tourism",
                       stay_preference="Boutique hotel", priorities=["Local culture"], notes="I walk a lot")


class ProductToolTest(_C3Case):

    def names(self, box):
        return [d.name for d in box.declarations()[0].function_declarations]

    def test_tool_offered_only_for_planning_with_a_key(self):
        self.assertIn("find_travel_products", self.names(AgentToolbox(ctx(), "free", allow_products=True)))
        self.assertNotIn("find_travel_products", self.names(AgentToolbox(ctx(), "free")), "chat")
        with mock.patch.object(settings, "CHANNEL3_API_KEY", ""):
            self.assertNotIn("find_travel_products", self.names(AgentToolbox(ctx(), "free", allow_products=True)))

    def test_queries_are_limited_deduplicated_and_tool_runs_once(self):
        fake = self.serve(FakeChannel3(ok(product("p1")), ok(product("p2")), ok(product("p3"))))
        box = AgentToolbox(ctx(), "free", allow_products=True)
        result = run(box.execute("find_travel_products", {"queries": [
            "rain jacket", "Rain  Jacket", "walking shoes", "travel adapter", "extra query", "x"]}))
        self.assertEqual(box.product_queries, ["rain jacket", "walking shoes", "travel adapter"])
        self.assertEqual(len(fake.requests), 3)
        self.assertEqual({p["id"] for p in result["products"]}, {"p1", "p2", "p3"})
        sent = json.dumps(result)
        self.assertNotIn("http", sent, "no URLs or images are sent to the model")
        again = run(box.execute("find_travel_products", {"queries": ["sunglasses"]}))
        self.assertIn("limit", again["error"])
        self.assertEqual(len(fake.requests), 3)

    def test_fatal_errors_stop_further_searches(self):
        fake = self.serve(FakeChannel3((402, {"detail": "no credits"})))
        box = AgentToolbox(ctx(), "free", allow_products=True)
        result = run(box.execute("find_travel_products", {"queries": ["a jacket", "b shoes", "c adapter"]}))
        self.assertEqual(len(fake.requests), 1)
        self.assertEqual(result["products"], [])
        self.assertIn("credits", result["message"])


# -------------------------------------------------------------- trip essentials ---
def plan_json(essentials):
    return {"summary": "s", "why_recommended": "w", "recommended_hotel_id": None,
            "itinerary": [{"day_number": n, "theme": "t", "activities": [{"time": "09:00 AM", "title": "x"}]}
                          for n in (1, 2, 3)], "essentials": essentials}


class TripEssentialsTest(_C3Case, _Api):

    def setUp(self):
        super().setUp()
        clear_plan_cache()
        for p in (mock.patch.object(agent_tools, "get_weather_forecast", side_effect=live_weather),
                  mock.patch.object(travel_agent, "get_weather_forecast", side_effect=live_weather)):
            p.start()
            self.addCleanup(p.stop)

    def trip(self, headers=None, **over):
        body = {"destination": "Lisbon, Portugal", "destination_city": "Lisbon", "destination_country": "Portugal",
                "departure_date": "2026-12-01", "return_date": "2026-12-04", "travelers": 2,
                "purpose": "Tourism", "stay_preference": "Boutique hotel", "priorities": ["Local culture"],
                "notes": "I walk a lot", **over}
        r = self.api.post("/api/trips/plan", json=body, headers=headers or {})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_gemini_queries_and_picks_become_real_products(self):
        c3 = self.serve(FakeChannel3(ok(product("p1")), ok(product("p2", "Walking Shoes"))))
        fake = FakeGemini([calls(("find_travel_products", {"queries": ["packable rain jacket", "walking shoes"]})),
                           text(plan_json([{"product_id": "p2", "reason": "You walk a lot."},
                                           {"product_id": "invented-id", "reason": "x"}]))])
        with fake.patch():
            trip = self.trip()
        self.assertEqual(trip["essentials"]["status"], "ok")
        self.assertEqual(trip["essentials"]["queries"], ["packable rain jacket", "walking shoes"])
        self.assertEqual([(p["id"], p["reason"]) for p in trip["travel_essentials"]], [("p2", "You walk a lot.")])
        self.assertIsNone(trip["travel_essentials"][0]["purchase_url"], "Free: no link")
        self.assertEqual(len(c3.requests), 2)
        system = fake.requests[0]["system"]
        self.assertIn("find_travel_products", system)
        self.assertIn("never assume gender", system)
        prompt = fake.requests[0]["contents"][-1].parts[0].text
        for value in ("Lisbon, Portugal", "2026-12-01", "Tourism", "Boutique hotel", "Local culture", "I walk a lot"):
            self.assertIn(value, prompt)

    def test_premium_gets_links_and_cached_plan_spends_no_credit(self):
        c3 = self.serve(FakeChannel3(ok(product("p1"))))
        fake = FakeGemini([calls(("find_travel_products", {"queries": ["rain jacket"]})),
                           text(plan_json([{"product_id": "p1", "reason": "Rainy season."}]))])
        headers = self._premium()
        with fake.patch():
            first = self.trip(headers=headers)
            again = self.trip(headers=headers)
        self.assertEqual(first["travel_essentials"][0]["purchase_url"], "https://shop-a.example/p1")
        self.assertEqual(again["travel_essentials"], first["travel_essentials"])
        self.assertTrue(again["ai"]["cached"])
        self.assertEqual(len(c3.requests), 1, "refresh: Gemini and Channel3 both served from cache")

    def test_states_without_key_or_ai(self):
        with mock.patch.object(settings, "CHANNEL3_API_KEY", ""):
            no_key = self.trip()
        self.assertEqual((no_key["essentials"]["status"], no_key["travel_essentials"]), ("not_configured", []))
        no_ai = self.trip(travelers=3)  # GEMINI_API_KEY is empty in tests
        self.assertEqual((no_ai["essentials"]["status"], no_ai["travel_essentials"]), ("ai_unavailable", []))

    def test_channel3_failure_is_reported_not_faked(self):
        self.serve(FakeChannel3((429, {"detail": "slow down"})))
        fake = FakeGemini([calls(("find_travel_products", {"queries": ["rain jacket"]})), text(plan_json([]))])
        with fake.patch():
            trip = self.trip()
        self.assertEqual(trip["essentials"]["status"], "unavailable")
        self.assertIn("rate limiting", trip["essentials"]["message"])
        self.assertEqual(trip["travel_essentials"], [])


if __name__ == "__main__":
    unittest.main()
