"""
Google Gemini access through the official `google-genai` SDK.

Configuration (backend/.env, read via app.core.config.settings):
    LLM_PROVIDER=gemini           only "gemini" is implemented
    GEMINI_API_KEY=...            required for any AI feature
    LLM_MODEL_NAME=...            default gemini-3.8-flash; retired 1.x names are replaced
    GEMINI_TIMEOUT_SECONDS=90     per Gemini request (also sent to Google as its server deadline)
    GEMINI_THINKING_LEVEL=low     low | medium | high (empty = model default)

The API key is passed only to the SDK client. It is never logged, returned or put
into an error message: every failure is mapped to a fixed, key-free GeminiError.
"""
import asyncio
import logging
from typing import Any, List, Optional

import httpx

from app.core.config import settings

log = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-3.8-flash"
# Gemini 1.0/1.5 models have been shut down by Google; requests to them fail.
RETIRED_PREFIXES = ("gemini-1.", "gemini-pro", "gemini-ultra")

ERROR_MESSAGES = {
    "NOT_CONFIGURED": "Gemini is not configured (GEMINI_API_KEY is empty).",
    "UNSUPPORTED_PROVIDER": "Only LLM_PROVIDER=gemini is supported.",
    "SDK_MISSING": "The google-genai package is not installed on the server.",
    "INVALID_API_KEY": "Gemini rejected the configured API key.",
    "QUOTA_EXHAUSTED": "The Gemini API quota or rate limit has been reached. Please try again later.",
    "MODEL_UNAVAILABLE": "The configured Gemini model is not available (check LLM_MODEL_NAME).",
    "TIMEOUT": "Gemini took too long to answer.",
    "NETWORK": "The server couldn't reach Gemini.",
    "SERVICE_ERROR": "Gemini returned a server error. Please try again.",
    "BLOCKED": "Gemini declined to answer this request.",
    "INVALID_RESPONSE": "Gemini returned a response MYMILE couldn't use.",
    "BAD_REQUEST": "Gemini rejected MYMILE's request settings (check LLM_MODEL_NAME and GEMINI_THINKING_LEVEL).",
}
THINKING_LEVELS = ("low", "medium", "high")


class GeminiError(Exception):
    """A Gemini failure with a fixed, key-free message."""

    def __init__(self, code: str):
        self.code = code
        self.message = ERROR_MESSAGES.get(code, ERROR_MESSAGES["SERVICE_ERROR"])
        super().__init__(f"{code}: {self.message}")


def api_key() -> str:
    return (settings.GEMINI_API_KEY or "").strip()


def provider() -> str:
    return (settings.LLM_PROVIDER or "gemini").strip().lower()


def resolve_model() -> str:
    name = (settings.LLM_MODEL_NAME or "").strip()
    if not name:
        return DEFAULT_MODEL
    if name.lower().startswith(RETIRED_PREFIXES):
        log.warning("LLM_MODEL_NAME %s is a retired Gemini model; using %s instead", name, DEFAULT_MODEL)
        return DEFAULT_MODEL
    return name


def check_available() -> None:
    """Raise GeminiError when AI can't be used at all (no request is made)."""
    if provider() != "gemini":
        raise GeminiError("UNSUPPORTED_PROVIDER")
    if not api_key():
        raise GeminiError("NOT_CONFIGURED")


def describe() -> dict:
    """Health info: no key material."""
    try:
        check_available()
        state = "configured"
    except GeminiError as err:
        state = err.code.lower()
    return {"provider": provider(), "model": resolve_model(), "status": state}


def timeout_seconds() -> float:
    return max(float(settings.GEMINI_TIMEOUT_SECONDS or 90), 1.0)


def thinking_level() -> Optional[str]:
    """Configured thinking level, or None to use the model's default."""
    level = (settings.GEMINI_THINKING_LEVEL or "").strip().lower()
    if not level:
        return None
    if level not in THINKING_LEVELS:
        log.warning("GEMINI_THINKING_LEVEL=%s is not one of %s; using the model default", level, THINKING_LEVELS)
        return None
    return level


def _make_client():
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        raise GeminiError("SDK_MISSING") from None
    return genai.Client(api_key=api_key(), http_options=types.HttpOptions(
        timeout=int(timeout_seconds() * 1000),
        retry_options=types.HttpRetryOptions(attempts=1),  # never retry silently
    ))


def _map_api_error(exc: Exception) -> GeminiError:
    code = getattr(exc, "code", None)
    status = str(getattr(exc, "status", "") or "").upper()
    text = str(getattr(exc, "message", "") or "").lower()
    if code == 429 or status == "RESOURCE_EXHAUSTED":
        return GeminiError("QUOTA_EXHAUSTED")
    if code in (401, 403) or "api key" in text or "api_key" in text or status == "PERMISSION_DENIED":
        return GeminiError("INVALID_API_KEY")
    if code == 404 or status == "NOT_FOUND":
        return GeminiError("MODEL_UNAVAILABLE")
    if code == 504 or status == "DEADLINE_EXCEEDED":
        return GeminiError("TIMEOUT")
    if isinstance(code, int) and code >= 500:
        return GeminiError("SERVICE_ERROR")
    return GeminiError("BAD_REQUEST" if code == 400 or status in ("INVALID_ARGUMENT", "FAILED_PRECONDITION")
                       else "SERVICE_ERROR")


async def generate(contents: List[Any], system_instruction: str, tools: Optional[list] = None,
                   json_output: bool = False, max_output_tokens: int = 8192):
    """One Gemini request (no automatic function calling: the agent loop executes tools).
    Returns the SDK response. Raises GeminiError.

    No temperature/top_p/top_k: Google deprecated them from Gemini 3.6 Flash onward
    ("deprecated and ignored ... Remove these parameters from all requests"; future
    models reject them with HTTP 400). Determinism comes from the system instruction."""
    check_available()
    from google.genai import errors, types

    level = thinking_level()
    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        max_output_tokens=max_output_tokens,
        tools=tools or None,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        response_mime_type="application/json" if json_output and not tools else None,
        thinking_config=types.ThinkingConfig(thinking_level=level.upper()) if level else None,
    )
    client = _make_client()
    try:
        response = await asyncio.wait_for(
            client.aio.models.generate_content(model=resolve_model(), contents=contents, config=config),
            timeout=timeout_seconds() + 5,  # local safety net; Google enforces timeout_seconds() itself
        )
    except GeminiError:
        raise
    except errors.APIError as exc:
        err = _map_api_error(exc)
        log.warning("Gemini request failed: %s (HTTP %s)", err.code, getattr(exc, "code", "?"))
        raise err from None
    except (asyncio.TimeoutError, httpx.TimeoutException):
        log.warning("Gemini request timed out")
        raise GeminiError("TIMEOUT") from None
    except httpx.HTTPError as exc:
        log.warning("Gemini request failed: %s", type(exc).__name__)
        raise GeminiError("NETWORK") from None
    except Exception as exc:  # e.g. aiohttp errors (the SDK uses aiohttp when installed)
        name = type(exc).__name__
        log.warning("Gemini request failed: %s", name)
        raise GeminiError("NETWORK" if "Client" in name or "Connection" in name or "OSError" in name
                          else "SERVICE_ERROR") from None

    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        feedback = getattr(response, "prompt_feedback", None)
        raise GeminiError("BLOCKED" if getattr(feedback, "block_reason", None) else "INVALID_RESPONSE")
    return response
