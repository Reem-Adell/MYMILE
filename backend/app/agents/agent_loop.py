"""
Function-calling loop (Groq by default, Gemini when LLM_PROVIDER=gemini).

    model turn -> (tool calls?) -> execute real backend tools -> results back
    -> ... until the model answers in text (or MAX_ROUNDS is reached).

The final answer must be a JSON object. If the text isn't valid JSON, ONE extra
request asks the model to restate it as JSON (JSON mode, no tools). Anything else
raises LLMError so callers can show a clearly labelled non-AI result.

`history` is provider-neutral: [{"role": "user" | "assistant", "content": "..."}].
"""
import asyncio
import json
import logging
import re
import time
from typing import Any, List, Optional, Tuple

from app.agents import gemini_client, groq_client, llm
from app.agents.gemini_client import GeminiError
from app.agents.groq_client import GroqError
from app.agents.tools import AgentToolbox
from app.core.config import settings

log = logging.getLogger(__name__)

MAX_ROUNDS = 5  # model requests with tools per run (the last one is forced to answer)
JSON_RETRY_PROMPT = "Return your final answer now as one JSON object exactly as specified, with no other text."


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
                    history: Optional[List[dict]] = None) -> Tuple[dict, int]:
    """Returns (final JSON object, number of model requests). Raises LLMError."""
    if llm.provider() == "gemini":
        return await _run_gemini(system_instruction, user_prompt, toolbox, history)
    return await _run_groq(system_instruction, user_prompt, toolbox, history)


# ------------------------------------------------------------------ Groq ---
def _tool_args(raw: Any) -> Optional[dict]:
    """Arguments of an OpenAI-style tool call, or None when they aren't a JSON object."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return {}
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


async def _run_groq(system_instruction: str, user_prompt: str, toolbox: Optional[AgentToolbox],
                    history: Optional[List[dict]]) -> Tuple[dict, int]:
    deadline = time.monotonic() + float(settings.AI_AGENT_DEADLINE_SECONDS or 180)
    messages: List[dict] = [{"role": "system", "content": system_instruction}]
    for msg in history or []:
        messages.append({"role": "assistant" if msg.get("role") == "assistant" else "user",
                         "content": str(msg.get("content") or "")})
    messages.append({"role": "user", "content": user_prompt})
    requests = 0

    async def call(**kwargs):
        nonlocal requests
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise GroqError("TIMEOUT")
        requests += 1
        try:
            return await asyncio.wait_for(groq_client.generate(messages, deadline=deadline, **kwargs),
                                          timeout=remaining)
        except asyncio.TimeoutError:
            raise GroqError("TIMEOUT") from None

    text = ""
    malformed = 0  # Groq "tool_use_failed" rejections: one retry, then answer without tools
    for round_no in range(MAX_ROUNDS):
        tools = (toolbox.openai_tools() if toolbox is not None and round_no < MAX_ROUNDS - 1
                 and toolbox.calls_left > 0 and malformed < 2 else None)
        try:
            # Only a round that should be a tool call (planning's Channel3 search) gets the small
            # limit; any other round may be the final JSON, so it gets the final-answer limit.
            tool_round = bool(tools) and toolbox.expects_tool_call
            response = await call(tools=tools or None, json_output=not tools,
                                  max_tokens=(groq_client.tool_round_max_tokens() if tool_round
                                              else groq_client.final_max_tokens()),
                                  purpose=f"round {round_no + 1} " + ("tool call" if tool_round else "may answer"))
        except GroqError as err:
            if err.code == "MALFORMED_TOOL_CALL" and tools:
                malformed += 1
                log.warning("Groq rejected a malformed tool call (%d)", malformed)
                continue
            raise
        message = response.choices[0].message
        truncated = getattr(response.choices[0], "finish_reason", None) == "length"
        tool_calls = list(getattr(message, "tool_calls", None) or []) if tools and not truncated else []
        if not tool_calls:
            # A cut-off answer is never used or sent back: the retry below asks again with room.
            text = "" if truncated else (getattr(message, "content", None) or "")
            if truncated:
                log.warning("Groq answer hit its completion limit in round %d; asking again", round_no + 1)
            break
        # gpt-oss makes one call per turn; any number is handled. The model's
        # reasoning text is not sent back (it isn't needed and costs tokens).
        echoed, results = [], []
        for i, tc in enumerate(tool_calls):
            call_id = getattr(tc, "id", None) or f"call_{round_no}_{i}"
            name = str(getattr(tc.function, "name", "") or "")
            raw_args = getattr(tc.function, "arguments", None)
            echoed.append({"id": call_id, "type": "function",
                           "function": {"name": name, "arguments": raw_args if isinstance(raw_args, str)
                                        else json.dumps(raw_args or {})}})
            args = _tool_args(raw_args)
            if args is None:
                result = {"error": "The tool arguments were not a valid JSON object. "
                                   "Call the tool again with valid arguments, or answer with what you have."}
            else:
                result = await toolbox.execute(name, args)
            results.append({"role": "tool", "tool_call_id": call_id,
                            "content": json.dumps(result, ensure_ascii=False, separators=(",", ":"), default=str)})
        messages.append({"role": "assistant", "content": getattr(message, "content", None) or None,
                         "tool_calls": echoed})
        messages.extend(results)

    data = extract_json(text)
    if data is None:
        if text:
            messages.append({"role": "assistant", "content": text})
        messages.append({"role": "user", "content": JSON_RETRY_PROMPT})
        # The single retry gets the full ceiling, so a long answer is not cut off again.
        response = await call(tools=None, json_output=True, max_tokens=groq_client.max_completion_tokens(),
                              purpose="json retry")
        if getattr(response.choices[0], "finish_reason", None) == "length":
            log.warning("Groq JSON retry hit the completion ceiling; the answer is not used")
        else:
            data = extract_json(getattr(response.choices[0].message, "content", None))
    if data is None:
        raise GroqError("INVALID_RESPONSE")
    return data, requests


# ---------------------------------------------------------------- Gemini ---
async def _run_gemini(system_instruction: str, user_prompt: str, toolbox: Optional[AgentToolbox],
                      history: Optional[List[dict]]) -> Tuple[dict, int]:
    from google.genai import types

    deadline = time.monotonic() + float(settings.AI_AGENT_DEADLINE_SECONDS or 180)
    contents: List[Any] = [types.Content(role="model" if m.get("role") == "assistant" else "user",
                                         parts=[types.Part(text=str(m.get("content") or ""))])
                           for m in history or []]
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
        contents.append(types.Content(role="user", parts=[types.Part(text=JSON_RETRY_PROMPT)]))
        data = extract_json(_text(await call(tools=None, json_output=True)))
    if data is None:
        raise GeminiError("INVALID_RESPONSE")
    return data, requests
