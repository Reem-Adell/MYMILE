"""
Trip-aware Channel3 product recommendations: every Plan a Trip field reaches product
discovery, purpose-specific categories (Umrah first), no assumed gender, relevance
guards, honest gaps, no filler, genuine data/links, Premium-only links, credit caps.

Run from backend/:
    venv\\Scripts\\python -m unittest tests.test_trip_products -v
No real Groq or Channel3 requests: both are mocked.
"""
from tests import _env  # noqa: F401  (must precede any app.* import)

import json
import unittest
from unittest import mock

from app.core.config import Settings, settings
from app.services import channel3_service, trip_shopping
from tests._fake_groq import FakeGroq, calls, text
from tests.test_channel3 import FakeChannel3, _C3Case, ok, product
from tests.test_gemini_agent import _AgentApi, clear_plan_cache, plan_json

UMRAH_SEARCHES = [
    {"category": "Ihram & Clothing", "query": "men's two piece ihram towel set", "audience": "men"},
    {"category": "Modest Clothing", "query": "women's abaya for umrah", "audience": "women"},
    {"category": "Prayer Essentials", "query": "travel prayer mat", "audience": "all"},
    {"category": "Footwear", "query": "comfortable walking sandals", "audience": "all"},
    {"category": "Personal Care", "query": "unscented travel toiletries", "audience": "all"},
    {"category": "Travel Bags & Organizers", "query": "drawstring shoe bag", "audience": "all"},
]


def umrah_channel3():
    """One response per search, in order (searches run sequentially)."""
    return FakeChannel3(
        ok(product("ihram1", "Men's Ihram Towel Set 2 Piece")),
        ok(product("abaya1", "Women's Black Abaya Open Front")),
        ok(product("yoga1", "Non Slip Yoga Mat"), product("pmat1", "Travel Prayer Mat with Pouch")),
        ok(product("sandal1", "Comfort Walking Sandals")),
        ok(product("soap1", "Scented Rose Body Wash")),        # off-topic for "unscented": removed
        ok(product("bag1", "Drawstring Shoe Bag 2 Pack")),
    )


def umrah_picks():
    return [
        {"product_id": "ihram1", "category": "Ihram & Clothing", "audience": "all", "per_traveler": True,
         "reason": "Ihram-compliant two-piece set."},                       # unverified claim: reason dropped
        {"product_id": "abaya1", "category": "Modest Clothing", "audience": "women", "per_traveler": True,
         "reason": "Open-front abaya, easy to wear between prayers."},
        {"product_id": "yoga1", "category": "Prayer Essentials", "reason": "Use it to pray."},  # removed server-side
        {"product_id": "pmat1", "category": "Prayer Essentials", "per_traveler": True,
         "reason": "Travel prayer mat with a pouch."},
        {"product_id": "sandal1", "category": "Footwear", "per_traveler": True,
         "reason": "Walking sandals for long walks between sites."},
        {"product_id": "bag1", "category": "Travel Bags & Organizers", "per_traveler": False,
         "reason": "Carry shoes at the mosque entrance."},
    ]


def prompt_parts(request):
    """{'trip': {...}, 'shopping': {...}} from the first user message MYMILE sent."""
    user = next(m["content"] for m in request["messages"] if m["role"] == "user")
    out = {}
    lines = user.split("\n")
    out["trip"] = json.loads(lines[1])
    for line in lines[2:]:
        key, _, value = line.partition(": ")
        out[key] = json.loads(value)
    return out


class _ProductsApi(_C3Case, _AgentApi):

    def setUp(self):
        super().setUp()
        for p in (mock.patch.object(settings, "CHANNEL3_MAX_QUERIES_PER_TRIP", 6),):
            p.start()
            self.addCleanup(p.stop)

    def umrah(self, headers=None, **over):
        body = dict(destination_city="Makkah", destination_country="Saudi Arabia", purpose="Umrah",
                    stay_preference="Budget stay", priorities=["Slow pace"],
                    notes="First Umrah, we walk a lot", travelers=2)
        body.update(over)
        return self._plan(headers=headers, **body)


# ------------------------------------------------------------ context ---
class ProductContextTest(_ProductsApi):

    def test_every_plan_a_trip_field_reaches_product_discovery(self):
        fake = FakeGroq([text(plan_json(None))])
        with fake.patch():
            self.umrah(headers=self._premium(), total_budget=1500, departure_date="2026-12-29",
                       return_date="2027-01-02", notes="First Umrah, please include a travel prayer rug")
        parts = prompt_parts(fake.requests[0])
        trip, shopping = parts["trip"], parts["shopping"]
        self.assertEqual((trip["city"], trip["country"]), ("Makkah", "Saudi Arabia"))
        self.assertEqual((trip["check_in"], trip["check_out"], trip["nights"]), ("2026-12-29", "2027-01-02", 4))
        self.assertEqual((trip["purpose"], trip["travelers"], trip["stay_preference"]), ("Umrah", 2, "Budget stay"))
        self.assertEqual(trip["trip_description"], "First Umrah, please include a travel prayer rug")
        self.assertEqual(trip["total_budget_usd"], 1500)
        self.assertEqual(shopping["purpose_type"], "umrah")
        self.assertEqual(shopping["travel_months"], ["December", "January"])
        self.assertIn("4 nights", shopping["trip_length"])
        self.assertEqual(shopping["budget"], {"level": "moderate", "per_traveler_per_night_usd": 188})
        self.assertEqual(shopping["named_products"], [{"category": "Prayer Essentials", "query": "travel prayer rug"}])
        self.assertEqual(shopping["fallback_categories"][:3], ["Ihram & Clothing", "Modest Clothing", "Prayer Essentials"])
        self.assertEqual(shopping["max_searches"], 6)
        self.assertNotIn("search_plan", shopping, "no fixed plan: the AI decides from the description")
        self.assertIn("tool_data", parts)
        self.assertEqual(fake.tool_names(0), ["find_travel_products"])

    def test_purpose_changes_the_fallback_categories(self):
        seen = {}
        for purpose in ("Umrah", "Business", "Tourism"):
            clear_plan_cache()
            fake = FakeGroq([text(plan_json(None))])
            with fake.patch():
                self.umrah(purpose=purpose, notes="A short trip.")
            seen[purpose] = prompt_parts(fake.requests[0])["shopping"]["fallback_categories"]
        self.assertIn("Ihram & Clothing", seen["Umrah"])
        self.assertIn("Formal Clothing", seen["Business"])
        self.assertIn("Day Bag", seen["Tourism"])
        for other in ("Business", "Tourism"):
            self.assertNotIn("Ihram & Clothing", seen[other])

    def test_budget_and_travelers_shape_the_context(self):
        levels = {}
        for budget in (300, 3000):
            clear_plan_cache()
            fake = FakeGroq([text(plan_json(None))])
            with fake.patch():
                self.umrah(headers=self._premium(), total_budget=budget)
            levels[budget] = prompt_parts(fake.requests[0])["shopping"]["budget"]["level"]
        self.assertEqual(levels, {300: "tight", 3000: "comfortable"})
        clear_plan_cache()
        fake = FakeGroq([text(plan_json(None))])
        with fake.patch():
            self.umrah(travelers=1, total_budget=99999)  # Free: a sent budget is ignored
        parts = prompt_parts(fake.requests[0])
        self.assertNotIn("budget", parts["shopping"])
        self.assertNotIn("total_budget_usd", parts["trip"])
        self.assertEqual(parts["shopping"]["travelers"], 1)

    def test_product_rules_forbid_assumptions_and_claims(self):
        fake = FakeGroq([text(plan_json(None))])
        with fake.patch():
            self.umrah()
        system = fake.requests[0]["messages"][0]["content"]
        for rule in ("trip_description is the PRIMARY source", "never assume gender",
                     "a yoga mat is not a prayer mat", "Ihram-compliant, halal, certified or unscented",
                     "a beach cover-up is not an abaya", "no religious rulings", "no fixed number",
                     "missing_categories", "Never search items of another"):
            self.assertIn(rule, system)


# --------------------------------------------------------- recommendations ---
class UmrahRecommendationTest(_ProductsApi):

    def plan(self, headers=None, picks=None, searches=UMRAH_SEARCHES, c3=None, **over):
        self.c3 = self.serve(c3 or umrah_channel3())
        self.fake = FakeGroq([calls(("find_travel_products", {"searches": searches})),
                              text(plan_json(None, essentials=umrah_picks() if picks is None else picks,
                                             missing_categories=["Personal Care"]))])
        with self.fake.patch():
            return self.umrah(headers=headers, **over)

    def test_umrah_essentials_are_relevant_grouped_and_labelled(self):
        trip = self.plan(headers=self._premium())
        items = trip["travel_essentials"]
        self.assertEqual([p["id"] for p in items], ["ihram1", "abaya1", "pmat1", "sandal1", "bag1"],
                         "more than three, and no yoga mat")
        by_id = {p["id"]: p for p in items}
        self.assertEqual(by_id["ihram1"]["group"], "Ihram & Clothing")
        self.assertEqual(by_id["ihram1"]["audience"], "men", "the men's search labels it, whatever the model said")
        self.assertEqual(by_id["abaya1"]["audience"], "women")
        self.assertEqual(by_id["pmat1"]["audience"], "all")
        self.assertIsNone(by_id["ihram1"]["reason"], "unverified 'compliant' claim is not shown")
        self.assertEqual(by_id["sandal1"]["reason"], "Walking sandals for long walks between sites.")
        self.assertTrue(by_id["sandal1"]["per_traveler"])
        self.assertFalse(by_id["bag1"]["per_traveler"])
        self.assertEqual(trip["essentials"]["status"], "ok")
        self.assertEqual(trip["essentials"]["missing"], ["Personal Care"])
        self.assertIn("No relevant options were found for: Personal Care", trip["essentials"]["message"])
        self.assertEqual(len(self.c3.requests), 6, "one credit per search, no duplicates")

        # The yoga mat and scented wash never reached the model.
        (_, result), = self.fake.tool_messages(1)
        found = {s["query"]: [p["id"] for p in s["products"]] for s in result["searches"]}
        self.assertEqual(found["travel prayer mat"], ["pmat1"])
        self.assertEqual(found["unscented travel toiletries"], [])
        care = next(s for s in result["searches"] if s["category"] == "Personal Care")
        self.assertIn("off-topic", care["note"])

    def test_genuine_data_and_premium_links(self):
        trip = self.plan(headers=self._premium())
        p = next(i for i in trip["travel_essentials"] if i["id"] == "pmat1")
        self.assertEqual(p["name"], "Travel Prayer Mat with Pouch")
        self.assertEqual(p["brand"], "Acme")
        self.assertEqual(p["image_url"], "https://img.example/pmat1.jpg")
        self.assertEqual((p["price"], p["currency"]), (79.0, "USD"))
        self.assertEqual(p["purchase_url"], "https://shop-a.example/pmat1")
        self.assertEqual({o["url"] for o in p["offers"]},
                         {"https://shop-a.example/pmat1", "https://shop-b.example/pmat1",
                          "https://shop-c.example/pmat1"})
        self.assertEqual(p["variants"], ["Size: S, L"])

    def test_free_users_get_no_links_anywhere(self):
        trip = self.plan()
        self.assertEqual(len(trip["travel_essentials"]), 5)
        for p in trip["travel_essentials"]:
            self.assertIsNone(p["purchase_url"])
            self.assertTrue(p["offers"])
            self.assertTrue(all(o["url"] is None for o in p["offers"]))
        self.assertNotIn("shop-a.example/", json.dumps(trip["travel_essentials"]))

    def test_no_filler_when_the_model_rejects_results(self):
        trip = self.plan(picks=[])
        self.assertEqual(trip["travel_essentials"], [], "unvetted Channel3 results are never shown")
        self.assertEqual(trip["essentials"]["status"], "empty")
        self.assertIn("none were selected", trip["essentials"]["message"])

    def test_only_picked_products_are_shown(self):
        trip = self.plan(picks=umrah_picks()[3:5])
        self.assertEqual([p["id"] for p in trip["travel_essentials"]], ["pmat1", "sandal1"])
        self.assertIn("Ihram & Clothing", trip["essentials"]["missing"])

    def test_cached_plan_keeps_groups_and_spends_no_credit(self):
        headers = self._premium()
        first = self.plan(headers=headers)
        with self.fake.patch():
            again = self.umrah(headers=headers)
        self.assertTrue(again["ai"]["cached"])
        self.assertEqual(again["travel_essentials"], first["travel_essentials"])
        self.assertEqual(again["essentials"]["missing"], first["essentials"]["missing"])
        self.assertEqual(len(self.c3.requests), 6)


class CreditSafeguardTest(_ProductsApi):

    def test_search_cap_is_shared_and_follow_up_search_is_allowed(self):
        self.serve(FakeChannel3(ok(product("x1", "Comfort Walking Sandals"))))
        fake = FakeGroq([
            calls(("find_travel_products", {"searches": UMRAH_SEARCHES[:3]})),
            calls(("find_travel_products", {"searches": [UMRAH_SEARCHES[0]] + UMRAH_SEARCHES[3:]})),
            calls(("find_travel_products", {"searches": [{"category": "x", "query": "extra"}]})),
            text(plan_json(None, essentials=[{"product_id": "x1", "category": "Footwear"}])),
        ])
        with fake.patch(), mock.patch.object(settings, "CHANNEL3_MAX_QUERIES_PER_TRIP", 4):
            trip = self.umrah()
        (_, second), = [m for m in fake.tool_messages(2) if m[0] == fake.echoed_calls(2)[1][0]]
        self.assertEqual([s["query"] for s in second["searches"]], ["comfortable walking sandals"],
                         "repeat skipped, then only the 4th search fits the cap")
        (_, third), = [m for m in fake.tool_messages(3) if m[0] == fake.echoed_calls(3)[2][0]]
        self.assertIn("limit", third["error"], "a 3rd product call is refused")
        self.assertEqual(trip["essentials"]["queries"], [s["query"] for s in UMRAH_SEARCHES[:4]])

    def test_channel3_with_nothing_found_is_reported(self):
        self.serve(FakeChannel3(ok()))
        fake = FakeGroq([calls(("find_travel_products", {"searches": UMRAH_SEARCHES[:2]})),
                         text(plan_json(None, essentials=[]))])
        with fake.patch():
            trip = self.umrah()
        self.assertEqual(trip["travel_essentials"], [])
        self.assertEqual(trip["essentials"]["status"], "empty")
        self.assertEqual(trip["essentials"]["message"], "No matching products were found.")
        self.assertEqual(trip["essentials"]["missing"], ["Ihram & Clothing", "Modest Clothing"])


def generic_searches(n, start=1):
    return [{"category": f"Category {i}", "query": f"travel item {i}"} for i in range(start, start + n)]


class SixSearchCapTest(_ProductsApi):
    """No trip can run more than 6 unique Channel3 searches, whatever the configuration
    or the model asks for, with the follow-up call sharing the same budget."""

    def setUp(self):
        super().setUp()
        p = mock.patch.object(settings, "CHANNEL3_MAX_QUERIES_PER_TRIP", 50)  # misconfigured on purpose
        p.start()
        self.addCleanup(p.stop)
        self.c3 = self.serve(FakeChannel3(ok(product("g1", "Comfort Walking Sandals"))))

    def run_plan(self, *tool_calls):
        fake = FakeGroq([calls(("find_travel_products", {"searches": s})) for s in tool_calls]
                        + [text(plan_json(None, essentials=[{"product_id": "g1", "category": "Footwear"}]))])
        with fake.patch():
            trip = self.umrah()
        return trip, fake

    def test_default_and_hard_maximum_are_six(self):
        self.assertEqual(Settings.model_fields["CHANNEL3_MAX_QUERIES_PER_TRIP"].default, 6)
        self.assertEqual(channel3_service.MAX_QUERIES_PER_TRIP, 6)
        self.assertEqual(channel3_service.max_queries_per_trip(), 6, "50 is clamped to 6")
        for configured, expected in ((0, 6), (None, 6), (3, 3), (6, 6), (12, 6)):
            with mock.patch.object(settings, "CHANNEL3_MAX_QUERIES_PER_TRIP", configured):
                self.assertEqual(channel3_service.max_queries_per_trip(), expected)

    def test_tool_schema_advertises_six(self):
        from app.agents.tools import AgentToolbox, TripContext
        box = AgentToolbox(TripContext(destination="Makkah, Saudi Arabia", city="Makkah", country="Saudi Arabia",
                                       check_in="2026-12-01", check_out="2026-12-04", nights=3, travelers=2,
                                       purpose="Umrah", stay_preference="Budget stay"), "free", allow_products=True)
        spec = next(t for t in box.openai_tools() if t["function"]["name"] == "find_travel_products")
        self.assertEqual(spec["function"]["parameters"]["properties"]["searches"]["maxItems"], 6)
        self.assertIn("up to 6 searches", spec["function"]["description"])

    def test_one_call_asking_for_more_than_six_runs_six(self):
        trip, fake = self.run_plan(generic_searches(9))
        self.assertEqual(len(self.c3.requests), 6)
        self.assertEqual(trip["essentials"]["queries"], [f"travel item {i}" for i in range(1, 7)])
        (_, result), = fake.tool_messages(1)
        self.assertEqual((len(result["searches"]), result["searches_left"]), (6, 0))

    def test_initial_and_follow_up_searches_share_six(self):
        first = generic_searches(4) + [{"category": "Dup", "query": "TRAVEL  ITEM 1"}]  # repeat: not counted
        follow_up = [{"category": "Again", "query": "travel item 2"}] + generic_searches(5, start=5)
        trip, fake = self.run_plan(first, follow_up, generic_searches(2, start=20))
        self.assertEqual(len(self.c3.requests), 6, "4 initial + 2 follow-up, never more")
        sent = [json.loads(r.content)["query"] for r in self.c3.requests]
        self.assertEqual(len(set(sent)), 6, "all unique")
        self.assertEqual(trip["essentials"]["queries"], [f"travel item {i}" for i in range(1, 7)])
        second = dict(fake.tool_messages(2))[fake.echoed_calls(2)[1][0]]
        self.assertEqual([s["query"] for s in second["searches"]], ["travel item 5", "travel item 6"])
        self.assertEqual(second["searches_left"], 0)
        third = dict(fake.tool_messages(3))[fake.echoed_calls(3)[2][0]]
        self.assertIn("limit", third["error"], "no third product call")

    def test_cached_replay_runs_no_extra_searches(self):
        self.run_plan(generic_searches(9))
        trip, _ = self.run_plan()  # identical request: served from the AI plan cache
        self.assertTrue(trip["ai"]["cached"])
        self.assertEqual(len(self.c3.requests), 6, "replay is read from the Channel3 cache")


# ------------------------------------------------------------- unit rules ---
class TripShoppingRulesTest(unittest.TestCase):

    def test_purpose_detection_never_guesses(self):
        self.assertEqual(trip_shopping.purpose_key("Umrah"), "umrah")
        self.assertEqual(trip_shopping.purpose_key("Other", "Performing Umrah with my mother"), "other",
                         "the chosen purpose is kept; the AI reads the description")
        self.assertEqual(trip_shopping.purpose_key("Other", "Visiting friends"), "other")
        self.assertEqual(trip_shopping.purpose_key("Tourism", "Makkah"), "tourism")

    def test_umrah_guidance_labels_gender_specific_items(self):
        cats = [{"category": c, "audience": a, "searches": s} for c, a, s in trip_shopping.PURPOSE_GUIDANCE["umrah"]]
        audiences = {c["category"]: c["audience"] for c in cats}
        self.assertEqual(audiences["Ihram & Clothing"], "men")
        self.assertEqual(audiences["Modest Clothing"], "women")
        self.assertEqual(audiences["Prayer Essentials"], "all")
        flat = " ".join(s for c in cats for s in c["searches"])
        for need in ("ihram", "abaya", "hijab", "prayer mat", "sandals", "unscented", "shoe bag", "water bottle"):
            self.assertIn(need, flat)
        self.assertNotIn("yoga", flat)

    def test_relevance_guards(self):
        yoga = {"name": "Non Slip Yoga Mat", "description": "Exercise mat"}
        prayer = {"name": "Travel Prayer Mat", "description": None}
        self.assertFalse(trip_shopping.is_relevant("travel prayer mat", yoga))
        self.assertTrue(trip_shopping.is_relevant("travel prayer mat", prayer))
        self.assertFalse(trip_shopping.is_relevant("men's ihram set", {"name": "White Bath Towel Set"}))
        self.assertFalse(trip_shopping.is_relevant("unscented soap", {"name": "Lavender Soap"}))
        self.assertTrue(trip_shopping.is_relevant("unscented soap", {"name": "Soap", "description": "Fragrance-free"}))
        self.assertTrue(trip_shopping.is_relevant("walking sandals", yoga), "no guard for generic searches")

    def test_claim_guard(self):
        towel = {"name": "White Towel Set", "description": "Two cotton towels"}
        self.assertIsNone(trip_shopping.safe_reason("Ihram-compliant towels", towel))
        self.assertIsNone(trip_shopping.safe_reason("Unscented and gentle", towel))
        self.assertEqual(trip_shopping.safe_reason("Two soft towels", towel), "Two soft towels")
        ihram = {"name": "Men's Ihram Towel Set", "description": "Two piece"}
        self.assertEqual(trip_shopping.safe_reason("Two-piece Ihram set", ihram), "Two-piece Ihram set")

    def test_budget_level(self):
        self.assertIsNone(trip_shopping.budget_level(None, 2, 3))
        self.assertEqual(trip_shopping.budget_level(600, 2, 3)["level"], "moderate")
        self.assertEqual(trip_shopping.budget_level(300, 2, 3)["level"], "tight")



class CompactProductPayloadTest(_ProductsApi):

    def test_model_gets_compact_text_and_users_get_full_products(self):
        long_desc = "Soft breathable cotton for long walks in hot weather, easy to pack and machine washable. " * 3
        eur = product("eur1", "Compact Folding Prayer Rug", description=long_desc,
                      brands=[{"id": "e", "name": "Sajada House"}], offers=[{
            "url": "https://shop-eu.example/eur1", "domain": "shop-eu.example",
            "price": {"price": 30.0, "currency": "EUR"}, "availability": "InStock"}])
        self.serve(FakeChannel3(ok(product("usd1", "Travel Prayer Mat", description=long_desc), eur)))
        fake = FakeGroq([calls(("find_travel_products", {"searches": [UMRAH_SEARCHES[2]]})),
                         text(plan_json(None, essentials=[{"product_id": "usd1", "category": "Prayer Essentials"},
                                                          {"product_id": "eur1", "category": "EU Imports"}]))])
        with fake.patch():
            trip = self.umrah(headers=self._premium())
        (_, result), = fake.tool_messages(1)
        self.assertEqual(result["prices_in"], "USD unless a product lists a currency")
        sent = {p["id"]: p for p in result["searches"][0]["products"]}
        self.assertLessEqual(len(sent["usd1"]["about"]), 60)
        self.assertNotIn("currency", sent["usd1"], "USD is stated once, not per product")
        self.assertEqual(sent["eur1"]["currency"], "EUR", "other currencies are kept")
        for key in ("title", "brand", "price", "rating", "reviews", "in_stock", "type"):
            self.assertIn(key, sent["usd1"])
        full = {p["id"]: p for p in trip["travel_essentials"]}
        self.assertEqual(full["usd1"]["description"], long_desc.strip(), "the user sees the full description")
        self.assertEqual((full["usd1"]["price"], full["usd1"]["currency"]), (79.0, "USD"))
        self.assertEqual(full["usd1"]["image_url"], "https://img.example/usd1.jpg")
        self.assertEqual(full["usd1"]["variants"], ["Size: S, L"])
        self.assertEqual(full["usd1"]["purchase_url"], "https://shop-a.example/usd1")
        self.assertEqual((full["eur1"]["price"], full["eur1"]["currency"]), (30.0, "EUR"))

    def test_default_is_five_results_per_search(self):
        self.assertEqual(Settings.model_fields["CHANNEL3_RESULTS_PER_QUERY"].default, 5)
        names = ["Comfort Walking Sandals", "Arch Support Slide", "Trail Sport Sandal", "Leather Slip-On Sandal",
                 "Cushioned Flip Flop", "Water Shoe", "Strappy Sandal"]
        c3 = self.serve(FakeChannel3(ok(*[product(f"s{i}", n) for i, n in enumerate(names)])))
        fake = FakeGroq([calls(("find_travel_products", {"searches": [UMRAH_SEARCHES[3]]})),
                         text(plan_json(None, essentials=[]))])
        with fake.patch(), mock.patch.object(settings, "CHANNEL3_RESULTS_PER_QUERY", None):
            self.umrah()
        self.assertEqual(json.loads(c3.requests[0].content)["limit"], 5)
        (_, result), = fake.tool_messages(1)
        self.assertEqual(len(result["searches"][0]["products"]), 5)

    def test_umrah_guidance_still_covers_men_women_and_all(self):
        fake = FakeGroq([text(plan_json(None))])
        with fake.patch():
            self.umrah()
        cats = prompt_parts(fake.requests[0])["shopping"]["fallback_categories"]
        self.assertEqual(cats[:2], ["Ihram & Clothing", "Modest Clothing"], "men's and women's items both offered")
        self.assertEqual(prompt_parts(fake.requests[0])["shopping"]["max_searches"], 6)


# ------------------------------------------------- quantity, diversity, duplicates ---
CATEGORY_PRODUCTS = {
    "Rain Gear": ["Compact Travel Umbrella", "Packable Rain Poncho", "Waterproof Shell Jacket",
                  "Rain Boot Covers", "Waterproof Dry Bag"],
    "Footwear": ["Comfort Walking Sandals", "Trail Running Shoe", "Cushioned Slip-On Loafer",
                 "Hiking Ankle Boot", "Canvas Slip-On Sneaker"],
    "Power": ["Universal Travel Adapter", "Portable Power Bank", "USB-C Charging Cable",
              "Compact Wall Charger", "Cable Organizer Case"],
    "Bags": ["Lightweight Daypack", "Anti-Theft Crossbody Bag", "Packing Cubes Trio",
             "Drawstring Shoe Bag", "Hanging Toiletry Bag"],
    "Comfort": ["Memory Foam Neck Pillow", "Silk Sleep Mask", "Foam Ear Plugs",
                "Compression Travel Socks", "Inflatable Lumbar Cushion"],
    "Hydration": ["Insulated Water Bottle", "Collapsible Silicone Bottle", "Water Filter Straw",
                  "Electrolyte Drink Tablets", "Stainless Travel Mug"],
}
SEARCHES = [{"category": c, "query": f"best {c.lower()} for travel"} for c in CATEGORY_PRODUCTS]


def category_channel3():
    """Distinct brands, like real results (the shared default brand would trip the brand limit)."""
    return FakeChannel3(*[ok(*[product(f"{c[:3].lower()}{i}", name, brands=[{"id": f"b{c}{i}", "name": f"Maker {c} {'ABCDE'[i]}x"}],
                               category={"slug": "t", "title": name, "path": [], "has_children": False})
                               for i, name in enumerate(names)])
                          for c, names in CATEGORY_PRODUCTS.items()])


def picks_for(per_category):
    """The model picks the first `n` products of each category, in category order."""
    out = []
    for c, names in CATEGORY_PRODUCTS.items():
        for i in range(per_category.get(c, 0)):
            out.append({"product_id": f"{c[:3].lower()}{i}", "category": c, "reason": f"Useful {names[i].lower()}."})
    return out


class ProductQuantityAndDiversityTest(_ProductsApi):

    def plan(self, picks, headers=None, searches=SEARCHES, c3=None, **over):
        self.c3 = self.serve(c3 or category_channel3())
        self.fake = FakeGroq([calls(("find_travel_products", {"searches": searches})),
                              text(plan_json(None, essentials=picks))])
        with self.fake.patch(), mock.patch.object(settings, "CHANNEL3_RESULTS_PER_QUERY", 5):
            return self.umrah(headers=headers, purpose="Tourism", notes="A short trip.", **over)

    def test_at_least_ten_products_across_categories_for_premium(self):
        trip = self.plan(picks_for({c: 3 for c in CATEGORY_PRODUCTS}), headers=self._premium())
        items = trip["travel_essentials"]
        self.assertGreaterEqual(len(items), 10)
        self.assertEqual(len(items), 18, "6 categories x 3")
        self.assertEqual(len({p["group"] for p in items}), 6, "spread over every category")
        self.assertEqual(len(self.c3.requests), 6, "six searches, one credit each")
        (_, result), = self.fake.tool_messages(1)
        self.assertEqual(sum(len(s["products"]) for s in result["searches"]), 30, "5 candidates per search")
        self.assertTrue(all(p["purchase_url"] for p in items), "Premium: genuine retailer links")
        self.assertTrue(all(p["purchase_url"].startswith("https://shop-a.example/") for p in items))

    def test_free_users_get_the_same_products_without_links(self):
        trip = self.plan(picks_for({c: 2 for c in CATEGORY_PRODUCTS}))
        items = trip["travel_essentials"]
        self.assertEqual(len(items), 12)
        for p in items:
            self.assertIsNone(p["purchase_url"])
            self.assertTrue(all(o["url"] is None for o in p["offers"]))
            self.assertTrue(p["image_url"] and p["name"] and p["brand"] and p["price"] is not None)

    def test_one_category_cannot_crowd_out_the_others(self):
        picks = picks_for({"Rain Gear": 5, **{c: 1 for c in list(CATEGORY_PRODUCTS)[1:]}})
        trip = self.plan(picks)
        groups = [p["group"] for p in trip["travel_essentials"]]
        self.assertEqual(groups.count("Rain Gear"), 3, "at most 3 per category when there are many categories")
        self.assertEqual(len(groups), 8)

    def test_few_categories_are_not_padded_to_reach_ten(self):
        trip = self.plan(picks_for({"Rain Gear": 5, "Footwear": 5}))
        groups = [p["group"] for p in trip["travel_essentials"]]
        self.assertEqual((groups.count("Rain Gear"), groups.count("Footwear")), (2, 2),
                         "two categories can't fill the list for the four missing ones")
        self.assertEqual(set(trip["essentials"]["missing"]), {"Power", "Bags", "Comfort", "Hydration"})

    def test_fewer_than_ten_relevant_shows_what_exists(self):
        trip = self.plan(picks_for({"Footwear": 2, "Power": 2}))
        self.assertEqual(len(trip["travel_essentials"]), 4)
        self.assertEqual(trip["essentials"]["status"], "ok", "no filler, still a valid result")
        self.assertEqual(set(trip["essentials"]["missing"]), {"Rain Gear", "Bags", "Comfort", "Hydration"})

    def test_near_identical_and_repeated_products_are_removed(self):
        cream = lambda pid, pack: product(pid, f"Neutrogena Hand Cream Unscented Travel Size 1.69 oz ({pack}-Pack)",
                                          brands=[{"id": "n", "name": "Neutrogena"}])
        other_brand = product("eu1", "Hand Cream Unscented Travel Size", brands=[{"id": "e", "name": "Eucerin"}])
        c3 = FakeChannel3(ok(cream("hc3", 3), cream("hc6", 6), other_brand), ok(cream("hc3", 3), product("x1", "Lip Balm")))
        searches = [{"category": "Personal Care", "query": "unscented hand cream"},
                    {"category": "Lip Care", "query": "unscented lip balm unscented"}]
        trip = self.plan([{"product_id": i, "category": "Personal Care"} for i in ("hc3", "hc6", "eu1")]
                         + [{"product_id": "x1", "category": "Lip Care"}], searches=searches, c3=c3)
        (_, result), = self.fake.tool_messages(1)
        first, second = result["searches"]
        self.assertEqual([p["id"] for p in first["products"]], ["hc3", "eu1"], "6-pack = same item; other brand shown")
        self.assertEqual(second["products"], [], "already shown, and lip balm isn't unscented by its data")
        self.assertEqual([p["id"] for p in trip["travel_essentials"]], ["hc3"],
                         "two near-identical hand creams in one category: only the first is recommended")

    def test_a_category_with_products_is_not_searched_again(self):
        c3 = category_channel3()
        self.c3 = self.serve(c3)
        fake = FakeGroq([
            calls(("find_travel_products", {"searches": SEARCHES[:2]})),
            calls(("find_travel_products", {"searches": [{"category": "Rain Gear", "query": "golf umbrella"},
                                                         {"category": "Power", "query": "power bank"}]})),
            text(plan_json(None, essentials=picks_for({"Rain Gear": 2, "Power": 2})))])
        with fake.patch(), mock.patch.object(settings, "CHANNEL3_RESULTS_PER_QUERY", 5):
            trip = self.umrah(purpose="Tourism", notes="A short trip.")
        self.assertEqual(len(self.c3.requests), 3, "the second Rain Gear search was refused, no credit used")
        second = dict(fake.tool_messages(2))[fake.echoed_calls(2)[1][0]]
        self.assertEqual([s["query"] for s in second["searches"]], ["power bank"])
        self.assertEqual(second["skipped"][0]["query"], "golf umbrella")
        self.assertIn("already has products", second["skipped"][0]["reason"])
        self.assertEqual(trip["essentials"]["queries"], ["best rain gear for travel", "best footwear for travel",
                                                         "power bank"])

    def test_cached_plan_keeps_the_products_and_spends_no_credit(self):
        headers = self._premium()
        first = self.plan(picks_for({c: 2 for c in CATEGORY_PRODUCTS}), headers=headers)
        with self.fake.patch(), mock.patch.object(settings, "CHANNEL3_RESULTS_PER_QUERY", 5):
            again = self.umrah(headers=headers, purpose="Tourism", notes="A short trip.")
        self.assertTrue(again["ai"]["cached"])
        self.assertEqual(again["travel_essentials"], first["travel_essentials"])
        self.assertEqual(len(self.c3.requests), 6, "replay served from the Channel3 cache")

    def test_prompt_asks_for_ten_diverse_products(self):
        fake = FakeGroq([text(plan_json(None))])
        with fake.patch():
            self.umrah()
        system = fake.requests[0]["messages"][0]["content"]
        self.assertIn("at least 10", system)
        self.assertIn("DIFFERENT kind of item", system)
        self.assertEqual(prompt_parts(fake.requests[0])["shopping"]["target_products"], 10)


class DuplicateRulesTest(unittest.TestCase):

    def test_near_duplicate_rules(self):
        a = {"id": "1", "name": "Neutrogena Hand Cream, Unscented, 1.69 oz (3-Pack)", "brand": "Neutrogena"}
        self.assertTrue(trip_shopping.is_near_duplicate(a, {"id": "2", "name": "Neutrogena Hand Cream Unscented 6 Pack",
                                                            "brand": "Neutrogena"}))
        self.assertTrue(trip_shopping.is_near_duplicate({"id": "p", "name": "Packing Cubes Set"},
                                                        {"id": "q", "name": "Packing Cubes Set"}))
        self.assertTrue(trip_shopping.is_near_duplicate({"id": "c1", "name": "Rain Poncho Black"},
                                                        {"id": "c2", "name": "Rain Poncho - Navy Blue"}))
        self.assertFalse(trip_shopping.is_near_duplicate({"id": "s", "name": "Samsonite 3pc. Packing Cubes",
                                                          "brand": "Samsonite"},
                                                         {"id": "c", "name": "Calpak Packing Cubes Set",
                                                          "brand": "Calpak"}), "other brand = real choice")
        self.assertFalse(trip_shopping.is_near_duplicate({"id": "u", "name": "Compact Travel Umbrella"},
                                                         {"id": "r", "name": "Packable Rain Poncho"}))

    def test_per_category_cap(self):
        from app.agents.travel_agent import _per_category_cap
        self.assertEqual([_per_category_cap(n) for n in (1, 2, 3, 4, 6)], [2, 2, 2, 3, 3])


if __name__ == "__main__":
    unittest.main()
