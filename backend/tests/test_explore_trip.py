"""
Explore page data: structured destination, verified hotel locations, transparent
Booking.com links and prices, Premium-only budget, destination hero image.

Run from backend/:
    venv\\Scripts\\python -m unittest discover -s tests -v
No real network calls: provider responses are mocked.
"""
from tests import _env  # noqa: F401  (must precede any app.* import)

import asyncio
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlparse

import httpx

from tests import test_paypal_payments as base
from app.core.config import settings
from app.services import destination_image, hotel_pricing, hotel_service

TRIP = {"destination": "Cairo, Egypt", "departure_date": "2026-12-01", "return_date": "2026-12-04",
        "travelers": 2, "purpose": "Tourism", "stay_preference": "Boutique hotel"}


def run(coro):
    return asyncio.run(coro)


class _Api(unittest.TestCase):
    setUp = base.PayPalPaymentsTest.setUp
    _register = base.PayPalPaymentsTest._register

    @classmethod
    def setUpClass(cls):
        _env.ensure_isolated_db()

    def _premium(self):
        from app.core import database
        user = self._register("prem")
        with database.connect() as conn:
            conn.execute("UPDATE users SET plan='premium', premium_until='2099-01-01T00:00:00+00:00' WHERE id=?",
                         (user["id"],))
        return user["headers"]

    def _plan(self, headers=None, **over):
        r = self.api.post("/api/trips/plan", json={**TRIP, **over}, headers=headers or {})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()


# ------------------------------------------------------------ destination ---
class StructuredDestinationTest(_Api):

    def test_structured_city_and_country_are_authoritative(self):
        trip = self._plan(destination="Kyoto, Japan", destination_city="Cairo", destination_country="Egypt")
        self.assertEqual((trip["destination"], trip["destination_city"], trip["destination_country"]),
                         ("Cairo, Egypt", "Cairo", "Egypt"))
        self.assertTrue(trip["all_hotels"])
        for h in trip["all_hotels"]:
            self.assertEqual((h["city"], h["country"], h["is_placeholder"]), ("Cairo", "EG", False), h["name"])

    def test_notes_never_change_the_destination(self):
        notes = "I will also visit Alexandria and Paris later. Please stay near the airport, quiet room."
        trip = self._plan(destination_city="Cairo", destination_country="Egypt", notes=notes)
        self.assertTrue(all(h["city"] == "Cairo" and h["country"] == "EG" for h in trip["all_hotels"]))
        self.assertIn("Airport", trip["recommended_hotel"]["name"], "notes still rank within Cairo")

    def test_same_trip_gives_the_same_hotels(self):
        a = self._plan(destination_city="Cairo", destination_country="Egypt", notes="near the museums")
        b = self._plan(destination_city="Cairo", destination_country="Egypt", notes="near the museums")
        self.assertEqual([h["id"] for h in a["all_hotels"]], [h["id"] for h in b["all_hotels"]])

    def test_other_city_and_country_combination(self):
        trip = self._plan(destination_city="Alexandria", destination_country="Egypt")
        self.assertTrue(trip["all_hotels"])
        self.assertTrue(all(h["city"] == "Alexandria" and h["country"] == "EG" for h in trip["all_hotels"]))
        paris = self._plan(destination_city="Paris", destination_country="France")
        self.assertTrue(all(h["city"] == "Paris" and h["country"] == "FR" for h in paris["all_hotels"]))

    def test_same_name_in_another_country_gets_no_curated_hotels(self):
        for city, country in (("Cairo", "United States"), ("Paris", "Texas"), ("Alexandria", "Virginia")):
            trip = self._plan(destination_city=city, destination_country=country)
            self.assertEqual(len(trip["all_hotels"]), 1, f"{city}, {country}")
            card = trip["all_hotels"][0]
            self.assertTrue(card["is_placeholder"], f"{city}, {country}: not presented as a hotel")
            self.assertEqual(card["rating"], 0)

    def test_unknown_destination_is_a_placeholder_not_a_hotel(self):
        trip = self._plan(destination_city="Lisbon", destination_country="Portugal")
        card = trip["recommended_hotel"]
        self.assertTrue(card["is_placeholder"])
        self.assertFalse(card["is_best_match"])
        self.assertIn("don't have verified hotels", trip["why_recommended"])

    def test_old_clients_with_free_text_destination_still_work(self):
        trip = self._plan(destination="Cairo, Egypt")
        self.assertTrue(all(h["country"] == "EG" for h in trip["all_hotels"]))


# ------------------------------------------------------ location validation ---
class HotelLocationValidationTest(unittest.TestCase):

    def test_inconsistent_hotel_data_is_never_recommended(self):
        bad = {**hotel_service.REAL_HOTELS_DB[0], "id": "bad-01", "name": "Wrong Country Hotel",
               "destination": "cairo", "country": "FR", "rating": 5.0, "tags": ["museums", "famous"]}
        with mock.patch.object(hotel_service, "REAL_HOTELS_DB", hotel_service.REAL_HOTELS_DB + [bad]):
            res = run(hotel_service.search_hotels("Cairo, Egypt", city="Cairo", country="Egypt"))
        self.assertNotIn("bad-01", [h.id for h in res.hotels])

    def test_every_curated_hotel_has_a_consistent_country(self):
        from app.core.destinations import CITY_COUNTRY_CODE
        for h in hotel_service.REAL_HOTELS_DB:
            self.assertEqual(h.get("country"), CITY_COUNTRY_CODE[h["destination"]], h["id"])
            self.assertNotIn("booking_slug", h, "no unverified Booking.com property slugs")


# ------------------------------------------------------------ booking links ---
class BookingLinkTest(_Api):

    def test_premium_links_are_transparent_searches_with_trip_details(self):
        trip = self._plan(headers=self._premium(), destination_city="Cairo", destination_country="Egypt", travelers=3)
        for h in trip["all_hotels"]:
            self.assertEqual(h["booking_link_type"], "search", h["name"])
            url = urlparse(h["booking_link"])
            self.assertEqual(url.path, "/searchresults.html")
            self.assertNotIn("/hotel/", h["booking_link"], "never a guessed property URL")
            q = parse_qs(url.query)
            self.assertEqual(q["ss"], [f"{h['name']}, Cairo, Egypt"])
            self.assertEqual((q["checkin"], q["checkout"], q["group_adults"], q["no_rooms"], q["group_children"]),
                             (["2026-12-01"], ["2026-12-04"], ["3"], ["2"], ["0"]))

    def test_free_users_get_no_booking_link(self):
        trip = self._plan(destination_city="Cairo", destination_country="Egypt")
        self.assertTrue(all(h["booking_link"] is None and h["booking_link_type"] is None for h in trip["all_hotels"]))


# ------------------------------------------------------------------ pricing ---
class PricingTransparencyTest(_Api):

    def test_estimates_are_labelled_and_totals_cover_nights_and_rooms(self):
        with mock.patch.object(settings, "HOTEL_API_KEY", None):
            trip = self._plan(destination_city="Cairo", destination_country="Egypt", travelers=3)
        for h in trip["all_hotels"]:
            self.assertEqual((h["price_source"], h["price_basis"], h["currency"]),
                             ("estimate", "per_room_per_night", "USD"))
            self.assertEqual((h["nights"], h["rooms"]), (3, 2))
            self.assertAlmostEqual(h["total_price"], h["price_per_night"] * 3 * 2, places=2)
            self.assertIsNone(h["taxes_included"])
            self.assertIsNone(h["price_checked_at"])

    def test_budget_is_premium_only(self):
        self.assertIsNone(self._plan(destination_city="Cairo", destination_country="Egypt")["budget_breakdown"])
        prem = self._plan(headers=self._premium(), destination_city="Cairo", destination_country="Egypt",
                          total_budget=2000)
        self.assertIsNotNone(prem["budget_breakdown"])


class ListedPriceParsingTest(unittest.TestCase):

    def test_stay_total_taxes_and_source_are_taken_from_the_provider(self):
        data = {"name": "Steigenberger Hotel El Tahrir", "prices": [
            {"source": "Agoda", "rate_per_night": {"extracted_lowest": 80}},
            {"source": "Booking.com", "rate_per_night": {"extracted_lowest": 100, "extracted_before_taxes_fees": 85},
             "total_rate": {"extracted_lowest": 310, "extracted_before_taxes_fees": 255}},
        ]}
        found = hotel_pricing._extract_price(data, "Steigenberger Hotel El Tahrir")
        self.assertEqual(found, {"nightly": 100, "total": 310, "taxes_included": True, "source": "Booking.com"})

    def test_unknown_tax_status_stays_unknown(self):
        found = hotel_pricing._extract_price(
            {"name": "Pension Roma", "rate_per_night": {"extracted_lowest": 30}}, "Pension Roma")
        self.assertEqual((found["taxes_included"], found["total"]), (None, None))
        only_before = hotel_pricing._rates({"rate_per_night": {"extracted_before_taxes_fees": 50}})
        self.assertFalse(only_before["taxes_included"])

    def test_a_different_hotel_never_supplies_the_price(self):
        data = {"properties": [{"name": "Four Seasons Hotel Alexandria at San Stefano",
                                "rate_per_night": {"extracted_lowest": 300}}]}
        self.assertIsNone(hotel_pricing._extract_price(data, "Four Seasons Hotel Cairo at Nile Plaza"))

    def test_listed_total_is_used_and_marked_with_time(self):
        hotel = hotel_service.HotelItem(id="cai-02", name="X", location="Cairo", rating=4, price_per_night=95,
                                        total_price=570, image_url="i", amenities=[], best_match_reason="r")

        async def fake_fetch(*args):
            return {"nightly": 100, "total": 310, "taxes_included": True, "source": "Booking.com",
                    "checked_at": "2026-11-11T10:00:00+00:00"}
        with mock.patch.object(settings, "HOTEL_API_KEY", "test-key"), \
             mock.patch.object(hotel_pricing, "_fetch_price", side_effect=fake_fetch):
            run(hotel_pricing.apply_live_prices([hotel], {"cai-02": "Cairo, Egypt"}, "a", "b", 3, 3, 2))
        self.assertEqual((hotel.price_per_night, hotel.total_price, hotel.price_source, hotel.price_provider),
                         (100, 620, "live", "Booking.com"))
        self.assertEqual((hotel.taxes_included, hotel.price_checked_at), (True, "2026-11-11T10:00:00+00:00"))

    def test_cache_key_includes_the_location(self):
        calls = []

        class FakeClient:
            async def get(self, url, params=None):
                calls.append(params["q"])
                req = httpx.Request("GET", url)
                return httpx.Response(200, json={"name": "Same Name Hotel",
                                                 "rate_per_night": {"extracted_lowest": 50}}, request=req)
        hotel_pricing._cache.clear()
        with mock.patch.object(settings, "HOTEL_API_KEY", "test-key"):
            run(hotel_pricing._fetch_price(FakeClient(), "Same Name Hotel", "Cairo, Egypt", "a", "b", 2))
            run(hotel_pricing._fetch_price(FakeClient(), "Same Name Hotel", "Paris, France", "a", "b", 2))
            run(hotel_pricing._fetch_price(FakeClient(), "Same Name Hotel", "Cairo, Egypt", "a", "b", 2))
        self.assertEqual(calls, ["Same Name Hotel Cairo, Egypt", "Same Name Hotel Paris, France"])


# --------------------------------------------------------- destination image ---
def _summary(**over):
    base_summary = {"type": "standard", "title": "Cairo", "description": "Capital and largest city of Egypt",
                    "extract": "Cairo is the capital of Egypt.",
                    "thumbnail": {"source": "https://upload.wikimedia.org/x/thumb/a/ab/Cairo.jpg/320px-Cairo.jpg"},
                    "originalimage": {"source": "https://upload.wikimedia.org/x/a/ab/Cairo.jpg"},
                    "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Cairo"}}}
    return {**base_summary, **over}


class FakeWiki:
    def __init__(self, responses):
        self.responses = list(responses)
        self.urls = []

    async def get(self, url):
        self.urls.append(url)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        status, body = item
        return httpx.Response(status, json=body, request=httpx.Request("GET", url))


class DestinationImageTest(unittest.TestCase):

    def setUp(self):
        destination_image._cache.clear()
        patcher = mock.patch.object(settings, "WIKIMEDIA_CONTACT", "ops@example.org")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_no_contact_configured_means_no_request(self):
        client = FakeWiki([(200, _summary())])
        with mock.patch.object(settings, "WIKIMEDIA_CONTACT", None):
            self.assertIsNone(run(destination_image.get_destination_image("Cairo", "Egypt", client=client)))
        self.assertEqual(client.urls, [], "Wikimedia refuses clients without contact details")

    def test_user_agent_carries_the_configured_contact(self):
        self.assertEqual(destination_image._headers()["User-Agent"], "MYMILE/1.0 (ops@example.org)")

    def test_policy_refusal_is_not_cached(self):
        client = FakeWiki([(403, {"detail": "robot policy"}), (200, _summary())])
        self.assertIsNone(run(destination_image.get_destination_image("Cairo", "Egypt", client=client)))
        self.assertIsNotNone(run(destination_image.get_destination_image("Cairo", "Egypt", client=client)))

    def test_verified_photo_is_returned_at_hero_width(self):
        img = run(destination_image.get_destination_image("Cairo", "Egypt", client=FakeWiki([(200, _summary())])))
        self.assertEqual(img["url"], "https://upload.wikimedia.org/x/thumb/a/ab/Cairo.jpg/1600px-Cairo.jpg")
        self.assertEqual(img["page_url"], "https://en.wikipedia.org/wiki/Cairo")

    def test_disambiguation_then_plain_title(self):
        client = FakeWiki([(200, _summary(type="disambiguation")), (200, _summary())])
        img = run(destination_image.get_destination_image("Cairo", "Egypt", client=client))
        self.assertIsNotNone(img)
        self.assertEqual(len(client.urls), 2)

    def test_article_about_another_country_is_rejected(self):
        wrong = _summary(description="City in Illinois, United States", extract="Cairo is a city in Illinois.")
        client = FakeWiki([(200, wrong), (200, wrong)])
        self.assertIsNone(run(destination_image.get_destination_image("Cairo", "Egypt", client=client)))

    def test_maps_and_flags_are_not_used(self):
        svg = _summary(thumbnail={"source": "https://upload.wikimedia.org/x/Flag.svg.png"},
                       originalimage={"source": "https://upload.wikimedia.org/x/Flag.svg"})
        client = FakeWiki([(200, svg), (200, svg)])
        self.assertIsNone(run(destination_image.get_destination_image("Cairo", "Egypt", client=client)))

    def test_results_are_cached(self):
        client = FakeWiki([(200, _summary())])
        run(destination_image.get_destination_image("Cairo", "Egypt", client=client))
        run(destination_image.get_destination_image("cairo", "egypt", client=client))
        self.assertEqual(len(client.urls), 1, "second lookup served from cache")

    def test_network_failure_returns_none_and_is_not_cached(self):
        client = FakeWiki([httpx.ConnectError("down"), (200, _summary())])
        self.assertIsNone(run(destination_image.get_destination_image("Cairo", "Egypt", client=client)))
        self.assertIsNotNone(run(destination_image.get_destination_image("Cairo", "Egypt", client=client)))


class DestinationImageRouteTest(_Api):

    def test_route_returns_image_or_null(self):
        async def fake(city, country):
            return {"url": "https://upload.wikimedia.org/p.jpg"} if city == "Cairo" else None
        with mock.patch("app.api.routes.places.get_destination_image", side_effect=fake):
            ok = self.api.get("/api/places/destination-image", params={"city": "Cairo", "country": "Egypt"})
            none = self.api.get("/api/places/destination-image", params={"city": "Nowhere"})
        self.assertEqual(ok.json(), {"image": {"url": "https://upload.wikimedia.org/p.jpg"}})
        self.assertEqual(none.json(), {"image": None})
        self.assertEqual(self.api.get("/api/places/destination-image").status_code, 422)


if __name__ == "__main__":
    unittest.main()
