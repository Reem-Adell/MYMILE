// PayPal Premium pass API (backend: backend/app/api/routes/payments.py).
//
// Every call goes through the authenticated backend. The frontend never talks
// to PayPal's REST API, never sees the client secret, and never decides price,
// currency, duration or whether Premium is active.
//
// Non-2xx answers that are part of the payment protocol (202/402/404/409/410/
// 503) are RETURNED, not thrown, so the checkout can react to each one.
// Only network failures/timeouts and 401 (session expired) are thrown.
import axios from 'axios';
import { apiClient } from './api';

// Payment calls may wait on PayPal (+ a reconciliation lookup) server-side.
const PAYMENT_TIMEOUT_MS = 60000;

export type OrderStatus =
  | 'CREATED' | 'COMPLETED' | 'PENDING' | 'DECLINED'
  | 'UNCERTAIN' | 'REJECTED' | 'EXPIRED' | 'NEEDS_REVIEW';

// GET /payments/paypal/config
export interface PayPalConfig {
  enabled: boolean;
  client_id: string | null;   // public client id; null when PayPal is not configured
  environment: string;        // "sandbox"
  intent: string;             // "capture"
  currency: string;
  price: string;
  duration_days: number;
  one_time: boolean;
  auto_renew: boolean;
}

// Client-safe order view (GET /orders/unresolved, GET /orders/{id}).
export interface PublicOrder {
  order_id: string;
  status: OrderStatus;
  amount: string;
  currency: string;
  created_at: string;
  completed_at: string | null;
  blocking: boolean;   // PENDING/UNCERTAIN: must be resolved on THIS order first
  resumable: boolean;  // CREATED/DECLINED and recent: continue THIS order in PayPal
  premium_until?: string | null;
}

// POST /orders -> 201 (new) or 200 (reused)
export interface CreatedOrder {
  order_id: string;
  status: string;
  approve_url: string | null;
  amount: string;
  currency: string;
  duration_days: number;
  one_time: boolean;
  reused: boolean;
}

// POST /orders/{id}/capture body (CaptureOutcome.as_dict) or a PaymentError
// body ({detail, ...extra}) for 404/409(not approved)/503.
export interface CaptureBody {
  order_id?: string;
  status?: OrderStatus | 'IN_PROGRESS';
  // Machine-readable outcome (e.g. ORDER_NOT_APPROVED, CAPTURE_ID_CONFLICT).
  // Interpret answers via decideCapture() in paymentOutcome.ts, never by HTTP status alone.
  code?: string;
  decline_issue?: string;   // e.g. COMPLIANCE_VIOLATION (with PAYMENT_DECLINED)
  message?: string;
  detail?: string;
  premium_granted?: boolean;
  premium_until?: string | null;
  already_processed?: boolean;
  retryable?: boolean;
}

export interface HttpResult<T> {
  httpStatus: number;
  data: T;
}

export class SessionExpiredError extends Error {
  constructor() {
    super('Your session has expired. Please log in again.');
  }
}

/** True for a network failure or timeout: the outcome of the request is UNKNOWN. */
export function isNetworkOrTimeout(err: unknown): boolean {
  return axios.isAxiosError(err) && !err.response;
}

async function call<T>(method: 'get' | 'post', url: string): Promise<HttpResult<T>> {
  const res = await apiClient.request<T>({
    method,
    url,
    timeout: PAYMENT_TIMEOUT_MS,
    validateStatus: () => true, // protocol statuses are handled by the caller
  });
  if (res.status === 401) throw new SessionExpiredError();
  return { httpStatus: res.status, data: res.data };
}

export const payments = {
  getConfig: () => call<PayPalConfig & { detail?: string }>('get', '/payments/paypal/config'),

  getUnresolved: () => call<{ order: PublicOrder | null; detail?: string }>('get', '/payments/paypal/orders/unresolved'),

  getOrder: (orderId: string) =>
    call<PublicOrder & { detail?: string }>('get', `/payments/paypal/orders/${encodeURIComponent(orderId)}`),

  // The backend ignores any body: price/currency/user/duration are server-side.
  createOrder: () =>
    call<CreatedOrder & { detail?: string; order_id?: string; status?: string; code?: string }>(
      'post', '/payments/paypal/orders'),

  capture: (orderId: string) =>
    call<CaptureBody>('post', `/payments/paypal/orders/${encodeURIComponent(orderId)}/capture`),

  // "Check payment status": the backend looks the order up at PayPal first and
  // never blindly re-captures. Same response shape/codes as capture.
  refresh: (orderId: string) =>
    call<CaptureBody>('post', `/payments/paypal/orders/${encodeURIComponent(orderId)}/refresh`),
};
