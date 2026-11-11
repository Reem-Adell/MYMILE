// Pure interpretation of backend payment answers (no React, no network), so
// the safety rules can be unit-tested with `npm test` (node:test).
//
// RULE: an answer is recognized ONLY when its HTTP status, machine-readable
// `code` and (where the backend sends one) `status` form one of the exact
// combinations the backend produces (backend/app/services/paypal_service.py):
//
//   capture  200 COMPLETED    PAYMENT_COMPLETED    -> success
//            202 PENDING      PAYMENT_PENDING      -> pending (re-check SAME order)
//            202 UNCERTAIN    PAYMENT_UNCERTAIN    -> pending
//            202 IN_PROGRESS  CAPTURE_IN_PROGRESS  -> pending
//            402 DECLINED     PAYMENT_DECLINED     -> declined (FINAL for that order: retry = NEW order)
//            409 CREATED      ORDER_NOT_APPROVED   -> not_approved (continue SAME order)
//            409 REJECTED     PAYMENT_REJECTED     -> rejected
//            409 NEEDS_REVIEW PAYMENT_NEEDS_REVIEW -> review (blocked; contact support)
//            409 (no status)  CAPTURE_ID_CONFLICT  -> conflict
//            410 EXPIRED      ORDER_EXPIRED        -> expired (only case that forgets the order)
//            404 (no status)  ORDER_NOT_FOUND      -> not_found
//            503 (no status)  PAYMENTS_UNAVAILABLE -> unavailable
//   create   201 ORDER_CREATED + valid order_id    -> order
//            200 ORDER_REUSED  + valid order_id    -> order
//            409 UNRESOLVED_PAYMENT + valid order_id -> unresolved (confirm THAT order)
//            409 CREATE_IN_PROGRESS                -> error (busy)
//
// Anything else (missing/unknown code, code that does not match the HTTP
// status or status field) is UNRECOGNIZED and fails safe:
//   capture -> 'unknown': not success, order id kept, no PayPal buttons
//              (no replacement payment), no automatic retry; the user may
//              contact support or trigger a status check of the SAME order.
//   create  -> 'error': no order id is ever handed to PayPal.
//
// Only type imports here (erased at runtime), so Node can run this file directly.
import type { CaptureBody, HttpResult } from './payments';

export type CaptureDecision =
  | { kind: 'success'; premiumUntil: string | null }
  | { kind: 'pending'; message: string }        // not final yet: re-check the SAME order
  | { kind: 'declined'; message: string; retryable: boolean }
  | { kind: 'not_approved'; message: string }   // safe: continue the SAME order
  | { kind: 'rejected'; message: string }       // terminal for this checkout
  | { kind: 'conflict'; message: string }       // terminal: capture already linked elsewhere
  | { kind: 'review'; message: string }         // terminal + blocking: needs manual review
  | { kind: 'expired'; message: string }        // backend-confirmed: order may be forgotten
  | { kind: 'not_found'; message: string }
  | { kind: 'unavailable'; message: string }    // keep order; user may retry the status check
  | { kind: 'unknown'; message: string };       // unrecognized answer: fail safe (see above)

// PayPal order ids as the backend accepts them (ORDER_ID_RE in paypal_service.py).
const ORDER_ID_RE = /^[A-Za-z0-9-]{1,64}$/;
export const isValidOrderId = (id: unknown): id is string => typeof id === 'string' && ORDER_ID_RE.test(id);

const PENDING_PAIRS: Record<string, string> = {
  PENDING: 'PAYMENT_PENDING',
  UNCERTAIN: 'PAYMENT_UNCERTAIN',
  IN_PROGRESS: 'CAPTURE_IN_PROGRESS',
};

export const MESSAGES = {
  pending: 'Your payment is still being confirmed. Please do not pay again.',
  declined: 'The payment was declined, so you have not been charged. Click the PayPal button again '
    + 'to start a new checkout and choose another payment method.',
  declinedCompliance: 'PayPal declined this payment for compliance reasons, so you have not been charged. '
    + 'This usually means a PayPal account restriction (in Sandbox: the test business or buyer account), '
    + 'so trying again with the same accounts will likely fail again.',
  review: 'We could not automatically verify this payment, so Premium was not activated. '
    + 'Please do not pay again. Contact support with the order reference below.',
  notApproved: 'PayPal approval was not completed, so you have not been charged. '
    + 'You can continue the same checkout below.',
  rejected: 'The payment could not be verified. Premium was not activated.',
  conflict: 'We could not verify this payment, so Premium was not activated. '
    + 'Please do not pay again. Contact support with the order reference below.',
  expired: 'Your previous checkout expired and was not charged. You can start a new payment.',
  notFound: 'That checkout could not be found. Please try again to reload your payment status.',
  unavailable: 'Payments are temporarily unavailable. Please try again later.',
  unknown: 'We received an unexpected answer and could not confirm this payment. '
    + 'Please do not pay again. Use "Check payment status" in a moment, or contact support '
    + 'with the order reference below.',
  createFailed: 'Could not start the payment. Please try again.',
  createBusy: 'A payment is already being started for your account. Please wait a moment, '
    + 'then use "Try again". Do not pay twice.',
  createUnresolved: 'You have a payment that is still being confirmed. Do not pay again.',
};

export function decideCapture({ httpStatus, data }: HttpResult<CaptureBody>): CaptureDecision {
  const body: CaptureBody = data && typeof data === 'object' ? data : {};
  const { code, status } = body;
  const msg = body.message || body.detail || '';
  const unknown: CaptureDecision = { kind: 'unknown', message: MESSAGES.unknown };

  switch (httpStatus) {
    case 200:
      return status === 'COMPLETED' && code === 'PAYMENT_COMPLETED'
        ? { kind: 'success', premiumUntil: body.premium_until ?? null }
        : unknown;
    case 202:
      return typeof status === 'string' && PENDING_PAIRS[status] !== undefined && PENDING_PAIRS[status] === code
        ? { kind: 'pending', message: msg || MESSAGES.pending }
        : unknown;
    case 402:
      return status === 'DECLINED' && code === 'PAYMENT_DECLINED'
        ? {
          kind: 'declined',
          message: body.decline_issue === 'COMPLIANCE_VIOLATION' ? MESSAGES.declinedCompliance : MESSAGES.declined,
          retryable: body.retryable === true,
        }
        : unknown;
    case 409:
      if (code === 'ORDER_NOT_APPROVED' && status === 'CREATED') {
        return { kind: 'not_approved', message: MESSAGES.notApproved };
      }
      if (code === 'PAYMENT_REJECTED' && status === 'REJECTED') {
        return { kind: 'rejected', message: msg || MESSAGES.rejected };
      }
      if (code === 'PAYMENT_NEEDS_REVIEW' && status === 'NEEDS_REVIEW') {
        return { kind: 'review', message: MESSAGES.review };
      }
      if (code === 'CAPTURE_ID_CONFLICT' && status === undefined) {
        return { kind: 'conflict', message: MESSAGES.conflict };
      }
      return unknown;
    case 410:
      return status === 'EXPIRED' && code === 'ORDER_EXPIRED'
        ? { kind: 'expired', message: msg || MESSAGES.expired }
        : unknown;
    case 404:
      return code === 'ORDER_NOT_FOUND' && status === undefined
        ? { kind: 'not_found', message: MESSAGES.notFound }
        : unknown;
    case 503:
      return code === 'PAYMENTS_UNAVAILABLE'
        ? { kind: 'unavailable', message: msg || MESSAGES.unavailable }
        : unknown;
    default:
      return unknown;
  }
}

// GET /orders/unresolved answer: `{"order": null}` or `{"order": PublicOrder}`.
// The endpoint has no `code`, so its SHAPE is validated instead. Only these
// combinations are produced by the backend (_find_unresolved/_public_order):
//   order: null                                              -> none (ready)
//   status PENDING|UNCERTAIN, blocking true,  resumable false -> blocking
//   status NEEDS_REVIEW,      blocking true,  resumable false -> review
//   status CREATED,           blocking false, resumable true  -> resumable_created
// (A DECLINED order is final and never returned as unresolved.)
// Anything else (non-200, missing `order` key, wrong types, unexpected status,
// inconsistent flags, malformed order_id) -> unknown: fail closed. Never
// 'ready', no PayPal buttons, no new order, and a known order id is kept.
export type UnresolvedDecision =
  | { kind: 'none' }
  | { kind: 'blocking'; orderId: string }
  | { kind: 'review'; orderId: string }
  | { kind: 'resumable_created'; orderId: string }
  | { kind: 'unknown'; message: string };

export const UNRESOLVED_UNKNOWN_MESSAGE = 'We could not load your payment status, so checkout is paused to keep '
  + 'you from paying twice. Please use "Check payment status" in a moment, or contact support.';

export function decideUnresolved({ httpStatus, data }: HttpResult<unknown>): UnresolvedDecision {
  const unknown: UnresolvedDecision = { kind: 'unknown', message: UNRESOLVED_UNKNOWN_MESSAGE };
  if (httpStatus !== 200 || data === null || typeof data !== 'object' || Array.isArray(data)) return unknown;
  if (!('order' in data)) return unknown;
  const order = (data as { order: unknown }).order;
  if (order === null) return { kind: 'none' };
  if (typeof order !== 'object' || Array.isArray(order)) return unknown;

  const { order_id: orderId, status, blocking, resumable } = order as Record<string, unknown>;
  if (!isValidOrderId(orderId) || typeof blocking !== 'boolean' || typeof resumable !== 'boolean') return unknown;

  if ((status === 'PENDING' || status === 'UNCERTAIN') && blocking && !resumable) {
    return { kind: 'blocking', orderId };
  }
  if (status === 'NEEDS_REVIEW' && blocking && !resumable) return { kind: 'review', orderId };
  if (status === 'CREATED' && !blocking && resumable) return { kind: 'resumable_created', orderId };
  return unknown;
}

// GET /payments/paypal/config answer. Checkout is available ONLY when the
// backend says so (200, enabled: true) and returns a public client id; any
// other answer keeps the "online payment isn't available" message.
export interface ConfigBody {
  enabled?: unknown;
  client_id?: unknown;
}

export function isCheckoutAvailable({ httpStatus, data }: HttpResult<ConfigBody | null | undefined>): boolean {
  if (httpStatus !== 200 || !data || typeof data !== 'object') return false;
  return data.enabled === true && typeof data.client_id === 'string' && data.client_id.trim() !== '';
}

// POST /orders answer.
export interface CreateBody {
  order_id?: string;
  status?: string;
  code?: string;
  detail?: string;
}

export type CreateDecision =
  | { kind: 'order'; orderId: string }                      // 201 new / 200 reused
  | { kind: 'unresolved'; orderId: string; message: string } // confirm THIS order; never create
  | { kind: 'unavailable'; message: string }
  | { kind: 'error'; message: string };                     // stop; user re-syncs via "Try again"

export function decideCreate({ httpStatus, data }: HttpResult<CreateBody>): CreateDecision {
  const body: CreateBody = data && typeof data === 'object' ? data : {};
  const { code } = body;
  if (httpStatus === 201 && code === 'ORDER_CREATED' && isValidOrderId(body.order_id)) {
    return { kind: 'order', orderId: body.order_id };
  }
  if (httpStatus === 200 && code === 'ORDER_REUSED' && isValidOrderId(body.order_id)) {
    return { kind: 'order', orderId: body.order_id };
  }
  if (httpStatus === 409 && code === 'UNRESOLVED_PAYMENT' && isValidOrderId(body.order_id)) {
    return { kind: 'unresolved', orderId: body.order_id, message: body.detail || MESSAGES.createUnresolved };
  }
  if (httpStatus === 409 && code === 'CREATE_IN_PROGRESS') {
    return { kind: 'error', message: MESSAGES.createBusy };
  }
  if (httpStatus === 503 && (code === 'PAYMENTS_UNAVAILABLE' || code === 'PRICING_MISCONFIGURED')) {
    return { kind: 'unavailable', message: body.detail || MESSAGES.unavailable };
  }
  if (httpStatus === 502 && (code === 'CREATE_UNCONFIRMED' || code === 'PAYPAL_ERROR')) {
    return { kind: 'error', message: body.detail || MESSAGES.createFailed };
  }
  // Missing, unknown or inconsistent answer: never hand an order id to PayPal.
  return { kind: 'error', message: MESSAGES.createFailed };
}
