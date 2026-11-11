// Premium pass checkout (PayPal, Sandbox). Rendered only for a LOGGED-IN user
// whose backend-verified plan is Free.
//
// Safety rules implemented here:
//  * The backend is the source of truth. Before any new order we ask
//    GET /orders/unresolved and continue THAT order if there is one.
//  * One order id is used for approval, capture and recovery. A network error or
//    timeout never leads to a replacement order: we re-sync from the backend.
//  * PayPal approval is not proof of payment. Premium is shown only after the
//    backend capture returns COMPLETED and a fresh /auth/me says "premium".
//  * Capture always goes through POST /orders/{id}/capture (never PayPal direct).
//  * Automatic re-checks are bounded (CONFIRM_DELAYS_MS); then the user decides.
//  * Backend answers are interpreted by their machine-readable `code`
//    (services/paymentOutcome.ts), never by HTTP status alone: only
//    ORDER_NOT_APPROVED returns to "ready"; any other 409 stops the checkout.
//  * A confirmed decline is final for that PayPal order: the next attempt is a
//    NEW order (new buyer approval). actions.restart() is never used.
import { useCallback, useEffect, useRef, useState } from 'react';
import { PayPalButtons, PayPalScriptProvider } from '@paypal/react-paypal-js';
import {
  CaptureBody,
  HttpResult,
  isNetworkOrTimeout,
  payments,
  PayPalConfig,
  SessionExpiredError,
} from '../services/payments';
import { decideCapture, decideUnresolved, isCheckoutAvailable, MESSAGES } from '../services/paymentOutcome';
import type { CreateDecision } from '../services/paymentOutcome';
import {
  type CheckoutPhase,
  CreateAborted,
  runCreateOrder,
  runStatusCheck,
  shouldRenderPayPalButtons,
  shouldShowStatusButton,
} from '../services/checkoutFlow';

// Phases are documented in services/checkoutFlow.ts.
type Phase = CheckoutPhase;

type Tone = 'info' | 'warn' | 'error' | 'success';

interface Props {
  /** Refresh the user from GET /auth/me; resolves true only if the backend now says Premium. */
  refreshUser: () => Promise<boolean>;
  onSessionExpired: () => void;
  premiumUntilLabel: (iso?: string | null) => string;
}

// Bounded automatic re-checks of an unfinished payment (same order each time).
const CONFIRM_DELAYS_MS = [2000, 4000, 8000, 15000, 30000];

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export function PremiumCheckout({ refreshUser, onSessionExpired, premiumUntilLabel }: Props) {
  const [config, setConfig] = useState<PayPalConfig | null>(null);
  const [phase, setPhaseState] = useState<Phase>('loading');
  const [notice, setNotice] = useState<{ tone: Tone; text: string } | null>(null);
  const [orderId, setOrderIdState] = useState<string | null>(null);
  const [premiumUntil, setPremiumUntil] = useState<string | null>(null);
  const [lastAction, setLastAction] = useState<'sync' | 'confirm' | 'refresh'>('sync');

  // Refs: PayPal invokes callbacks asynchronously, so read the latest values here.
  const orderRef = useRef<string | null>(null);
  const busyRef = useRef(false);
  const mountedRef = useRef(true);
  const startedRef = useRef(false);
  // phaseRef is updated in the SAME call as the React state (never via an
  // effect), so PayPal callbacks such as createOrder always see the current
  // phase, even before React re-renders.
  const phaseRef = useRef<Phase>('loading');
  const setPhase = useCallback((next: Phase) => {
    phaseRef.current = next;
    setPhaseState(next);
  }, []);
  // Set when createOrder aborts on purpose; PayPal then calls onError, which
  // must not overwrite the message we already showed.
  const abortedRef = useRef(false);
  // resync is defined after confirmOrder (which it calls); confirmOrder reaches
  // it through this ref after a confirmed expiry.
  const resyncRef = useRef<(() => Promise<void>) | null>(null);

  const setOrderId = (id: string | null) => {
    orderRef.current = id;
    setOrderIdState(id);
  };
  const say = (tone: Tone, text: string) => mountedRef.current && setNotice({ tone, text });

  const handleThrown = useCallback((err: unknown, fallback: string) => {
    if (err instanceof SessionExpiredError) {
      onSessionExpired();
      return;
    }
    setPhase('error');
    say('error', isNetworkOrTimeout(err)
      ? "We couldn't reach the server, so the payment state is unknown. Nothing new was started. Please try again."
      : fallback);
  }, [onSessionExpired]);

  // ---- success: backend capture COMPLETED -> confirm with /auth/me ----
  const finishSuccess = useCallback(async (fromCapture?: string | null) => {
    setPhase('working');
    setLastAction('refresh');
    say('info', 'Payment confirmed by MYMILE. Updating your account…');
    for (let i = 0; i < 3 && mountedRef.current; i++) {
      try {
        if (await refreshUser()) {
          setOrderId(null);
          setPremiumUntil(fromCapture ?? null);
          setPhase('success');
          say('success', 'Premium is active. Thank you!');
          return;
        }
      } catch (err) {
        if (err instanceof SessionExpiredError) return onSessionExpired();
      }
      await sleep(1500);
    }
    if (!mountedRef.current) return;
    setPhase('error');
    say('warn', 'Your payment was confirmed, but your account has not refreshed yet. '
      + 'Please do not pay again; use "Try again" to refresh.');
  }, [refreshUser, onSessionExpired]);

  // ---- interpret one backend capture answer ----
  // Returns 'retry' when the payment is not final yet and should be re-checked.
  const applyCapture = useCallback(async (
    res: HttpResult<CaptureBody>,
  ): Promise<'done' | 'retry' | 'resync'> => {
    const d = decideCapture(res);
    switch (d.kind) {
      case 'success':
        await finishSuccess(d.premiumUntil);
        return 'done';
      case 'pending':
        setPhase('waiting');
        say('warn', d.message);
        return 'retry';
      case 'declined':
        // Confirmed decline: FINAL for this order (nothing charged). The order is
        // forgotten and a status sync must confirm nothing is unresolved; the
        // next click then creates a NEW order the buyer approves again. No
        // actions.restart(): the same order is never captured again.
        setOrderId(null);
        setPhase('loading');
        setLastAction('sync');
        say('warn', d.message);
        return 'resync';
      case 'not_approved':
        // code ORDER_NOT_APPROVED only: nothing charged, continue the SAME order.
        setPhase('ready');
        say('info', d.message);
        return 'done';
      case 'rejected':
      case 'conflict':
      case 'review':
        // Terminal for this checkout: no PayPal buttons, no automatic retry.
        // (CAPTURE_ID_CONFLICT / NEEDS_REVIEW are never shown as "awaiting
        // approval"; the backend keeps the order blocking.)
        setPhase('rejected');
        say('error', d.message);
        return 'done';
      case 'expired':
        // EXPIRED, confirmed by the backend: only now forget the order. Do NOT
        // go to 'ready' here: without an order id the next click would create
        // a new one, so a fresh status sync must first confirm that no
        // blocking payment exists. The caller runs that sync ('resync').
        setOrderId(null);
        setPhase('loading');
        setLastAction('sync');
        say('info', d.message);
        return 'resync';
      case 'not_found':
        // Only for 404 + ORDER_NOT_FOUND; the next step re-syncs from the backend.
        setOrderId(null);
        setPhase('error');
        setLastAction('sync');
        say('warn', d.message);
        return 'done';
      case 'unavailable':
        // 503 + PAYMENTS_UNAVAILABLE: order kept; "Try again" re-checks the SAME order.
        setPhase('error');
        say('error', d.message);
        return 'done';
      case 'unknown':
      default:
        // Unrecognized answer (missing/unknown/inconsistent code): never success,
        // order id KEPT, PayPal buttons hidden ('waiting' => no replacement
        // payment), NO automatic retry ('done'). The user may run a status check
        // of the same order ("Check payment status") or contact support.
        setPhase('waiting');
        say('warn', d.message);
        return 'done';
    }
  }, [finishSuccess]);

  // ---- confirm an unfinished payment on the SAME order, bounded retries ----
  const confirmOrder = useCallback(async (id: string, firstDelay = false) => {
    if (busyRef.current) return;
    busyRef.current = true;
    setLastAction('confirm');
    let resyncAfter = false;
    try {
      for (let attempt = 0; attempt <= CONFIRM_DELAYS_MS.length && mountedRef.current; attempt++) {
        if (attempt > 0 || firstDelay) await sleep(CONFIRM_DELAYS_MS[Math.max(0, attempt - 1)]);
        if (!mountedRef.current) return;
        if (attempt === 0) setPhase('working');
        try {
          // Re-checks look the order up first (backend /refresh); they never blindly re-capture.
          const res = await payments.refresh(id);
          const outcome = await applyCapture(res);
          if (outcome === 'resync') { resyncAfter = true; return; }
          if (outcome === 'done') return;
        } catch (err) {
          if (err instanceof SessionExpiredError) return onSessionExpired();
          // Unknown outcome: keep the order, check again (never a new order).
          setPhase('waiting');
          say('warn', "We couldn't confirm your payment yet (connection problem). Checking again…");
        }
      }
      if (mountedRef.current) {
        setPhase('waiting');
        say('warn', 'Your payment is still being confirmed. Please do not pay again. '
          + 'Use "Check payment status" in a little while.');
      }
    } finally {
      busyRef.current = false;
      // Confirmed expiry: only a fresh status sync may lead back to 'ready'.
      if (resyncAfter && mountedRef.current) void resyncRef.current?.();
    }
  }, [applyCapture, onSessionExpired]);

  // ---- sync with the backend: what is this user's unfinished order? ----
  const resync = useCallback(async () => {
    if (busyRef.current) return;
    busyRef.current = true;
    setLastAction('sync');
    setPhase('loading');
    let next: (() => Promise<void>) | null = null;
    try {
      const d = decideUnresolved(await payments.getUnresolved());
      if (d.kind === 'none') {
        // Valid `{"order": null}`: the backend confirms there is nothing unfinished.
        setOrderId(null);
        setPhase('ready');
      } else if (d.kind === 'blocking') {
        const id = d.orderId;
        setOrderId(id);
        say('warn', 'You have a payment that is still being confirmed. Checking it now — please do not pay again.');
        next = () => confirmOrder(id);
      } else if (d.kind === 'review') {
        // Blocked for manual review: show it, no PayPal buttons, no new order.
        setOrderId(d.orderId);
        setPhase('rejected');
        say('error', MESSAGES.review);
      } else if (d.kind === 'resumable_created') {
        // Maybe approved but the capture was interrupted (e.g. page closed): one
        // safe check. If not approved, the backend says so and nothing is charged.
        const id = d.orderId;
        setOrderId(id);
        next = async () => {
          busyRef.current = true;
          try {
            const res = await payments.capture(id);
            if (decideCapture(res).kind === 'not_approved') {
              setPhase('ready');
              say('info', 'You have an unfinished checkout. Continue it with PayPal below; you have not been charged.');
              return;
            }
            const outcome = await applyCapture(res);
            if (outcome === 'retry') {
              busyRef.current = false;
              await confirmOrder(id, true);
            } else if (outcome === 'resync') {
              busyRef.current = false;
              await resyncRef.current?.(); // confirmed expiry: re-check before 'ready'
            }
          } catch (err) {
            handleThrown(err, 'Could not check your unfinished checkout.');
          } finally {
            busyRef.current = false;
          }
        };
      } else {
        // Malformed / unexpected answer: fail closed. Never 'ready'; 'waiting'
        // hides the PayPal buttons (no new order); any known order id is KEPT.
        // "Check payment status" re-runs this sync (lastAction is 'sync').
        setPhase('waiting');
        say('warn', d.message);
      }
    } catch (err) {
      handleThrown(err, 'Could not load your payment status.');
    } finally {
      busyRef.current = false;
    }
    if (next && mountedRef.current) await next();
  }, [applyCapture, confirmOrder, handleThrown]);
  resyncRef.current = resync;

  // ---- initial load: config, then unresolved order ----
  const init = useCallback(async () => {
    setPhase('loading');
    setNotice(null);
    try {
      const res = await payments.getConfig();
      if (!isCheckoutAvailable(res)) {
        // Backend says PayPal is not configured (or answered unexpectedly).
        setConfig(null);
        setPhase('unavailable');
        return;
      }
      setConfig(res.data);
    } catch (err) {
      handleThrown(err, 'Could not load the checkout.');
      return;
    }
    await resync();
  }, [resync, handleThrown]);

  useEffect(() => {
    mountedRef.current = true;
    if (!startedRef.current) {   // StrictMode runs effects twice in development
      startedRef.current = true;
      void init();
    }
    return () => { mountedRef.current = false; };
  }, [init]);

  // ---- PayPal button callbacks ----
  // The gate itself (phase guard, same-order reuse, busy guard, single backend
  // call, strict answer validation) lives in services/checkoutFlow.ts and is
  // unit-tested there; this wires its outcomes into the UI.
  const applyCreateDecision = (d: CreateDecision) => {
    if (d.kind === 'order') {
      // 201 ORDER_CREATED / 200 ORDER_REUSED: the create endpoint itself has
      // just confirmed there is no blocking payment.
      setOrderId(d.orderId);
      setPhase('ready');
      return;
    }
    if (d.kind === 'unresolved') {
      // code UNRESOLVED_PAYMENT: confirm THAT order; never create another one.
      setOrderId(d.orderId);
      say('warn', d.message);
      void confirmOrder(d.orderId);
      return;
    }
    // Unavailable, busy, or any unexpected answer (incl. an unknown 409): no
    // order id goes to PayPal; "Try again" re-syncs with the backend first.
    setLastAction('sync');
    setPhase(d.kind === 'unavailable' ? 'unavailable' : 'error');
    say('error', d.message);
  };

  const createOrder = async (): Promise<string> => {
    try {
      return await runCreateOrder({
        phaseRef,
        busyRef,
        orderRef,
        setPhase,
        createOrderApi: payments.createOrder,
        onThrown: (err) => {
          if (err instanceof SessionExpiredError) {
            onSessionExpired();
            return 'session';
          }
          // Unknown outcome (network/timeout): the order MAY exist. Re-sync from
          // the backend; never call create again blindly.
          say('warn', "We couldn't confirm whether the checkout started. Checking with the server — please wait.");
          void resync();
          return 'unknown';
        },
        onDecision: applyCreateDecision,
      });
    } catch (err) {
      // Refused on purpose: PayPal will call onError next; keep our message.
      if (err instanceof CreateAborted) abortedRef.current = true;
      throw err;
    }
  };

  const onApprove = async (data: { orderID: string }) => {
    const id = data.orderID || orderRef.current;
    if (!id) return;
    setOrderId(id);
    if (busyRef.current) return;
    busyRef.current = true;
    setPhase('working');
    setLastAction('confirm');
    say('info', 'Confirming your payment with MYMILE…');
    let retry = false;
    let resyncAfter = false;
    try {
      const res = await payments.capture(id);
      const outcome = await applyCapture(res);
      retry = outcome === 'retry';
      resyncAfter = outcome === 'resync';
    } catch (err) {
      if (err instanceof SessionExpiredError) { busyRef.current = false; return onSessionExpired(); }
      retry = true; // unknown outcome: re-check the SAME order
      setPhase('waiting');
      say('warn', "We couldn't confirm your payment yet (connection problem). Checking again — do not pay again.");
    } finally {
      busyRef.current = false;
    }
    if (retry && mountedRef.current) await confirmOrder(id, true);
    else if (resyncAfter && mountedRef.current) await resync(); // confirmed expiry
  };

  const onCancel = () => {
    // Popup closed without approval: nothing was charged. The phase is NOT
    // changed here: it is 'ready' only if a backend answer already confirmed
    // this order (createOrder 201/200); while the create is still in flight
    // ('working'), its own answer decides the next phase.
    if (phaseRef.current !== 'ready') return;
    say('info', 'Checkout cancelled. You have not been charged and can continue the same checkout any time.');
  };

  const onError = () => {
    if (!mountedRef.current) return;
    // Errors we raised on purpose (CreateAborted) already updated the UI.
    if (abortedRef.current) {
      abortedRef.current = false;
      return;
    }
    const current = phaseRef.current;
    if (current !== 'ready' && current !== 'working' && current !== 'loading') return;
    say('warn', 'PayPal could not complete the checkout. Checking your payment status…');
    void resync();
  };

  // Manual "Check payment status": exactly one lookup-first status check, never
  // overlapping (runStatusCheck), with the button hidden while it runs.
  const checkStatusOnce = async (id: string) => {
    setLastAction('confirm');
    let res: HttpResult<CaptureBody> | null;
    try {
      res = await runStatusCheck({ busyRef, setPhase, refreshApi: () => payments.refresh(id) });
    } catch (err) {
      if (err instanceof SessionExpiredError) return onSessionExpired();
      setPhase('waiting');
      say('warn', "We couldn't reach the server, so the payment state is still unknown. "
        + 'Please do not pay again; check again in a moment.');
      return;
    }
    if (!res || !mountedRef.current) return; // another check is already running
    if ((await applyCapture(res)) === 'resync' && mountedRef.current) await resync();
    // 'retry' (still pending/uncertain): stays in 'waiting'; the user may check again.
  };

  const retryLast = () => {
    if (lastAction === 'confirm' && orderRef.current) return void checkStatusOnce(orderRef.current);
    if (lastAction === 'refresh') return void finishSuccess(premiumUntil);
    if (!config) return void init();
    return void resync();
  };

  // ---- render ----
  const toneClass: Record<Tone, string> = {
    info: 'bg-blue-50 border-blue-200 text-blue-900',
    warn: 'bg-amber-50 border-amber-300 text-amber-900',
    error: 'bg-red-50 border-red-200 text-red-800',
    success: 'bg-green-50 border-green-200 text-green-800',
  };

  if (phase === 'unavailable') {
    return (
      <div className="rounded-xl border border-slate-200 bg-white/90 p-3 text-xs text-gray-700">
        Online payment isn't available right now, so Premium can't be purchased at the moment.
        You have not been charged. Please check back later.
      </div>
    );
  }

  if (phase === 'success') {
    return (
      <div className={`rounded-xl border p-3 text-sm font-semibold ${toneClass.success}`}>
        ✓ Premium is active{premiumUntil ? ` until ${premiumUntilLabel(premiumUntil)}` : ''}.
      </div>
    );
  }

  const buttonsUsable = phase === 'ready' && !busyRef.current;

  return (
    <div className="space-y-2">
      {notice && (
        <div className={`rounded-xl border p-3 text-xs leading-relaxed ${toneClass[notice.tone]}`}>
          {notice.text}
          {orderId && (phase === 'waiting' || phase === 'rejected' || phase === 'error') && (
            <div className="mt-1 font-mono text-[11px] opacity-80">Order reference: {orderId}</div>
          )}
        </div>
      )}

      {(phase === 'loading' || phase === 'working') && (
        <div className="text-xs font-semibold text-gray-600">
          {phase === 'loading' ? 'Loading secure checkout…' : 'Please wait…'}
        </div>
      )}

      {shouldShowStatusButton(phase) && (
        <button className="btn btn-secondary full-btn" onClick={retryLast} disabled={busyRef.current}>
          {phase === 'waiting' ? 'Check payment status' : 'Try again'}
        </button>
      )}

      {config && config.client_id && (
        // The SDK script provider stays mounted; only the buttons come and go.
        <PayPalScriptProvider options={{ clientId: config.client_id, currency: config.currency, intent: 'capture' }}>
          {/* Buttons exist ONLY in 'ready' (backend-confirmed safe to start or
              continue) and 'working' (kept mounted so an open PayPal popup is
              not torn down mid-checkout). Never in loading / waiting / error /
              rejected; 'unavailable' and 'success' return earlier. */}
          {shouldRenderPayPalButtons(phase) && (
            <PayPalButtons
              style={{ layout: 'vertical', shape: 'pill', label: 'pay' }}
              disabled={!buttonsUsable}
              // Callbacks read refs, so the buttons never need re-rendering mid-checkout
              // (re-rendering while the PayPal window is open would break it).
              forceReRender={[config.client_id, config.currency]}
              createOrder={createOrder}
              onApprove={onApprove}
              onCancel={onCancel}
              onError={onError}
            />
          )}
        </PayPalScriptProvider>
      )}
    </div>
  );
}
