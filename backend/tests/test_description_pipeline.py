"""
One product pipeline, led by the trip description ("Tell us about your trip"):

    description (required, <= 500 chars) + compact context -> the AI infers needs and chooses
    up to 6 searches -> server checks (named products searched, other purposes' items refused,
    audience, overlaps) -> Channel3 -> relevance, category match, audience, duplicates -> the
    AI picks -> server caps -> honest gaps.

Run from backend/:
    venv\\Scripts\\python -m unittest tests.test_description_pipeline -v
No real Groq or Channel3 requests (both mocked). These tests prove what the server does with
the AI's searches; they can't prove what a live model infers.
"""
from tests import _env  # noqa: F401  (must precede any app.* import)

import json
from unittest import mock

from app.core.config import settings
from app.services import trip_shopping
from tests._fake_groq import FakeGroq, calls, text
from tests.test_channel3 import FakeChannel3, ok
from tests.test_gemini_agent import clear_plan_cache, plan_json
from tests.test_product_coverage import live
from tests.test_trip_products import _ProductsApi, prompt_parts

BEACH = "A summer beach vacation in Barcelona with some city exploration in the evenings."
CONFERENCE = "A business trip to London for an important conference where I present on day two."
UMRAH = "Our first Umrah; we want to be comfortable during the rites and long walks to the Haram."
FAMILY = "A family trip with two young children, lots of parks and a long flight."


def sent_queries(c3):
    return [json.loads(r.content)["query"] for r in c3.requests]


class _Pipeline(_ProductsApi):

    def trip(self, searches, picks=(), c3=None, **over):
        self.c3 = self.serve(c3 or FakeChannel3(ok()))
        self.fake = FakeGroq([calls(("find_travel_products", {"searches": searches})),
                              text(plan_json(None, essentials=list(picks)))])
        body = dict(destination_city="Barcelona", destination_country="Spain", purpose="Tourism",
                    departure_date="2026-07-06", return_date="2026-07-10", travelers=2,
                    stay_preference="Boutique hotel", priorities=[], notes=BEACH)
        body.update(over)
        with self.fake.patch(), mock.patch.object(settings, "CHANNEL3_RESULTS_PER_QUERY", 5):
            return self._plan(**body)


# ------------------------------------------------------------------ validation ---
class DescriptionValidationTest(_ProductsApi):

    def post(self, **over):
        body = {"destination": "Barcelona, Spain", "departure_date": "2026-07-06", "return_date": "2026-07-10"}
        body.update(over)
        return self.api.post("/api/trips/plan", json=body)

    def test_required_trimmed_and_at_most_500_characters(self):
        self.assertEqual(self.post().status_code, 422, "missing")
        self.assertEqual(self.post(notes="   \n  ").status_code, 422, "only whitespace")
        self.assertEqual(self.post(notes="x" * 501).status_code, 422, "too long")
        self.assertEqual(self.post(notes="x" * 500).status_code, 200)
        self.assertEqual(self.post(notes=("  " + "y" * 500 + "  ")).status_code, 200, "trimmed before counting")
        self.assertEqual(self.post(notes=BEACH, shopping_audience="kids").status_code, 422, "unknown audience")
        self.assertEqual(self.post(notes=BEACH).status_code, 200, "no shopping_audience: everyone")

    def test_the_trimmed_description_reaches_the_ai_once(self):
        fake = FakeGroq([text(plan_json(None))])
        with fake.patch():
            self._plan(destination_city="Barcelona", destination_country="Spain", notes=f"  {BEACH}  \n")
        parts = prompt_parts(fake.requests[0])
        self.assertEqual(parts["trip"]["trip_description"], BEACH)
        user = next(m["content"] for m in fake.requests[0]["messages"] if m["role"] == "user")
        self.assertEqual(user.count("summer beach vacation"), 1, "sent once (compact)")
        self.assertLess(len(json.dumps(parts["shopping"])), 700, "supporting context stays small")
        self.assertIn("trip_description is the PRIMARY source", fake.requests[0]["messages"][0]["content"])


# --------------------------------------------------------------- trip scenarios ---
class ScenarioTest(_Pipeline):

    def test_tourism_beach_description_drives_the_searches(self):
        searches = [{"category": c, "query": q} for c, q in [
            ("Beachwear", "quick dry swimwear"), ("Sunglasses", "polarized sunglasses"), ("Sun Care", "reef safe sunscreen"),
            ("Footwear", "walking sandals"), ("Beach Bag", "waterproof beach tote bag")]]
        c3 = FakeChannel3(ok(live("sw1", "Quick Dry Swim Trunks", "Speedo", "Swimwear", 30.0)),
                          ok(live("sg1", "Polarized Sunglasses", "Ray-Ban", "Sunglasses", 120.0),
                             live("ht1", "Straw Sun Hat", "Brixton", "Hats", 40.0)),
                          ok(live("ss1", "Reef Safe Sunscreen SPF 50", "Sun Bum", "Sunscreen", 15.0)),
                          ok(live("sd1", "Walking Sandals", "Teva", "Sandals", 60.0)),
                          ok(live("bt1", "Waterproof Beach Tote Bag", "Baggu", "Tote Bags", 35.0)))
        picks = [{"product_id": i, "category": "Summer"} for i in ("sw1", "sg1", "ht1", "ss1", "sd1", "bt1")]
        trip = self.trip(searches, picks, c3)
        self.assertEqual(sent_queries(self.c3), [s["query"] for s in searches], "the AI's searches run as sent")
        got = {p["id"]: p["group"] for p in trip["travel_essentials"]}
        self.assertNotIn("ht1", got, "a hat isn't what a sunglasses search was for")
        self.assertEqual(got, {"sw1": "Beachwear", "sg1": "Sunglasses", "ss1": "Sun Care", "sd1": "Footwear",
                               "bt1": "Beach Bag"}, "each product shows under the category it was searched for")

    def test_business_conference_description(self):
        searches = [{"category": "Formal Clothing", "query": "wrinkle resistant blazer"},
                    {"category": "Professional Shoes", "query": "leather dress shoes"},
                    {"category": "Laptop Accessories", "query": "laptop sleeve 14 inch"}]
        self.trip(searches, notes=CONFERENCE, purpose="Business", destination_city="London",
                  destination_country="United Kingdom", departure_date="2026-12-07", return_date="2026-12-10")
        self.assertEqual(sent_queries(self.c3), [s["query"] for s in searches])

    def test_umrah_description(self):
        searches = [{"category": "Ihram & Clothing", "query": "men's two piece ihram towel set", "audience": "men"},
                    {"category": "Modest Clothing", "query": "women's abaya and hijab", "audience": "women"},
                    {"category": "Prayer Essentials", "query": "travel prayer rug"}]
        self.trip(searches, notes=UMRAH, purpose="Umrah", destination_city="Makkah", destination_country="Saudi Arabia")
        self.assertEqual(sent_queries(self.c3), [s["query"] for s in searches])

    def test_family_description(self):
        searches = [{"category": "Kids Travel", "query": "kids travel activity kit"},
                    {"category": "Family Health", "query": "family travel first aid kit"},
                    {"category": "Comfort", "query": "kids travel neck pillow"}]
        c3 = FakeChannel3(ok(live("k1", "Kids Travel Activity Kit", "Melissa", "Kids Toys", 25.0),
                             live("x1", "Leather Briefcase", "Fossil", "Briefcases", 180.0)), ok(), ok())
        trip = self.trip(searches, [{"product_id": "k1", "category": "Kids Travel"},
                                    {"product_id": "x1", "category": "Kids Travel"}], c3, notes=FAMILY)
        self.assertEqual(sent_queries(self.c3), [s["query"] for s in searches])
        self.assertEqual([p["id"] for p in trip["travel_essentials"]], ["k1"], "the briefcase didn't match the search")
        self.assertIn("Family Health", trip["essentials"]["missing"], "nothing found: reported, not substituted")


# --------------------------------------------------- named products & purposes ---
class NamedProductsAndPurposeTest(_Pipeline):

    def test_a_named_product_is_searched_even_if_the_ai_skips_it(self):
        trip = self.trip([{"category": "Formal Clothing", "query": "wrinkle resistant blazer"}],
                         notes="Conference in London. My mouse broke last week and I need a new one.",
                         purpose="Business", destination_city="London", destination_country="United Kingdom")
        self.assertEqual(sent_queries(self.c3), ["wireless computer mouse", "wrinkle resistant blazer"])
        self.assertEqual(prompt_parts(self.fake.requests[0])["shopping"]["named_products"],
                         [{"category": "Computer Mouse", "query": "wireless computer mouse"}])
        self.assertIn("Computer Mouse", trip["essentials"]["missing"], "searched, nothing found: honest")

    def test_a_named_product_in_other_words_is_not_searched_twice(self):
        self.trip([{"category": "Work Gear", "query": "bluetooth mouse"}], purpose="Business",
                  notes="Business trip; my mouse broke.")
        self.assertEqual(sent_queries(self.c3), ["bluetooth mouse"])

    def test_items_of_another_purpose_are_refused_without_a_reason_in_the_description(self):
        searches = [{"category": "Formal Clothing", "query": "slim fit blazer"},
                    {"category": "Ihram", "query": "two piece ihram set"},
                    {"category": "Beachwear", "query": "swim trunks"}]
        self.trip(searches)  # Tourism, beach description
        self.assertEqual(sent_queries(self.c3), ["swim trunks"], "no Channel3 credit spent on refused searches")
        (_, result), = self.fake.tool_messages(1)
        self.assertEqual({s["query"] for s in result["skipped"]}, {"slim fit blazer", "two piece ihram set"})

    def test_the_description_can_justify_them(self):
        self.trip([{"category": "Formal Clothing", "query": "slim fit blazer"}],
                  notes="A beach holiday that ends with my sister's wedding in Seville.")
        self.assertEqual(sent_queries(self.c3), ["slim fit blazer"])

    def test_switching_from_business_to_tourism_cannot_produce_business_products(self):
        business = [{"category": "Formal Clothing", "query": "wrinkle resistant blazer"},
                    {"category": "Laptop Bag", "query": "laptop backpack for business travel"}]
        c3 = FakeChannel3(ok(live("bz1", "Wrinkle Resistant Blazer", "Bonobos", "Blazers", 250.0)), ok())
        first = self.trip(business, [{"product_id": "bz1", "category": "Formal Clothing"}], c3, purpose="Business",
                          notes=CONFERENCE, destination_city="London", destination_country="United Kingdom")
        self.assertEqual([p["id"] for p in first["travel_essentials"]], ["bz1"])

        clear_plan_cache()
        # Even if the AI repeated the Business searches, the Tourism trip refuses them.
        second = self.trip(business + [{"category": "Beachwear", "query": "swim trunks"}],
                           [{"product_id": "bz1", "category": "Formal Clothing"}])
        self.assertEqual(sent_queries(self.c3), ["swim trunks"])
        self.assertEqual(second["travel_essentials"], [])
        parts = prompt_parts(self.fake.requests[0])
        self.assertEqual(parts["trip"]["trip_description"], BEACH)
        self.assertNotIn("Formal Clothing", parts["shopping"]["fallback_categories"])
        self.assertNotIn("conference", json.dumps(parts).lower(), "nothing from the previous trip is carried over")
        self.assertFalse(second["ai"]["cached"])

    def test_purpose_conflict_rules(self):
        conflict = trip_shopping.purpose_conflict
        self.assertTrue(conflict("Tourism", BEACH, "men's blazer"))
        self.assertTrue(conflict("Business", CONFERENCE, "ihram towel set"))
        self.assertFalse(conflict("Business", CONFERENCE, "leather dress shoes"))
        self.assertFalse(conflict("Umrah", UMRAH, "travel prayer rug"))
        self.assertFalse(conflict("Other", "", "ihram towel set"), "Other: the AI decides from the description")
        self.assertFalse(conflict("Tourism", "Visiting the mosques of Istanbul, I pray daily", "travel prayer rug"))


# ------------------------------------------------------------ audience & matching ---
class AudienceAndMatchingTest(_Pipeline):

    def test_audience_shapes_clothing_searches_and_filters_products(self):
        c3 = FakeChannel3(ok(live("w1", "Women's Swim Shorts", "Roxy", "Swimwear", 40.0),
                             live("m1", "Men's Swim Trunks", "Speedo", "Swimwear", 35.0)), ok())
        trip = self.trip([{"category": "Beachwear", "query": "swim trunks"},
                          {"category": "Sunglasses", "query": "polarized sunglasses"}],
                         [{"product_id": "w1", "category": "Beachwear"}, {"product_id": "m1", "category": "Beachwear"}],
                         c3, shopping_audience="men")
        self.assertEqual(sent_queries(self.c3), ["men's swim trunks", "polarized sunglasses"])
        self.assertEqual([p["id"] for p in trip["travel_essentials"]], ["m1"])
        self.assertEqual(prompt_parts(self.fake.requests[0])["shopping"]["shopping_for"], "men")

    def test_everyone_adds_nothing(self):
        self.trip([{"category": "Beachwear", "query": "swim trunks"}], shopping_audience="all")
        self.assertEqual(sent_queries(self.c3), ["swim trunks"])
        self.assertNotIn("shopping_for", prompt_parts(self.fake.requests[0])["shopping"])

    def test_category_match(self):
        match = trip_shopping.matches_category
        self.assertTrue(match("polarized sunglasses", "Sunglasses", {"name": "Classic Aviator Sunglasses"}))
        self.assertFalse(match("polarized sunglasses", "Sunglasses", {"name": "Straw Sun Hat"}))
        self.assertTrue(match("wireless computer mouse", "Computer Mouse", {"name": "M720", "category": "Computer Mice"}))
        self.assertTrue(match("swimwear", "Beachwear", {"name": "Quick Dry Swim Trunks"}))
        self.assertFalse(match("kids travel activity kit", "Kids Travel", {"name": "Leather Briefcase"}))
        self.assertTrue(match("travel essentials", None, {"name": "Anything"}), "nothing specific to check")
