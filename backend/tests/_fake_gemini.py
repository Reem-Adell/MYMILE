"""
A scripted stand-in for gemini_client.generate (no network, no quota).

    fake = FakeGemini([calls(("search_hotels", {})), text({"reply": "..."})])
    with fake.patch(): ...

Each scripted step is returned for one Gemini request. `fake.requests` records
what MYMILE sent (system instruction, contents, whether tools were offered).
"""
import json
from types import SimpleNamespace
from unittest import mock

from google.genai import types

from app.agents import gemini_client
from app.core.config import settings


def calls(*pairs):
    return ("calls", list(pairs))


def text(value):
    return ("text", value if isinstance(value, str) else json.dumps(value))


def error(code):
    return ("error", code)


class FakeGemini:
    def __init__(self, script):
        self.script = list(script)
        self.requests = []

    async def __call__(self, contents, system_instruction, tools=None, json_output=False, **kwargs):
        self.requests.append({"system": system_instruction, "contents": list(contents),
                              "tools": tools, "json_output": json_output})
        if not self.script:
            raise AssertionError("Gemini called more times than scripted")
        kind, value = self.script.pop(0)
        if kind == "error":
            raise gemini_client.GeminiError(value)
        if kind == "calls":
            # Unique ids, like Gemini; MYMILE must echo each one in its function response.
            step = len(self.requests)
            fcs = [types.FunctionCall(id=f"call-{step}-{i}", name=n, args=a) for i, (n, a) in enumerate(value)]
            content = types.Content(role="model", parts=[types.Part(function_call=fc) for fc in fcs])
            return SimpleNamespace(function_calls=fcs, candidates=[SimpleNamespace(content=content)], text=None)
        content = types.Content(role="model", parts=[types.Part(text=value)])
        return SimpleNamespace(function_calls=None, candidates=[SimpleNamespace(content=content)], text=value)

    def patch(self, key="test-gemini-key"):
        stack = [mock.patch.object(gemini_client, "generate", new=self.__call__),
                 mock.patch.object(settings, "GEMINI_API_KEY", key)]

        class _Ctx:
            def __enter__(self_inner):
                for p in stack:
                    p.start()
                return self

            def __exit__(self_inner, *exc):
                for p in reversed(stack):
                    p.stop()
        return _Ctx()

    def function_responses(self, request_index):
        """(id, name, result) for each function response sent in a given request."""
        return [(part.function_response.id, part.function_response.name, part.function_response.response["result"])
                for content in self.requests[request_index]["contents"] for part in content.parts or []
                if part.function_response is not None]

    def function_calls_made(self, request_index):
        """(id, name, args) of the function calls the model made (echoed back in the next request)."""
        return [(part.function_call.id, part.function_call.name, dict(part.function_call.args or {}))
                for content in self.requests[request_index]["contents"] for part in content.parts or []
                if part.function_call is not None]

    def tool_results(self, request_index):
        """Function responses MYMILE sent back to the model in a given request."""
        out = []
        for content in self.requests[request_index]["contents"]:
            for part in content.parts or []:
                if part.function_response is not None:
                    out.append((part.function_response.name, part.function_response.response["result"]))
        return out
