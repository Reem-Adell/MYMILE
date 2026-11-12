"""
Gemini travel agent: real function calling over backend services, validated AI
output, clearly labelled fallbacks, caching, limits, Free/Premium rules, no key
leakage.

Run from backend/:
    venv\\Scripts\\python -m unittest tests.test_gemini_agent -v
No real Gemini, SerpApi or weather requests: all are mocked.
"""
from tests import _env  # noqa: F401  (must precede any app.* import)

import asyncio
import json
import logging
import unittest
from contextlib import closing
from types import SimpleNamespace
from unittest import mock

from google.genai import errors

from app.agents import agent_loop, gemini_client, tools, travel_agent
from app.agents.tools import AgentToolbox, TripContext
from app.core.config import settings
from app.schemas.weather_schema import WeatherForecastDay, WeatherResponse
from tests._fake_gemini import FakeGemini, calls, error, text
from tests.test_explore_trip import TRIP, _Api, run

KEY = "AIza-test-SECRET-gemini-key-000"


async def live_weather(*args, **kwargs):
    return WeatherResponse(destination="Cairo, Egypt", latitude=30.0, longitude=31.2, current_temp_c=24.0,
                           current_condition="Clear sky", packing_tip="Light layers.",
                           forecast=[WeatherForecastDay(date="2026-12-01", condition="Clear sky", temp_min_c=14,
                                                        temp_max_c=24, temp_min_f=57, temp_max_f=75,
                                                        precipitation_prob=5)],
                           source="Open-Meteo Live API")


def plan_json(hotel_id="cai-03", days=3, **over):
    return {"summary": "Three relaxed museum days in Cairo.",
            "why_recommended": "The Nile Ritz-Carlton is next to the Egyptian Museum, matching your museum priority.",
            "recommended_hotel_id": hotel_id,
            "itinerary": [{"day_number": n, "theme": f"AI day {n}",
                           "activities": [{"time": "09:00 AM", "title": f"Activity {n}", "description": "d",
                                           "location": "Cairo", "icon": "pin", "cost_estimate": 12}]}
                          for n in range(1, days + 1)], **over}


def clear_plan_cache():
    with closing(travel_agent._plan_cache_db()) as conn:
        conn.execute("DELETE FROM ai_plan_cache")
        conn.commit()


class _AgentApi(_Api):
    def setUp(self):
        super().setUp()
        clear_plan_cache()
        for p in (mock.patch.object(tools, "get_weather_forecast", side_effect=live_weather),
                  mock.patch.object(travel_agent, "get_weather_forecast", side_effect=live_weather)):
            p.start()
            self.addCleanup(p.stop)

    def cairo(self, headers=None, **over):
        return self._plan(headers=headers, destination_city="Cairo", destination_country="Egypt",
                          priorities=["Museums"], notes="I love museums", **over)


# ------------------------------------------------------------- client ---
class GeminiClientTest(unittest.TestCase):

    def test_availability_and_model_resolution(self):
        with mock.patch.object(settings, "GEMINI_API_KEY", ""):
            with self.assertRaises(gemini_client.GeminiError) as ctx:
                gemini_client.check_available()
            self.assertEqual(ctx.exception.code, "NOT_CONFIGURED")
        with mock.patch.object(settings, "GEMINI_API_KEY", KEY), mock.patch.object(settings, "LLM_PROVIDER", "openai"):
            with self.assertRaises(gemini_client.GeminiError) as ctx:
                gemini_client.check_available()
            self.assertEqual(ctx.exception.code, "UNSUPPORTED_PROVIDER")
        for name, expected in (("", "gemini-3.8-flash"), ("gemini-1.5-flash", "gemini-3.8-flash"),
                               ("gemini-2.5-pro", "gemini-2.5-pro")):
            with mock.patch.object(settings, "LLM_MODEL_NAME", name):
                self.assertEqual(gemini_client.resolve_model(), expected)

    def _client(self, behaviour, captured):
        async def generate_content(**kwargs):
            captured.update(kwargs)
            if isinstance(behaviour, BaseException):
                raise behaviour
            return behaviour
        return SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate_content)))

    def _generate(self, behaviour, captured=None, **kw):
        captured = {} if captured is None else captured
        with mock.patch.object(settings, "GEMINI_API_KEY", KEY), \
             mock.patch.object(gemini_client, "_make_client", return_value=self._client(behaviour, captured)):
            return run(gemini_client.generate(["hi"], "sys", **kw))

    def test_request_uses_configured_model_and_manual_tool_execution(self):
        from google.genai import types
        captured = {}
        ok = SimpleNamespace(candidates=[object()], function_calls=None, text="{}")
        tool = types.Tool(function_declarations=[types.FunctionDeclaration(name="t", description="d")])
        with mock.patch.object(settings, "LLM_MODEL_NAME", "gemini-3.8-flash"):
            self.assertIs(self._generate(ok, captured, tools=[tool]), ok)
        self.assertEqual(captured["model"], "gemini-3.8-flash")
        cfg = captured["config"]
        self.assertTrue(cfg.automatic_function_calling.disable, "our loop executes tools, not the SDK")
        self.assertEqual(cfg.system_instruction, "sys")
        self.assertEqual(cfg.tools[0].function_declarations[0].name, "t")
        self.assertIsNone(cfg.response_mime_type, "JSON mode is never combined with tools")
        # Deprecated from Gemini 3.6 Flash onward ("Remove these parameters from all requests").
        self.assertEqual((cfg.temperature, cfg.top_p, cfg.top_k), (None, None, None))

    def test_default_model_is_gemini_3_8_flash(self):
        self.assertEqual(gemini_client.DEFAULT_MODEL, "gemini-3.8-flash")
        self.assertEqual(type(settings).model_fields["LLM_MODEL_NAME"].default, "gemini-3.8-flash")

    def test_timeout_and_thinking_defaults(self):
        fields = type(settings).model_fields
        self.assertEqual((fields["GEMINI_TIMEOUT_SECONDS"].default, fields["AI_AGENT_DEADLINE_SECONDS"].default,
                          fields["GEMINI_THINKING_LEVEL"].default), (90.0, 180.0, "low"))

    def test_thinking_level_is_sent_and_configurable(self):
        ok = SimpleNamespace(candidates=[object()], function_calls=None, text="{}")
        for configured, expected in (("low", "LOW"), ("HIGH", "HIGH"), ("", None), ("turbo", None)):
            captured = {}
            with mock.patch.object(settings, "GEMINI_THINKING_LEVEL", configured):
                self._generate(ok, captured)
            cfg = captured["config"].thinking_config
            if expected is None:
                self.assertIsNone(cfg, configured)
            else:
                self.assertEqual(cfg.thinking_level.value, expected)
                self.assertIsNone(cfg.thinking_budget, "thinking_budget is replaced by thinking_level")

    def test_client_uses_configured_timeout_and_never_retries(self):
        from google import genai
        with mock.patch.object(settings, "GEMINI_API_KEY", KEY), \
             mock.patch.object(settings, "GEMINI_TIMEOUT_SECONDS", 90.0), \
             mock.patch.object(genai, "Client") as client_cls:
            gemini_client._make_client()
        options = client_cls.call_args.kwargs["http_options"]
        self.assertEqual(options.timeout, 90000, "ms; the SDK also sends it as X-Server-Timeout")
        self.assertEqual(options.retry_options.attempts, 1)

    def test_transport_errors_of_any_http_library_are_mapped(self):
        import aiohttp
        for exc, code in ((aiohttp.ClientConnectionError("down"), "NETWORK"),
                          (ConnectionResetError("reset"), "NETWORK"),
                          (RuntimeError("unexpected"), "SERVICE_ERROR")):
            with self.assertRaises(gemini_client.GeminiError) as ctx:
                self._generate(exc)
            self.assertEqual(ctx.exception.code, code, type(exc).__name__)
            self.assertIsNone(ctx.exception.__cause__)

    def test_invalid_request_settings_are_reported_as_bad_request(self):
        exc = errors.ClientError(400, {"error": {"code": 400, "message": "Unsupported thinking level",
                                                 "status": "INVALID_ARGUMENT"}})
        with self.assertRaises(gemini_client.GeminiError) as ctx:
            self._generate(exc)
        self.assertEqual(ctx.exception.code, "BAD_REQUEST")

    def test_errors_are_mapped_to_clear_key_free_codes(self):
        cases = [
            (errors.ClientError(429, {"error": {"code": 429, "message": "Quota exceeded", "status": "RESOURCE_EXHAUSTED"}}),
             "QUOTA_EXHAUSTED"),
            (errors.ClientError(400, {"error": {"code": 400, "message": f"API key not valid: {KEY}",
                                                "status": "INVALID_ARGUMENT"}}), "INVALID_API_KEY"),
            (errors.ClientError(404, {"error": {"code": 404, "message": "models/x is not found", "status": "NOT_FOUND"}}),
             "MODEL_UNAVAILABLE"),
            (errors.ServerError(503, {"error": {"code": 503, "message": "overloaded", "status": "UNAVAILABLE"}}),
             "SERVICE_ERROR"),
            (asyncio.TimeoutError(), "TIMEOUT"),
        ]
        for exc, code in cases:
            with self.assertRaises(gemini_client.GeminiError) as ctx:
                self._generate(exc)
            self.assertEqual(ctx.exception.code, code)
            self.assertNotIn(KEY, str(ctx.exception))
            self.assertIsNone(ctx.exception.__cause__, "no chained provider text")

    def test_blocked_or_empty_response(self):
        blocked = SimpleNamespace(candidates=[], prompt_feedback=SimpleNamespace(block_reason="SAFETY"))
        with self.assertRaises(gemini_client.GeminiError) as ctx:
            self._generate(blocked)
        self.assertEqual(ctx.exception.code, "BLOCKED")

    def test_health_description_has_no_key(self):
        with mock.patch.object(settings, "GEMINI_API_KEY", KEY):
            info = gemini_client.describe()
        self.assertEqual(info["status"], "configured")
        self.assertNotIn(KEY, json.dumps(info))


# ----------------------------------------------------------- planning ---
class AiTripPlanningTest(_AgentApi):

    def test_gemini_calls_real_tools_and_its_plan_is_used(self):
        fake = FakeGemini([calls(("get_weather_forecast", {}), ("search_hotels", {})),
                           text(plan_json("cai-03"))])
        with fake.patch():
            trip = self.cairo()
        self.assertEqual(trip["ai"]["generated_by"], "gemini")
        self.assertEqual(trip["ai"]["tools_used"], ["get_weather_forecast", "search_hotels"])
        self.assertIsNone(trip["match_score"], "no fabricated score")
        self.assertEqual(trip["destination_summary"], "Three relaxed museum days in Cairo.")
        self.assertEqual(trip["recommended_hotel"]["id"], "cai-03")
        self.assertTrue(trip["recommended_hotel"]["is_best_match"])
        self.assertEqual(sum(h["is_best_match"] for h in trip["all_hotels"]), 1)
        self.assertNotIn("itinerary", trip)
        names = [d.name for d in fake.requests[0]["tools"][0].function_declarations]
        self.assertNotIn("find_activities", names)
        self.assertEqual(trip["weather"]["current_condition"], "Clear sky")

        results = dict(fake.tool_results(1))
        self.assertTrue(results["get_weather_forecast"]["available"])
        hotel_ids = [h["id"] for h in results["search_hotels"]["hotels"]]
        self.assertIn("cai-03", hotel_ids)
        sent = json.dumps(results)
        for private in ("booking_link", "image_url", "http"):
            self.assertNotIn(private, sent, "only needed data goes to the model")

    def test_function_responses_carry_the_matching_call_ids(self):
        fake = FakeGemini([
            calls(("search_hotels", {"max_price_per_night": 60}), ("get_weather_forecast", {}),
                  ("search_hotels", {"max_price_per_night": 250})),
            text(plan_json("cai-03")),
        ])
        with fake.patch():
            trip = self.cairo()
        self.assertEqual(trip["ai"]["generated_by"], "gemini")
        made = fake.function_calls_made(1)
        responses = fake.function_responses(1)
        self.assertEqual([r[0] for r in responses], [c[0] for c in made], "same ids, same order")
        self.assertEqual(len({r[0] for r in responses}), 3, "ids are distinct")
        by_id = {r[0]: r for r in responses}
        for call_id, name, args in made:
            self.assertEqual(by_id[call_id][1], name)
            if name == "search_hotels":
                prices = [h["price_per_night_usd"] for h in by_id[call_id][2]["hotels"]]
                self.assertTrue(prices and max(prices) <= args["max_price_per_night"],
                                "each parallel result belongs to its own call")
        cheap, wide = (by_id[c[0]][2]["hotels"] for c in made if c[1] == "search_hotels")
        self.assertLess(len(cheap), len(wide))

    def test_missing_call_id_is_sent_as_none(self):
        from google.genai import types
        from app.agents import agent_loop

        seen = []

        async def generate(contents, system_instruction, tools=None, json_output=False, **kw):
            seen.append(list(contents))
            if len(seen) == 1:
                fc = types.FunctionCall(name="find_activities", args={})
                content = types.Content(role="model", parts=[types.Part(function_call=fc)])
                return SimpleNamespace(function_calls=[fc], candidates=[SimpleNamespace(content=content)], text=None)
            return SimpleNamespace(function_calls=None, candidates=[object()], text='{"ok": true}')

        box = AgentToolbox(TripContext(destination="Cairo, Egypt", city="Cairo", country="Egypt",
                                       check_in="2026-12-01", check_out="2026-12-04", nights=3, travelers=2,
                                       purpose="Tourism", stay_preference="Boutique hotel"), "free")
        with mock.patch.object(gemini_client, "generate", new=generate):
            data, _ = run(agent_loop.run_agent("sys", "go", box))
        self.assertEqual(data, {"ok": True})
        response = seen[1][-1].parts[0].function_response
        self.assertEqual((response.id, response.name), (None, "find_activities"))

    def _scripted(self, responses):
        """generate() stand-in returning prepared SDK-shaped responses; records contents."""
        seen = []

        async def generate(contents, system_instruction, tools=None, json_output=False, **kw):
            seen.append({"contents": list(contents), "tools": tools, "json_output": json_output})
            return responses.pop(0)
        return seen, generate

    def _box(self):
        return AgentToolbox(TripContext(destination="Cairo, Egypt", city="Cairo", country="Egypt",
                                        check_in="2026-12-01", check_out="2026-12-04", nights=3, travelers=2,
                                        purpose="Tourism", stay_preference="Boutique hotel"), "free")

    def test_thought_signatures_survive_tool_rounds_and_the_json_repair(self):
        from google.genai import types
        from app.agents import agent_loop

        sig_call, sig_text = b"sig-for-call-\x00\x01", b"sig-for-text-\x02\x03"
        fc = types.FunctionCall(id="call-A", name="find_activities", args={})
        call_turn = types.Content(role="model", parts=[types.Part(function_call=fc, thought_signature=sig_call)])
        text_turn = types.Content(role="model", parts=[types.Part(text="Here you go: not json",
                                                                  thought_signature=sig_text)])
        responses = [
            SimpleNamespace(function_calls=[fc], candidates=[SimpleNamespace(content=call_turn)], text=None),
            SimpleNamespace(function_calls=None, candidates=[SimpleNamespace(content=text_turn)],
                            text="Here you go: not json"),
            SimpleNamespace(function_calls=None, candidates=[object()], text='{"done": true}'),
        ]
        seen, generate = self._scripted(responses)
        with mock.patch.object(gemini_client, "generate", new=generate):
            data, requests = run(agent_loop.run_agent("sys", "go", self._box()))
        self.assertEqual((data, requests), ({"done": True}, 3))
        second = seen[1]["contents"]
        self.assertIs(second[-2], call_turn, "model turn with the function call is sent back unchanged")
        self.assertEqual(second[-2].parts[0].thought_signature, sig_call)
        self.assertEqual(second[-1].parts[0].function_response.id, "call-A")
        third = seen[2]["contents"]
        self.assertIs(third[-2], text_turn, "repair keeps the original text turn and its signature")
        self.assertEqual(third[-2].parts[0].thought_signature, sig_text)
        self.assertTrue(seen[2]["json_output"])
        self.assertIsNone(seen[2]["tools"])

    def test_unexecuted_function_calls_are_not_sent_back(self):
        from google.genai import types
        from app.agents import agent_loop

        fc = types.FunctionCall(id="late", name="search_hotels", args={})
        turn = types.Content(role="model", parts=[types.Part(function_call=fc, thought_signature=b"s")])
        # No toolbox: tools are never offered, so a function call can't be executed.
        responses = [SimpleNamespace(function_calls=[fc], candidates=[SimpleNamespace(content=turn)], text=None),
                     SimpleNamespace(function_calls=None, candidates=[object()], text='{"reply": "ok"}')]
        seen, generate = self._scripted(responses)
        with mock.patch.object(gemini_client, "generate", new=generate):
            data, _ = run(agent_loop.run_agent("sys", "go", None))
        self.assertEqual(data, {"reply": "ok"})
        self.assertNotIn(turn, seen[1]["contents"])

    def test_agent_deadline_stops_further_requests(self):
        from app.agents import agent_loop

        async def slow(contents, system_instruction, **kw):
            await asyncio.sleep(0.5)
        with mock.patch.object(gemini_client, "generate", new=slow), \
             mock.patch.object(settings, "AI_AGENT_DEADLINE_SECONDS", 0.05):
            with self.assertRaises(gemini_client.GeminiError) as ctx:
                run(agent_loop.run_agent("sys", "go", self._box()))
        self.assertEqual(ctx.exception.code, "TIMEOUT")

    def test_prompt_carries_trip_details_and_budget_only_for_premium(self):
        fake = FakeGemini([text(plan_json())])
        with fake.patch():
            self.cairo(total_budget=900)
        prompt = fake.requests[0]["contents"][-1].parts[0].text
        for value in ('"check_in": "2026-12-01"', '"nights": 3', '"travelers": 2', '"purpose": "Tourism"',
                      "I love museums", "Museums"):
            self.assertIn(value, prompt)
        self.assertNotIn("total_budget_usd", prompt, "Free: no budget data")
        self.assertIn("verified by the server: free", fake.requests[0]["system"])

        clear_plan_cache()
        fake = FakeGemini([text(plan_json())])
        with fake.patch():
            self.cairo(headers=self._premium(), total_budget=900)
        self.assertIn('"total_budget_usd": 900', fake.requests[0]["contents"][-1].parts[0].text)

    def test_unknown_hotel_id_falls_back_to_a_real_hotel(self):
        with FakeGemini([calls(("search_hotels", {})), text(plan_json("made-up-hotel"))]).patch():
            trip = self.cairo()
        self.assertEqual(trip["ai"]["generated_by"], "gemini")
        self.assertIn(trip["recommended_hotel"]["id"], [h["id"] for h in trip["all_hotels"]])

    def test_non_json_answer_gets_one_json_repair_request(self):
        fake = FakeGemini([text("Here is your plan: day 1 pyramids..."), text(plan_json())])
        with fake.patch():
            trip = self.cairo()
        self.assertEqual(trip["ai"]["generated_by"], "gemini")
        self.assertEqual(len(fake.requests), 2)
        self.assertTrue(fake.requests[1]["json_output"])
        self.assertIsNone(fake.requests[1]["tools"])

    def test_incomplete_answer_is_rejected_and_labelled_as_template(self):
        with FakeGemini([text({"summary": "Only a summary."})]).patch():
            trip = self.cairo()
        self.assertEqual(trip["ai"]["generated_by"], "rules")
        self.assertIn("couldn't use", trip["ai"]["notice"])
        self.assertIn("Template plan (not AI-personalized)", trip["why_recommended"])
        self.assertNotIn("itinerary", trip, "the template has no itinerary either")

    def test_no_key_means_labelled_template_and_no_gemini_request(self):
        fake = FakeGemini([])
        with mock.patch.object(gemini_client, "generate", new=fake.__call__):
            trip = self.cairo()
        self.assertEqual(fake.requests, [])
        self.assertEqual(trip["ai"], {"generated_by": "rules", "model": None, "tools_used": [], "cached": False,
                                      "notice": gemini_client.ERROR_MESSAGES["NOT_CONFIGURED"]})
        self.assertIsNone(trip["match_score"])

    def test_gemini_errors_fall_back_clearly(self):
        for code in ("QUOTA_EXHAUSTED", "TIMEOUT", "INVALID_API_KEY", "MODEL_UNAVAILABLE"):
            clear_plan_cache()
            with FakeGemini([error(code)]).patch():
                trip = self.cairo()
            self.assertEqual(trip["ai"]["generated_by"], "rules", code)
            self.assertEqual(trip["ai"]["notice"], gemini_client.ERROR_MESSAGES[code])

    def test_identical_requests_reuse_the_cached_ai_plan(self):
        fake = FakeGemini([calls(("search_hotels", {"sort_by": "rating"})), text(plan_json("cai-03")),
                           text(plan_json("cai-01"))])
        with fake.patch():
            first = self.cairo()
            second = self.cairo()
            self.assertEqual(len(fake.requests), 2, "page refresh: no new Gemini request")
            self.assertTrue(second["ai"]["cached"])
            self.assertEqual(second["destination_summary"], first["destination_summary"])
            self.assertEqual(second["recommended_hotel"]["id"], "cai-03")
            other = self.cairo(travelers=3)
        self.assertEqual(len(fake.requests), 3)
        self.assertFalse(other["ai"]["cached"])

    def test_free_vs_premium_rules_are_unchanged(self):
        fake = FakeGemini([text(plan_json())])
        with fake.patch():
            free = self.cairo()
        names = [d.name for d in fake.requests[0]["tools"][0].function_declarations]
        self.assertNotIn("estimate_budget", names)
        self.assertIsNone(free["budget_breakdown"])
        self.assertTrue(all(h["booking_link"] is None for h in free["all_hotels"]))

        fake = FakeGemini([calls(("search_hotels", {})), calls(("estimate_budget", {"hotel_id": "cai-03"})),
                           text(plan_json("cai-03"))])
        with fake.patch():
            prem = self.cairo(headers=self._premium(), total_budget=2000)
        names = [d.name for d in fake.requests[0]["tools"][0].function_declarations]
        self.assertNotIn("estimate_budget", names, "planning has no budget tool: the server adds the breakdown")
        self.assertNotIn("estimate_budget", prem["ai"]["tools_used"])
        refused = dict(fake.tool_results(2))["estimate_budget"]
        self.assertIn("server adds the budget", refused["error"])
        self.assertIsNotNone(prem["budget_breakdown"])
        self.assertEqual(prem["budget_breakdown"]["user_budget"], 2000)
        self.assertTrue(all(h["booking_link"] for h in prem["all_hotels"]))

    def test_model_cannot_change_destination_or_dates_of_tools(self):
        fake = FakeGemini([calls(("search_hotels", {"destination": "Paris, France", "check_in": "2027-01-01"})),
                           text(plan_json())])
        with fake.patch():
            trip = self.cairo()
        self.assertTrue(all(h["city"] == "Cairo" for h in trip["all_hotels"]))


class SerpApiQuotaThroughAgentTest(_AgentApi):

    def test_agent_hotel_searches_share_one_serpapi_request(self):
        from tests.test_serpapi_hotels import CHECK_IN, CHECK_OUT, FakeSerpApi, prop, search_body
        from app.services import serpapi_hotels
        serpapi_hotels.reset_guards()
        with closing(serpapi_hotels._db()) as conn:
            conn.execute("DELETE FROM hotel_api_cache")
            conn.commit()
        serp = FakeSerpApi((200, search_body(prop("Hotel A", "tok-a", nightly=90), prop("Hotel B", "tok-b", nightly=200))))
        fake = FakeGemini([calls(("search_hotels", {}), ("search_hotels", {"sort_by": "price_low_to_high"})),
                           calls(("search_hotels", {"max_price_per_night": 100})), text(plan_json(None))])
        with mock.patch.object(settings, "HOTEL_API_KEY", "serp-test"), \
             mock.patch.object(serpapi_hotels, "_make_client", side_effect=serp.client), fake.patch():
            trip = self._plan(destination_city="Lisbon", destination_country="Portugal",
                              departure_date=CHECK_IN, return_date=CHECK_OUT)
        self.assertEqual(len(serp.requests), 1, "filters are applied locally; one SerpApi search")
        self.assertEqual(trip["ai"]["tools_used"], ["search_hotels"])
        self.assertEqual([h["name"] for h in trip["all_hotels"]], ["Hotel A"], "last search's filters")


# --------------------------------------------------------------- tools ---
class ToolboxLimitsTest(unittest.TestCase):

    def ctx(self):
        return TripContext(destination="Cairo, Egypt", city="Cairo", country="Egypt", check_in="2026-12-01",
                           check_out="2026-12-04", nights=3, travelers=2, purpose="Tourism",
                           stay_preference="Boutique hotel")

    def test_identical_calls_are_deduplicated(self):
        box = AgentToolbox(self.ctx(), "free")
        with mock.patch.object(tools, "get_weather_forecast", side_effect=live_weather) as weather:
            run(box.execute("get_weather_forecast", {}))
            run(box.execute("get_weather_forecast", {}))
        self.assertEqual(weather.call_count, 1)
        self.assertEqual(box.calls, ["get_weather_forecast"])

    def test_per_tool_and_total_limits(self):
        box = AgentToolbox(self.ctx(), "free")
        for price in (500, 400, 300):
            self.assertIn("hotels", run(box.execute("search_hotels", {"max_price_per_night": price})))
        limited = run(box.execute("search_hotels", {"max_price_per_night": 200}))
        self.assertIn("limit", limited["error"])
        self.assertEqual(box.calls.count("search_hotels"), tools.MAX_CALLS_PER_TOOL)

    def test_free_users_cannot_run_the_budget_tool(self):
        box = AgentToolbox(self.ctx(), "free")
        self.assertIn("Premium", run(box.execute("estimate_budget", {}))["error"])
        self.assertIsNone(box.budget)
        self.assertEqual(box.calls, [])

    def test_unavailable_live_weather_is_not_passed_off_as_data(self):
        async def offline(*a, **k):
            w = await live_weather()
            return w.model_copy(update={"source": "Open-Meteo Baseline Meteorological Cache"})
        box = AgentToolbox(self.ctx(), "free")
        with mock.patch.object(tools, "get_weather_forecast", side_effect=offline):
            result = run(box.execute("get_weather_forecast", {}))
        self.assertFalse(result["available"])
        self.assertNotIn("current", result)

    def test_failing_service_returns_an_error_to_the_model(self):
        box = AgentToolbox(self.ctx(), "free")
        with mock.patch.object(tools, "get_weather_forecast", side_effect=RuntimeError("down")):
            self.assertIn("unavailable", run(box.execute("get_weather_forecast", {}))["error"])

    def test_json_extraction(self):
        self.assertEqual(agent_loop.extract_json('```json\n{"a": 1}\n```'), {"a": 1})
        self.assertEqual(agent_loop.extract_json('Sure! {"a": 2} done'), {"a": 2})
        self.assertIsNone(agent_loop.extract_json("no json"))
        self.assertIsNone(agent_loop.extract_json("[1, 2]"))


# ---------------------------------------------------------------- chat ---
CONTEXT = {
    "destination": "Cairo, Egypt", "destination_city": "Cairo", "destination_country": "Egypt",
    "departure_date": "2026-12-01", "return_date": "2026-12-04", "travelers": 2, "purpose": "Tourism",
    "stay_preference": "Boutique hotel", "priorities": ["Museums"],
    "recommended_hotel": {"id": "cai-03", "name": "The Nile Ritz-Carlton, Cairo", "price_per_night": 260},
    "itinerary": [{"day_number": n, "theme": f"Day {n}", "activities": [{"time": "09:00 AM", "title": f"Visit {n}"}]}
                  for n in (1, 2, 3)],
}


class AiChatTest(_AgentApi):

    def chat(self, message, headers=None, context=CONTEXT, history=None):
        r = self.api.post("/api/trips/chat", headers=headers or {}, json={
            "message": message, "current_trip_context": context, "history": history or []})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_find_a_cheaper_hotel(self):
        box = AgentToolbox(TripContext(destination="Cairo, Egypt", city="Cairo", country="Egypt",
                                       check_in="2026-12-01", check_out="2026-12-04", nights=3, travelers=2,
                                       purpose="Tourism", stay_preference="Boutique hotel"), "free")
        cheap = run(box.fetch_hotels("price_low_to_high", 100))
        self.assertTrue(cheap)
        fake = FakeGemini([
            calls(("search_hotels", {"sort_by": "price_low_to_high", "max_price_per_night": 100})),
            text({"reply": f"{cheap[0].name} is cheaper.", "suggestions": ["Use it", "Show more", "x", "y"],
                  "suggested_hotel_id": cheap[0].id,
                  "itinerary_changes": [{"day_number": 2, "theme": "ignored now"}]}),
        ])
        history = [{"role": "user", "content": "I like quiet places"}, {"role": "assistant", "content": "Noted."}]
        with fake.patch():
            res = self.chat("Find a cheaper hotel and make day 2 slower", history=history)
        self.assertEqual((res["generated_by"], res["tools_called"]), ("gemini", ["search_hotels"]))
        self.assertTrue(res["hotel_options"])
        self.assertTrue(all(h["price_per_night"] <= 100 for h in res["hotel_options"]))
        self.assertEqual(res["suggested_hotel_id"], cheap[0].id)
        self.assertEqual(len(res["suggestions"]), 3)
        self.assertNotIn("updated_itinerary_days", res, "itinerary edits from the model are ignored")

        sent = fake.requests[0]["contents"]
        self.assertEqual([c.role for c in sent[:2]], ["user", "model"], "conversation history is sent")
        prompt = sent[-1].parts[0].text
        self.assertIn('"current_hotel"', prompt)
        self.assertNotIn("Visit 2", prompt, "an old client's itinerary is not sent to the model")
        self.assertNotIn("itinerary", fake.requests[0]["system"])

    def test_suggested_hotel_must_come_from_this_turns_search(self):
        with FakeGemini([text({"reply": "Try Hotel X", "suggested_hotel_id": "cai-01"})]).patch():
            res = self.chat("cheaper hotel?")
        self.assertIsNone(res["suggested_hotel_id"])
        self.assertEqual(res["hotel_options"], [])

    def test_no_key_says_unavailable_and_claims_nothing(self):
        res = self.chat("Make day 3 slower")
        self.assertEqual(res["generated_by"], "unavailable")
        self.assertIn("AI assistant is unavailable", res["reply"])
        self.assertNotIn("adjusted", res["reply"].lower())
        self.assertEqual(res["tools_called"], [])

    def test_api_errors_are_reported(self):
        with FakeGemini([error("QUOTA_EXHAUSTED")]).patch():
            res = self.chat("hi")
        self.assertEqual(res["generated_by"], "unavailable")
        self.assertIn("quota", res["reply"].lower())

    def test_loose_old_context_disables_tools(self):
        fake = FakeGemini([text({"reply": "General tips."})])
        with fake.patch():
            res = self.chat("What should I pack?", context={"destination": "Cairo", "weather": "Clear"})
        self.assertIsNone(fake.requests[0]["tools"])
        self.assertEqual(res["generated_by"], "gemini")

    def test_free_chat_gets_no_budget_tool_and_no_links(self):
        fake = FakeGemini([calls(("estimate_budget", {}), ("search_hotels", {})), text({"reply": "ok"})])
        with fake.patch():
            res = self.chat("How is my budget?")
        results = dict(fake.tool_results(1))
        self.assertIn("Premium", results["estimate_budget"]["error"])
        self.assertTrue(all(h["booking_link"] is None for h in res["hotel_options"]))
        self.assertEqual(res["tools_called"], ["search_hotels"])


class NoKeyLeakageTest(_AgentApi):

    def test_key_not_in_responses_or_logs(self):
        records = []
        handler = logging.Handler(level=logging.DEBUG)
        handler.emit = lambda r: records.append(r.getMessage())
        root = logging.getLogger()
        root.addHandler(handler)
        old = root.level
        root.setLevel(logging.DEBUG)
        try:
            for code in ("INVALID_API_KEY", "QUOTA_EXHAUSTED"):
                clear_plan_cache()
                with FakeGemini([error(code), error(code)]).patch(key=KEY):
                    plan = self.api.post("/api/trips/plan", json={**TRIP, "destination_city": "Cairo",
                                                                   "destination_country": "Egypt"})
                    chat = self.api.post("/api/trips/chat", json={"message": "hi", "current_trip_context": CONTEXT})
                    health = self.api.get("/api/health")
                for r in (plan, chat, health):
                    self.assertNotIn(KEY, r.text)
        finally:
            root.removeHandler(handler)
            root.setLevel(old)
        self.assertFalse([m for m in records if KEY in m])


if __name__ == "__main__":
    unittest.main()
