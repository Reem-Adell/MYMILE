// Run: npm test
//
// Exercises runCreateOrder() — the exact function PremiumCheckout passes to
// <PayPalButtons createOrder> — with a stubbed payments.createOrder().
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  CreateAborted,
  runCreateOrder,
  shouldRenderPayPalButtons,
  type CheckoutPhase,
} from '../src/services/checkoutFlow.ts';
import type { CreateDecision } from '../src/services/paymentOutcome.ts';

const ALL_PHASES: CheckoutPhase[] = [
  'loading', 'unavailable', 'ready', 'working', 'waiting', 'success', 'rejected', 'error'];
const NOT_READY = ALL_PHASES.filter((p) => p !== 'ready');

type Reply = { httpStatus: number; data: unknown } | Error;

/** A checkout state plus a stub API that counts calls. `onDecision` mimics the
 *  component: a valid order -> 'ready' + order id; anything else -> 'error'. */
function harness(opts: { phase: CheckoutPhase; busy?: boolean; orderId?: string | null;
  reply?: Reply | (() => Promise<Reply>) }) {
  const state = {
    apiCalls: 0,
    phases: [] as CheckoutPhase[],
    decisions: [] as CreateDecision[],
    thrown: [] as unknown[],
    duringCall: [] as { phase: CheckoutPhase; busy: boolean; buttons: boolean }[],
  };
  const phaseRef = { current: opts.phase };
  const busyRef = { current: opts.busy ?? false };
  const orderRef = { current: opts.orderId ?? null };
  const setPhase = (p: CheckoutPhase) => { phaseRef.current = p; state.phases.push(p); };
  const deps = {
    phaseRef, busyRef, orderRef, setPhase,
    createOrderApi: async () => {
      state.apiCalls += 1;
      state.duringCall.push({
        phase: phaseRef.current, busy: busyRef.current, buttons: shouldRenderPayPalButtons(phaseRef.current) });
      const r = typeof opts.reply === 'function' ? await opts.reply() : opts.reply;
      if (r instanceof Error) throw r;
      return (r ?? { httpStatus: 201, data: { code: 'ORDER_CREATED', order_id: 'NEWORDER1' } }) as never;
    },
    onThrown: (err: unknown) => { state.thrown.push(err); setPhase('loading'); return 'unknown'; },
    onDecision: (d: CreateDecision) => {
      state.decisions.push(d);
      if (d.kind === 'order') { orderRef.current = d.orderId; setPhase('ready'); } else setPhase('error');
    },
  };
  return { state, deps, phaseRef, busyRef, orderRef, run: () => runCreateOrder(deps) };
}

async function assertAborted(p: Promise<string>, reason: string) {
  await assert.rejects(p, (e: unknown) => e instanceof CreateAborted && e.reason === reason);
}

// ------------------------------------------------------------- phase guard ---
for (const phase of NOT_READY) {
  test(`createOrder in '${phase}' never calls payments.createOrder()`, async () => {
    const h = harness({ phase });
    await assertAborted(h.run(), 'not-ready');
    assert.equal(h.state.apiCalls, 0);
    assert.deepEqual(h.state.phases, [], 'phase untouched');
    assert.equal(h.busyRef.current, false, 'busy untouched');
    assert.equal(h.state.decisions.length + h.state.thrown.length, 0);
  });

  test(`createOrder in '${phase}' does not hand out a known order id either`, async () => {
    const h = harness({ phase, orderId: 'KNOWN1' });
    await assertAborted(h.run(), 'not-ready');
    assert.equal(h.state.apiCalls, 0);
    assert.equal(h.orderRef.current, 'KNOWN1', 'known order id preserved');
  });
}

test('the phase guard is synchronous (rejects before any await)', () => {
  const h = harness({ phase: 'error' });
  const p = h.run();               // no await yet
  assert.equal(h.state.apiCalls, 0);
  assert.deepEqual(h.state.phases, []);
  return assertAborted(p, 'not-ready');
});

// --------------------------------------------------------- in-flight guard ---
test("createOrder in 'ready' while another request is in flight never calls the API", async () => {
  const h = harness({ phase: 'ready', busy: true });
  await assertAborted(h.run(), 'busy');
  assert.equal(h.state.apiCalls, 0);
  assert.equal(h.busyRef.current, true, 'the other request still owns the busy flag');
});

test('two simultaneous clicks create at most one order', async () => {
  let release!: () => void;
  const gate = new Promise<void>((r) => { release = r; });
  const h = harness({
    phase: 'ready',
    reply: async () => { await gate; return { httpStatus: 201, data: { code: 'ORDER_CREATED', order_id: 'ONE1' } }; },
  });
  const first = h.run();
  const second = h.run();          // first is in flight: phase is already 'working'
  await assertAborted(second, 'not-ready');
  release();
  assert.equal(await first, 'ONE1');
  assert.equal(h.state.apiCalls, 1);
});

test('a click after a failed create (phase error) is rejected without an API call', async () => {
  const h = harness({ phase: 'ready', reply: { httpStatus: 201, data: { order_id: 'X1' } } }); // no code
  await assertAborted(h.run(), 'error');
  assert.equal(h.phaseRef.current, 'error');
  await assertAborted(h.run(), 'not-ready');
  assert.equal(h.state.apiCalls, 1);
});

// --------------------------------------------------- normal PayPal popup flow ---
test("normal flow: 'ready' -> 'working' (buttons stay mounted) -> 'ready' with the new order id", async () => {
  const h = harness({ phase: 'ready' });
  const id = await h.run();
  assert.equal(id, 'NEWORDER1');
  assert.equal(h.state.apiCalls, 1);
  assert.deepEqual(h.state.duringCall, [{ phase: 'working', busy: true, buttons: true }],
    'during the create call the phase is working and the PayPal buttons/popup stay mounted');
  assert.deepEqual(h.state.phases, ['working', 'ready']);
  assert.ok(h.state.phases.every(shouldRenderPayPalButtons), 'buttons never unmounted during the flow');
  assert.equal(h.busyRef.current, false);
  assert.equal(h.orderRef.current, 'NEWORDER1');
});

test('reused order (200 ORDER_REUSED) follows the same flow', async () => {
  const h = harness({ phase: 'ready', reply: { httpStatus: 200, data: { code: 'ORDER_REUSED', order_id: 'OLD1' } } });
  assert.equal(await h.run(), 'OLD1');
  assert.deepEqual(h.state.phases, ['working', 'ready']);
});

test("'ready' with a known order continues the SAME order without calling the API", async () => {
  const h = harness({ phase: 'ready', orderId: 'SAME1' });
  assert.equal(await h.run(), 'SAME1');
  assert.equal(h.state.apiCalls, 0);
  assert.deepEqual(h.state.phases, []);
});

test("'ready' with a known order while busy continues that order and never calls the API", async () => {
  const h = harness({ phase: 'ready', busy: true, orderId: 'KNOWN2' });
  assert.equal(await h.run(), 'KNOWN2');
  assert.equal(h.state.apiCalls, 0);
});

test('retry after a final decline: after the sync (ready, no order) exactly one NEW order is created', async () => {
  // The component clears the declined order and re-syncs; the sync ends in
  // 'ready' with no order id, so the next click creates a new order.
  const h = harness({ phase: 'ready', orderId: null,
    reply: { httpStatus: 201, data: { code: 'ORDER_CREATED', order_id: 'NEWAFTERDECLINE1' } } });
  assert.equal(await h.run(), 'NEWAFTERDECLINE1');
  assert.equal(h.state.apiCalls, 1);
});

test('while the post-decline sync is running (loading) no order can be started', async () => {
  const h = harness({ phase: 'loading', orderId: null });
  await assertAborted(h.run(), 'not-ready');
  assert.equal(h.state.apiCalls, 0);
});

// ------------------------------------------------------------ failure paths ---
test('network failure while creating: aborted, busy released, no order id', async () => {
  const h = harness({ phase: 'ready', reply: new Error('Network Error') });
  await assertAborted(h.run(), 'unknown');
  assert.equal(h.state.apiCalls, 1);
  assert.equal(h.state.thrown.length, 1);
  assert.equal(h.busyRef.current, false);
  assert.equal(h.orderRef.current, null);
  await assertAborted(h.run(), 'not-ready'); // phase moved on (component re-syncs)
  assert.equal(h.state.apiCalls, 1);
});

test('409 UNRESOLVED_PAYMENT: no id is handed to PayPal', async () => {
  const h = harness({ phase: 'ready',
    reply: { httpStatus: 409, data: { code: 'UNRESOLVED_PAYMENT', order_id: 'BLOCK1', status: 'UNCERTAIN' } } });
  await assertAborted(h.run(), 'unresolved');
  assert.equal(h.state.decisions[0].kind, 'unresolved');
});

for (const reply of [
  { httpStatus: 201, data: { order_id: 'A1' } },
  { httpStatus: 200, data: { order_id: 'A1', code: 'ORDER_CREATED' } },
  { httpStatus: 503, data: { code: 'PAYMENTS_UNAVAILABLE' } },
  { httpStatus: 500, data: 'Internal Server Error' },
]) {
  test(`create answer ${reply.httpStatus} ${JSON.stringify(reply.data)} -> aborted, no id`, async () => {
    const h = harness({ phase: 'ready', reply });
    await assert.rejects(h.run(), CreateAborted);
    assert.equal(h.orderRef.current, null);
    assert.equal(h.busyRef.current, false);
  });
}

// ----------------------------------------------------------- render rule ---
test('PayPal buttons render only in ready and working', () => {
  for (const phase of ALL_PHASES) {
    assert.equal(shouldRenderPayPalButtons(phase), phase === 'ready' || phase === 'working', phase);
  }
});

// ------------------------------------------------- "Check payment status" ---
import { runStatusCheck, shouldShowStatusButton } from '../src/services/checkoutFlow.ts';

function statusHarness(busy = false, reply?: () => Promise<unknown>) {
  const s = { refreshCalls: 0, phases: [] as CheckoutPhase[], busyDuringCall: [] as boolean[] };
  const busyRef = { current: busy };
  const setPhase = (p: CheckoutPhase) => { s.phases.push(p); };
  const refreshApi = async () => {
    s.refreshCalls += 1;
    s.busyDuringCall.push(busyRef.current);
    if (reply) await reply();
    return { httpStatus: 202, data: { status: 'UNCERTAIN', code: 'PAYMENT_UNCERTAIN' } } as never;
  };
  return { s, busyRef, run: () => runStatusCheck({ busyRef, setPhase, refreshApi }) };
}

test('status check calls the lookup-first refresh API once, shows loading, releases busy', async () => {
  const h = statusHarness();
  const res = await h.run();
  assert.equal(res?.httpStatus, 202);
  assert.equal(h.s.refreshCalls, 1);
  assert.deepEqual(h.s.busyDuringCall, [true], 'busy while the request runs');
  assert.deepEqual(h.s.phases, ['working'], "'working' = loading text, button hidden");
  assert.equal(h.busyRef.current, false);
});

test('repeated clicks while a check is running make no second request', async () => {
  let release!: () => void;
  const gate = new Promise<void>((r) => { release = r; });
  const h = statusHarness(false, () => gate);
  const first = h.run();
  const second = await h.run();     // clicked again while the first is in flight
  assert.equal(second, null);
  release();
  await first;
  assert.equal(h.s.refreshCalls, 1);
});

test('no status check while another payment request is in flight', async () => {
  const h = statusHarness(true);
  assert.equal(await h.run(), null);
  assert.equal(h.s.refreshCalls, 0);
  assert.equal(h.busyRef.current, true, 'the other request still owns the busy flag');
});

test('busy flag is released even if the status request fails', async () => {
  const h = statusHarness(false, async () => { throw new Error('Network Error'); });
  await assert.rejects(h.run());
  assert.equal(h.busyRef.current, false);
});

test('status button is shown only while waiting for the user (hidden during checks)', () => {
  for (const phase of ALL_PHASES) {
    assert.equal(shouldShowStatusButton(phase), phase === 'waiting' || phase === 'error', phase);
  }
  assert.equal(shouldShowStatusButton('working'), false);
});
