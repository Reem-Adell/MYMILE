"""
Gemini function-calling loop.

    model turn -> (function calls?) -> execute real backend tools -> results back
    -> ... until the model answers in text (or MAX_ROUNDS is reached).

The final answer must be a JSON object. If the text isn't valid JSON, ONE extra
request asks Gemini to restate it as JSON (JSON mode, no tools). Anything else
raises GeminiError so callers can show a clearly labelled non-AI result.
"""
import asyncio
import json
import re
import time
from typing import Any, List, Optional, Tuple

from app.agents import gemini_client
from app.agents.gemini_client import GeminiError
from app.agents.tools import AgentToolbox
from app.core.config import settings

MAX_ROUNDS = 5  # Gemini requests with tools per run (the last one is forced to answer)


def extract_json(text: Optional[str]) -> Optional[dict]:
    if not text:
        return None
    candidates = [text.strip()]
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fenced:
        candidates.insert(0, fenced.group(1).strip())
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start:end + 1])
    for c in candidates:
        try:
            value = json.loads(c)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    return None


def _text(response) -> str:
    try:
        return response.text or ""
    except (ValueError, AttributeError):
        return ""


async def run_agent(system_instruction: str, user_prompt: str, toolbox: Optional[AgentToolbox],
                    history: Optional[List[Any]] = None) -> Tuple[dict, int]:
    """Returns (final JSON object, number of Gemini requests). Raises GeminiError."""
    from google.genai import types

    deadline = time.monotonic() + float(settings.AI_AGENT_DEADLINE_SECONDS or 180)
    contents: List[Any] = list(history or [])
    contents.append(types.Content(role="user", parts=[types.Part(text=user_prompt)]))
    requests = 0

    async def call(**kwargs):
        nonlocal requests
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise GeminiError("TIMEOUT")
        requests += 1
        try:
            return await asyncio.wait_for(gemini_client.generate(contents, system_instruction, **kwargs),
                                          timeout=remaining)
        except asyncio.TimeoutError:
            raise GeminiError("TIMEOUT") from None

    text = ""
    last_content = None  # the model's final turn exactly as received
    for round_no in range(MAX_ROUNDS):
        allow_tools = toolbox is not None and round_no < MAX_ROUNDS - 1 and toolbox.calls_left > 0
        response = await call(tools=toolbox.declarations() if allow_tools else None,
                              json_output=not allow_tools)
        calls = list(getattr(response, "function_calls", None) or []) if allow_tools else []
        if not calls:
            text = _text(response)
            last_content = getattr(response.candidates[0], "content", None) if response.candidates else None
            break
        contents.append(response.candidates[0].content)
        parts = []
        for fc in calls:
            result = await toolbox.execute(fc.name, dict(fc.args or {}))
            # Echo the call's id so each result stays matched to its call, including
            # parallel calls of the same tool (id is None when Gemini sends none).
            parts.append(types.Part(function_response=types.FunctionResponse(
                id=fc.id, name=fc.name, response={"result": result})))
        contents.append(types.Content(role="user", parts=parts))

    data = extract_json(text)
    if data is None:
        # Send the model's turn back unchanged (thought signatures included), unless it
        # holds function calls we didn't execute: unanswered calls would be rejected.
        if last_content is not None and last_content.parts and \
                not any(p.function_call for p in last_content.parts):
            contents.append(last_content)
        contents.append(types.Content(role="user", parts=[types.Part(
            text="Return your final answer now as one JSON object exactly as specified, with no other text.")]))
        data = extract_json(_text(await call(tools=None, json_output=True)))
    if data is None:
        raise GeminiError("INVALID_RESPONSE")
    return data, requests
