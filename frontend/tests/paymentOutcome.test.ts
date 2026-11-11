// Run: npm test   (Node's built-in test runner; Node >= 22.18 strips TS types natively)
//
// The contract below mirrors backend/app/services/paypal_service.py exactly.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { decideCapture, decideCreate, decideUnresolved, isCheckoutAvailable } from '../src/services/paymentOutcome.ts';

type Body = Record<string, unknown>;
const cap = (httpStatus: number, data: unknown) => decideCapture({ httpStatus, data } as never);
const create = (httpStatus: number, data: unknown) => decideCreate({ httpStatus, data } as never);

// Every recognized capture answer: [http, body, expected kind].
const RECOGNIZED: Array<[number, Body, string]> = [
  [200, { status: 'COMPLETED', code: 'PAYMENT_COMPLETED', premium_until: '2026-12-10T00:00:00+00:00' }, 'success'],
  [202, { status: 'PENDING', code: 'PAYMENT_PENDING' }, 'pending'],
  [202, { status: 'UNCERTAIN', code: 'PAYMENT_UNCERTAIN', retryable: true }, 'pending'],
  [202, { status: 'IN_PROGRESS', code: 'CAPTURE_IN_PROGRESS', retryable: true }, 'pending'],
  [402, { status: 'DECLINED', code: 'PAYMENT_DECLINED', retryable: true }, 'declined'],
  [409, { status: 'CREATED', code: 'ORDER_NOT_APPROVED', order_id: 'O1', detail: 'x' }, 'not_approved'],
  [409, { status: 'REJECTED', code: 'PAYMENT_REJECTED' }, 'rejected'],
  [409, { status: 'NEEDS_REVIEW', code: 'PAYMENT_NEEDS_REVIEW', detail: 'x' }, 'review'],
  [409, { code: 'CAPTURE_ID_CONFLICT', detail: 'x' }, 'conflict'],
  [410, { status: 'EXPIRED', code: 'ORDER_EXPIRED' }, 'expired'],
  [404, { code: 'ORDER_NOT_FOUND', detail: 'Order not found.' }, 'not_found'],
  [503, { code: 'PAYMENTS_UNAVAILABLE', detail: 'x' }, 'unavailable'],
];

// Kinds that change local state in a way that needs proof from the backend.
const STATE_CHANGING = ['success', 'not_approved', 'expired', 'not_found', 'declined'];

// ------------------------------------------------------------ recognized ---
for (const [http, body, kind] of RECOGNIZED) {
  test(`capture ${http} ${body.status ?? '-'} ${body.code} -> ${kind}`, () => {
    assert.equal(cap(http, body).kind, kind);
  });
}

test('NEEDS_REVIEW needs both the code and the status; never success or not_approved', () => {
  assert.equal(cap(409, { status: 'NEEDS_REVIEW', code: 'PAYMENT_NEEDS_REVIEW' }).kind, 'review');
  assert.equal(cap(409, { code: 'PAYMENT_NEEDS_REVIEW' }).kind, 'unknown');
  assert.equal(cap(409, { status: 'CREATED', code: 'PAYMENT_NEEDS_REVIEW' }).kind, 'unknown');
  assert.equal(cap(200, { status: 'NEEDS_REVIEW', code: 'PAYMENT_NEEDS_REVIEW' }).kind, 'unknown');
  const d = cap(409, { status: 'NEEDS_REVIEW', code: 'PAYMENT_NEEDS_REVIEW' });
  assert.match(d.kind === 'review' ? d.message : '', /do not pay again/i);
});

test('a declined capture tells the user a new checkout will be started', () => {
  const d = cap(402, { status: 'DECLINED', code: 'PAYMENT_DECLINED', next_step: 'new_order' });
  assert.equal(d.kind, 'declined');
  assert.match(d.kind === 'declined' ? d.message : '', /new checkout/i);
});

test('success carries premium_until; declined carries retryable', () => {
  assert.deepEqual(cap(...(RECOGNIZED[0].slice(0, 2) as [number, Body])),
    { kind: 'success', premiumUntil: '2026-12-10T00:00:00+00:00' });
  const d = cap(402, { status: 'DECLINED', code: 'PAYMENT_DECLINED', retryable: true });
  assert.equal(d.kind === 'declined' && d.retryable, true);
});

// ---------------------------------------------------------- missing code ---
for (const [http, body, kind] of RECOGNIZED) {
  test(`capture ${http} -> ${kind} WITHOUT code is unknown`, () => {
    const { code: _drop, ...noCode } = body;
    assert.equal(cap(http, noCode).kind, 'unknown');
  });
}

// ---------------------------------------------------------- unknown code ---
for (const [http, body, kind] of RECOGNIZED) {
  test(`capture ${http} (${kind} shape) with an unknown code is unknown`, () => {
    assert.equal(cap(http, { ...body, code: 'SOMETHING_NEW' }).kind, 'unknown');
  });
}

// ------------------------------------------- code / HTTP status mismatch ---
test('every recognized code under every other HTTP status is unknown', () => {
  const statuses = [200, 201, 202, 400, 402, 404, 409, 410, 422, 500, 502, 503];
  for (const [http, body] of RECOGNIZED) {
    for (const other of statuses.filter((s) => s !== http)) {
      assert.equal(cap(other, body).kind, 'unknown', `${body.code} with HTTP ${other}`);
    }
  }
});

test('code / status-field mismatch is unknown', () => {
  assert.equal(cap(200, { status: 'PENDING', code: 'PAYMENT_COMPLETED' }).kind, 'unknown');
  assert.equal(cap(202, { status: 'PENDING', code: 'PAYMENT_UNCERTAIN' }).kind, 'unknown');
  assert.equal(cap(202, { status: 'COMPLETED', code: 'PAYMENT_PENDING' }).kind, 'unknown');
  assert.equal(cap(402, { status: 'CREATED', code: 'PAYMENT_DECLINED' }).kind, 'unknown');
  assert.equal(cap(409, { status: 'REJECTED', code: 'ORDER_NOT_APPROVED' }).kind, 'unknown');
  assert.equal(cap(409, { status: 'CREATED', code: 'PAYMENT_REJECTED' }).kind, 'unknown');
  assert.equal(cap(409, { status: 'CREATED', code: 'CAPTURE_ID_CONFLICT' }).kind, 'unknown');
  assert.equal(cap(410, { status: 'CREATED', code: 'ORDER_EXPIRED' }).kind, 'unknown');
  assert.equal(cap(404, { status: 'EXPIRED', code: 'ORDER_NOT_FOUND' }).kind, 'unknown');
});

// ----------------------------------------------------- order is not lost ---
test('410 without ORDER_EXPIRED never clears the order (not "expired")', () => {
  for (const body of [{ status: 'EXPIRED' }, { status: 'EXPIRED', code: 'X' }, {}, { code: 'ORDER_NOT_FOUND' }]) {
    const d = cap(410, body);
    assert.notEqual(d.kind, 'expired', JSON.stringify(body));
    assert.equal(d.kind, 'unknown');
  }
});

test('404 without ORDER_NOT_FOUND never clears the order (not "not_found")', () => {
  for (const body of [{}, { detail: 'Not Found' }, { code: 'X' }, { code: 'ORDER_EXPIRED' }]) {
    const d = cap(404, body);
    assert.notEqual(d.kind, 'not_found', JSON.stringify(body));
    assert.equal(d.kind, 'unknown');
  }
});

test('unrecognized answers never yield a state-changing decision', () => {
  const weird: Array<[number, unknown]> = [
    [200, {}], [200, { status: 'COMPLETED' }], [200, { code: 'PAYMENT_COMPLETED' }],
    [500, { detail: 'Internal Server Error' }], [500, 'Internal Server Error'], [200, null],
    [409, {}], [409, { status: 'CREATED' }], [418, { code: 'PAYMENT_COMPLETED', status: 'COMPLETED' }],
  ];
  for (const [http, body] of weird) {
    const d = cap(http, body);
    assert.equal(d.kind, 'unknown', `${http} ${JSON.stringify(body)}`);
    assert.ok(!STATE_CHANGING.includes(d.kind));
    assert.match(d.kind === 'unknown' ? d.message : '', /do not pay again/i);
  }
});

// ---------------------------------------------------------------- create ---
test('create 201 ORDER_CREATED / 200 ORDER_REUSED with valid id -> order', () => {
  assert.deepEqual(create(201, { order_id: 'A1-B2', code: 'ORDER_CREATED' }), { kind: 'order', orderId: 'A1-B2' });
  assert.deepEqual(create(200, { order_id: 'A1-B2', code: 'ORDER_REUSED' }), { kind: 'order', orderId: 'A1-B2' });
});

test('create 201 with order_id but missing/wrong code never passes the id to PayPal', () => {
  for (const code of [undefined, 'ORDER_REUSED', 'SOMETHING_NEW', 'UNRESOLVED_PAYMENT', '']) {
    const d = create(201, { order_id: 'A1', code });
    assert.equal(d.kind, 'error', String(code));
    assert.ok(!('orderId' in d));
  }
});

test('create 200 with order_id but missing/wrong code never passes the id to PayPal', () => {
  for (const code of [undefined, 'ORDER_CREATED', 'SOMETHING_NEW', 'UNRESOLVED_PAYMENT', '']) {
    const d = create(200, { order_id: 'A1', code });
    assert.equal(d.kind, 'error', String(code));
    assert.ok(!('orderId' in d));
  }
});

test('create with a right code but missing/invalid order_id -> error', () => {
  for (const order_id of [undefined, '', 'has space', 'x'.repeat(65), 123, '../etc']) {
    assert.equal(create(201, { order_id, code: 'ORDER_CREATED' }).kind, 'error', String(order_id));
    assert.equal(create(200, { order_id, code: 'ORDER_REUSED' }).kind, 'error', String(order_id));
    assert.equal(create(409, { order_id, code: 'UNRESOLVED_PAYMENT' }).kind, 'error', String(order_id));
  }
});

test('create 409 UNRESOLVED_PAYMENT -> confirm that order, not a new one', () => {
  const d = create(409, { code: 'UNRESOLVED_PAYMENT', order_id: 'B2', status: 'UNCERTAIN', detail: 'x' });
  assert.equal(d.kind, 'unresolved');
  assert.equal(d.kind === 'unresolved' && d.orderId, 'B2');
});

test('create 409 other codes / no code never yield an order id', () => {
  assert.equal(create(409, { code: 'CREATE_IN_PROGRESS' }).kind, 'error');
  assert.equal(create(409, { code: 'ORDER_ALREADY_PROCESSED', order_id: 'C3', status: 'COMPLETED' }).kind, 'error');
  assert.equal(create(409, { order_id: 'C3', status: 'CREATED' }).kind, 'error');
  assert.equal(create(409, { order_id: 'C3', code: 'ORDER_CREATED' }).kind, 'error');
});

test('create code / HTTP status mismatch -> error', () => {
  assert.equal(create(202, { order_id: 'A1', code: 'ORDER_CREATED' }).kind, 'error');
  assert.equal(create(500, { order_id: 'A1', code: 'ORDER_REUSED' }).kind, 'error');
  assert.equal(create(201, { order_id: 'A1', code: 'UNRESOLVED_PAYMENT' }).kind, 'error');
  assert.equal(create(200, { code: 'CREATE_IN_PROGRESS' }).kind, 'error');
  assert.equal(create(502, { code: 'PAYMENTS_UNAVAILABLE' }).kind, 'error');
});

test('create 502 / 503 with their codes', () => {
  assert.equal(create(502, { code: 'CREATE_UNCONFIRMED', detail: 'x' }).kind, 'error');
  assert.equal(create(502, { code: 'PAYPAL_ERROR' }).kind, 'error');
  assert.equal(create(503, { code: 'PAYMENTS_UNAVAILABLE' }).kind, 'unavailable');
  assert.equal(create(503, { code: 'PRICING_MISCONFIGURED' }).kind, 'unavailable');
  assert.equal(create(503, {}).kind, 'error');
  assert.equal(create(500, 'Internal Server Error').kind, 'error');
});

// ------------------------------------------------- GET /orders/unresolved ---
const unres = (httpStatus: number, data: unknown) => decideUnresolved({ httpStatus, data } as never);
// A real backend order (_public_order) with overrides.
const ord = (over: Body = {}): Body => ({
  order_id: 'TESTORDER0001ABCDEF', status: 'CREATED', amount: '9.00', currency: 'USD',
  created_at: '2026-11-10T10:00:00+00:00', completed_at: null, blocking: false, resumable: true, ...over,
});

test('unresolved: valid empty response -> none', () => {
  assert.deepEqual(unres(200, { order: null }), { kind: 'none' });
});

test('unresolved: valid blocking responses (PENDING, UNCERTAIN)', () => {
  for (const status of ['PENDING', 'UNCERTAIN']) {
    assert.deepEqual(unres(200, { order: ord({ status, blocking: true, resumable: false }) }),
      { kind: 'blocking', orderId: 'TESTORDER0001ABCDEF' }, status);
  }
});

test('unresolved: valid resumable response (CREATED)', () => {
  assert.deepEqual(unres(200, { order: ord() }), { kind: 'resumable_created', orderId: 'TESTORDER0001ABCDEF' });
});

test('unresolved: a DECLINED order is final, never resumable (-> unknown if ever sent)', () => {
  assert.equal(unres(200, { order: ord({ status: 'DECLINED' }) }).kind, 'unknown');
  assert.equal(unres(200, { order: ord({ status: 'DECLINED', blocking: true, resumable: false }) }).kind, 'unknown');
});

test('unresolved: NEEDS_REVIEW (blocking) -> review, keeps the order id', () => {
  assert.deepEqual(unres(200, { order: ord({ status: 'NEEDS_REVIEW', blocking: true, resumable: false }) }),
    { kind: 'review', orderId: 'TESTORDER0001ABCDEF' });
  for (const over of [{ blocking: false, resumable: false }, { blocking: true, resumable: true },
    { blocking: false, resumable: true }]) {
    assert.equal(unres(200, { order: ord({ status: 'NEEDS_REVIEW', ...over }) }).kind, 'unknown', JSON.stringify(over));
  }
});

test('unresolved: malformed envelope -> unknown (never ready)', () => {
  for (const data of [undefined, null, {}, [], 'ok', 42, true, { orders: null }, { detail: 'x' }, { order: undefined }]) {
    assert.equal(unres(200, data).kind, 'unknown', JSON.stringify(data) ?? String(data));
  }
});

test('unresolved: non-200 -> unknown, even with a valid-looking body', () => {
  for (const http of [201, 204, 304, 400, 401, 404, 409, 500, 502, 503]) {
    assert.equal(unres(http, { order: null }).kind, 'unknown', String(http));
    assert.equal(unres(http, { order: ord() }).kind, 'unknown', String(http));
  }
});

test('unresolved: order of the wrong type -> unknown', () => {
  for (const order of ['TESTORDER0001', 7, true, false, [], [ord()]]) {
    assert.equal(unres(200, { order }).kind, 'unknown', JSON.stringify(order));
  }
});

test('unresolved: missing required fields -> unknown', () => {
  for (const field of ['order_id', 'status', 'blocking', 'resumable']) {
    const o = ord();
    delete o[field];
    assert.equal(unres(200, { order: o }).kind, 'unknown', `missing ${field}`);
    const b = ord({ status: 'UNCERTAIN', blocking: true, resumable: false });
    delete b[field];
    assert.equal(unres(200, { order: b }).kind, 'unknown', `missing ${field} (blocking)`);
  }
});

test('unresolved: wrong field types -> unknown', () => {
  const bad: Body[] = [
    { blocking: 'false' }, { blocking: 0 }, { blocking: null },
    { resumable: 'true' }, { resumable: 1 }, { resumable: null },
    { status: 1 }, { status: null }, { status: ['CREATED'] },
    { order_id: 123 }, { order_id: null }, { order_id: ['TESTORDER0001'] },
  ];
  for (const over of bad) {
    assert.equal(unres(200, { order: ord(over) }).kind, 'unknown', JSON.stringify(over));
  }
});

test('unresolved: unexpected status values -> unknown', () => {
  for (const status of ['COMPLETED', 'REJECTED', 'EXPIRED', 'IN_PROGRESS', 'APPROVED', 'created', '', 'UNKNOWN']) {
    assert.equal(unres(200, { order: ord({ status }) }).kind, 'unknown', status);
    assert.equal(unres(200, { order: ord({ status, blocking: true, resumable: false }) }).kind, 'unknown', status);
  }
});

test('unresolved: flags inconsistent with status -> unknown', () => {
  const bad: Body[] = [
    { status: 'PENDING', blocking: false, resumable: true },   // blocking status not flagged blocking
    { status: 'UNCERTAIN', blocking: false, resumable: false },
    { status: 'UNCERTAIN', blocking: true, resumable: true },
    { status: 'CREATED', blocking: true, resumable: false },   // resumable status flagged blocking
    { status: 'CREATED', blocking: false, resumable: false },  // e.g. outside the reuse window
    { status: 'DECLINED', blocking: true, resumable: true },
    { status: 'DECLINED', blocking: false, resumable: false },
  ];
  for (const over of bad) {
    assert.equal(unres(200, { order: ord(over) }).kind, 'unknown', JSON.stringify(over));
  }
});

test('unresolved: malformed order ids -> unknown (no id is ever returned)', () => {
  for (const order_id of ['', ' ', 'has space', 'x'.repeat(65), '../etc', 'A/B', 'A?B', 'ORDER\n1', 'Ä1']) {
    for (const over of [{}, { status: 'UNCERTAIN', blocking: true, resumable: false }]) {
      const d = unres(200, { order: ord({ order_id, ...over }) });
      assert.equal(d.kind, 'unknown', JSON.stringify(order_id));
      assert.ok(!('orderId' in d));
    }
  }
});

test('unresolved: unknown decision carries a safe message', () => {
  const d = unres(500, 'Internal Server Error');
  assert.equal(d.kind, 'unknown');
  assert.match(d.kind === 'unknown' ? d.message : '', /paying twice|contact support/i);
});

// --------------------------------------------- GET /payments/paypal/config ---
test('checkout is available only for 200 + enabled:true + a client id', () => {
  const ok = { enabled: true, client_id: 'sandbox-client-id', environment: 'sandbox' };
  assert.equal(isCheckoutAvailable({ httpStatus: 200, data: ok } as never), true);
});

test('missing/invalid PayPal configuration keeps checkout unavailable', () => {
  const cases: Array<[number, unknown]> = [
    [200, { enabled: false, client_id: null }],          // backend: credentials missing
    [200, { enabled: true, client_id: null }],
    [200, { enabled: true, client_id: '' }],
    [200, { enabled: true, client_id: '   ' }],
    [200, { enabled: 'true', client_id: 'x' }],          // wrong type
    [200, { client_id: 'x' }],
    [200, null], [200, 'ok'],
    [503, { detail: 'Premium pricing is not configured correctly.' }],
    [404, { detail: 'Not Found' }], [500, 'Internal Server Error'],
  ];
  for (const [httpStatus, data] of cases) {
    assert.equal(isCheckoutAvailable({ httpStatus, data } as never), false, `${httpStatus} ${JSON.stringify(data)}`);
  }
});

test('a COMPLIANCE_VIOLATION decline explains the account restriction; still a final decline', () => {
  const d = cap(402, { status: 'DECLINED', code: 'PAYMENT_DECLINED', decline_issue: 'COMPLIANCE_VIOLATION' });
  assert.equal(d.kind, 'declined');
  assert.match(d.kind === 'declined' ? d.message : '', /compliance/i);
  const plain = cap(402, { status: 'DECLINED', code: 'PAYMENT_DECLINED' });
  assert.doesNotMatch(plain.kind === 'declined' ? plain.message : '', /compliance/i);
});

test('an UNCERTAIN status-check answer never counts as success or as approved', () => {
  const d = cap(202, { status: 'UNCERTAIN', code: 'PAYMENT_UNCERTAIN', retryable: true });
  assert.equal(d.kind, 'pending');
  assert.equal(cap(202, { status: 'IN_PROGRESS', code: 'CAPTURE_IN_PROGRESS' }).kind, 'pending');
  assert.equal(cap(200, { status: 'APPROVED', code: 'PAYMENT_COMPLETED' }).kind, 'unknown');
});
