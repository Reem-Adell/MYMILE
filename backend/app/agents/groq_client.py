"""
Groq access through its OpenAI-compatible Chat Completions API, using the official
`openai` SDK (already a backend dependency).

Configuration (backend/.env, read via app.core.config.settings):
    LLM_PROVIDER=groq                 primary provider
    GROQ_API_KEY=...                  required for any AI feature
    GROQ_MODEL=openai/gpt-oss-120b
    GROQ_BASE_URL=https://api.groq.com/openai/v1
    GROQ_TIMEOUT_SECONDS=60           per Groq request (capped by the agent's overall deadline)
    GROQ_REASONING_EFFORT=low         low | medium | high (empty = model default)
    GROQ_TOOL_ROUND_MAX_TOKENS=1024   output cap of tool-call rounds (reasoning included)
    GROQ_FINAL_BASE_TOKENS=3000       final JSON answer, capped at GROQ_MAX_COMPLETION_TOKENS
    GROQ_MAX_COMPLETION_TOKENS=8192   ceiling, also used for the one retry after a truncated answer
    GROQ_RATE_LIMIT_RETRIES=2         429 retries per request, honouring retry-after
    GROQ_RETRY_MAX_WAIT_SECONDS=20    a longer retry-after (e.g. daily quota) is reported, not waited for

The API key is passed only to the SDK client. It is never logged, returned or put
into an error message: every failure is mapped to a fixed, key-free GroqError.
The SDK's own retries are disabled; the only retry is the bounded 429 retry below.
"""
import asyncio
import logging
import re
import time
from typing import Any, List, Optional

from app.agents.llm_errors import LLMError
from app.core.config import settings

log = logging.getLogger(__name__)

DEFAULT_MODEL = "openai/gpt-oss-120b"
DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"
REASONING_EFFORTS = ("low", "medium", "high")
DEFAULT_RETRY_WAIT = 2.0  # seconds, when a 429 carries no retry-after information
_sleep = asyncio.sleep  # indirection so tests can observe retry waits without sleeping

ERROR_MESSAGES = {
    "NOT_CONFIGURED": "Groq is not configured (GROQ_API_KEY is empty).",
    "SDK_MISSING": "The openai package is not installed on the server.",
    "INVALID_API_KEY": "Groq rejected the configured API key.",
    "QUOTA_EXHAUSTED": "The Groq rate limit or quota has been reached. Please try again later.",
    "REQUEST_TOO_LARGE": "This request is larger than the Groq rate limit allows. Please try again later.",
    "MODEL_UNAVAILABLE": "The configured Groq model is not available (check GROQ_MODEL).",
    "TIMEOUT": "Groq took too long to answer.",
    "NETWORK": "The server couldn't reach Groq.",
    "SERVICE_ERROR": "Groq returned a server error. Please try again.",
    "INVALID_RESPONSE": "Groq returned a response MYMILE couldn't use.",
    "MALFORMED_TOOL_CALL": "The Groq model produced an invalid tool call.",
    "BAD_REQUEST": "Groq rejected MYMILE's request settings (check GROQ_MODEL and GROQ_REASONING_EFFORT).",
}


class GroqError(LLMError):
    """A Groq failure with a fixed, key-free message."""

    MESSAGES = ERROR_MESSAGES


def api_key() -> str:
    return (settings.GROQ_API_KEY or "").strip()


def resolve_model() -> str:
    return (settings.GROQ_MODEL or "").strip() or DEFAULT_MODEL


def base_url() -> str:
    return (settings.GROQ_BASE_URL or "").strip().rstrip("/") or DEFAULT_BASE_URL


def timeout_seconds() -> float:
    return max(float(settings.GROQ_TIMEOUT_SECONDS or 60), 1.0)


def max_completion_tokens() -> int:
    """Ceiling for any request (and the retry after a truncated final answer)."""
    return max(int(settings.GROQ_MAX_COMPLETION_TOKENS or 8192), 256)


def tool_round_max_tokens() -> int:
    """Rounds that may call tools: a tool call is short."""
    return min(max(int(settings.GROQ_TOOL_ROUND_MAX_TOKENS or 1024), 256), max_completion_tokens())


def final_max_tokens() -> int:
    """The final JSON answer (summary, hotel choice, product picks), within the ceiling."""
    return min(max(int(settings.GROQ_FINAL_BASE_TOKENS or 3000), 512), max_completion_tokens())


# --------------------------------------------------------------- logging ---
RATE_LIMIT_HEADERS = ("retry-after", "x-ratelimit-limit-requests", "x-ratelimit-remaining-requests",
                      "x-ratelimit-reset-requests", "x-ratelimit-limit-tokens", "x-ratelimit-remaining-tokens",
                      "x-ratelimit-reset-tokens")
_LIMIT_KIND = re.compile(r"\((RPM|RPD|TPM|TPD|ASH|ASD|ITPM|OTPM)\)")
_SECRETS = re.compile(r"(gsk[_-]|sk-|AIza)[A-Za-z0-9_\-]+|\borg_[A-Za-z0-9]+", re.I)


def _field(obj, name):
    if obj is None:
        return None
    return obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)


def usage_summary(response) -> dict:
    """Token usage reported by Groq; missing fields are None (never guessed)."""
    usage = _field(response, "usage")
    out = {k: _field(usage, k) for k in ("prompt_tokens", "completion_tokens", "total_tokens")}
    out["cached_tokens"] = _field(_field(usage, "prompt_tokens_details"), "cached_tokens")
    out["reasoning_tokens"] = _field(_field(usage, "completion_tokens_details"), "reasoning_tokens")
    return {k: (v if isinstance(v, int) else None) for k, v in out.items()}


def log_usage(response, purpose: str) -> None:
    u = usage_summary(response)
    choices = getattr(response, "choices", None) or []
    finish = getattr(choices[0], "finish_reason", None) if choices else None
    log.info("Groq usage (%s, model=%s): prompt=%s completion=%s total=%s cached=%s reasoning=%s finish=%s",
             purpose, resolve_model(), u["prompt_tokens"], u["completion_tokens"], u["total_tokens"],
             u["cached_tokens"], u["reasoning_tokens"], finish)


def rate_limit_details(exc: Exception) -> dict:
    """Groq's 429/413 message (identifiers masked, clipped), the limit kind it names
    (RPM/RPD/TPM/TPD...) and the rate-limit headers. No keys, prompts or payloads."""
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    found = {}
    if headers is not None and hasattr(headers, "get"):
        for name in RATE_LIMIT_HEADERS:
            value = headers.get(name)
            if value is not None:
                found[name] = str(value)[:40]
    body = getattr(exc, "body", None)
    message = _field(body, "message") if isinstance(body, dict) else None
    message = str(message or getattr(exc, "message", "") or "")
    message = _SECRETS.sub(lambda m: m.group(0)[:4] + "***", message)[:300]
    kind = _LIMIT_KIND.search(message)
    return {"limit": kind.group(1) if kind else None, "message": message, "headers": found}


def log_rate_limit(exc: Exception, wait: float, retrying: bool) -> None:
    d = rate_limit_details(exc)
    log.warning("Groq rate limit (HTTP %s, limit=%s, retry-after %.1fs, %s): %s | headers=%s",
                getattr(exc, "status_code", "?"), d["limit"] or "unknown", wait,
                "retrying" if retrying else "not retrying", d["message"] or "(no message)", d["headers"] or "{}")


def rate_limit_retries() -> int:
    return max(min(int(settings.GROQ_RATE_LIMIT_RETRIES or 0), 5), 0)


def retry_max_wait() -> float:
    return max(float(settings.GROQ_RETRY_MAX_WAIT_SECONDS or 0), 0.0)


def reasoning_effort() -> Optional[str]:
    level = (settings.GROQ_REASONING_EFFORT or "").strip().lower()
    if not level:
        return None
    if level not in REASONING_EFFORTS:
        log.warning("GROQ_REASONING_EFFORT=%s is not one of %s; using the model default", level, REASONING_EFFORTS)
        return None
    return level


def check_available() -> None:
    """Raise GroqError when AI can't be used at all (no request is made)."""
    if not api_key():
        raise GroqError("NOT_CONFIGURED")


def describe() -> dict:
    try:
        check_available()
        state = "configured"
    except GroqError as err:
        state = err.code.lower()
    return {"provider": "groq", "model": resolve_model(), "status": state}


def _make_client():
    try:
        from openai import AsyncOpenAI
    except ImportError:
        raise GroqError("SDK_MISSING") from None
    return AsyncOpenAI(api_key=api_key(), base_url=base_url(), max_retries=0, timeout=timeout_seconds())


_DURATION = re.compile(r"try again in\s+(?:(\d+(?:\.\d+)?)m(?!s))?\s*(?:(\d+(?:\.\d+)?)(ms|s))?", re.I)


def retry_after_seconds(exc: Exception) -> Optional[float]:
    """Seconds to wait from a 429: the retry-after header, else Groq's 'try again in 7.5s' text."""
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None) or {}
    value = headers.get("retry-after") if hasattr(headers, "get") else None
    if value is not None:
        try:
            return max(float(value), 0.0)
        except (TypeError, ValueError):
            pass
    match = _DURATION.search(str(getattr(exc, "message", "") or exc))
    if match and (match.group(1) or match.group(2)):
        minutes = float(match.group(1) or 0)
        amount = float(match.group(2) or 0)
        return minutes * 60 + (amount / 1000 if (match.group(3) or "").lower() == "ms" else amount)
    return None


def _map_status_error(exc: Exception) -> GroqError:
    status = getattr(exc, "status_code", None)
    code = str(getattr(exc, "code", "") or "").lower()
    if status == 400 and code == "tool_use_failed":
        return GroqError("MALFORMED_TOOL_CALL")
    if status in (401, 403):
        return GroqError("INVALID_API_KEY")
    if status == 404 or code == "model_not_found":
        return GroqError("MODEL_UNAVAILABLE")
    if status == 413:
        return GroqError("REQUEST_TOO_LARGE")
    if status == 429:
        return GroqError("QUOTA_EXHAUSTED")
    if status in (408, 504):
        return GroqError("TIMEOUT")
    if isinstance(status, int) and status >= 500:
        return GroqError("SERVICE_ERROR")
    if status in (400, 422):
        return GroqError("BAD_REQUEST")
    return GroqError("SERVICE_ERROR")


async def _request(params: dict, timeout: float):
    import openai

    client = _make_client()
    try:
        return await asyncio.wait_for(client.chat.completions.create(**params, timeout=timeout),
                                      timeout=timeout + 5)  # local safety net
    except (asyncio.TimeoutError, openai.APITimeoutError):
        log.warning("Groq request timed out")
        raise GroqError("TIMEOUT") from None
    except openai.APIConnectionError as exc:
        log.warning("Groq request failed: %s", type(exc).__name__)
        raise GroqError("NETWORK") from None
    finally:
        try:
            await client.close()
        except Exception:  # closing must never mask the real outcome
            pass


async def generate(messages: List[dict], tools: Optional[list] = None, json_output: bool = False,
                   deadline: Optional[float] = None, max_tokens: Optional[int] = None,
                   purpose: str = "request") -> Any:
    """One Groq chat completion (tools are executed by the agent loop, not here).
    Returns the SDK response, which has at least one choice. Raises GroqError.

    429s are retried at most GROQ_RATE_LIMIT_RETRIES times, waiting for the provider's
    retry-after, and only when that wait is short and still fits before `deadline`
    (a time.monotonic() value). Anything else is raised at once."""
    check_available()
    import openai

    params = {"model": resolve_model(), "messages": messages,
              "max_completion_tokens": max_tokens or max_completion_tokens()}
    if tools:
        params["tools"] = tools
        params["tool_choice"] = "auto"
    elif json_output:
        params["response_format"] = {"type": "json_object"}
    effort = reasoning_effort()
    if effort:
        params["reasoning_effort"] = effort

    if deadline is None:
        deadline = time.monotonic() + timeout_seconds()
    retries = 0
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise GroqError("TIMEOUT")
        try:
            response = await _request(params, min(timeout_seconds(), remaining))
            break
        except openai.RateLimitError as exc:
            wait = retry_after_seconds(exc)
            wait = DEFAULT_RETRY_WAIT if wait is None else wait
            retries += 1
            fits = wait <= retry_max_wait() and time.monotonic() + wait + 1 < deadline
            retrying = retries <= rate_limit_retries() and fits
            log_rate_limit(exc, wait, retrying)
            if not retrying:
                raise GroqError("QUOTA_EXHAUSTED") from None
            await _sleep(wait)
        except openai.APIStatusError as exc:
            err = _map_status_error(exc)
            if getattr(exc, "status_code", None) == 413:  # a single request above the TPM limit
                log_rate_limit(exc, 0.0, False)
            log.warning("Groq request failed: %s (HTTP %s)", err.code, getattr(exc, "status_code", "?"))
            raise err from None
        except GroqError:
            raise
        except openai.OpenAIError as exc:
            log.warning("Groq request failed: %s", type(exc).__name__)
            raise GroqError("SERVICE_ERROR") from None

    if not getattr(response, "choices", None):
        raise GroqError("INVALID_RESPONSE")
    try:
        log_usage(response, purpose)
    except Exception:  # logging must never break a request
        pass
    return response
