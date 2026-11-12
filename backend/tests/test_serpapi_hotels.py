"""
SerpApi Google Hotels integration: real hotel data, provider booking links,
quota-saving cache, error handling, Free/Premium rules, no API key leakage.

Run from backend/:
    venv\\Scripts\\python -m unittest tests.test_serpapi_hotels -v
No real network calls: every SerpApi response is served by httpx.MockTransport.
"""
from tests import _env  # noqa: F401  (must precede any app.* import)

import asyncio
import json
import logging
import time
import unittest
from contextlib import closing
from datetime import date, timedelta
from unittest import mock

import httpx

from app.core.config import settings
from app.services import hotel_service, serpapi_hotels
from tests.test_explore_trip import _Api, run

KEY = "sk-test-SECRET-key-123456"
CHECK_IN = (date.today() + timedelta(days=30)).isoformat()
CHECK_OUT = (date.today() + timedelta(days=33)).isoformat()
TRIP = {"destination": "Lisbon, Portugal", "destination_city": "Lisbon", "destination_country": "Portugal",
        "departure_date": CHECK_IN, "return_date": CHECK_OUT, "travelers": 2, "purpose": "Tourism",
        "stay_preference": "Boutique hotel", "notes": "A relaxed city break with museums."}


def rate(nightly, total=None, before=None):
    out = {"rate_per_night": {"lowest": f"${nightly}", "extracted_lowest": nightly}}
    if before:
        out["rate_per_night"]["extracted_before_taxes_fees"] = before
    if total:
        out["total_rate"] = {"lowest": f"${total}", "extracted_lowest": total}
    return out


def prop(name, token, nightly=120, total=360, prices=None, **extra):
    p = {"type": "hotel", "name": name, "property_token": token,
         "description": f"{name} description from Google.",
         "link": f"https://www.{token}-hotel.example/",
         "gps_coordinates": {"latitude": 38.71, "longitude": -9.14},
         "overall_rating": 4.6, "reviews": 1834, "hotel_class": "4-star hotel", "extracted_hotel_class": 4,
         "amenities": ["Free Wi-Fi", "Pool", "Breakfast"],
         "images": [{"thumbnail": f"https://lh.example/{token}-t.jpg",
                     "original_image": f"https://lh.example/{token}.jpg"}],
         "nearby_places": [{"name": "Rossio Station", "transportations": [{"type": "Walking", "duration": "5 min"}]}],
         **(rate(nightly, total) if nightly else {}),
         **extra}
    if prices is not None:
        p["prices"] = prices
    return p


def search_body(*props):
    return {"search_metadata": {"status": "Success"}, "properties": list(props)}


class FakeSerpApi:
    """Records requests; answers from a list of (status, json) or a function."""

    def __init__(self, *responses, handler=None):
        self.responses = list(responses)
        self.handler = handler
        self.requests = []

    def __call__(self, request: httpx.Request):
        self.requests.append(request)
        if self.handler:
            return self.handler(request)
        item = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(item, Exception):
            raise item
        status, body = item
        return httpx.Response(status, json=body)

    def client(self):
        return httpx.AsyncClient(transport=httpx.MockTransport(self))

    def params(self, i=-1):
        return dict(self.requests[i].url.params)


class _SerpApiCase(unittest.TestCase):

    def setUp(self):
        super().setUp()
        serpapi_hotels.reset_guards()
        with closing(serpapi_hotels._db()) as conn:
            conn.execute("DELETE FROM hotel_api_cache")
            conn.commit()
        for patcher in (mock.patch.object(settings, "HOTEL_API_KEY", KEY),
                        mock.patch.object(settings, "HOTEL_CACHE_TTL_HOURS", 24.0)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def serve(self, fake: FakeSerpApi):
        patcher = mock.patch.object(serpapi_hotels, "_make_client", side_effect=fake.client)
        patcher.start()
        self.addCleanup(patcher.stop)
        return fake

    def search(self, plan="free", **over):
        args = {"destination": "Lisbon, Portugal", "city": "Lisbon", "country": "Portugal",
                "check_in": CHECK_IN, "check_out": CHECK_OUT, "total_nights": 3, "travelers": 2,
                "plan": plan, **over}
        return run(hotel_service.search_hotels(**args))


# ---------------------------------------------------------------- search ---
class LiveSearchTest(_SerpApiCase):

    def test_request_uses_exact_destination_dates_adults_and_usd(self):
        fake = self.serve(FakeSerpApi((200, search_body(prop("Hotel A", "tok-a")))))
        self.search(travelers=3)
        p = fake.params()
        self.assertEqual(str(fake.requests[0].url).split("?")[0], "https://serpapi.com/search.json")
        self.assertEqual((p["engine"], p["q"], p["check_in_date"], p["check_out_date"], p["adults"], p["currency"]),
                         ("google_hotels", "Lisbon, Portugal", CHECK_IN, CHECK_OUT, "3", "USD"))
        self.assertEqual(p["api_key"], KEY, "key is sent to SerpApi only")

    def test_hotel_details_are_extracted_from_the_response(self):
        self.serve(FakeSerpApi((200, search_body(prop("Hotel Avenida", "tok-a", nightly=120, total=365)))))
        res = self.search()
        self.assertEqual((res.source, res.results_status), ("Google Hotels via SerpApi", "live"))
        h = res.hotels[0]
        self.assertEqual((h.name, h.rating, h.reviews_count, h.hotel_class), ("Hotel Avenida", 4.6, 1834, "4-star hotel"))
        self.assertEqual((h.price_per_night, h.total_price, h.total_price_basis, h.currency), (120, 365, "listed", "USD"))
        self.assertEqual((h.price_source, h.price_provider, h.data_source), ("live", "Google Hotels", "serpapi"))
        self.assertEqual(h.image_url, "https://lh.example/tok-a.jpg")
        self.assertFalse(h.image_is_illustrative)
        self.assertEqual(h.amenities, ["Free Wi-Fi", "Pool", "Breakfast"])
        self.assertEqual((h.latitude, h.longitude), (38.71, -9.14))
        self.assertEqual(h.description, "Hotel Avenida description from Google.")
        self.assertEqual(h.distance_to_center, "Rossio Station · 5 min by walking")
        # Portugal is not in MYMILE's country-code table: the ISO code is left empty, never guessed.
        self.assertEqual((h.property_token, h.city, h.country, h.adults), ("tok-a", "Lisbon", None, 2))
        self.assertIsNotNone(h.price_checked_at)
        self.assertTrue(h.is_best_match)
        self.assertFalse(h.is_placeholder)

    def test_never_returns_curated_hotels_when_live(self):
        self.serve(FakeSerpApi((200, search_body(prop("Hotel Cairo Live", "tok-c")))))
        res = self.search(destination="Cairo, Egypt", city="Cairo", country="Egypt")
        self.assertEqual([h.name for h in res.hotels], ["Hotel Cairo Live"])
        self.assertTrue(all(h.data_source == "serpapi" for h in res.hotels))

    def test_missing_price_and_images_are_never_invented(self):
        bare = {"type": "hotel", "name": "Bare Hotel", "property_token": "tok-bare"}
        self.serve(FakeSerpApi((200, search_body(bare))))
        h = self.search().hotels[0]
        self.assertEqual((h.price_per_night, h.total_price, h.total_price_basis), (None, None, None))
        self.assertEqual((h.rating, h.reviews_count, h.amenities, h.images), (0, 0, [], []))
        self.assertTrue(h.image_is_illustrative)
        self.assertIsNone(h.description)
        self.assertEqual(h.best_match_reason, "Listed on Google Hotels for your dates.")

    def test_nightly_only_total_is_marked_as_computed(self):
        self.serve(FakeSerpApi((200, search_body(prop("Hotel N", "tok-n", nightly=100, total=None)))))
        h = self.search().hotels[0]
        self.assertEqual((h.total_price, h.total_price_basis), (300, "nightly_x_nights"))

    def test_single_hotel_match_at_top_level_is_supported(self):
        self.serve(FakeSerpApi((200, {"search_metadata": {"status": "Success"}, **prop("Only Hotel", "tok-o")})))
        self.assertEqual([h.name for h in self.search().hotels], ["Only Hotel"])

    def test_empty_results_show_an_empty_state(self):
        for body in (search_body(), {"error": "Google Hotels hasn't returned any results for this query."}):
            serpapi_hotels.reset_guards()
            with closing(serpapi_hotels._db()) as conn:
                conn.execute("DELETE FROM hotel_api_cache")
                conn.commit()
            with mock.patch.object(serpapi_hotels, "_make_client", side_effect=FakeSerpApi((200, body)).client):
                res = self.search()
            self.assertEqual(res.results_status, "empty")
            self.assertEqual(len(res.hotels), 1)
            card = res.hotels[0]
            self.assertTrue(card.is_placeholder)
            self.assertIsNone(card.price_per_night)
            self.assertIsNone(card.booking_link)
            self.assertIn("didn't list any hotels", card.best_match_reason)


# --------------------------------------------------------- booking links ---
BOOKING = {"source": "Booking.com", "link": "https://www.booking.com/hotel/pt/avenida.html?aid=1", **rate(130, 390)}
EXPEDIA = {"source": "Expedia", "link": "https://www.expedia.com/Lisbon-Hotels-Avenida.h123.Hotel-Information",
           **rate(125, 375)}
AGODA = {"source": "Agoda", "link": "https://www.agoda.com/avenida/hotel/lisbon-pt.html", **rate(110, 330)}
NO_LINK = {"source": "Hotels.com", **rate(100, 300)}


class BookingLinkSelectionTest(_SerpApiCase):

    def test_booking_com_link_is_used_when_available(self):
        self.serve(FakeSerpApi((200, search_body(prop("H", "tok-a", prices=[AGODA, BOOKING, EXPEDIA])))))
        h = self.search(plan="premium").hotels[0]
        self.assertEqual((h.booking_provider, h.booking_link, h.booking_link_type),
                         ("Booking.com", BOOKING["link"], "provider"))
        self.assertEqual([o.provider for o in h.booking_offers], ["Agoda", "Booking.com", "Expedia"])

    def test_falls_back_to_another_real_provider(self):
        self.serve(FakeSerpApi((200, search_body(prop("H", "tok-a", prices=[EXPEDIA, AGODA, NO_LINK])))))
        h = self.search(plan="premium").hotels[0]
        self.assertEqual((h.booking_provider, h.booking_link), ("Agoda", AGODA["link"]), "cheapest with a URL")
        self.assertNotIn("Hotels.com", [o.provider for o in h.booking_offers], "offers without URL aren't links")

    def test_missing_booking_url_means_no_link_and_website_is_not_a_booking_link(self):
        self.serve(FakeSerpApi((200, search_body(prop("H", "tok-a", prices=[NO_LINK])))))
        h = self.search(plan="premium").hotels[0]
        self.assertIsNone(h.booking_link)
        self.assertIsNone(h.booking_provider)
        self.assertEqual(h.official_website, "https://www.tok-a-hotel.example/")

    def test_non_http_urls_are_rejected(self):
        bad = {"source": "Booking.com", "link": "javascript:alert(1)", **rate(130)}
        self.assertIsNone(serpapi_hotels.select_offer(serpapi_hotels.parse_offers([bad])))


# ---------------------------------------------------------- offers route ---
class OffersRouteTest(_SerpApiCase, _Api):
    # setUp: _SerpApiCase.setUp -> super() -> _Api.setUp (test client + isolated DB)

    def _offers(self, headers, token="tok-a", **over):
        params = {"property_token": token, "destination": "Lisbon, Portugal", "city": "Lisbon",
                  "country": "Portugal", "check_in": CHECK_IN, "check_out": CHECK_OUT, "adults": 2, **over}
        return self.api.get("/api/hotels/offers", params=params, headers=headers)

    def test_details_request_supplies_links_once_then_cache(self):
        details = {"search_metadata": {"status": "Success"}, "name": "H", "address": "Av. da Liberdade 1, Lisbon",
                   "phone": "+351 21 000 0000", "link": "https://www.tok-a-hotel.example/",
                   "featured_prices": [EXPEDIA], "prices": [BOOKING, NO_LINK]}
        fake = self.serve(FakeSerpApi((200, search_body(prop("H", "tok-a", prices=[NO_LINK]))), (200, details)))
        headers = self._premium()
        self._plan(headers=headers, **TRIP)
        self.assertEqual(len(fake.requests), 1, "the search itself makes one request")

        body = self._offers(headers).json()
        self.assertEqual(fake.params()["property_token"], "tok-a")
        self.assertEqual((body["status"], body["booking_provider"], body["booking_link"]),
                         ("ok", "Booking.com", BOOKING["link"]))
        self.assertEqual((body["address"], body["phone"], body["official_website"]),
                         ("Av. da Liberdade 1, Lisbon", "+351 21 000 0000", "https://www.tok-a-hotel.example/"))
        self.assertNotEqual(body["booking_link"], body["official_website"])

        self._offers(headers)
        self.assertEqual(len(fake.requests), 2, "details are cached: no third request")

    def test_links_already_in_search_need_no_details_request(self):
        fake = self.serve(FakeSerpApi((200, search_body(prop("H", "tok-a", prices=[EXPEDIA])))))
        headers = self._premium()
        self._plan(headers=headers, **TRIP)
        body = self._offers(headers).json()
        self.assertEqual((body["booking_provider"], body["booking_link"]), ("Expedia", EXPEDIA["link"]))
        self.assertEqual(len(fake.requests), 1)

    def test_no_provider_link_is_reported_clearly(self):
        details = {"search_metadata": {"status": "Success"}, "name": "H", "prices": [NO_LINK]}
        self.serve(FakeSerpApi((200, search_body(prop("H", "tok-a", prices=[NO_LINK]))), (200, details)))
        headers = self._premium()
        self._plan(headers=headers, **TRIP)
        body = self._offers(headers).json()
        self.assertIsNone(body["booking_link"])
        self.assertEqual(body["message"], "No booking provider link was listed for this hotel.")

    def test_free_users_cannot_get_links_and_spend_no_quota(self):
        fake = self.serve(FakeSerpApi((200, search_body(prop("H", "tok-a", prices=[BOOKING])))))
        trip = self._plan(**TRIP)
        for h in trip["all_hotels"]:
            self.assertEqual((h["booking_link"], h["booking_offers"], h["official_website"]), (None, [], None))
        r = self._offers({})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()["detail"]["code"], "PREMIUM_REQUIRED")
        self.assertEqual(len(fake.requests), 1)

    def test_tokens_from_outside_a_search_are_refused_without_a_request(self):
        fake = self.serve(FakeSerpApi((200, search_body(prop("H", "tok-a")))))
        headers = self._premium()
        self._plan(headers=headers, **TRIP)
        self.assertEqual(self._offers(headers, token="someone-elses-token").status_code, 404)
        self.assertEqual(self._offers(headers, check_out=CHECK_IN).status_code, 404, "different dates")
        self.assertEqual(len(fake.requests), 1)

    def test_trip_plan_free_vs_premium_rules_are_unchanged(self):
        self.serve(FakeSerpApi((200, search_body(prop("H", "tok-a", prices=[BOOKING])))))
        free = self._plan(**TRIP)
        self.assertIsNone(free["budget_breakdown"])
        self.assertFalse(free["is_premium"])
        prem = self._plan(headers=self._premium(), total_budget=2000, **TRIP)
        self.assertIsNotNone(prem["budget_breakdown"])
        self.assertEqual(prem["recommended_hotel"]["booking_link"], BOOKING["link"])


# ---------------------------------------------------------------- errors ---
class ErrorHandlingTest(_SerpApiCase):

    def test_invalid_api_key(self):
        fake = self.serve(FakeSerpApi((401, {"error": "Invalid API key. Your API key should be here: "
                                                      "https://serpapi.com/manage-api-key"})))
        res = self.search()
        self.assertEqual(res.results_status, "unavailable")
        card = res.hotels[0]
        self.assertTrue(card.is_placeholder)
        self.assertIn("rejected MYMILE's API key", card.best_match_reason)
        self.search()
        self.assertEqual(len(fake.requests), 1, "no retries against a rejected key for a while")

    def test_quota_exhausted(self):
        fake = self.serve(FakeSerpApi((429, {"error": "Your account has run out of searches."})))
        res = self.search()
        self.assertIn("allowance has been used up", res.hotels[0].best_match_reason)
        self.search(check_out=(date.today() + timedelta(days=34)).isoformat())
        self.assertEqual(len(fake.requests), 1, "quota errors pause requests")

    def test_timeout_network_and_bad_responses(self):
        cases = [(httpx.ReadTimeout("slow"), "took too long"), (httpx.ConnectError("down"), "couldn't reach"),
                 ((200, ["not", "an", "object"]), "unexpected response"),
                 ((500, {"error": "Internal"}), "returned an error")]
        for item, text in cases:
            serpapi_hotels.reset_guards()
            with mock.patch.object(serpapi_hotels, "_make_client", side_effect=FakeSerpApi(item).client):
                res = self.search()
            self.assertEqual(res.results_status, "unavailable", text)
            self.assertIn(text, res.hotels[0].best_match_reason)

    def test_past_dates_never_send_a_request(self):
        fake = self.serve(FakeSerpApi((200, search_body(prop("H", "tok-a")))))
        res = self.search(check_in="2020-01-01", check_out="2020-01-03")
        self.assertEqual(res.results_status, "unavailable")
        self.assertEqual(fake.requests, [])

    def test_no_key_configured_keeps_the_curated_behaviour(self):
        fake = self.serve(FakeSerpApi((200, search_body(prop("H", "tok-a")))))
        with mock.patch.object(settings, "HOTEL_API_KEY", ""):
            res = self.search(destination="Cairo, Egypt", city="Cairo", country="Egypt")
        self.assertEqual(res.source, "MYMILE curated hotels")
        self.assertEqual(fake.requests, [])


# ----------------------------------------------------------------- cache ---
class CacheTest(_SerpApiCase):

    def test_cache_hit_makes_no_second_request_even_after_restart(self):
        fake = self.serve(FakeSerpApi((200, search_body(prop("H", "tok-a")))))
        self.search()
        serpapi_hotels.reset_guards()  # in-memory state gone, as after a backend restart
        again = self.search(plan="premium", stay_preference="Luxury hotel")
        self.assertEqual(len(fake.requests), 1)
        self.assertEqual(again.results_status, "live")

    def test_destination_dates_and_adults_are_part_of_the_key(self):
        fake = self.serve(FakeSerpApi((200, search_body(prop("H", "tok-a")))))
        self.search()
        self.search(travelers=3)
        self.search(check_out=(date.today() + timedelta(days=34)).isoformat())
        self.search(destination="Porto, Portugal", city="Porto")
        self.search(destination="lisbon,  portugal", city="lisbon", country="portugal")  # same search
        self.assertEqual(len(fake.requests), 4)

    def test_cache_expires(self):
        fake = self.serve(FakeSerpApi((200, search_body(prop("H", "tok-a")))))
        self.search()
        real_time = time.time
        with mock.patch.object(serpapi_hotels.time, "time", side_effect=lambda: real_time() + 25 * 3600):
            self.search()
        self.assertEqual(len(fake.requests), 2)

    def test_failed_refresh_serves_cached_results_marked_stale(self):
        fake = self.serve(FakeSerpApi((200, search_body(prop("H", "tok-a")))))
        first = self.search()
        fake.responses = [(503, {"error": "Service unavailable"})]
        real_time = time.time
        with mock.patch.object(serpapi_hotels.time, "time", side_effect=lambda: real_time() + 25 * 3600):
            res = self.search()
        self.assertEqual(res.results_status, "cached")
        self.assertTrue(res.hotels[0].results_stale)
        self.assertEqual(res.hotels[0].price_checked_at, first.hotels[0].price_checked_at)
        self.assertEqual(len(fake.requests), 2)

    def test_failures_are_not_cached(self):
        fake = self.serve(FakeSerpApi((503, {"error": "busy"}), (200, search_body(prop("H", "tok-a")))))
        self.assertEqual(self.search().results_status, "unavailable")
        self.assertEqual(self.search().results_status, "live")
        self.assertEqual(len(fake.requests), 2)

    def test_simultaneous_identical_searches_share_one_request(self):
        async def slow_handler_test():
            async def handler(request):
                await asyncio.sleep(0.05)
                return httpx.Response(200, json=search_body(prop("H", "tok-a")))
            calls = []

            def client():
                async def counted(request):
                    calls.append(request)
                    return await handler(request)
                return httpx.AsyncClient(transport=httpx.MockTransport(counted))
            with mock.patch.object(serpapi_hotels, "_make_client", side_effect=client):
                results = await asyncio.gather(*[
                    serpapi_hotels.search_hotels("Lisbon, Portugal", CHECK_IN, CHECK_OUT, 2) for _ in range(5)])
            return calls, results
        calls, results = run(slow_handler_test())
        self.assertEqual(len(calls), 1)
        self.assertTrue(all(r["properties"][0]["name"] == "H" for r in results))


# ----------------------------------------------------------- key leakage ---
class NoKeyLeakageTest(_SerpApiCase, _Api):

    def test_key_never_appears_in_responses_or_logs(self):
        cases = [(200, search_body(prop("H", "tok-a", prices=[BOOKING]))),
                 (401, {"error": f"Invalid API key {KEY}"}),
                 (429, {"error": "Your account has run out of searches."}),
                 httpx.ConnectError(f"failed GET https://serpapi.com/search.json?api_key={KEY}")]
        root = logging.getLogger()
        records = []
        handler = logging.Handler(level=logging.DEBUG)
        handler.emit = lambda record: records.append(record.getMessage())
        root.addHandler(handler)
        old_level = root.level
        root.setLevel(logging.DEBUG)
        try:
            for item in cases:
                serpapi_hotels.reset_guards()
                with closing(serpapi_hotels._db()) as conn:
                    conn.execute("DELETE FROM hotel_api_cache")
                    conn.commit()
                with mock.patch.object(serpapi_hotels, "_make_client", side_effect=FakeSerpApi(item).client):
                    trip = self.api.post("/api/trips/plan", json=TRIP, headers=self._premium())
                    search = self.api.get("/api/hotels/search", params={"destination": "Lisbon, Portugal",
                                                                         "check_in": CHECK_IN, "check_out": CHECK_OUT,
                                                                         "nights": 3})
                for r in (trip, search):
                    self.assertEqual(r.status_code, 200)
                    self.assertNotIn(KEY, r.text)
        finally:
            root.removeHandler(handler)
            root.setLevel(old_level)
        self.assertTrue(records, "logging was captured")
        self.assertFalse([m for m in records if KEY in m], "API key found in a log message")
        self.assertGreaterEqual(logging.getLogger("httpx").level, logging.WARNING)
        with closing(serpapi_hotels._db()) as conn:
            stored = " ".join(r[0] + r[1] for r in conn.execute("SELECT cache_key, payload FROM hotel_api_cache"))
        self.assertNotIn(KEY, stored)

    def test_error_objects_carry_no_key(self):
        err = serpapi_hotels.HotelApiError("INVALID_API_KEY")
        self.assertNotIn(KEY, str(err))
        self.assertNotIn(KEY, json.dumps(serpapi_hotels.ERROR_MESSAGES))


if __name__ == "__main__":
    unittest.main()
