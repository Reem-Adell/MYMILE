"""
PayPal Premium pass endpoints (Sandbox).

All endpoints require a valid Bearer token (`require_user`): no token or an
invalid/expired token -> 401. Guests never reach the payment logic.

Request bodies are intentionally NOT read: plan, price, amount, currency,
user id and duration are decided by the backend only.

Handlers are plain `def` so FastAPI runs the blocking PayPal SDK calls in its
thread pool instead of on the event loop.
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from app.api.routes.auth import require_user
from app.core.config import settings
from app.core.paypal_client import is_paypal_configured
from app.schemas.auth_schema import UserOut
from app.services import paypal_service
from app.services.paypal_service import PaymentError

router = APIRouter(prefix="/payments/paypal", tags=["Payments"])


@router.get("/config")
def paypal_config(current_user: UserOut = Depends(require_user)):
    """Public PayPal settings for the frontend. Never includes the client secret."""
    try:
        terms = paypal_service.premium_terms()
    except PaymentError as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.message)
    enabled = is_paypal_configured()
    return {
        "enabled": enabled,
        "client_id": settings.PAYPAL_CLIENT_ID if enabled else None,  # public by design
        "environment": "sandbox",
        "intent": "capture",
        "currency": terms["currency"],
        "price": terms["price"],
        "duration_days": terms["duration_days"],
        "one_time": True,
        "auto_renew": False,
    }


def _error(exc: PaymentError) -> JSONResponse:
    """`detail` stays a string (frontend contract), `code` is machine-readable
    (clients must branch on it, not on the HTTP status), plus client-safe extras."""
    return JSONResponse(status_code=exc.http_status,
                        content={"detail": exc.message, "code": exc.code, **exc.extra})


@router.post("/orders", status_code=201)
def create_order(current_user: UserOut = Depends(require_user)):
    """201 = new order. 200 = a recent uncharged order was reused (`reused: true`).
    409 = a previous payment is still unresolved (`order_id`, `status` included):
    resolve that SAME order by retrying its capture; never pay again."""
    try:
        result = paypal_service.create_premium_order(current_user.id)
    except PaymentError as exc:
        return _error(exc)
    return JSONResponse(status_code=200 if result["reused"] else 201, content=result)


# Declared before /orders/{order_id} so "unresolved" is not taken as an order id.
@router.get("/orders/unresolved")
def unresolved_order(current_user: UserOut = Depends(require_user)):
    """The caller's order that needs attention after a refresh/interruption:
    `{"order": {..., "blocking", "resumable"}}` or `{"order": null}`."""
    return paypal_service.get_unresolved_order(current_user.id)


@router.get("/orders/{order_id}")
def order_status(order_id: str, current_user: UserOut = Depends(require_user)):
    """Owner-only local status of an order (404 if unknown or not yours). No PayPal call."""
    try:
        return paypal_service.get_order_status(current_user.id, order_id)
    except PaymentError as exc:
        return _error(exc)


@router.post("/orders/{order_id}/refresh")
def refresh_order(order_id: str, current_user: UserOut = Depends(require_user)):
    """"Check payment status" for an unfinished payment: looks the order up at
    PayPal first and never blindly re-captures (see refresh_order_status).
    Same response shape and codes as capture."""
    try:
        outcome = paypal_service.refresh_order_status(current_user.id, order_id)
    except PaymentError as exc:
        return _error(exc)
    return JSONResponse(status_code=outcome.http_status, content=outcome.as_dict(order_id))


@router.post("/orders/{order_id}/capture")
def capture_order(order_id: str, current_user: UserOut = Depends(require_user)):
    try:
        outcome = paypal_service.capture_premium_order(current_user.id, order_id)
    except PaymentError as exc:
        return _error(exc)
    return JSONResponse(status_code=outcome.http_status, content=outcome.as_dict(order_id))
