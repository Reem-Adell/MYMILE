"""
Shopping audience ("Who are you shopping for?"), products named in the notes becoming real
Channel3 searches (the London "broken mouse" case), and the manual product search endpoint.

Run from backend/:
    venv\\Scripts\\python -m unittest tests.test_shopping_audience_and_requests -v
No real Groq, Channel3 or weather requests: all are mocked.
"""
from tests import _env  # noqa: F401  (must precede any app.* import)

import json
from contextlib import contextmanager
from unittest import mock

import httpx

from app.agents import tools, travel_agent
from app.core.config import settings
from app.services import trip_shopping
from tests._fake_groq import FakeGroq, calls, text
from tests.test_channel3 import FakeChannel3, ok
from tests.test_gemini_agent import plan_json
from tests.test_product_coverage import live
from tests.test_trip_context_products import LONDON
from tests.test_trip_products import _ProductsApi, prompt_parts

LONDON_NOTE = ("I'm traveling to London for a 3-day business conference. My mouse broke last week and I need a new "
               "one for work. I also need professional outfits and comfortable formal shoes.")
MOUSE = live("ms1", "Logitech M720 Wireless Mouse", "Logitech", "Computer Mice", 39.99)


class _LondonApi(_ProductsApi):

    @contextmanager
    def london(self):
        async def fake(*args, **kwargs):
            return LONDON
        with mock.patch.object(tools, "get_weather_forecast", side_effect=fake), \
             mock.patch.object(travel_agent, "get_weather_forecast", side_effect=fake):
            yield

    def london_trip(self, fake, headers=None, **over):
        body = dict(destination_city="London", destination_country="United Kingdom", purpose="Business",
                    departure_date="2026-12-07", return_date="2026-12-10", travelers=1,
                    stay_preference="Boutique hotel", priorities=[], notes=LONDON_NOTE)
        body.update(over)
        with self.london(), fake.patch(), mock.patch.object(settings, "CHANNEL3_RESULTS_PER_QUERY", 5):
            return self._plan(headers=headers, **body)


# ------------------------------------------------------- the broken-mouse case ---
# -------------------------------------------------------------- manual search ---
class ManualSearchTest(_ProductsApi):

    def search(self, headers=None, **params):
        return self.api.get("/api/products/search", params=params, headers=headers or {})

    def test_exact_query_goes_to_channel3(self):
        c3 = self.serve(FakeChannel3(ok(MOUSE)))
        r = self.search(query="  Wireless   Mouse ", limit=6)
        self.assertEqual(r.status_code, 200, r.text)
        body = json.loads(c3.requests[0].content)
        self.assertEqual((body["query"], body["limit"]), ("Wireless Mouse", 4),
                         "exact words; limit capped by CHANNEL3_RESULTS_PER_QUERY (4 in these tests)")
        data = r.json()
        self.assertEqual((data["status"], [p["id"] for p in data["products"]]), ("ok", ["ms1"]))
        self.assertIsNone(data["products"][0]["purchase_url"], "guest/Free: no retailer link")

    def test_premium_gets_the_retailer_link(self):
        self.serve(FakeChannel3(ok(MOUSE)))
        data = self.search(headers=self._premium(), query="wireless mouse").json()
        self.assertEqual(data["products"][0]["purchase_url"], "https://shop.example/ms1")

    def test_audience_refines_clothing_only_and_filters(self):
        c3 = self.serve(FakeChannel3(ok(live("w1", "Women's Leather Loafer", "Clarks", "Dress Shoes", 80.0),
                                        live("m1", "Men's Oxford Dress Shoe", "Ecco", "Dress Shoes", 120.0))))
        data = self.search(query="dress shoes", audience="men").json()
        self.assertEqual(json.loads(c3.requests[0].content)["query"], "men's dress shoes")
        self.assertEqual([p["id"] for p in data["products"]], ["m1"])
        self.search(query="wireless mouse", audience="women")
        self.assertEqual(json.loads(c3.requests[1].content)["query"], "wireless mouse", "no audience words for gear")

    def test_cached_search_spends_no_second_credit(self):
        c3 = self.serve(FakeChannel3(ok(MOUSE)))
        self.search(query="wireless mouse")
        self.search(query="Wireless  mouse")
        self.assertEqual(len(c3.requests), 1)

    def test_invalid_empty_and_error_states(self):
        self.assertEqual(self.search(query="").status_code, 422)
        self.assertEqual(self.search(query="x").status_code, 422)
        self.assertEqual(self.search(query="ok", audience="kids").status_code, 422)
        self.serve(FakeChannel3(ok()))
        empty = self.search(query="nothing like this").json()
        self.assertEqual((empty["status"], empty["products"]), ("empty", []))
        self.serve(FakeChannel3(httpx.ConnectError("down")))
        err = self.search(query="wireless keyboard").json()
        self.assertEqual(err["status"], "unavailable")
        self.assertIn("couldn't reach Channel3", err["message"])
