"""
Named-need search priority (A), accurate missing-need states (B) and the selection rule for
named needs (D), from the Dubai comparison (2026-11-12).

Run from backend/:
    venv\\Scripts\\python -m unittest tests.test_named_priority_and_reporting -v
No real Groq or Channel3 requests.
"""
from tests import _env  # noqa: F401  (must precede any app.* import)

import json
from unittest import mock

from app.core.config import settings
from tests._fake_groq import FakeGroq, calls, text
from tests.test_channel3 import FakeChannel3, ok
from tests.test_gemini_agent import plan_json
from tests.test_product_coverage import live
from tests.test_trip_products import _ProductsApi, prompt_parts

GENERIC = [{"category": "Comfort", "query": "travel neck pillow"},
           {"category": "Organizers", "query": "packing cubes"},
           {"category": "Rain Gear", "query": "compact travel umbrella"},
           {"category": "Gadgets", "query": "digital luggage scale"}]
SEVEN = ("Tech conference in Dubai. I need lightweight clothing, professional outfits, formal shoes, a laptop bag, "
         "a new mouse, a power bank and headphones.")


def sent(c3):
    return [json.loads(r.content)["query"] for r in c3.requests]


class _Trip(_ProductsApi):

    def trip(self, searches, picks=(), c3=None, notes="Business trip to Dubai; my mouse broke, I need a power bank "
                                                       "and headphones.", purpose="Business"):
        self.c3 = self.serve(c3 or FakeChannel3(ok()))
        self.fake = FakeGroq([calls(("find_travel_products", {"searches": searches})),
                              text(plan_json(None, essentials=list(picks)))])
        with self.fake.patch(), mock.patch.object(settings, "CHANNEL3_RESULTS_PER_QUERY", 5):
            return self._plan(destination_city="Dubai", destination_country="United Arab Emirates", purpose=purpose,
                              departure_date="2026-11-16", return_date="2026-11-21", travelers=1, notes=notes,
                              shopping_audience="women")


# --------------------------------------------------------------------- A. priority ---
class NamedSearchPriorityTest(_Trip):

    def test_ai_searches_that_cover_named_needs_are_kept_and_go_first(self):
        searches = [GENERIC[0], {"category": "Headphones", "query": "noise cancelling headphones"},
                    {"category": "Work Electronics", "query": "ergonomic bluetooth mouse"}] + GENERIC[1:]
        self.trip(searches)
        self.assertEqual(sent(self.c3), [
            "ergonomic bluetooth mouse",       # named 1: the AI's own wording, not the default query
            "portable power bank",             # named 2: not covered by the AI, server default
            "noise cancelling headphones",     # named 3: the AI's own wording
            "travel neck pillow", "packing cubes", "compact travel umbrella",  # generic, AI order
        ])                                     # "digital luggage scale" is what the 6-search cap cuts

    def test_generic_searches_never_displace_named_needs(self):
        self.trip(GENERIC + [{"category": "Snacks", "query": "protein bars"},
                             {"category": "Books", "query": "travel journal"}], notes=SEVEN)
        queries = sent(self.c3)
        self.assertEqual(len(queries), 6)
        for generic in ("travel neck pillow", "packing cubes", "protein bars", "travel journal"):
            self.assertNotIn(generic, queries)
        self.assertEqual(queries[0], "women's lightweight breathable clothing", "description order")

    def test_seven_named_needs_with_six_searches(self):
        ai = [{"category": "Lightweight Clothing", "query": "linen shirt lightweight clothing"},
              {"category": "Formal Clothing", "query": "women's tailored blazer"},
              {"category": "Professional Shoes", "query": "women's low heel pumps dress shoes"},
              {"category": "Laptop Bag", "query": "slim laptop bag"},
              {"category": "Work Electronics", "query": "bluetooth mouse"},
              {"category": "Power & Charging", "query": "magsafe power bank"},
              {"category": "Headphones", "query": "anc headphones"}]
        trip = self.trip(list(reversed(ai)), notes=SEVEN)
        queries = sent(self.c3)
        self.assertEqual(queries, ["women's linen shirt lightweight clothing", "women's tailored blazer",
                                   "women's low heel pumps dress shoes", "slim laptop bag", "bluetooth mouse",
                                   "magsafe power bank"], "all AI wording, description order, no server defaults")
        states = {d["category"]: d["state"] for d in trip["essentials"]["missing_detail"]}
        self.assertEqual(states["Headphones"], "not_searched", "the 7th named need didn't fit")
        self.assertEqual(trip["essentials"]["status"], "empty", "nothing found in this fake: empty-state message")


# ------------------------------------------------------------------- B. reporting ---
class MissingStatesTest(_Trip):
    NOTES = "Business trip to Dubai; my mouse broke, I need a power bank and headphones."

    def test_three_states_are_told_apart(self):
        mice = [live("m1", "Slim Wireless Mouse", "HP", "Mice & Trackballs", 20.0),
                live("m2", "Bluetooth Travel Mouse", "Logitech", "Mice & Trackballs", 30.0)]
        searches = [{"category": "Work Electronics", "query": "ergonomic bluetooth mouse"},
                    {"category": "Power & Charging", "query": "portable power bank"}] + GENERIC
        trip = self.trip(searches, [], FakeChannel3(ok(*mice), ok()), notes=self.NOTES)
        states = {d["category"]: d["state"] for d in trip["essentials"]["missing_detail"]}
        self.assertEqual(states["Computer Mouse"], "not_selected", "relevant mice existed, none was chosen")
        self.assertNotIn("Work Electronics", states, "one need, reported once, under the traveler's word")
        self.assertEqual(states["Power & Charging"], "not_found")
        self.assertEqual(states["Headphones"], "not_found", "named, so the server searched it; nothing came back")

    def test_not_searched_wording(self):
        bank = live("p1", "Portable Power Bank 10000mAh", "Anker", "Power Banks", 25.0)
        ai = [{"category": "Lightweight Clothing", "query": "linen shirt lightweight clothing"},
              {"category": "Formal Clothing", "query": "women's tailored blazer"},
              {"category": "Professional Shoes", "query": "women's low heel pumps dress shoes"},
              {"category": "Laptop Bag", "query": "slim laptop bag"},
              {"category": "Work Electronics", "query": "bluetooth mouse"},
              {"category": "Power & Charging", "query": "magsafe power bank"}]
        trip = self.trip(ai, [{"product_id": "p1", "category": "Power & Charging"}],
                         FakeChannel3(ok(), ok(), ok(), ok(), ok(), ok(bank)), notes=SEVEN)
        self.assertIn("Not searched (the search limit was reached) for: Headphones.", trip["essentials"]["message"])
        self.assertIn("No relevant options were found for: Lightweight Clothing", trip["essentials"]["message"])

    def test_nothing_selected_at_all_is_not_called_irrelevant(self):
        mice = [live("m1", "Slim Wireless Mouse", "HP", "Mice & Trackballs", 20.0)]
        trip = self.trip([{"category": "Work Electronics", "query": "ergonomic bluetooth mouse"}], [],
                         FakeChannel3(ok(*mice), ok()), notes=self.NOTES)
        self.assertEqual(trip["essentials"]["status"], "empty")
        self.assertEqual(trip["essentials"]["message"], "Relevant products were found, but none were selected for this trip.")
        self.assertNotIn("relevant enough", trip["essentials"]["message"])

    def test_messages_never_say_not_found_for_unselected_products(self):
        mice = [live("m1", "Slim Wireless Mouse", "HP", "Mice & Trackballs", 20.0)]
        bank = live("p1", "Portable Power Bank 10000mAh", "Anker", "Power Banks", 25.0)
        trip = self.trip([{"category": "Work Electronics", "query": "ergonomic bluetooth mouse"},
                          {"category": "Power & Charging", "query": "portable power bank"}] + GENERIC,
                         [{"product_id": "p1", "category": "Power & Charging"}],
                         FakeChannel3(ok(*mice), ok(bank), ok()), notes=self.NOTES)
        message = trip["essentials"]["message"]
        self.assertIn("Relevant options were found but not selected for: Computer Mouse.", message)
        self.assertIn("No relevant options were found for: Headphones", message)
        self.assertNotIn("No relevant options were found for: Computer Mouse", message)
        self.assertNotIn("Power & Charging", message, "shown, so not missing")

    def test_not_found_keeps_its_wording_and_refused_needs_are_not_reported(self):
        trip = self.trip([{"category": "Power & Charging", "query": "portable power bank"}],
                         notes="A beach holiday in Dubai; I need a power bank.")
        self.assertEqual(trip["essentials"]["missing_detail"], [{"category": "Power & Charging", "state": "not_found"}])
        self.assertIsNone(trip["essentials"]["message"]) if trip["travel_essentials"] else None
        refused = self.trip([{"category": "Formal Clothing", "query": "slim fit blazer"},
                             {"category": "Beachwear", "query": "swim trunks"}],
                            notes="A beach holiday in Dubai with lots of swimming.", purpose="Tourism")
        self.assertFalse(any("blazer" in q for q in sent(self.c3)), "refused: not for this trip")
        self.assertNotIn("Formal Clothing", refused["essentials"]["missing"], "a refused search is never reported")


# --------------------------------------------------------------- D. selection rule ---
class NamedSelectionRuleTest(_Trip):

    def test_prompt_asks_for_two_per_named_need_without_filler(self):
        self.trip([GENERIC[0]])
        system = self.fake.requests[0]["messages"][0]["content"]
        self.assertIn("For each named_products need,\npick 2 suitable products when at least 2 suitable candidates exist "
                      "(prefer 2 to 1), fewer if only one\nfits; never pick a product just to fill this.", system)
        self.assertEqual([n["category"] for n in prompt_parts(self.fake.requests[0])["shopping"]["named_products"]],
                         ["Computer Mouse", "Power & Charging", "Headphones"], "the rule applies to these only")
