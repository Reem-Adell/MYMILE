"""
Reconcile ONE payment whose capture PayPal already declined with
COMPLIANCE_VIOLATION, but which an older backend version left UNCERTAIN
(the 422 was only logged, never stored).

    cd backend
    venv\\Scripts\\python -m app.tools.reconcile_declined <ORDER_ID> --issue COMPLIANCE_VIOLATION [--verify]

Safety:
  * Updates the row ONLY if, in one conditional UPDATE: status = UNCERTAIN,
    capture_id IS NULL, completed_at IS NULL, and --issue is exactly
    COMPLIANCE_VIOLATION. Anything else (a changed, completed or captured
    payment) -> refused, nothing written.
  * Makes NO PayPal call by default. --verify performs ONE read-only order
    lookup (GET /v2/checkout/orders/{id}) and refuses unless PayPal reports the
    order APPROVED with no capture at all. This module never calls capture.
  * After reconciliation the row is DECLINED (terminal): the backend answers
    every later capture/status request locally and never captures it again.
  * Prints only the order id and statuses; never credentials or payer data.
"""
import argparse
import logging
import sys
from typing import Any, Optional, Tuple

from app.core import database

ALLOWED_ISSUE = "COMPLIANCE_VIOLATION"
log = logging.getLogger("reconcile_declined")


def _verify_with_paypal(order_id: str, client: Any) -> Tuple[bool, str]:
    """Read-only lookup. OK only for status APPROVED with no capture in any unit."""
    from paypalserversdk.exceptions.api_exception import ApiException

    try:
        order = client.orders.get_order({"id": order_id}).body
    except ApiException as exc:
        return False, f"PayPal lookup failed (http {exc.response_code}); nothing changed"
    except Exception as exc:  # noqa: BLE001  (network etc.)
        return False, f"PayPal lookup failed ({type(exc).__name__}); nothing changed"
    if getattr(order, "id", None) != order_id:
        return False, "PayPal returned a different order id; nothing changed"
    status = getattr(order, "status", None)
    for unit in getattr(order, "purchase_units", None) or []:
        payments_obj = getattr(unit, "payments", None)
        captures = (getattr(payments_obj, "captures", None) or []) if payments_obj is not None else []
        if captures:
            return False, f"PayPal reports {len(captures)} capture(s) on this order; refusing to mark it declined"
    if status != "APPROVED":
        return False, f"PayPal reports order status {status}, not APPROVED without capture; nothing changed"
    return True, "PayPal reports APPROVED with no capture"


def reconcile_compliance_decline(order_id: str, issue: str, verify: bool = False,
                                 client: Optional[Any] = None) -> Tuple[bool, str]:
    """Returns (reconciled, message). Never raises for a refusal."""
    if issue != ALLOWED_ISSUE:
        return False, f"refused: --issue must be {ALLOWED_ISSUE}"

    with database.connect() as conn:
        database.migrate(conn)  # additive; ensures last_capture_result exists
        row = conn.execute("SELECT status, capture_id, completed_at FROM payments WHERE order_id = ?",
                           (order_id,)).fetchone()
    if row is None:
        return False, "refused: order not found"
    if row["status"] != "UNCERTAIN" or row["capture_id"] is not None or row["completed_at"] is not None:
        return False, (f"refused: payment is {row['status']} (capture recorded: {row['capture_id'] is not None}, "
                       f"completed: {row['completed_at'] is not None}); only an UNCERTAIN, uncaptured, "
                       f"uncompleted payment can be reconciled")

    if verify:
        if client is None:
            from app.core.paypal_client import get_paypal_client
            client = get_paypal_client()
        ok, why = _verify_with_paypal(order_id, client)
        if not ok:
            return False, f"refused: {why}"

    with database.connect() as conn:
        # Conditional: if anything changed since the checks above, nothing is written.
        cur = conn.execute(
            "UPDATE payments SET status = 'DECLINED', last_capture_result = ? "
            "WHERE order_id = ? AND status = 'UNCERTAIN' AND capture_id IS NULL AND completed_at IS NULL",
            (f"HTTP_422:{ALLOWED_ISSUE}", order_id))
        if cur.rowcount != 1:
            return False, "refused: the payment changed during reconciliation; nothing changed"
    return True, (f"reconciled: order {order_id} UNCERTAIN -> DECLINED ({ALLOWED_ISSUE}); "
                  "it will never be captured again and a new payment may be started")


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("order_id")
    parser.add_argument("--issue", required=True, help=f"must be {ALLOWED_ISSUE}")
    parser.add_argument("--verify", action="store_true",
                        help="one read-only PayPal order lookup before updating (no capture is ever sent)")
    args = parser.parse_args(argv)
    ok, message = reconcile_compliance_decline(args.order_id, args.issue, verify=args.verify)
    print(message)
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
