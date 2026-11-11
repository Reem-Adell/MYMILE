import os
from typing import List, Optional
from pydantic_settings import BaseSettings
from pydantic import Field, SecretStr

# Values that have been published (in this repo or as common examples) and so
# must never be used to sign tokens. Compared case-insensitively after strip().
KNOWN_INSECURE_SECRET_KEYS = frozenset({
    "mymile-hackathon-super-secret-key-change-in-production-2026",
    "change-me", "changeme", "change_me", "change-this", "replace-me",
    "secret", "secret-key", "secret_key", "your-secret-key", "your_secret_key",
    "your-secret-key-here", "supersecret", "super-secret-key", "dev", "development",
    "test", "password", "mysecret",
})
MIN_SECRET_KEY_LENGTH = 32


class InsecureSecretKeyError(RuntimeError):
    """SECRET_KEY is missing, too short, or a known public placeholder.

    The message never contains the key itself.
    """


def validate_secret_key(value: Optional[str]) -> None:
    key = (value or "").strip()
    hint = ('Set a random SECRET_KEY in backend/.env, e.g. generate one with: '
            'python -c "import secrets; print(secrets.token_urlsafe(48))"')
    if not key:
        raise InsecureSecretKeyError(f"SECRET_KEY is missing or empty. {hint}")
    if key.lower() in KNOWN_INSECURE_SECRET_KEYS:
        raise InsecureSecretKeyError(f"SECRET_KEY is a publicly known placeholder value. {hint}")
    if len(key) < MIN_SECRET_KEY_LENGTH:
        raise InsecureSecretKeyError(
            f"SECRET_KEY must be at least {MIN_SECRET_KEY_LENGTH} characters. {hint}")


class Settings(BaseSettings):
    PROJECT_NAME: str = "MYMILE - AI Travel Agent & E-commerce Platform"
    TAGLINE: str = "Your Smile, With You Every Mile."
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api"
    
    # Security
    # Signs login tokens. No default on purpose: it must come from backend/.env
    # (or the environment). Validated in model_post_init below; repr=False keeps
    # it out of repr(settings).
    SECRET_KEY: str = Field(default="", env="SECRET_KEY", repr=False)
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days
    
    # CORS
    # Explicit origins only (no "*"): the Vite dev server.
    BACKEND_CORS_ORIGINS: List[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
    
    # AI / LLM Configuration
    # Supported providers: "gemini", "openai"
    LLM_PROVIDER: str = Field(default="gemini", env="LLM_PROVIDER")
    GEMINI_API_KEY: Optional[str] = Field(default=None, env="GEMINI_API_KEY")
    OPENAI_API_KEY: Optional[str] = Field(default=None, env="OPENAI_API_KEY")
    LLM_MODEL_NAME: str = Field(default="gemini-3.8-flash", env="LLM_MODEL_NAME")
    # Gemini agent limits. One trip plan = a few Gemini requests (tool rounds);
    # identical plan requests reuse the cached AI result for AI_PLAN_CACHE_TTL_HOURS.
    GEMINI_TIMEOUT_SECONDS: float = Field(default=90.0, env="GEMINI_TIMEOUT_SECONDS")
    AI_AGENT_DEADLINE_SECONDS: float = Field(default=180.0, env="AI_AGENT_DEADLINE_SECONDS")
    # low | medium | high (Gemini 3.8 Flash supports these; its default is medium). Empty = model default.
    GEMINI_THINKING_LEVEL: str = Field(default="low", env="GEMINI_THINKING_LEVEL")
    AI_PLAN_CACHE_TTL_HOURS: float = Field(default=24.0, env="AI_PLAN_CACHE_TTL_HOURS")
    
    # Sponsor: Channel3 E-commerce Integration
    # Official docs: https://www.channel3.ai/
    CHANNEL3_API_KEY: Optional[str] = Field(default=None, env="CHANNEL3_API_KEY")
    CHANNEL3_BASE_URL: str = Field(default="https://api.trychannel3.com", env="CHANNEL3_BASE_URL")
    # Each Channel3 search costs 1 credit (1,000 free per month), so results are
    # cached and every trip is limited to a few small searches.
    CHANNEL3_CACHE_TTL_HOURS: float = Field(default=24.0, env="CHANNEL3_CACHE_TTL_HOURS")
    CHANNEL3_TIMEOUT_SECONDS: float = Field(default=15.0, env="CHANNEL3_TIMEOUT_SECONDS")
    CHANNEL3_MAX_QUERIES_PER_TRIP: int = Field(default=3, env="CHANNEL3_MAX_QUERIES_PER_TRIP")
    CHANNEL3_RESULTS_PER_QUERY: int = Field(default=4, env="CHANNEL3_RESULTS_PER_QUERY")
    
    # Weather API (Default: Open-Meteo, 100% free and real without API key, or OpenWeatherMap)
    WEATHER_API_KEY: Optional[str] = Field(default=None, env="WEATHER_API_KEY")
    WEATHER_BASE_URL: str = Field(default="https://api.open-meteo.com/v1", env="WEATHER_BASE_URL")
    
    # Hotels & Places API
    HOTEL_API_KEY: Optional[str] = Field(default=None, env="HOTEL_API_KEY")
    HOTEL_BASE_URL: Optional[str] = Field(default=None, env="HOTEL_BASE_URL")
    # SerpApi Google Hotels (HOTEL_API_KEY above). Each distinct search (destination,
    # dates, adults) and each hotel's provider-link lookup costs one SerpApi search,
    # so results are cached in the database for this many hours.
    HOTEL_CACHE_TTL_HOURS: float = Field(default=24.0, env="HOTEL_CACHE_TTL_HOURS")
    HOTEL_API_TIMEOUT_SECONDS: float = Field(default=15.0, env="HOTEL_API_TIMEOUT_SECONDS")
    PLACES_API_KEY: Optional[str] = Field(default=None, env="PLACES_API_KEY")
    PLACES_BASE_URL: Optional[str] = Field(default=None, env="PLACES_BASE_URL")
    # Explore hero photos come from Wikipedia / Wikimedia Commons (no API key).
    # Wikimedia requires API clients to send contact details in the User-Agent
    # (an email address or website you choose). Empty = no photo lookups; the
    # Explore hero then shows its fallback.
    WIKIMEDIA_CONTACT: Optional[str] = Field(default=None, env="WIKIMEDIA_CONTACT")

    # Sponsor: PayPal Payments (PayPal Server SDK, generated by APIMatic)
    # Official docs: https://developer.paypal.com/
    # Sandbox only for now. Credentials come from a Sandbox REST app at
    # https://developer.paypal.com/dashboard/applications/sandbox
    PAYPAL_CLIENT_ID: Optional[str] = Field(default=None, env="PAYPAL_CLIENT_ID")
    # SecretStr masks the value as '**********' in repr/str/logs; read it only
    # with .get_secret_value() at the point it is handed to the SDK.
    PAYPAL_CLIENT_SECRET: Optional[SecretStr] = Field(default=None, env="PAYPAL_CLIENT_SECRET")
    PAYPAL_ENVIRONMENT: str = Field(default="sandbox", env="PAYPAL_ENVIRONMENT")
    PAYPAL_CURRENCY: str = Field(default="USD", env="PAYPAL_CURRENCY")
    PAYPAL_TIMEOUT_SECONDS: int = Field(default=30, env="PAYPAL_TIMEOUT_SECONDS")

    # Premium pass: a ONE-TIME payment that unlocks Premium for a fixed number
    # of days. It is NOT a recurring subscription and does not auto-renew.
    # Price is a string so it is sent to PayPal exactly as written (no float rounding).
    PREMIUM_PRICE: str = Field(default="9.00", env="PREMIUM_PRICE")
    PREMIUM_CURRENCY: str = Field(default="USD", env="PREMIUM_CURRENCY")
    PREMIUM_DURATION_DAYS: int = Field(default=30, env="PREMIUM_DURATION_DAYS")

    def model_post_init(self, __context) -> None:
        # Runs during Settings() construction, so the app refuses to start with
        # an unsafe key. Raised as a plain exception (not a pydantic
        # ValidationError) because ValidationError would echo the value.
        validate_secret_key(self.SECRET_KEY)

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

settings = Settings()
