// The PayPal `createOrder` gate, extracted from PremiumCheckout so the exact
// code the component runs can be unit-tested with `npm test` (node:test).
//
// Safety rules enforced here:
//  1. Synchronous phase guard FIRST: only the 'ready' phase may hand an order
//     id to PayPal. Every other phase (loading, working, waiting, error,
//     unavailable, rejected, success) is rejected before anything else runs.
//  2. A known order is always continued (same id, no backend call).
//  3. No new order while another request is in flight (busy flag).
//  4. payments.createOrder() is called at most once per click; its answer is
//     interpreted only through decideCreate() (strict code validation).
//
// Only `import type` from React-free modules, plus an explicit `.ts`
// extension, so Node can run this file directly in tests.
import type { CaptureBody, HttpResult } from './payments';
import { decideCreate } from './paymentOutcome.ts';
import type { CreateBody, CreateDecision } from './paymentOutcome.ts';

export type CheckoutPhase =
  | 'loading'      // fetching PayPal config / unresolved order
  | 'unavailable'  // PayPal not configured or pricing misconfigured
  | 'ready'        // backend-confirmed: no blocking payment (new or safely resumable order)
  | 'working'      // creating / capturing / refreshing account (PayPal popup may be open)
  | 'waiting'      // payment not final yet, or answer not recognized
  | 'success'      // backend capture COMPLETED and /me confirms Premium
  | 'rejected'     // backend could not verify the payment; contact support
  | 'error';       // could not reach the server; user can retry the SAME state

/** PayPal buttons exist only while a checkout may legitimately start or is
 *  in progress. 'working' keeps them mounted so an open PayPal popup is not
 *  torn down while the order is being created or approved. */
export function shouldRenderPayPalButtons(phase: CheckoutPhase): boolean {
  return phase === 'ready' || phase === 'working';
}

/** The "Check payment status" / "Try again" button is shown only while the
 *  checkout waits for the user. During a check the phase is 'working', so the
 *  button disappears (no double clicks) and "Please wait…" is shown instead. */
export function shouldShowStatusButton(phase: CheckoutPhase): boolean {
  return phase === 'waiting' || phase === 'error';
}

export interface StatusCheckDeps {
  busyRef: { current: boolean };
  setPhase: (phase: CheckoutPhase) => void;
  /** POST /orders/{id}/refresh (payments.refresh): lookup first, never a blind capture. */
  refreshApi: () => Promise<HttpResult<CaptureBody>>;
}

/** One manual status check. Returns null (and does nothing) if another
 *  request is already running, so repeated clicks never overlap. */
export async function runStatusCheck(deps: StatusCheckDeps): Promise<HttpResult<CaptureBody> | null> {
  if (deps.busyRef.current) return null;
  deps.busyRef.current = true;
  deps.setPhase('working');
  try {
    return await deps.refreshApi();
  } finally {
    deps.busyRef.current = false;
  }
}

/** createOrder refused on purpose; the UI has already been updated. */
export class CreateAborted extends Error {
  reason: string;
  constructor(reason: string) {
    super(reason);
    this.reason = reason;
  }
}

export interface CreateOrderDeps {
  phaseRef: { current: CheckoutPhase };
  busyRef: { current: boolean };
  orderRef: { current: string | null };
  setPhase: (phase: CheckoutPhase) => void;
  /** POST /orders (payments.createOrder in the app, a stub in tests). */
  createOrderApi: () => Promise<HttpResult<CreateBody>>;
  /** Network failure / session expiry while creating; returns the abort reason. */
  onThrown: (err: unknown) => string;
  /** Apply a validated create answer to the UI (order, unresolved, failure). */
  onDecision: (decision: CreateDecision) => void;
}

export async function runCreateOrder(deps: CreateOrderDeps): Promise<string> {
  // 1. Synchronous phase guard: nothing may start outside 'ready'.
  if (deps.phaseRef.current !== 'ready') throw new CreateAborted('not-ready');
  // 2. Continue the SAME order (e.g. after decline/cancel); no backend call.
  if (deps.orderRef.current) return deps.orderRef.current;
  // 3. Another request is in flight.
  if (deps.busyRef.current) throw new CreateAborted('busy');

  deps.busyRef.current = true;
  deps.setPhase('working'); // keeps the PayPal buttons (and popup) mounted
  let res: HttpResult<CreateBody>;
  try {
    res = await deps.createOrderApi();
  } catch (err) {
    deps.busyRef.current = false;
    // Unknown outcome: the order MAY exist. Never call create again blindly.
    throw new CreateAborted(deps.onThrown(err));
  }
  deps.busyRef.current = false;
  const decision = decideCreate(res);
  deps.onDecision(decision);
  if (decision.kind === 'order') return decision.orderId;
  throw new CreateAborted(decision.kind);
}
