"""
Regressions from the live Alexandria summer test (2026-11-12): the description named a
swimsuit and sunglasses, but Groq's six searches (modest dress, sandals, sunscreen, beach bag,
phone pouch, day backpack) included neither, and the server's named-product safety net didn't
recognise those words. A modest swimsuit search would also have been emptied by the "modest
rules out beachwear" guard. Plus: no unexplained Business categories, honest missing lists,
distinct needs before extra alternatives, no cross-trip contamination.

Run from backend/:
    venv\\Scripts\\python -m unittest tests.test_alexandria_regressions -v
No real Groq or Channel3 requests.
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

ALEXANDRIA = ("A summer trip to Alexandria with beach days, city walks along the Corniche and modest outfits. "
              "I need a swimsuit and sunglasses.")
# Groq's actual six searches in the live run.
LIVE_SEARCHES = [
    {"query": "lightweight modest summer dress women", "category": "Modest Clothing", "audience": "women"},
    {"query": "women comfortable walking sandals", "category": "Footwear", "audience": "women"},
    {"query": "broad spectrum sunscreen SPF50", "category": "Sun Care", "audience": "all"},
    {"query": "large beach bag waterproof", "category": "Beach Accessories", "audience": "all"},
    {"query": "waterproof phone pouch", "category": "Phone Accessories", "audience": "all"},
    {"query": "lightweight day backpack travel", "category": "Day Bag", "audience": "all"},
]


def sent(c3):
    return [json.loads(r.content)["query"] for r in c3.requests]


class _Alexandria(_ProductsApi):

    def trip(self, searches, picks=(), c3=None, **over):
        self.c3 = self.serve(c3 or FakeChannel3(ok()))
        self.fake = FakeGroq([calls(("find_travel_products", {"searches": searches})),
                              text(plan_json(None, essentials=list(picks), **over.pop("model_extra", {})))])
        body = dict(destination_city="Alexandria", destination_country="Egypt", purpose="Tourism",
                    departure_date="2026-07-06", return_date="2026-07-11", travelers=1,
                    stay_preference="Luxury hotel", priorities=[], notes=ALEXANDRIA, shopping_audience="women")
        body.update(over)
        with self.fake.patch(), mock.patch.object(settings, "CHANNEL3_RESULTS_PER_QUERY", 5):
            return self._plan(**body)


class NamedBeachItemsTest(_Alexandria):

    def test_root_cause_named_products_are_now_recognised(self):
        self.assertEqual([n["category"] for n in trip_shopping.named_products(ALEXANDRIA)],
                         ["Modest Clothing", "Swimwear", "Sunglasses"], "modest outfits is not formal clothing")
        for casual in ("summer outfits", "beach outfits", "comfy outfits for the flight"):
            self.assertNotIn("Formal Clothing", [n["category"] for n in trip_shopping.named_products(casual)])
        self.assertIn("Formal Clothing",
                      [n["category"] for n in trip_shopping.named_products("I need professional outfits")])

    def test_swimsuit_and_sunglasses_are_searched_even_when_groq_skips_them(self):
        # Request order: modest dress (Groq's, covers "modest outfits"), then the server's swimsuit and
        # sunglasses searches, then Groq's other searches until the cap.
        c3 = FakeChannel3(ok(), ok(live("sw1", "Women's Modest Swimsuit Burkini", "Hasema", "Swimwear", 59.0)),
                          ok(live("sg1", "Women's Polarized Sunglasses", "Ray-Ban", "Sunglasses", 140.0)),
                          ok(), ok(), ok())
        trip = self.trip(LIVE_SEARCHES, [{"product_id": "sw1", "category": "Swimwear"},
                                         {"product_id": "sg1", "category": "Sunglasses"}], c3)
        queries = sent(self.c3)
        self.assertEqual(queries[:3], ["lightweight modest summer dress women", "women's swimsuit", "polarized sunglasses"],
                         "named needs first, in description order; Groq's own covering search is kept")
        self.assertEqual(len(queries), 6, "still six searches: the model's last two are what the limit cuts")
        self.assertNotIn("waterproof phone pouch", queries)
        self.assertEqual({p["id"]: p["group"] for p in trip["travel_essentials"]},
                         {"sw1": "Swimwear", "sg1": "Sunglasses"})

    def test_groq_searching_them_itself_is_not_repeated(self):
        searches = [{"query": "women's modest swimsuit", "category": "Beachwear", "audience": "women"},
                    {"query": "cat eye sunglasses", "category": "Eyewear"}] + LIVE_SEARCHES[:4]
        self.trip(searches)
        queries = sent(self.c3)
        self.assertEqual(queries[:3], ["lightweight modest summer dress women", "women's modest swimsuit",
                                       "cat eye sunglasses"], "Groq's own wording kept for every named need")
        self.assertEqual(len(queries), 6)
        self.assertEqual(sum("swim" in q for q in queries), 1)

    def test_a_modest_swimsuit_is_not_filtered_as_beachwear(self):
        c3 = FakeChannel3(ok(live("bk1", "Women's Modest Swimsuit Burkini", "Hasema", "Swimwear", 59.0),
                             live("bc1", "Beach Cover-Up Mini Dress", "Roxy", "Cover Ups", 45.0)))
        self.trip([{"query": "women's modest swimsuit", "category": "Swimwear"}], c3=c3)
        (_, result), = self.fake.tool_messages(1)
        shown = [p["id"] for s in result["searches"] for p in s["products"]]
        self.assertIn("bk1", shown, "a modest swimsuit search keeps swimwear")
        self.assertNotIn("bc1", shown, "a cover-up still isn't a swimsuit")
        self.assertFalse(trip_shopping.is_relevant("women's abaya for umrah",
                                                   {"name": "Pima Mini Abaya", "description": "an elegant beach cover-up"}),
                         "the abaya guard still rejects beachwear")

    def test_unfound_named_items_are_reported(self):
        trip = self.trip(LIVE_SEARCHES[:2])
        states = {d["category"]: d["state"] for d in trip["essentials"]["missing_detail"]}
        self.assertEqual((states["Swimwear"], states["Sunglasses"]), ("not_found", "not_found"))


class NoUnexplainedBusinessTest(_Alexandria):

    def test_tourism_refuses_formal_clothing_and_does_not_list_it_as_missing(self):
        searches = [{"query": "women's wrinkle resistant travel blazer", "category": "Formal Clothing"},
                    {"query": "leather dress shoes", "category": "Professional Shoes"}] + LIVE_SEARCHES[:2]
        trip = self.trip(searches, model_extra={"missing_categories": ["Formal Clothing", "Ihram & Clothing", "Laptop Bag"]})
        queries = sent(self.c3)
        self.assertFalse(any("blazer" in q or "dress shoes" in q for q in queries))
        missing = trip["essentials"]["missing"]
        for irrelevant in ("Formal Clothing", "Professional Shoes", "Ihram & Clothing", "Laptop Bag"):
            self.assertNotIn(irrelevant, missing)
        self.assertEqual(set(missing), {"Swimwear", "Sunglasses", "Modest Clothing", "Footwear"},
                         "only what was searched or named")

    def test_business_items_allowed_when_the_description_explains_them(self):
        self.trip([{"query": "linen blazer", "category": "Formal Clothing"}],
                  notes="Beach week in Alexandria, then a client meeting in Cairo.")
        self.assertIn("women's linen blazer", sent(self.c3))


class DistinctNeedsFirstTest(_Alexandria):

    def test_two_options_per_need_while_a_named_need_is_uncovered(self):
        def items(prefix, kind, names):
            return [live(f"{prefix}{i}", n, f"Brand{prefix}{'ABC'[i]}x", f"{kind} {i}", 20.0 + i) for i, n in enumerate(names)]
        c3 = FakeChannel3(ok(*items("d", "Dresses", ["Linen Midi Dress", "Smocked Maxi Dress", "Button Shirt Dress"])),
                          ok(), ok(),  # swimsuit and sunglasses: nothing found
                          ok(*items("s", "Sandals", ["Wedge Sandal", "Flat Slide Sandal", "Strappy Sandal"])),
                          ok(*items("u", "Sunscreen", ["Mineral Sunscreen SPF 50", "Sport Sunscreen Spray", "Tinted Sunscreen"])),
                          ok(*items("b", "Tote Bags", ["Beach Tote Bag", "Canvas Beach Bag", "Mesh Beach Bag"])))
        picks = [{"product_id": f"{p}{i}", "category": "x"} for p in "dsub" for i in range(3)]
        trip = self.trip(LIVE_SEARCHES, picks, c3)
        groups = [p["group"] for p in trip["travel_essentials"]]
        for g in ("Modest Clothing", "Footwear", "Sun Care", "Beach Accessories"):
            self.assertEqual(groups.count(g), 2, f"{g}: at most 2 while swimsuit/sunglasses are uncovered")
        self.assertEqual(trip["essentials"]["missing"], ["Swimwear", "Sunglasses"])

    def test_three_options_again_when_no_named_need_is_uncovered(self):
        def items(prefix, kind, names):
            return [live(f"{prefix}{i}", n, f"Brand{prefix}{'ABC'[i]}x", f"{kind} {i}", 20.0 + i) for i, n in enumerate(names)]
        c3 = FakeChannel3(ok(*items("d", "Dresses", ["Linen Midi Dress", "Smocked Maxi Dress", "Button Shirt Dress"])),
                          ok(*items("s", "Sandals", ["Wedge Sandal", "Flat Slide Sandal", "Strappy Sandal"])),
                          ok(*items("u", "Sunscreen", ["Mineral Sunscreen SPF 50", "Sport Sunscreen Spray", "Tinted Sunscreen"])),
                          ok(*items("b", "Tote Bags", ["Beach Tote Bag", "Canvas Beach Bag", "Mesh Beach Bag"])))
        picks = [{"product_id": f"{p}{i}", "category": "x"} for p in "dsub" for i in range(3)]
        trip = self.trip(LIVE_SEARCHES[:4], picks, c3, notes="A relaxed summer week in Alexandria by the sea.")
        groups = [p["group"] for p in trip["travel_essentials"]]
        self.assertEqual([groups.count(g) for g in ("Modest Clothing", "Footwear", "Sun Care", "Beach Accessories")],
                         [3, 3, 3, 3], "nothing named is missing: the usual 3 per category with 4+ categories")


class NoCrossTripContaminationTest(_Alexandria):

    def test_a_second_trip_shares_nothing_with_the_first(self):
        c3 = FakeChannel3(ok(), ok(live("sw1", "Women's Modest Swimsuit Burkini", "Hasema", "Swimwear", 59.0)), ok())
        first = self.trip(LIVE_SEARCHES[:1], [{"product_id": "sw1", "category": "Swimwear"}], c3)
        self.assertEqual([p["id"] for p in first["travel_essentials"]], ["sw1"])

        clear_plan_cache()
        second = self.trip([{"query": "warm wool coat", "category": "Warm Layers"}],
                           [{"product_id": "sw1", "category": "Swimwear"}],  # an id from the first trip
                           notes="A winter city break in Vienna with Christmas markets.",
                           destination_city="Vienna", destination_country="Austria",
                           departure_date="2026-12-14", return_date="2026-12-18")
        self.assertEqual(sent(self.c3), ["women's warm wool coat"], "no swimsuit/sunglasses carried over")
        self.assertEqual(second["travel_essentials"], [], "a product from the last trip can't be picked")
        self.assertNotIn("Swimwear", second["essentials"]["missing"])
        parts = prompt_parts(self.fake.requests[0])
        self.assertEqual(parts["shopping"]["named_products"], [])
        self.assertNotIn("Alexandria", json.dumps(parts))
        self.assertFalse(second["ai"]["cached"])

    def test_same_trip_fields_with_another_description_is_not_served_from_cache(self):
        self.trip(LIVE_SEARCHES[:1])
        second = self.trip([{"query": "travel umbrella", "category": "Rain Gear"}],
                           notes="Summer in Alexandria, mostly museums and cafes; I need an umbrella.")
        self.assertFalse(second["ai"]["cached"], "the description is part of the plan cache key")
        self.assertIn("travel umbrella", sent(self.c3))
