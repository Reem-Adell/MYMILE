"""
PayPal Server SDK client (Sandbox only).

One long-lived client is built on first use and reused for the life of the
process, so the SDK can cache its OAuth access token and reuse connections.

The client is built explicitly from `settings` rather than with
`PaypalServersdkClient.from_environment()`: that helper reads a generic
`ENVIRONMENT` variable (ours is "development") and `O_AUTH_CLIENT_ID` /
`O_AUTH_CLIENT_SECRET`, not the PAYPAL_* names this project uses.
"""
from threading import Lock
from typing import Optional

from paypalserversdk.configuration import Environment
from paypalserversdk.http.auth.o_auth_2 import ClientCredentialsAuthCredentials
from paypalserversdk.paypal_serversdk_client import PaypalServersdkClient

from app.core.config import settings

SANDBOX_BASE_URL = "https://api-m.sandbox.paypal.com"


class PayPalNotConfiguredError(RuntimeError):
    """Raised when PayPal credentials are missing or the environment is not allowed."""


_client: Optional[PaypalServersdkClient] = None
_lock = Lock()


def _client_id() -> str:
    return (settings.PAYPAL_CLIENT_ID or "").strip()


def _client_secret() -> str:
    # The only place the secret is unwrapped. Never print or log this value.
    secret = settings.PAYPAL_CLIENT_SECRET
    return secret.get_secret_value().strip() if secret is not None else ""


def is_paypal_configured() -> bool:
    """True when both Sandbox credentials are non-empty (does not contact PayPal)."""
    return bool(_client_id() and _client_secret())


def _resolve_environment() -> Environment:
    # Sandbox is the only environment allowed at this stage. Production is
    # refused on purpose so live money can't be moved by a config typo.
    if settings.PAYPAL_ENVIRONMENT.strip().lower() != "sandbox":
        raise PayPalNotConfiguredError(
            f"PAYPAL_ENVIRONMENT={settings.PAYPAL_ENVIRONMENT!r} is not allowed; "
            "only 'sandbox' is supported."
        )
    return Environment.SANDBOX


def _build_client() -> PaypalServersdkClient:
    if not is_paypal_configured():
        raise PayPalNotConfiguredError(
            "PayPal is not configured: set PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET in backend/.env."
        )

    client = PaypalServersdkClient(
        environment=_resolve_environment(),
        client_credentials_auth_credentials=ClientCredentialsAuthCredentials(
            o_auth_client_id=_client_id(),
            o_auth_client_secret=_client_secret(),
        ),
        timeout=settings.PAYPAL_TIMEOUT_SECONDS,
        # SDK default: retries only GET/PUT, so order creation/capture (POST)
        # is never re-sent automatically.
        max_retries=0,
    )

    # Belt and braces: confirm the SDK really resolved to the Sandbox host.
    base_uri = client.config.get_base_uri()
    if base_uri != SANDBOX_BASE_URL:
        raise PayPalNotConfiguredError(f"Refusing non-sandbox PayPal host: {base_uri}")
    return client


def get_paypal_client() -> PaypalServersdkClient:
    """Return the shared Sandbox client, building it on first call."""
    global _client
    if _client is None:
        with _lock:
            if _client is None:
                _client = _build_client()
    return _client
