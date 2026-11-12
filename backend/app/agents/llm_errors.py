"""Provider-neutral AI error: a fixed code plus a fixed, key-free message."""


class LLMError(Exception):
    """Base class for Groq/Gemini failures. Subclasses set MESSAGES (code -> user-facing text)."""

    MESSAGES = {
        "UNSUPPORTED_PROVIDER": 'LLM_PROVIDER must be "groq" or "gemini".',
        "SERVICE_ERROR": "The AI provider returned an error. Please try again.",
    }

    def __init__(self, code: str):
        self.code = code
        self.message = (self.MESSAGES.get(code) or self.MESSAGES.get("SERVICE_ERROR")
                        or LLMError.MESSAGES["SERVICE_ERROR"])
        super().__init__(f"{code}: {self.message}")
