"""
A scripted stand-in for Groq's Chat Completions endpoint (no network, no credits).

    fake = FakeGroq([calls(("find_travel_products", {"queries": ["rain jacket"]})), text({...})])
    with fake.patch(): ...

It replaces only `groq_client._make_client`, so MYMILE's real request building,
429 retry, error mapping and agent loop all run. Each scripted step answers one
HTTP request; `fake.requests` records the parameters MYMILE sent (messages are
deep-copied at send time). `fake.sleeps` records 429 retry waits (none are slept).
"""
import json
from contextlib import ExitStack, contextmanager
from types import SimpleNamespace
from unittest import mock

import httpx
import openai

from app.agents import groq_client
from app.core.config import settings

KEY = "gsk-test-SECRET-groq-key-000"
_REQUEST = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
_STATUS_ERRORS = {400: openai.BadRequestError, 401: openai.AuthenticationError, 403: openai.PermissionDeniedError,
                  404: openai.NotFoundError, 429: openai.RateLimitError, 500: openai.InternalServerError}


def calls(*pairs):
    """One assistant turn with tool calls; args may be a dict or a raw (possibly invalid) string."""
    return ("calls", list(pairs))


def text(value):
    return ("text", value if isinstance(value, str) else json.dumps(value))


def status(code, error_code=None, headers=None, message="error"):
    return ("status", (code, error_code, headers or {}, message))


def truncated(value="{\"summary\": \"cut off"):
    """An answer that hit max_completion_tokens (finish_reason "length")."""
    return ("truncated", value if isinstance(value, str) else json.dumps(value))


def timeout():
    return ("timeout", None)


def network():
    return ("network", None)


def status_error(code, error_code=None, headers=None, message="error"):
    response = httpx.Response(code, headers=headers or {}, request=_REQUEST)
    cls = _STATUS_ERRORS.get(code, openai.APIStatusError)
    return cls(message, response=response, body={"message": message, "type": "x", "code": error_code})


class FakeGroq:
    def __init__(self, script):
        self.script = list(script)
        self.requests = []
        self.sleeps = []
        self.clients = 0
        self.closed = 0
        self.usage = None  # optional usage object attached to every response (like Groq's)

    # --- the fake SDK client -------------------------------------------------
    async def _create(self, **params):
        sent = dict(params)
        sent["messages"] = json.loads(json.dumps(params["messages"]))
        self.requests.append(sent)
        if not self.script:
            raise AssertionError("Groq called more times than scripted")
        kind, value = self.script.pop(0)
        if kind == "status":
            raise status_error(*value)
        if kind == "timeout":
            raise openai.APITimeoutError(request=_REQUEST)
        if kind == "network":
            raise openai.APIConnectionError(request=_REQUEST)
        if kind == "calls":
            step = len(self.requests)
            tool_calls = [SimpleNamespace(id=f"call_{step}_{i}", type="function", function=SimpleNamespace(
                name=name, arguments=args if isinstance(args, str) else json.dumps(args)))
                for i, (name, args) in enumerate(value)]
            message = SimpleNamespace(role="assistant", content=None, tool_calls=tool_calls,
                                      reasoning="internal reasoning")
        else:
            message = SimpleNamespace(role="assistant", content=value, tool_calls=None, reasoning="internal reasoning")
        finish = "length" if kind == "truncated" else "stop"
        response = SimpleNamespace(choices=[SimpleNamespace(index=0, message=message, finish_reason=finish)])
        if self.usage is not None:
            response.usage = self.usage
        return response

    def _client(self):
        self.clients += 1

        async def close():
            self.closed += 1

        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=self._create)), close=close)

    async def _sleep(self, seconds):
        self.sleeps.append(seconds)

    @contextmanager
    def patch(self, key=KEY, **settings_over):
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(settings, "LLM_PROVIDER", "groq"))
            stack.enter_context(mock.patch.object(settings, "GROQ_API_KEY", key))
            for name, value in settings_over.items():
                stack.enter_context(mock.patch.object(settings, name, value))
            stack.enter_context(mock.patch.object(groq_client, "_make_client", side_effect=self._client))
            stack.enter_context(mock.patch.object(groq_client, "_sleep", new=self._sleep))
            yield self

    # --- helpers for assertions ------------------------------------------------
    def tool_names(self, request_index):
        tools = self.requests[request_index].get("tools") or []
        return [t["function"]["name"] for t in tools]

    def tool_messages(self, request_index):
        """(tool_call_id, parsed result) MYMILE sent back in a given request."""
        return [(m["tool_call_id"], json.loads(m["content"]))
                for m in self.requests[request_index]["messages"] if m["role"] == "tool"]

    def echoed_calls(self, request_index):
        """(id, name, raw arguments) of the assistant tool calls echoed in a given request."""
        return [(c["id"], c["function"]["name"], c["function"]["arguments"])
                for m in self.requests[request_index]["messages"] if m["role"] == "assistant"
                for c in m.get("tool_calls") or []]
