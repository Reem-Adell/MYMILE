"""
Regressions from the live Dubai business trip (2026-11-12):
  1. "No relevant options were found for: Computer Mouse" while two mice were shown: the
     missing report compared category names only ("Computer Mouse" vs the search's "Work
     Electronics"); it now uses the same category-OR-query rule as the named-search safety net.
  2. "Lightweight clothing" in the description wasn't a named need, so when Groq skipped it
     nothing searched it and nothing reported it.

Run from backend/:
    venv\\Scripts\\python -m unittest tests.test_dubai_regressions -v
No real Groq or Channel3 requests.
"""
from tests import _env  # noqa: F401  (must precede any app.* import)

import json
from unittest import mock

from app.core.config import settings
from app.services import trip_shopping
from tests._fake_groq import FakeGroq, calls, text
from tests.test_channel3 import FakeChannel3, ok
from tests.test_gemini_agent import plan_json
from tests.test_product_coverage import live
from tests.test_trip_products import _ProductsApi

DUBAI = ("A 5-day business trip to Dubai for a technology conference with meetings. My wireless mouse broke, so I "
         "need a new one, and lightweight clothing suitable for Dubai's November weather.")
# Groq's actual six searches in the live run.
LIVE_SEARCHES = [
    {"query": "wrinkle resistant travel blazer women", "category": "Formal Clothing", "audience": "women"},
    {"query": "comfortable leather dress shoes women", "category": "Professional Shoes", "audience": "women"},
    {"query": "women laptop backpack business travel", "category": "Laptop Bag", "audience": "women"},
    {"query": "wireless computer mouse ergonomic women", "category": "Work Electronics", "audience": "women"},
    {"query": "portable power bank high capacity", "category": "Power & Charging", "audience": "women"},
    {"query": "noise cancelling headphones women", "category": "Headphones", "audience": "women"},
]
MICE = [live("EVeGttw", "Wavy Chips Bluetooth Mouse", "Lofree", "Mice & Trackballs", 89.0),
        live("cASbUbl", "Team Stripe Wireless Mouse", "Keyscaper", "Mice & Trackballs", 29.99)]
BLAZER = live("v0zVe8B", "Wrinkle-resistant Notched Collar Work Blazer", "halara", "Blazers", 49.0)


def sent(c3):
    return [json.loads(r.content)["query"] for r in c3.requests]


class _Dubai(_ProductsApi):

    def trip(self, searches, picks, c3, notes=DUBAI):
        self.c3 = self.serve(c3)
        self.fake = FakeGroq([calls(("find_travel_products", {"searches": searches})),
                              text(plan_json(None, essentials=picks))])
        with self.fake.patch(), mock.patch.object(settings, "CHANNEL3_RESULTS_PER_QUERY", 5):
            return self._plan(destination_city="Dubai", destination_country="United Arab Emirates",
                              purpose="Business", departure_date="2026-11-16", return_date="2026-11-21",
                              travelers=1, stay_preference="Luxury hotel", notes=notes, shopping_audience="women")


class MouseMissingReportTest(_Dubai):

    def test_two_mice_shown_means_computer_mouse_is_not_missing(self):
        notes = "Tech conference in Dubai; my wireless mouse broke and I need a new one."
        # Groq's mouse search covers the named mouse: it runs first, then Groq's other searches.
        c3 = FakeChannel3(ok(*MICE), ok(BLAZER), ok(), ok(), ok(), ok())
        picks = [{"product_id": "v0zVe8B", "category": "Formal Clothing"},
                 {"product_id": "cASbUbl", "category": "Work Electronics"},
                 {"product_id": "EVeGttw", "category": "Work Electronics"}]
        trip = self.trip(LIVE_SEARCHES, picks, c3, notes=notes)
        expected = [LIVE_SEARCHES[3]["query"]] + [s["query"] for i, s in enumerate(LIVE_SEARCHES) if i != 3]
        self.assertEqual(sent(self.c3), expected, "Groq's own mouse search kept; no second mouse search")
        shown = {p["id"]: p["group"] for p in trip["travel_essentials"]}
        self.assertEqual(shown.get("cASbUbl"), "Work Electronics")
        self.assertEqual(shown.get("EVeGttw"), "Work Electronics")
        self.assertNotIn("Computer Mouse", trip["essentials"]["missing"])
        self.assertNotIn("Computer Mouse", trip["essentials"]["message"] or "")
        self.assertNotIn("Work Electronics", trip["essentials"]["missing"])

    def test_a_mouse_that_was_not_found_is_still_reported(self):
        notes = "Tech conference in Dubai; my wireless mouse broke and I need a new one."
        trip = self.trip(LIVE_SEARCHES, [], FakeChannel3(ok()), notes=notes)
        self.assertIn("Computer Mouse", trip["essentials"]["missing"])

    def test_mice_found_but_not_picked_are_reported(self):
        notes = "Tech conference in Dubai; my wireless mouse broke and I need a new one."
        c3 = FakeChannel3(ok(*MICE), ok(BLAZER), ok(), ok(), ok(), ok())
        trip = self.trip(LIVE_SEARCHES, [{"product_id": "v0zVe8B", "category": "Formal Clothing"}], c3, notes=notes)
        self.assertIn("Computer Mouse", trip["essentials"]["missing"], "only a picked product covers the need")

    def test_the_shared_coverage_rule(self):
        need = trip_shopping.named_products("my mouse broke")[0]
        cover = trip_shopping.search_covers_need
        self.assertTrue(cover("Work Electronics", "wireless computer mouse ergonomic women", need), "query overlap")
        self.assertTrue(cover("Computer Mouse", "something else", need), "same category")
        self.assertFalse(cover("Power & Charging", "portable power bank", need))


class LightweightClothingTest(_Dubai):

    def test_detected_only_when_described(self):
        named = lambda d: [n["category"] for n in trip_shopping.named_products(d)]
        for d in ("lightweight clothing", "lightweight clothes", "breathable clothing", "breathable clothes",
                  "summer clothing", "summer clothes", "lightweight outfits", "breathable outfits", "light-weight clothes"):
            self.assertEqual(named(d), ["Lightweight Clothing"], d)
        self.assertEqual(named("I need professional outfits for meetings"), ["Formal Clothing"])
        self.assertEqual(named("a lightweight blazer"), ["Formal Clothing"])
        self.assertNotIn("Lightweight Clothing", named("A business trip to Dubai with meetings."))

    def test_searched_first_with_the_audience_within_six_searches(self):
        dress = live("ld1", "Women's Linen Midi Dress", "Quince", "Dresses", 60.0)
        # Description order: mouse (Groq's search covers it), lightweight clothing (server default).
        c3 = FakeChannel3(ok(*MICE), ok(dress), ok(BLAZER), ok(), ok(), ok())
        picks = [{"product_id": "ld1", "category": "Lightweight Clothing"},
                 {"product_id": "cASbUbl", "category": "Work Electronics"}]
        trip = self.trip(LIVE_SEARCHES, picks, c3)
        queries = sent(self.c3)
        self.assertEqual(queries[:2], ["wireless computer mouse ergonomic women", "women's lightweight breathable clothing"])
        self.assertEqual(len(queries), 6, "still six: the model's last search is what the cap cuts")
        self.assertNotIn("noise cancelling headphones women", queries)
        self.assertEqual({p["id"]: p["group"] for p in trip["travel_essentials"]},
                         {"ld1": "Lightweight Clothing", "cASbUbl": "Work Electronics"})
        self.assertNotIn("Lightweight Clothing", trip["essentials"]["missing"])
        self.assertNotIn("Computer Mouse", trip["essentials"]["missing"])

    def test_reported_when_nothing_relevant_is_found(self):
        c3 = FakeChannel3(ok(*MICE), ok(), ok(BLAZER), ok(), ok(), ok())
        trip = self.trip(LIVE_SEARCHES, [{"product_id": "cASbUbl", "category": "Work Electronics"}], c3)
        self.assertEqual(sent(self.c3)[1], "women's lightweight breathable clothing")
        self.assertIn("Lightweight Clothing", trip["essentials"]["missing"])

    def test_not_searched_when_the_description_does_not_ask(self):
        trip = self.trip(LIVE_SEARCHES, [], FakeChannel3(ok()),
                         notes="A business trip to Dubai for a conference; I need professional outfits.")
        self.assertFalse(any("lightweight" in q for q in sent(self.c3)))
        self.assertNotIn("Lightweight Clothing", trip["essentials"]["missing"])
