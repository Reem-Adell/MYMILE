// Run: npm test
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  MAX_TRIPS,
  accountKey,
  getActiveTrip,
  isValidTripRequest,
  cleanDescription,
  descriptionError,
  DESCRIPTION_MAX,
  loadTrips,
  saveTrip,
  setActiveTrip,
  toPlanPayload,
  type KeyValueStore,
  type TripRequest,
} from '../src/services/tripStore.ts';

function memoryStore(): KeyValueStore & { data: Map<string, string> } {
  const data = new Map<string, string>();
  return { data, getItem: (k) => data.get(k) ?? null, setItem: (k, v) => void data.set(k, v) };
}

function trip(id: string, over: Partial<TripRequest> = {}): TripRequest {
  return {
    id, created_at: '2026-11-11T10:00:00Z', destination: 'Cairo, Egypt', destination_city: 'Cairo',
    destination_country: 'Egypt', departure_date: '2026-12-01', return_date: '2026-12-04', travelers: 2,
    purpose: 'Tourism', stay_preference: 'Boutique hotel', priorities: ['Local culture'],
    notes: 'near the museums', ...over,
  };
}

test('no stored trip -> nothing to show (Explore stays empty)', () => {
  const s = loadTrips(memoryStore(), 'guest');
  assert.deepEqual(s, { activeId: null, trips: [] });
  assert.equal(getActiveTrip(s), null);
  assert.equal(getActiveTrip(loadTrips(null, 'guest')), null, 'no storage available');
});

test('a saved trip becomes the active trip and survives a reload', () => {
  const store = memoryStore();
  saveTrip(store, 'user:1', trip('a'));
  const reloaded = loadTrips(store, 'user:1');     // simulates a browser refresh
  assert.equal(getActiveTrip(reloaded)?.id, 'a');
  assert.equal(getActiveTrip(reloaded)?.destination_city, 'Cairo');
});

test('the newest trip is active; switching makes another one active', () => {
  const store = memoryStore();
  saveTrip(store, 'user:1', trip('a'));
  saveTrip(store, 'user:1', trip('b', { destination_city: 'Paris', destination_country: 'France' }));
  assert.equal(getActiveTrip(loadTrips(store, 'user:1'))?.id, 'b');
  const switched = setActiveTrip(store, 'user:1', 'a');
  assert.equal(getActiveTrip(switched)?.destination_city, 'Cairo');
  assert.equal(getActiveTrip(loadTrips(store, 'user:1'))?.id, 'a', 'switch persisted');
  assert.equal(getActiveTrip(setActiveTrip(store, 'user:1', 'nope'))?.id, 'a', 'unknown id ignored');
});

test('trips are kept per account (no other account’s trip is shown)', () => {
  const store = memoryStore();
  saveTrip(store, accountKey('u1'), trip('a'));
  assert.equal(getActiveTrip(loadTrips(store, accountKey('u2'))), null);
  assert.equal(getActiveTrip(loadTrips(store, accountKey(null))), null, 'guest sees nothing');
  assert.equal(accountKey(undefined), 'guest');
});

test('the list is capped and de-duplicated', () => {
  const store = memoryStore();
  for (let i = 0; i < MAX_TRIPS + 3; i++) saveTrip(store, 'g', trip(`t${i}`));
  saveTrip(store, 'g', trip(`t${MAX_TRIPS + 2}`));
  const s = loadTrips(store, 'g');
  assert.equal(s.trips.length, MAX_TRIPS);
  assert.equal(new Set(s.trips.map((t) => t.id)).size, MAX_TRIPS);
});

test('corrupt or tampered storage is ignored safely', () => {
  const store = memoryStore();
  store.setItem('mymile.trips.v1.g', '{not json');
  assert.deepEqual(loadTrips(store, 'g'), { activeId: null, trips: [] });
  store.setItem('mymile.trips.v1.g', JSON.stringify({ activeId: 'x', trips: [{ id: 'x', destination_city: '' }] }));
  assert.equal(getActiveTrip(loadTrips(store, 'g')), null, 'invalid trip dropped');
  const throwing: KeyValueStore = { getItem: () => { throw new Error('blocked'); }, setItem: () => { throw new Error('full'); } };
  assert.deepEqual(loadTrips(throwing, 'g'), { activeId: null, trips: [] });
  assert.doesNotThrow(() => saveTrip(throwing, 'g', trip('a')));
});

test('invalid trips are never saved', () => {
  for (const bad of [trip('a', { destination_city: ' ' }), trip('a', { destination_country: '' }),
    trip('a', { departure_date: '12/01/2026' }), trip('a', { travelers: 0 }), trip('a', { total_budget: -5 }),
    trip('a', { shopping_audience: 'kids' as never })]) {
    assert.equal(isValidTripRequest(bad), false);
  }
  const store = memoryStore();
  saveTrip(store, 'g', trip('a', { destination_city: '' }));
  assert.equal(loadTrips(store, 'g').trips.length, 0);
});

test('re-planning sends EVERY field (notes, priorities, city, country, budget, shopping audience)', () => {
  const p = toPlanPayload(trip('a', { total_budget: 1500, shopping_audience: 'women' }), 'premium');
  assert.deepEqual(p, {
    destination: 'Cairo, Egypt', destination_city: 'Cairo', destination_country: 'Egypt',
    departure_date: '2026-12-01', return_date: '2026-12-04', travelers: 2, purpose: 'Tourism',
    stay_preference: 'Boutique hotel', priorities: ['Local culture'], notes: 'near the museums',
    plan: 'premium', total_budget: 1500, shopping_audience: 'women',
  });
});

test('trips saved before the shopping audience existed still load and re-plan as "everyone"', () => {
  const old = trip('old');
  assert.equal(isValidTripRequest(old), true);
  const p = toPlanPayload(old, 'free');
  assert.equal(p.shopping_audience, undefined, 'absent field: not sent, backend treats it as everyone');
  for (const who of ['men', 'women', 'all'] as const) assert.equal(isValidTripRequest(trip('a', { shopping_audience: who })), true);
});

test('the trip description is required, trimmed and at most 500 characters', () => {
  assert.equal(DESCRIPTION_MAX, 500);
  assert.equal(cleanDescription('  A beach   holiday \n'), 'A beach holiday');
  assert.match(descriptionError('   ')!, /Tell us about your trip/);
  assert.match(descriptionError('x'.repeat(501))!, /500 characters/);
  assert.equal(descriptionError('x'.repeat(500)), null);
  assert.equal(descriptionError('A beach holiday'), null);
  assert.equal(isValidTripRequest(trip('a', { notes: '' })), false, 'saved trips need a description');
  assert.equal(isValidTripRequest(trip('a', { notes: 'y'.repeat(501) })), false);
  assert.equal(isValidTripRequest(trip('a', { notes: 'A beach holiday' })), true);
});
