"""
Which LLM provider this process uses, chosen ONLY by LLM_PROVIDER:

    groq    (default, primary)  -> app.agents.groq_client   (GROQ_API_KEY, GROQ_MODEL)
    gemini  (optional, legacy)  -> app.agents.gemini_client (GEMINI_API_KEY, LLM_MODEL_NAME)

There is no automatic fallback between providers: a Groq failure is reported as
such and never spends Gemini quota.
"""
from app.agents import gemini_client, groq_client
from app.agents.llm_errors import LLMError
from app.core.config import settings

PROVIDERS = {"groq": groq_client, "gemini": gemini_client}
ERRORS = {"groq": groq_client.GroqError, "gemini": gemini_client.GeminiError}


def provider() -> str:
    return (settings.LLM_PROVIDER or "groq").strip().lower()


def error(code: str) -> LLMError:
    """An error of the active provider's type (its messages name that provider)."""
    return ERRORS.get(provider(), LLMError)(code)


def check_available() -> None:
    """Raise LLMError when AI can't be used at all (no request is made)."""
    client = PROVIDERS.get(provider())
    if client is None:
        raise LLMError("UNSUPPORTED_PROVIDER")
    client.check_available()


def resolve_model() -> str:
    client = PROVIDERS.get(provider())
    return client.resolve_model() if client else ""


def describe() -> dict:
    """Health info: no key material."""
    client = PROVIDERS.get(provider())
    if client is None:
        return {"provider": provider(), "model": "", "status": "unsupported_provider"}
    return client.describe()
