"""
Product recommendation coverage: the search plan (requested items and trip purpose first,
one search per category), repeated brands and product types, cross-retailer duplicates,
honest missing categories, and the relevance-filter fixes found in the live Umrah test
(abaya OR hijab; toiletry containers aren't "scented"). Fixtures are the real Channel3
results of that test (titles, brands, types, prices).

Run from backend/:
    venv\\Scripts\\python -m unittest tests.test_product_coverage -v
No real Groq or Channel3 requests.
"""
from tests import _env  # noqa: F401  (must precede any app.* import)

import json
import unittest
from unittest import mock

from app.core.config import settings
from app.services import trip_shopping
from tests._fake_groq import FakeGroq, calls, text
from tests.test_channel3 import FakeChannel3, ok, product
from tests.test_gemini_agent import plan_json
from tests.test_trip_products import _ProductsApi, prompt_parts


def live(pid, title, brand, kind, price):
    return product(pid, title, description=f"{title}.", brands=[{"id": brand[:3], "name": brand}],
                   category={"slug": "c", "title": kind, "path": [], "has_children": False},
                   offers=[{"url": f"https://shop.example/{pid}", "domain": "shop.example",
                            "price": {"price": price, "currency": "USD"}, "availability": "InStock"}])


# The live Umrah test (2026-11-12): the model's six searches and Channel3's real answers.
LIVE_SEARCHES = [
    {"query": "UK Type G plug adapter Saudi Arabia", "category": "Travel Adapter", "audience": "all"},
    {"query": "men's two piece ihram set", "category": "Ihram & Clothing", "audience": "men"},
    {"query": "women's abaya hijab set", "category": "Modest Clothing", "audience": "women"},
    {"query": "foldable travel prayer mat", "category": "Prayer Essentials", "audience": "all"},
    {"query": "comfortable walking sandals", "category": "Footwear", "audience": "all"},
    {"query": "unscented travel toiletries set", "category": "Personal Care", "audience": "all"},
]
LIVE_RESULTS = [
    [live("vCg62eB", "Travel Adapter - 2 in 1 - Type G - Compact Design", "Orei LLC", "Travel Plug Adapters", 6.99),
     live("u27c0mM", "Travel Power Plug Adapter", "Ceptics", "Travel Plug Adapters", 8.99),
     live("dTzUQC3", "Ceptics UK Travel Plug Adapter", "Ceptics", "Travel Plug Adapters", 12.99),
     live("7OnufJf", "LENCENT US to UK Plug Adapter Type G Travel Adaptor", "TESSAN", "Travel Plug Adapters", 21.56),
     live("HobsKDD", "US Type-B to UK Type-G Plug Adapter", "Watson", "Travel Plug Adapters", 8.95)],
    [live("ih1", "2-piece Sports Set With Drymove", "H&M", "Activewear", 29.99),
     live("ih2", "2-pack silver men's boxers", "Calvin", "Boxer Shorts", 24.0),
     live("ih3", "Men Top Daily Comfort", "Uniqlo", "Men's Undershirts", 14.9),
     live("ih4", "Two-Piece Lingerie Set", "Aerie", "Lingerie Sets", 39.0)],
    [live("ORWkOeS", "Amira Hijab Undercap", "Ecardin", "Undercaps & Underscarves", 20.47),
     live("Q8VgvGd", "Jersey Hijab Shawl", "Walmart", "Shawls", 19.98),
     live("sJn2ReJ", "Risha Swim Hijab", "Moeva", "Burkinis", 40.0),
     live("hzHnKuA", "Alexia Wrap Skirt Set", "Fashion Nova", "Outfit Sets", 34.99),
     live("GtwxFPv", "Medina Cardigan With Scarf", "Apiece Apart", "Cardigans", 270.0)],
    [live("bhhTjEv", "Moab Rocks Foldable Travel Yoga Mat", "Yune", "Yoga & Pilates Mats", 58.0),
     live("ccqarSE", "Foldable Travel Yoga Mat", "Yune", "Yoga & Pilates Mats", 58.0),
     live("8QP2eAu", "FoldingMat", "WellnessMats", "Anti-Fatigue Mats", 273.0),
     live("bPa3xrE", "Foldable Yoga Mat", "Gaiam", "Yoga & Pilates Mats", 24.99)],
    [live("SBB1JhM", "Lightweight Soft Footbed Walking Sandals", "Dream Pairs", "Sandals", 43.99),
     live("AxqAnV9", "Women's Go Walk Arch Fit 2.0 Sport Sandal", "Skechers", "Sandals", 65.98),
     live("02bCueb", "Go Walk Arch Fit 2.0 Sandal W", "Skechers", "Sandals", 42.47),
     live("hHjF2fD", "Go Walk Flex Sandals Emma", "Skechers", "Sandals", 50.0),
     live("vNauVUz", "Cloudsteppers Sunmaze Bali Sandal", "Clarks", "Sandals", 49.99)],
    [live("mJufTTa", "Anywear Toiletry Set", "Oleada", "Toiletry Bags", 115.0),
     live("gF1BeR2", "Plastic Travel Bottle Set", "Conair", "Travel Bottles & Containers", 12.79),
     live("UIa8U7X", "Peter Thomas Roth Travel Set", "Peter Thomas Roth", "Skin Care Kits & Sets", 35.4),
     live("51r1tGm", "Getaway Trio", "DR. SQUATCH", "Personal Care Gift Sets & Kits", 46.5),
     live("n9PzzFk", "Travel Bottle Set", "Samsonite", "Travel Bottles & Containers", 12.0)],
]


class LiveUmrahReplayTest(_ProductsApi):
    """The exact live case, with a model that greedily picks everything it is shown."""

    def run_live(self, headers=None):
        self.serve(FakeChannel3(*[ok(*r) for r in LIVE_RESULTS]))
        self.fake = FakeGroq([calls(("find_travel_products", {"searches": LIVE_SEARCHES})), "picks"])
        greedy = self.fake._create

        async def create(**params):  # final turn: pick every product the tool showed
            if self.fake.script and self.fake.script[0] == "picks":
                tool = json.loads(next(m["content"] for m in params["messages"] if m["role"] == "tool"))
                picks = [{"product_id": p["id"], "category": s["category"]}
                         for s in tool["searches"] for p in s["products"]]
                self.fake.script[0] = text(plan_json(None, essentials=picks))
            return await greedy(**params)
        with self.fake.patch(), mock.patch.object(self.fake, "_create", new=create), \
             mock.patch.object(settings, "CHANNEL3_RESULTS_PER_QUERY", 5):
            return self.umrah(headers=headers, notes="I need a UK plug adapter", stay_preference="Budget stay")

    def test_live_case_now_covers_four_categories_without_padding(self):
        trip = self.run_live()
        got = [(p["group"], p["name"]) for p in trip["travel_essentials"]]
        self.assertEqual(got, [
            ("Travel Adapter", "Travel Adapter - 2 in 1 - Type G - Compact Design"),
            ("Travel Adapter", "Travel Power Plug Adapter"),
            ("Modest Clothing", "Amira Hijab Undercap"),
            ("Modest Clothing", "Jersey Hijab Shawl"),
            ("Footwear", "Lightweight Soft Footbed Walking Sandals"),
            ("Footwear", "Women's Go Walk Arch Fit 2.0 Sport Sandal"),
            ("Personal Care", "Anywear Toiletry Set"),
            ("Personal Care", "Plastic Travel Bottle Set"),
        ])
        self.assertEqual(trip["essentials"]["missing"], ["Ihram & Clothing", "Prayer Essentials"],
                         "unavailable categories are reported, not filled")
        self.assertIn("No relevant options were found for: Ihram & Clothing, Prayer Essentials",
                      trip["essentials"]["message"])

    def test_what_the_model_was_shown(self):
        self.run_live()
        (_, result), = self.fake.tool_messages(1)
        shown = {s["category"]: [p["id"] for p in s["products"]] for s in result["searches"]}
        self.assertNotIn("dTzUQC3", shown["Travel Adapter"], "second Ceptics listing = same product")
        self.assertNotIn("02bCueb", shown["Footwear"], "same Skechers model at another retailer")
        self.assertEqual(shown["Modest Clothing"], ["ORWkOeS", "Q8VgvGd"], "hijabs kept; swim hijab, skirt rejected")
        self.assertEqual(shown["Personal Care"], ["mJufTTa", "gF1BeR2", "n9PzzFk"],
                         "containers aren't scented; scented kits rejected")
        self.assertEqual(shown["Prayer Essentials"], [], "yoga and anti-fatigue mats are not prayer mats")
        self.assertEqual(shown["Ihram & Clothing"], [])

    def test_premium_keeps_genuine_links_free_gets_none(self):
        prem = self.run_live(headers=self._premium())
        self.assertTrue(all(p["purchase_url"].startswith("https://shop.example/") for p in prem["travel_essentials"]))
        clear = self.run_live()
        self.assertTrue(all(p["purchase_url"] is None for p in clear["travel_essentials"]))


class BrandAndTypeLimitTest(_ProductsApi):

    def select(self, products, picks, category="Footwear"):
        self.serve(FakeChannel3(ok(*products)))
        fake = FakeGroq([calls(("find_travel_products", {"searches": [{"category": category, "query": "travel plug adapter" if category == "Travel Adapter" else "walking sandals"}]})),
                         text(plan_json(None, essentials=picks))])
        with fake.patch(), mock.patch.object(settings, "CHANNEL3_RESULTS_PER_QUERY", 5):
            return self.umrah(purpose="Tourism", notes="A short trip.")

    def test_one_product_per_brand_per_category(self):
        skechers = [live("k1", "Go Walk Flex Sandals Emma", "Skechers", "Sandals", 50.0),
                    live("k2", "Reggae Slim Sandal", "Skechers", "Sandals", 45.0),
                    live("c1", "Cloudsteppers Sunmaze Bali Sandal", "Clarks", "Sandals", 49.99)]
        trip = self.select(skechers, [{"product_id": i, "category": "Footwear"} for i in ("k1", "k2", "c1")])
        self.assertEqual([p["id"] for p in trip["travel_essentials"]], ["k1", "c1"])

    def test_a_brands_mens_and_womens_items_are_both_allowed(self):
        items = [live("m1", "Men's Trail Sandal", "Teva", "Sandals", 60.0),
                 live("w1", "Women's Trail Sandal Lite", "Teva", "Sandals", 60.0),
                 live("u1", "Original Universal Sandal", "Teva", "Sandals", 55.0)]
        trip = self.select(items, [{"product_id": i, "category": "Footwear"} for i in ("m1", "w1", "u1")])
        self.assertEqual([(p["id"], p["audience"]) for p in trip["travel_essentials"]],
                         [("m1", "men"), ("w1", "women")], "a unisex one competes with both")

    def test_at_most_two_of_the_same_product_type(self):
        adapters = [live(f"a{i}", t, b, "Travel Plug Adapters", 9.0 + i) for i, (t, b) in enumerate([
            ("Travel Adapter Type G Compact", "Orei LLC"), ("Power Plug Adapter UK", "Ceptics"),
            ("Universal Adaptor With USB", "TESSAN"), ("Type-G Plug Converter", "Watson")])]
        trip = self.select(adapters, [{"product_id": f"a{i}", "category": "Travel Adapter"} for i in range(4)],
                           category="Travel Adapter")
        self.assertEqual([p["id"] for p in trip["travel_essentials"]], ["a0", "a1"])


class CrossRetailerDuplicateTest(unittest.TestCase):

    def test_same_model_listed_differently(self):
        a = {"id": "1", "name": "Women's Go Walk Arch Fit 2.0 Sport Sandal", "brand": "Skechers", "price": 65.98}
        b = {"id": "2", "name": "Go Walk Arch Fit 2.0 Sandal W", "brand": "Skechers", "price": 42.47}
        self.assertTrue(trip_shopping.is_near_duplicate(a, b), "same model, other retailer and title")
        c = {"id": "3", "name": "Skechers Go Walk Arch Fit 2.0 Sandal - Black", "brand": None}
        self.assertTrue(trip_shopping.is_near_duplicate(a, c), "brand only in one title, plus a color")
        self.assertFalse(trip_shopping.is_near_duplicate(a, {"id": "4", "name": "Go Walk Flex Sandals Emma",
                                                             "brand": "Skechers"}), "another Skechers model")

    def test_pack_sizes_colors_and_same_price_listings(self):
        self.assertTrue(trip_shopping.is_near_duplicate(
            {"id": "1", "name": "Packable Rain Poncho - Navy"}, {"id": "2", "name": "Packable Rain Poncho (Black)"}))
        self.assertTrue(trip_shopping.is_near_duplicate(
            {"id": "1", "name": "Moab Rocks Foldable Travel Yoga Mat", "brand": "Yune", "price": 58.0},
            {"id": "2", "name": "Foldable Travel Yoga Mat", "brand": "Yune", "price": 58.0}))
        self.assertTrue(trip_shopping.is_near_duplicate(
            {"id": "1", "name": "Ceptics UK Travel Plug Adapter", "brand": "Ceptics"},
            {"id": "2", "name": "Travel Power Plug Adapter", "brand": "Ceptics"}))

    def test_different_brands_are_choice_but_similar_items_are_limited(self):
        a = {"id": "1", "name": "Neutrogena Hand Cream Unscented Travel Size", "brand": "Neutrogena"}
        b = {"id": "2", "name": "Hand Cream Unscented Travel Size", "brand": "Eucerin"}
        self.assertFalse(trip_shopping.is_near_duplicate(a, b))
        self.assertTrue(trip_shopping.is_similar(a, b))


class RelevanceFixesTest(unittest.TestCase):

    def test_a_search_for_abaya_and_hijab_accepts_either(self):
        q = "women's abaya hijab set"
        kept = [p["title"] for p in LIVE_RESULTS[2]
                if trip_shopping.is_relevant(q, {"name": p["title"], "category": p["category"]["title"]})]
        self.assertEqual(kept, ["Amira Hijab Undercap", "Jersey Hijab Shawl"])
        self.assertTrue(trip_shopping.is_relevant(q, {"name": "Black Open Front Abaya"}))

    def test_unscented_applies_to_care_products_not_containers(self):
        q = "unscented travel toiletries set"
        check = lambda name, kind: trip_shopping.is_relevant(q, {"name": name, "category": kind})
        self.assertTrue(check("Anywear Toiletry Set", "Toiletry Bags"))
        self.assertTrue(check("Travel Bottle Set", "Travel Bottles & Containers"))
        self.assertFalse(check("Getaway Trio", "Personal Care Gift Sets & Kits"))
        self.assertTrue(check("Unscented Body Wash", "Body Wash"))


if __name__ == "__main__":
    unittest.main()
