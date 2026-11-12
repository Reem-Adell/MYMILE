"""
Regression tests for: product relevance & unsupported claims, audience classification,
the Premium budget allocation terms, and MYMILE's application logging (Groq usage).
Product examples are the real Channel3 results from the 2026-11-11 Umrah investigation.

Run from backend/:
    venv\\Scripts\\python -m unittest tests.test_quality_improvements -v
No real Groq or Channel3 requests.
"""
from tests import _env  # noqa: F401  (must precede any app.* import)

import io
import json
import logging
import unittest
from types import SimpleNamespace
from unittest import mock

from app.agents import groq_client
from app.core import logging_config
from app.core.config import Settings
from app.services import trip_shopping
from app.services.budget_service import optimize_budget
from tests._fake_groq import KEY, FakeGroq, calls, text
from tests.test_channel3 import FakeChannel3, ok, product
from tests.test_gemini_agent import plan_json
from tests.test_trip_products import _ProductsApi

# Real results (title, description, Channel3 category) from the investigation.
PIMA = {"name": "Pima Mini Abaya", "category": "Cover Ups",
        "description": "The Pima Mini Abaya by Pitusa is an effortlessly elegant beach cover-up, perfect for resort days."}
ALINE = {"name": "A-Line Sundress Muslim Abaya", "category": "Dresses",
         "description": "Package included:1 Dress Material:95% Polyester+5% Spandex Colors:Black"}
REEM = {"name": "Reem Long Blazer", "category": "Blazers",
        "description": "The Reem Long Blazer Abaya is a minimal and architectural piece designed for layering."}
YOGA = {"name": "Travel Yoga Mat", "category": "Yoga & Pilates Mats",
        "description": "A portable and lightweight yoga mat designed for travel, featuring a non-slip surface."}
PLAY = {"name": "Play-Anywhere Travel Mat", "category": "Play Mats",
        "description": "The Dreambaby Play-Anywhere Travel Mat is a portable, double-sided play mat."}
HAND_CREAM = {"name": "Neutrogena Concentrated Hand Cream, Unscented, Norwegian Formula, Travel Size",
              "category": "Hand Creams", "description": "Soothe and protect dry hands."}
BATH_WRAP = {"name": "2 Pcs Men's Bath Wrap Towel Adjustable Robes With Hair Dry Cap", "category": "Bath Towels",
             "description": "A two-piece men's bath wrap towel set featuring adjustable waist."}
IHRAM = {"name": "Men's Ihram Towel Set 2 Piece Cotton for Hajj and Umrah", "category": "Ihram Clothing",
         "description": "Two white cotton towels with a belt."}
WALK_SANDAL = {"name": "Women's Go Walk Arch Fit 2.0 Sport Sandal", "category": "Sandals",
               "description": "Experience ultimate comfort and support."}


class RelevanceTest(unittest.TestCase):
    ABAYA = "women's abaya for umrah"

    def test_beach_cover_up_is_not_an_abaya(self):
        self.assertFalse(trip_shopping.is_relevant(self.ABAYA, PIMA))
        self.assertFalse(trip_shopping.is_relevant(self.ABAYA, {"name": "Pima Mini Abaya"}),
                         "'mini abaya' alone contradicts the category")

    def test_a_line_muslim_abaya_is_kept_but_claims_stay_conservative(self):
        self.assertTrue(trip_shopping.is_relevant(self.ABAYA, ALINE), "its title says abaya; nothing contradicts")
        self.assertIsNone(trip_shopping.safe_reason("Modest abaya suitable for Umrah.", ALINE),
                          "no 'modest' or 'Umrah' in its data")
        self.assertIsNone(trip_shopping.safe_reason("Comfortable for long prayers.", ALINE))
        self.assertEqual(trip_shopping.safe_reason("Black polyester-spandex abaya.", ALINE),
                         "Black polyester-spandex abaya.")
        self.assertTrue(trip_shopping.is_relevant(self.ABAYA, REEM), "its description names it an abaya")

    def test_genuine_ihram_is_accepted_and_bath_wraps_are_not(self):
        self.assertTrue(trip_shopping.is_relevant("men's two piece ihram towel set", IHRAM))
        self.assertEqual(trip_shopping.safe_reason("Two-piece cotton Ihram set for Umrah.", IHRAM),
                         "Two-piece cotton Ihram set for Umrah.")
        self.assertFalse(trip_shopping.is_relevant("men's two piece ihram towel set", BATH_WRAP))
        self.assertFalse(trip_shopping.is_relevant("men's ihram garment",
                                                   {"name": "Men's Arab Sheikh Ihram Costume"}))

    def test_yoga_and_play_mats_are_not_prayer_mats(self):
        for mat in (YOGA, PLAY):
            self.assertFalse(trip_shopping.is_relevant("travel prayer mat", mat))
        self.assertTrue(trip_shopping.is_relevant("travel prayer mat", {"name": "Travel Prayer Mat"}),
                        "a valid product with no description is kept")
        self.assertIsNone(trip_shopping.safe_reason("Use it to pray anywhere.", YOGA))

    def test_unscented_claims_need_product_evidence(self):
        self.assertTrue(trip_shopping.is_relevant("unscented travel toiletries", HAND_CREAM))
        self.assertEqual(trip_shopping.safe_reason("Unscented hand cream without fragrance.", HAND_CREAM),
                         "Unscented hand cream without fragrance.")
        lavender = {"name": "Lavender Hand Lotion", "description": "Calming scent"}
        self.assertFalse(trip_shopping.is_relevant("unscented travel toiletries", lavender))
        self.assertIsNone(trip_shopping.safe_reason("Unscented and gentle.", lavender))

    def test_religious_trip_searches_reject_beachwear_and_costumes(self):
        q = "lightweight modest dress for umrah"
        self.assertFalse(trip_shopping.is_relevant(q, {"name": "Beach Cover-Up Maxi Dress"}))
        self.assertFalse(trip_shopping.is_relevant("hijab with underscarf set", {"name": "Risha Swim Hijab"}))
        self.assertTrue(trip_shopping.is_relevant(q, {"name": "Linen Maxi Dress, Long Sleeve"}))

    def test_other_unsupported_claims(self):
        towel = {"name": "White Towel Set", "description": "Two cotton towels"}
        for claim in ("Halal certified towels.", "Sharia compliant set.", "Approved for pilgrims.",
                      "Ideal Islamic travel gear.", "Ihram-ready towels."):
            self.assertIsNone(trip_shopping.safe_reason(claim, towel), claim)
        self.assertEqual(trip_shopping.safe_reason("Two soft cotton towels.", towel), "Two soft cotton towels.")


class AudienceTest(unittest.TestCase):

    def test_explicit_audience_terms(self):
        cases = [(WALK_SANDAL, "women"), ({"name": "Men's Trail Sandal"}, "men"), ({"name": "Unisex Slide"}, "all"),
                 ({"name": "Go Walk Flex Sandals Emma"}, None), ({"name": "Men's and Women's Socks"}, "all"),
                 ({"name": "Women’s Linen Scarf"}, "women"), ({"name": "Female Travel Robe"}, "women"),
                 ({"name": "Male Grooming Kit"}, "men"), ({"name": "Batman Tee"}, None),
                 ({"name": "Ladies Prayer Dress"}, "women"), ({"name": "Sandal", "category": "Men's Sandals"}, "men")]
        for prod, expected in cases:
            self.assertEqual(trip_shopping.infer_audience(prod), expected, prod["name"])


class AudienceThroughAgentTest(_ProductsApi):

    def test_product_evidence_beats_search_label_and_model_guess(self):
        sandal = product("w1", "Women's Go Walk Arch Fit 2.0 Sport Sandal", brands=[{"id": "s", "name": "Skechers"}])
        plain_men = product("m1", "Ihram Towel Set 2 Piece")
        womens_in_mens = product("w2", "Women's Ihram-Style White Shawl Ihram")
        unknown = product("u1", "Cloudsteppers Sunmaze Bali Sandal", brands=[{"id": "c", "name": "Clarks"}])
        self.serve(FakeChannel3(ok(womens_in_mens, plain_men), ok(sandal, unknown)))
        picks = [{"product_id": "w1", "category": "Footwear", "audience": "all"},
                 {"product_id": "u1", "category": "Footwear", "audience": "women"},
                 {"product_id": "m1", "category": "Ihram & Clothing", "audience": "all"},
                 {"product_id": "w2", "category": "Ihram & Clothing", "audience": "men"}]
        fake = FakeGroq([calls(("find_travel_products", {"searches": [
            {"category": "Ihram & Clothing", "query": "men's ihram set", "audience": "men"},
            {"category": "Footwear", "query": "comfortable walking sandals", "audience": "all"}]})),
            text(plan_json(None, essentials=picks))])
        with fake.patch():
            trip = self.umrah()
        got = {p["id"]: p["audience"] for p in trip["travel_essentials"]}
        self.assertEqual(got, {"w1": "women", "u1": "all", "m1": "men", "w2": "women"})
        (_, result), = fake.tool_messages(1)
        sent = {p["id"]: p for s in result["searches"] for p in s["products"]}
        self.assertEqual(sent["w1"].get("for"), "women", "the model sees the stated audience")
        self.assertNotIn("for", sent["u1"])


class BudgetAllocationTermsTest(unittest.TestCase):

    def budget(self, total, hotel, days=5, people=2):
        return optimize_budget(destination="Makkah, Saudi Arabia", duration_days=days, travelers=people,
                               total_budget=total, selected_hotel_total=hotel, stay_preference="Budget stay",
                               plan="premium").breakdown

    def assert_consistent(self, b, total):
        categories = b.food + b.transportation + b.activities + b.travel_essentials + b.contingency_and_other
        self.assertAlmostEqual(b.allocated_total, round(b.accommodation + categories, 2), places=2)
        self.assertEqual(b.allocated_total, b.total_estimated, "same number, clearer name")
        self.assertAlmostEqual(b.unallocated_budget, round(total - b.allocated_total, 2), places=2)
        self.assertEqual(b.unallocated_budget, b.remaining_balance, "backward compatible")
        self.assertEqual(b.allocation_mode, "allocated")
        self.assertEqual(b.user_budget, total)

    def test_hotel_below_75_percent_is_fully_allocated(self):
        b = self.budget(3000, 1000)
        self.assert_consistent(b, 3000)
        self.assertEqual((b.unallocated_budget, b.fully_allocated, b.status), (0, True, "balanced"))
        self.assertIn("planned limits, not a forecast", b.allocation_note)

    def test_hotel_at_75_percent(self):
        b = self.budget(3000, 2250)
        self.assert_consistent(b, 3000)
        self.assertEqual((b.unallocated_budget, b.fully_allocated), (0, True))

    def test_hotel_above_75_percent_can_be_over_allocated(self):
        b = self.budget(3000, 2700)
        self.assert_consistent(b, 3000)
        self.assertLess(b.unallocated_budget, 0)
        self.assertFalse(b.fully_allocated)
        self.assertEqual(b.status, "over_budget")
        self.assertIn("exceed your budget by USD", b.allocation_note)

    def test_hotel_above_75_percent_without_minimums_binding(self):
        b = self.budget(3000, 2300, days=1, people=1)
        self.assert_consistent(b, 3000)
        self.assertEqual(b.unallocated_budget, 0)

    def test_no_budget_is_an_estimate_not_an_allocation(self):
        b = optimize_budget(destination="Makkah", duration_days=3, travelers=1, plan="premium").breakdown
        self.assertEqual((b.allocation_mode, b.unallocated_budget, b.allocated_total), ("estimated", None, None))
        self.assertIn("no budget was set", b.allocation_note)


class BudgetThroughApiTest(_ProductsApi):

    def test_premium_plan_carries_the_allocation_terms_and_free_gets_none(self):
        prem = self.umrah(headers=self._premium(), total_budget=3000)
        b = prem["budget_breakdown"]
        self.assertEqual(b["allocation_mode"], "allocated")
        self.assertEqual(b["allocated_total"], b["total_estimated"])
        self.assertEqual(b["unallocated_budget"], b["remaining_balance"])
        self.assertAlmostEqual(b["unallocated_budget"], round(3000 - b["allocated_total"], 2), places=2)
        self.assertIsNone(self.umrah(total_budget=3000)["budget_breakdown"], "Free: no Premium budget")


class AppLoggingTest(unittest.TestCase):

    def setUp(self):
        self.logger = logging.getLogger("app")
        self.saved = (list(self.logger.handlers), self.logger.level, list(logging.getLogger().handlers))
        self.logger.handlers = [h for h in self.logger.handlers if h.get_name() != logging_config.HANDLER_NAME]
        logging.getLogger().handlers = []

    def tearDown(self):
        handlers, level, root_handlers = self.saved
        self.logger.handlers, self.logger.level = handlers, level
        logging.getLogger().handlers = root_handlers

    def test_default_level_is_info(self):
        self.assertEqual(Settings.model_fields["LOG_LEVEL"].default, "INFO")

    def test_groq_usage_info_is_printed_once_and_secrets_are_masked(self):
        stream = io.StringIO()
        handler = logging_config.configure_logging("INFO", stream)
        self.assertIs(logging_config.configure_logging("INFO", stream), handler, "idempotent")
        self.assertEqual([h.get_name() for h in self.logger.handlers].count(logging_config.HANDLER_NAME), 1)

        fake = FakeGroq([text("{}")])
        fake.usage = SimpleNamespace(prompt_tokens=2063, completion_tokens=1650, total_tokens=3713,
                                     prompt_tokens_details=SimpleNamespace(cached_tokens=1900),
                                     completion_tokens_details=SimpleNamespace(reasoning_tokens=240))
        with fake.patch():
            from tests.test_explore_trip import run
            run(groq_client.generate([{"role": "user", "content": "secret prompt text"}], purpose="round 2"))
        logging.getLogger("app.agents.test").info("leak check %s Bearer abc.def org_ABC123", KEY)
        out = stream.getvalue()
        line = next(l for l in out.splitlines() if "Groq usage" in l)
        for part in ("INFO:", "app.agents.groq_client", "prompt=2063", "completion=1650", "total=3713",
                     "cached=1900", "reasoning=240", "finish=stop"):
            self.assertIn(part, line)
        self.assertEqual(out.count("Groq usage"), 1, "no duplicate lines")
        for secret in (KEY, "secret prompt text", "abc.def", "org_ABC123"):
            self.assertNotIn(secret, out)

    def test_no_second_handler_when_root_already_prints(self):
        logging.getLogger().handlers = [logging.NullHandler()]
        self.assertIsNone(logging_config.configure_logging("INFO"))
        self.assertFalse([h for h in self.logger.handlers if h.get_name() == logging_config.HANDLER_NAME])
        self.assertEqual(self.logger.level, logging.INFO)

    def test_bad_level_falls_back_to_info(self):
        logging_config.configure_logging("loud", io.StringIO())
        self.assertEqual(self.logger.level, logging.INFO)

    def test_uvicorn_loggers_are_untouched(self):
        before = [(n, list(logging.getLogger(n).handlers)) for n in ("uvicorn", "uvicorn.access")]
        logging_config.configure_logging("INFO", io.StringIO())
        self.assertEqual(before, [(n, list(logging.getLogger(n).handlers)) for n in ("uvicorn", "uvicorn.access")])


if __name__ == "__main__":
    unittest.main()
