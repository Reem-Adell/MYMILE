"""
Groq (primary LLM) travel agent: OpenAI-compatible tool calling over real backend
services, server-side prefetch, validated JSON, bounded 429 retry, error mapping,
Free/Premium rules, no Gemini fallback and no key leakage.

Run from backend/:
    venv\\Scripts\\python -m unittest tests.test_groq_agent -v
No real Groq, Gemini, SerpApi, Channel3 or weather requests: all are mocked.
"""
from tests import _env  # noqa: F401  (must precede any app.* import)

import asyncio
import json
import logging
import time
import unittest
from unittest import mock

from app.agents import agent_loop, gemini_client, groq_client, llm, tools
from app.agents.groq_client import GroqError
from app.agents.tools import AgentToolbox, TripContext
from app.core.config import settings
from types import SimpleNamespace

from app.services.budget_service import optimize_budget
from tests._fake_groq import KEY, FakeGroq, calls, network, status, text, timeout, truncated
from tests.test_channel3 import FakeChannel3, _C3Case, ok, product
from tests.test_explore_trip import TRIP, run
from tests.test_gemini_agent import CONTEXT, _AgentApi, clear_plan_cache, live_weather, plan_json

PLAN_TOOLS = ["find_travel_products"]  # the only tool trip planning offers after the prefetch


def gemini_must_not_run():
    async def boom(*args, **kwargs):
        raise AssertionError("Gemini must never be called when LLM_PROVIDER=groq")
    return mock.patch.object(gemini_client, "generate", new=boom)


def tool_data(request):
    prompt = request["messages"][-1]["content"] if request["messages"][-1]["role"] == "user" else \
        next(m["content"] for m in request["messages"] if m["role"] == "user")
    return json.loads(prompt.split("tool_data: ", 1)[1])


# ------------------------------------------------------------------ client ---
class GroqClientTest(unittest.TestCase):

    def gen(self, fake, **kwargs):
        with fake.patch():
            return run(groq_client.generate([{"role": "user", "content": "hi"}], **kwargs))

    def test_not_configured_sends_nothing(self):
        fake = FakeGroq([])
        with fake.patch(key=""):
            with self.assertRaises(GroqError) as ctx:
                run(groq_client.generate([{"role": "user", "content": "hi"}]))
        self.assertEqual(ctx.exception.code, "NOT_CONFIGURED")
        self.assertEqual(fake.clients, 0)

    def test_sdk_client_uses_groq_base_url_and_no_sdk_retries(self):
        with mock.patch.object(settings, "GROQ_API_KEY", KEY), \
             mock.patch.object(settings, "GROQ_BASE_URL", "https://api.groq.com/openai/v1/"), \
             mock.patch("openai.AsyncOpenAI") as cls:
            groq_client._make_client()
        kwargs = cls.call_args.kwargs
        self.assertEqual(kwargs["base_url"], "https://api.groq.com/openai/v1")
        self.assertEqual(kwargs["max_retries"], 0, "the only retry is MYMILE's bounded 429 retry")
        self.assertEqual(kwargs["api_key"], KEY)

    def test_request_parameters(self):
        fake = FakeGroq([text("{}"), text("{}")])
        self.gen(fake, tools=[{"type": "function", "function": {"name": "t", "parameters": {}}}])
        self.gen(fake, json_output=True)
        with_tools, json_mode = fake.requests
        self.assertEqual(with_tools["model"], "openai/gpt-oss-120b")
        self.assertEqual(with_tools["tool_choice"], "auto")
        self.assertNotIn("response_format", with_tools, "JSON mode is never combined with tools")
        self.assertEqual(json_mode["response_format"], {"type": "json_object"})
        self.assertNotIn("tools", json_mode)
        self.assertEqual(with_tools["reasoning_effort"], "low")
        self.assertEqual(with_tools["max_completion_tokens"], 8192, "no explicit limit: the ceiling")
        self.assertEqual(fake.closed, fake.clients, "every SDK client is closed")

    def test_unknown_reasoning_effort_is_not_sent(self):
        fake = FakeGroq([text("{}")])
        with mock.patch.object(settings, "GROQ_REASONING_EFFORT", "extreme"):
            self.gen(fake)
        self.assertNotIn("reasoning_effort", fake.requests[0])

    def test_429_waits_for_retry_after_then_succeeds(self):
        fake = FakeGroq([status(429, "rate_limit_exceeded", {"retry-after": "3"}), text("{}")])
        self.gen(fake, deadline=time.monotonic() + 60)
        self.assertEqual(fake.sleeps, [3.0])
        self.assertEqual(len(fake.requests), 2)

    def test_429_wait_is_read_from_the_message_when_no_header(self):
        fake = FakeGroq([status(429, message="Rate limit reached ... Please try again in 1m2.5s."), text("{}")])
        with mock.patch.object(settings, "GROQ_RETRY_MAX_WAIT_SECONDS", 120.0):
            self.gen(fake, deadline=time.monotonic() + 600)
        self.assertEqual(fake.sleeps, [62.5])
        fake = FakeGroq([status(429, message="Please try again in 446ms."), text("{}")])
        self.gen(fake, deadline=time.monotonic() + 60)
        self.assertAlmostEqual(fake.sleeps[0], 0.446)

    def test_429_retries_are_bounded(self):
        fake = FakeGroq([status(429, headers={"retry-after": "1"})] * 3)
        with self.assertRaises(GroqError) as ctx:
            self.gen(fake, deadline=time.monotonic() + 60)
        self.assertEqual(ctx.exception.code, "QUOTA_EXHAUSTED")
        self.assertEqual(len(fake.requests), 3, "1 request + GROQ_RATE_LIMIT_RETRIES (2) retries")
        self.assertEqual(fake.sleeps, [1.0, 1.0])

    def test_long_retry_after_is_reported_not_waited(self):
        fake = FakeGroq([status(429, headers={"retry-after": "3600"}, message="tokens per day (TPD)")])
        with self.assertRaises(GroqError) as ctx:
            self.gen(fake, deadline=time.monotonic() + 600)
        self.assertEqual((ctx.exception.code, fake.sleeps), ("QUOTA_EXHAUSTED", []))

    def test_retry_never_runs_past_the_deadline(self):
        fake = FakeGroq([status(429, headers={"retry-after": "10"})])
        with self.assertRaises(GroqError) as ctx:
            self.gen(fake, deadline=time.monotonic() + 5)
        self.assertEqual((ctx.exception.code, fake.sleeps), ("QUOTA_EXHAUSTED", []))

    def test_errors_are_mapped(self):
        cases = [(status(401), "INVALID_API_KEY"), (status(403), "INVALID_API_KEY"),
                 (status(404, "model_not_found"), "MODEL_UNAVAILABLE"), (status(413), "REQUEST_TOO_LARGE"),
                 (status(500), "SERVICE_ERROR"), (status(503), "SERVICE_ERROR"),
                 (status(400, "tool_use_failed"), "MALFORMED_TOOL_CALL"), (status(400), "BAD_REQUEST"),
                 (timeout(), "TIMEOUT"), (network(), "NETWORK")]
        for step, code in cases:
            fake = FakeGroq([step])
            with self.subTest(code=code), self.assertRaises(GroqError) as ctx:
                self.gen(fake)
            self.assertEqual(ctx.exception.code, code)
            self.assertNotIn(KEY, ctx.exception.message)
            self.assertEqual(len(fake.requests), 1, "only 429 is retried")

    def test_empty_choices_is_invalid(self):
        fake = FakeGroq([])

        async def create(**params):
            return mock.Mock(choices=[])
        with fake.patch(), mock.patch.object(fake, "_create", new=create):
            with self.assertRaises(GroqError) as ctx:
                run(groq_client.generate([{"role": "user", "content": "hi"}]))
        self.assertEqual(ctx.exception.code, "INVALID_RESPONSE")

    def test_provider_selection_and_health(self):
        with mock.patch.object(settings, "LLM_PROVIDER", "groq"), mock.patch.object(settings, "GROQ_API_KEY", ""):
            self.assertEqual(llm.describe(), {"provider": "groq", "model": "openai/gpt-oss-120b",
                                              "status": "not_configured"})
        with mock.patch.object(settings, "LLM_PROVIDER", "openai"):
            with self.assertRaises(Exception) as ctx:
                llm.check_available()
            self.assertEqual(ctx.exception.code, "UNSUPPORTED_PROVIDER")
        with mock.patch.object(settings, "LLM_PROVIDER", ""):
            self.assertEqual(llm.provider(), "groq", "Groq is the default")


# ---------------------------------------------------------------- toolbox ---
class ToolSchemaTest(unittest.TestCase):

    def box(self, plan="free"):
        return AgentToolbox(TripContext(destination="Cairo, Egypt", city="Cairo", country="Egypt",
                                        check_in="2026-12-01", check_out="2026-12-04", nights=3, travelers=2,
                                        purpose="Tourism", stay_preference="Boutique hotel"), plan)

    def test_openai_tools_match_the_gemini_declarations(self):
        box = self.box("premium")
        groq_tools = box.openai_tools()
        self.assertTrue(all(t["type"] == "function" for t in groq_tools))
        gemini = box.declarations()[0].function_declarations
        self.assertEqual([t["function"]["name"] for t in groq_tools], [d.name for d in gemini])
        for t, d in zip(groq_tools, gemini):
            self.assertEqual(t["function"]["parameters"], d.parameters_json_schema)

    def test_free_never_gets_the_budget_tool(self):
        names = [t["function"]["name"] for t in self.box("free").openai_tools()]
        self.assertNotIn("estimate_budget", names)

    def test_prefetch_runs_fixed_tools_once_and_restricts_the_rest(self):
        box = self.box("premium")
        with mock.patch.object(tools, "get_weather_forecast", side_effect=live_weather):
            data = run(box.prefetch())
        self.assertEqual(set(data), {"get_weather_forecast", "search_hotels"}, "no activities tool anymore")
        self.assertTrue(data["get_weather_forecast"]["available"])
        self.assertLessEqual(len(data["search_hotels"]["hotels"]), tools.PROMPT_MAX_HOTELS)
        self.assertEqual(box.calls, ["get_weather_forecast", "search_hotels"])
        self.assertEqual(box.openai_tools(), [], "Channel3 is off and planning has no budget tool")
        again = run(box.execute("search_hotels", {"sort_by": "rating"}))
        self.assertIn("already in the prompt", again["error"])
        self.assertEqual(len(box.hotel_lists), 1, "no second hotel search")
        sent = json.dumps(data)
        for private in ("booking_link", "image_url", "http"):
            self.assertNotIn(private, sent)


# --------------------------------------------------------- trip planning ---
class GroqTripPlanningTest(_AgentApi):

    def test_plan_uses_prefetched_data_and_groq_json(self):
        fake = FakeGroq([text(plan_json("cai-03"))])
        with fake.patch(), gemini_must_not_run():
            trip = self.cairo()
        self.assertEqual(trip["ai"]["generated_by"], "groq")
        self.assertEqual(trip["ai"]["model"], "openai/gpt-oss-120b")
        self.assertEqual(trip["recommended_hotel"]["id"], "cai-03")
        self.assertNotIn("itinerary", trip, "no day-by-day itinerary is generated")
        self.assertEqual(trip["ai"]["tools_used"], ["get_weather_forecast", "search_hotels"])
        self.assertEqual(len(fake.requests), 1, "one model request: no tool rounds were needed")
        first = fake.requests[0]
        self.assertNotIn("tools", first, "Free without Channel3 has no remaining tools")
        self.assertEqual(first["response_format"], {"type": "json_object"})
        self.assertEqual(first["messages"][0]["role"], "system")
        self.assertIn("tool_data", first["messages"][0]["content"])
        data = tool_data(first)
        self.assertIn("cai-03", [h["id"] for h in data["search_hotels"]["hotels"]])
        self.assertNotIn("find_activities", json.dumps(first))
        system = first["messages"][0]["content"]
        self.assertNotIn("itinerary", system)
        self.assertNotIn("day_number", system)
        self.assertNotIn("reasoning", json.dumps(first["messages"]))

    def test_invalid_json_gets_one_json_mode_retry(self):
        fake = FakeGroq([text("Here is your plan: day 1 pyramids..."), text(plan_json())])
        with fake.patch():
            trip = self.cairo()
        self.assertEqual(trip["ai"]["generated_by"], "groq")
        retry = fake.requests[1]
        self.assertEqual(retry["response_format"], {"type": "json_object"})
        self.assertEqual([m["role"] for m in retry["messages"][-2:]], ["assistant", "user"])

    def test_unusable_output_gives_a_labelled_template(self):
        for script in ([text("no json"), text("still no json")], [text({"summary": "Only a summary."})],
                       [text({"summary": "", "why_recommended": ""})]):
            clear_plan_cache()
            with self.subTest(script=script[0][1][:20]), FakeGroq(script).patch():
                trip = self.cairo()
            self.assertEqual(trip["ai"]["generated_by"], "rules")
            self.assertIn("Groq returned a response MYMILE couldn't use", trip["ai"]["notice"])
            self.assertIn("Template plan (not AI-personalized)", trip["why_recommended"])

    def test_rate_limit_is_reported_and_gemini_is_not_used(self):
        fake = FakeGroq([status(429, headers={"retry-after": "1"})] * 3)
        with fake.patch(GEMINI_API_KEY="AIza-would-spend-gemini-quota"), gemini_must_not_run():
            trip = self.cairo()
        self.assertEqual(trip["ai"]["generated_by"], "rules")
        self.assertIn("Groq rate limit", trip["ai"]["notice"])
        self.assertEqual(fake.sleeps, [1.0, 1.0])
        self.assertTrue(trip["all_hotels"], "real hotel data is still shown")

    def test_overall_deadline_is_enforced(self):
        async def slow(*args, **kwargs):
            await asyncio.sleep(1)
        fake = FakeGroq([])
        with fake.patch(), mock.patch.object(groq_client, "generate", new=slow), \
             mock.patch.object(settings, "AI_AGENT_DEADLINE_SECONDS", 0.05):
            trip = self.cairo()
        self.assertEqual(trip["ai"]["generated_by"], "rules")
        self.assertIn("Groq took too long", trip["ai"]["notice"])

    def test_auth_error_is_reported(self):
        with FakeGroq([status(401)]).patch():
            trip = self.cairo()
        self.assertEqual(trip["ai"]["generated_by"], "rules")
        self.assertIn("Groq rejected the configured API key", trip["ai"]["notice"])

    def test_cached_plan_spends_no_groq_request(self):
        fake = FakeGroq([text(plan_json())])
        with fake.patch():
            first = self.cairo()
            again = self.cairo()
        self.assertFalse(first["ai"]["cached"])
        self.assertTrue(again["ai"]["cached"])
        self.assertEqual(again["ai"]["generated_by"], "groq")
        self.assertEqual(len(fake.requests), 1)


class GroqToolRoundsTest(_C3Case, _AgentApi):
    """Channel3 configured: the model calls real tools one per turn across several rounds."""

    def test_premium_plan_needs_no_budget_round(self):
        c3 = self.serve(FakeChannel3(ok(product("p1")), ok(product("p2", "Walking Shoes"))))
        fake = FakeGroq([
            calls(("find_travel_products", {"queries": ["packable rain jacket", "walking shoes"]})),
            text(plan_json("cai-03", essentials=[{"product_id": "p2", "reason": "You walk a lot."},
                                                 {"product_id": "invented-id", "reason": "x"}])),
        ])
        with fake.patch(), gemini_must_not_run():
            trip = self.cairo(headers=self._premium(), total_budget=3000)
        self.assertEqual(trip["ai"]["generated_by"], "groq")
        self.assertEqual(len(fake.requests), 2, "Premium: products round + final answer, no budget round")
        self.assertEqual(fake.tool_names(0), PLAN_TOOLS)
        self.assertNotIn("estimate_budget", fake.requests[0]["messages"][0]["content"])

        (call_id, name, args), = fake.echoed_calls(1)
        self.assertEqual(name, "find_travel_products")
        (result_id, result), = fake.tool_messages(1)
        self.assertEqual(result_id, call_id)
        self.assertEqual(sorted(p["id"] for s in result["searches"] for p in s["products"]), ["p1", "p2"])
        self.assertNotIn("http", json.dumps(result), "no purchase links go to the model")

        self.assertEqual(trip["ai"]["tools_used"], ["get_weather_forecast", "search_hotels", "find_travel_products"])
        self.assertEqual([(p["id"], p["reason"]) for p in trip["travel_essentials"]], [("p2", "You walk a lot.")],
                         "only genuine Channel3 ids are kept")
        self.assertEqual(trip["travel_essentials"][0]["purchase_url"], "https://shop-a.example/p2", "Premium: link")
        self.assertEqual(len(c3.requests), 2)
        # The Premium budget is the same server-side calculation as before, for the chosen hotel.
        expected = optimize_budget(destination="Cairo, Egypt", duration_days=3, travelers=2, total_budget=3000,
                                   currency="USD", selected_hotel_total=trip["recommended_hotel"]["total_price"],
                                   stay_preference="Boutique hotel", plan="premium").breakdown.model_dump()
        self.assertEqual(trip["budget_breakdown"], json.loads(json.dumps(expected)))

    def test_budget_tool_called_anyway_in_planning_is_refused(self):
        self.serve(FakeChannel3(ok(product("p1"))))
        fake = FakeGroq([calls(("estimate_budget", {"hotel_id": "cai-03"})), text(plan_json("cai-03"))])
        with fake.patch():
            trip = self.cairo(headers=self._premium(), total_budget=3000)
        (_, refused), = fake.tool_messages(1)
        self.assertIn("server adds the budget", refused["error"])
        self.assertNotIn("estimate_budget", trip["ai"]["tools_used"])
        self.assertIsNotNone(trip["budget_breakdown"], "Premium still gets the breakdown")

    def test_free_plan_has_no_budget_tool_even_if_the_model_calls_it(self):
        self.serve(FakeChannel3(ok(product("p1"))))
        fake = FakeGroq([calls(("estimate_budget", {"hotel_id": "cai-03"})),
                         calls(("find_travel_products", {"queries": ["rain jacket"]})),
                         text(plan_json("cai-03", essentials=[{"product_id": "p1", "reason": "Rain."}]))])
        with fake.patch():
            trip = self.cairo()
        self.assertEqual(fake.tool_names(0), ["find_travel_products"])
        (_, refused), = fake.tool_messages(1)
        self.assertIn("Premium", refused["error"])
        self.assertIsNone(trip["budget_breakdown"])
        self.assertIsNone(trip["travel_essentials"][0]["purchase_url"], "Free: no purchase link")
        self.assertNotIn("estimate_budget", trip["ai"]["tools_used"])

    def test_malformed_arguments_and_unknown_tools_are_answered_with_errors(self):
        self.serve(FakeChannel3(ok(product("p1"))))
        fake = FakeGroq([calls(("find_travel_products", "{not json")),
                         calls(("book_hotel", {"id": "cai-03"})),
                         calls(("search_hotels", {"sort_by": "rating"})),
                         calls(("find_travel_products", {"queries": ["rain jacket"]})),
                         text(plan_json("cai-03"))])
        with fake.patch():
            trip = self.cairo()
        self.assertEqual(trip["ai"]["generated_by"], "groq")
        results = [r for _, r in fake.tool_messages(4)]
        self.assertIn("not a valid JSON object", results[0]["error"])
        self.assertIn("Unknown tool", results[1]["error"])
        self.assertIn("already in the prompt", results[2]["error"])
        self.assertEqual(results[3]["searches"][0]["products"][0]["id"], "p1")
        self.assertNotIn("tools", fake.requests[4], "the 5th request (MAX_ROUNDS) must answer")

    def test_rejected_tool_call_is_retried_once_then_answered_without_tools(self):
        self.serve(FakeChannel3(ok(product("p1"))))
        fake = FakeGroq([status(400, "tool_use_failed"),
                         calls(("find_travel_products", {"queries": ["rain jacket"]})),
                         text(plan_json("cai-03"))])
        with fake.patch():
            trip = self.cairo()
        self.assertEqual(trip["ai"]["generated_by"], "groq")
        self.assertIn("find_travel_products", trip["ai"]["tools_used"])

        clear_plan_cache()
        fake = FakeGroq([status(400, "tool_use_failed"), status(400, "tool_use_failed"), text(plan_json("cai-03"))])
        with fake.patch():
            trip = self.cairo(travelers=3)
        self.assertEqual(trip["ai"]["generated_by"], "groq")
        self.assertNotIn("tools", fake.requests[2])
        self.assertEqual(fake.requests[2]["response_format"], {"type": "json_object"})

    def test_channel3_failure_is_reported_not_faked(self):
        self.serve(FakeChannel3((429, {"detail": "slow down"})))
        fake = FakeGroq([calls(("find_travel_products", {"queries": ["rain jacket"]})), text(plan_json("cai-03"))])
        with fake.patch():
            trip = self.cairo()
        self.assertEqual(trip["essentials"]["status"], "unavailable")
        self.assertEqual(trip["travel_essentials"], [])


# ------------------------------------------------------------------- chat ---
class GroqChatTest(_AgentApi):

    def chat(self, message, context=CONTEXT, history=None):
        r = self.api.post("/api/trips/chat", json={"message": message, "current_trip_context": context,
                                                     "history": history or []})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_chat_tool_round_and_history(self):
        fake = FakeGroq([calls(("search_hotels", {"sort_by": "price_low_to_high", "max_price_per_night": 100})),
                         text({"reply": "Here are cheaper hotels.", "suggestions": ["Use the first"]})])
        history = [{"role": "user", "content": "I like quiet places"}, {"role": "assistant", "content": "Noted."}]
        with fake.patch(), gemini_must_not_run():
            res = self.chat("Find a cheaper hotel", history=history)
        self.assertEqual((res["generated_by"], res["model"]), ("groq", "openai/gpt-oss-120b"))
        self.assertEqual(res["tools_called"], ["search_hotels"])
        self.assertTrue(all(h["price_per_night"] <= 100 for h in res["hotel_options"]))
        roles = [m["role"] for m in fake.requests[0]["messages"]]
        self.assertEqual(roles, ["system", "user", "assistant", "user"], "history uses OpenAI roles")
        self.assertNotIn("estimate_budget", fake.tool_names(0), "Free chat: no budget tool")
        self.assertIn("search_hotels", fake.tool_names(0), "chat keeps its tools (no prefetch)")

    def test_chat_errors_say_unavailable(self):
        with FakeGroq([status(429, headers={"retry-after": "999"})]).patch():
            res = self.chat("hi")
        self.assertEqual(res["generated_by"], "unavailable")
        self.assertIn("Groq rate limit", res["reply"])
        self.assertNotIn("updated_itinerary_days", res, "chat no longer edits itinerary days")


class GroqNoKeyLeakageTest(_AgentApi):

    def test_key_not_in_responses_or_logs(self):
        records = []
        handler = logging.Handler(level=logging.DEBUG)
        handler.emit = lambda r: records.append(r.getMessage())
        root = logging.getLogger()
        root.addHandler(handler)
        old = root.level
        root.setLevel(logging.DEBUG)
        try:
            for step in (status(401, message=f"Invalid API Key {KEY}"), status(429, headers={"retry-after": "999"})):
                clear_plan_cache()
                with FakeGroq([step, step]).patch():
                    plan = self.api.post("/api/trips/plan", json={**TRIP, "destination_city": "Cairo",
                                                                   "destination_country": "Egypt"})
                    chat = self.api.post("/api/trips/chat", json={"message": "hi", "current_trip_context": CONTEXT})
                    health = self.api.get("/api/health")
                for r in (plan, chat, health):
                    self.assertNotIn(KEY, r.text)
                self.assertEqual(health.json()["integrations"]["llm"]["provider"], "groq")
        finally:
            root.removeHandler(handler)
            root.setLevel(old)
        self.assertFalse([m for m in records if KEY in m])



# ------------------------------------------------------- rate-limit optimizations ---
TPM_MESSAGE = ("Rate limit reached for model `openai/gpt-oss-120b` in organization `org_01abcDEF9` service tier "
               "`on_demand` on tokens per minute (TPM): Limit 8000, Used 7900, Requested 2100. "
               "Please try again in 15.2s.")


class CompletionLimitAndLoggingTest(unittest.TestCase):

    def gen(self, fake, **kwargs):
        with fake.patch():
            return run(groq_client.generate([{"role": "user", "content": "hi"}], **kwargs))

    def test_limits(self):
        self.assertEqual(groq_client.tool_round_max_tokens(), 1024)
        self.assertEqual(groq_client.final_max_tokens(), 3000, "no per-day allowance: there is no itinerary")
        with mock.patch.object(settings, "GROQ_FINAL_BASE_TOKENS", 99999):
            self.assertEqual(groq_client.final_max_tokens(), 8192, "never above the ceiling")
        with mock.patch.object(settings, "GROQ_TOOL_ROUND_MAX_TOKENS", 99999):
            self.assertEqual(groq_client.tool_round_max_tokens(), 8192)

    def test_usage_is_logged(self):
        fake = FakeGroq([text("{}")])
        fake.usage = SimpleNamespace(prompt_tokens=2100, completion_tokens=900, total_tokens=3000,
                                     prompt_tokens_details=SimpleNamespace(cached_tokens=1800),
                                     completion_tokens_details=SimpleNamespace(reasoning_tokens=250))
        with self.assertLogs("app.agents.groq_client", "INFO") as logs:
            self.gen(fake, purpose="round 2 final")
        line = next(m for m in logs.output if "Groq usage" in m)
        for part in ("round 2 final", "model=openai/gpt-oss-120b", "prompt=2100", "completion=900", "total=3000",
                     "cached=1800", "reasoning=250", "finish=stop"):
            self.assertIn(part, line)

    def test_missing_usage_is_logged_as_unknown(self):
        for usage in (None, SimpleNamespace(prompt_tokens=10), {"prompt_tokens": 5, "total_tokens": "x"}):
            fake = FakeGroq([text("{}")])
            fake.usage = usage
            with self.subTest(usage=usage), self.assertLogs("app.agents.groq_client", "INFO") as logs:
                self.gen(fake)
            line = next(m for m in logs.output if "Groq usage" in m)
            self.assertIn("cached=None", line)
            self.assertIn("completion=None", line)

    def test_429_logs_the_limit_kind_message_and_headers_without_secrets(self):
        headers = {"retry-after": "60", "x-ratelimit-limit-tokens": "8000", "x-ratelimit-remaining-tokens": "100",
                   "x-ratelimit-reset-tokens": "15.2s", "x-ratelimit-remaining-requests": "990",
                   "authorization": f"Bearer {KEY}"}
        fake = FakeGroq([status(429, "rate_limit_exceeded", headers, TPM_MESSAGE + f" key {KEY}")])
        with self.assertLogs("app.agents.groq_client", "WARNING") as logs, self.assertRaises(GroqError):
            self.gen(fake, deadline=time.monotonic() + 600)
        line = next(m for m in logs.output if "Groq rate limit" in m)
        for part in ("HTTP 429", "limit=TPM", "retry-after 60.0s", "not retrying", "Limit 8000, Used 7900",
                     "x-ratelimit-remaining-tokens", "'100'", "x-ratelimit-remaining-requests"):
            self.assertIn(part, line)
        self.assertNotIn("org_01abcDEF9", line)
        self.assertNotIn(KEY, line)
        self.assertNotIn("authorization", line.lower())

    def test_429_without_headers_or_message_is_logged_safely(self):
        fake = FakeGroq([status(429, message=""), text("{}")])
        with self.assertLogs("app.agents.groq_client", "WARNING") as logs:
            self.gen(fake, deadline=time.monotonic() + 60)
        line = next(m for m in logs.output if "Groq rate limit" in m)
        self.assertIn("limit=unknown", line)
        self.assertIn("retrying", line)
        self.assertEqual(fake.sleeps, [2.0], "default wait when Groq sends no retry-after")


class FinalAnswerLimitTest(_AgentApi):

    def test_tool_rounds_are_small_and_the_final_answer_limit_is_fixed(self):
        from app.services import channel3_service
        for days in (3, 10):
            clear_plan_cache()
            ret = f"2026-12-{1 + days:02d}"
            with mock.patch.object(channel3_service, "is_enabled", return_value=True), \
                 mock.patch.object(tools.channel3_service, "search",
                                   side_effect=lambda q, limit=None: asyncio.sleep(0, {"products": []})):
                fake = FakeGroq([calls(("find_travel_products", {"queries": ["walking shoes"]})),
                                 text(plan_json("cai-03", days=days))])
                with fake.patch():
                    trip = self.cairo(return_date=ret)
            self.assertEqual(trip["ai"]["generated_by"], "groq")
            self.assertEqual(trip["total_days"], days)
            self.assertEqual(fake.requests[0]["max_completion_tokens"], 1024, "tool round")
            self.assertEqual(fake.requests[1]["max_completion_tokens"], 3000,
                             "the round after the search may answer: final limit, same for any trip length")
            self.assertEqual(fake.tool_names(1), ["find_travel_products"], "follow-up search still possible")

    def test_truncated_final_answer_is_never_used_and_retried_with_room(self):
        fake = FakeGroq([truncated(), text(plan_json("cai-03"))])
        with fake.patch():
            trip = self.cairo()
        self.assertEqual(trip["ai"]["generated_by"], "groq")
        retry = fake.requests[1]
        self.assertEqual(retry["max_completion_tokens"], 8192)
        self.assertEqual(retry["response_format"], {"type": "json_object"})
        self.assertNotIn("cut off", json.dumps(retry["messages"]), "the cut-off text isn't sent back")

    def test_truncated_twice_gives_a_labelled_template(self):
        with FakeGroq([truncated(), truncated(plan_json("cai-03"))]).patch():
            trip = self.cairo()
        self.assertEqual(trip["ai"]["generated_by"], "rules")
        self.assertIn("Groq returned a response MYMILE couldn't use", trip["ai"]["notice"])

    def test_answer_in_the_search_round_is_retried_not_truncated(self):
        fake = FakeGroq([truncated(), text(plan_json("cai-03"))])
        from app.services import channel3_service
        with fake.patch(), mock.patch.object(channel3_service, "is_enabled", return_value=True):
            trip = self.cairo()
        self.assertEqual(fake.requests[0]["max_completion_tokens"], 1024)
        self.assertEqual(fake.requests[1]["max_completion_tokens"], 8192)
        self.assertEqual(trip["ai"]["generated_by"], "groq")

    def test_premium_chat_keeps_the_budget_tool(self):
        fake = FakeGroq([text({"reply": "Your budget looks fine."})])
        with fake.patch():
            r = self.api.post("/api/trips/chat", headers=self._premium(),
                              json={"message": "How is my budget?", "current_trip_context": CONTEXT})
        self.assertEqual(r.json()["generated_by"], "groq")
        self.assertIn("estimate_budget", fake.tool_names(0))
        self.assertEqual(fake.requests[0]["max_completion_tokens"], 3000, "any chat round may be the answer")

if __name__ == "__main__":
    unittest.main()
