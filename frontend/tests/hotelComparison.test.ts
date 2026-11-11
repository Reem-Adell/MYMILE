// Run: npm test
// Hotel comparison grid: sorting, quick search, selection and budget impact.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  applyHotelSelection,
  budgetImpact,
  createSelectionGate,
  hotelSearchText,
  nullsLastComparator,
  ratingValue,
  recalculateBudget,
} from '../src/services/hotelComparison.ts';
import type { BudgetBreakdown, Hotel, TripPlan } from '../src/types/index.ts';

function hotel(id: string, over: Partial<Hotel> = {}): Hotel {
  return {
    id, name: `Hotel ${id}`, location: 'Cairo', rating: 4.5, reviews_count: 100, price_per_night: 100,
    total_price: 300, currency: 'USD', image_url: 'i', amenities: ['Free Wi-Fi', 'Pool'], best_match_reason: 'r',
    category: 'Hotel', is_best_match: false, ...over,
  };
}

const BUDGET: BudgetBreakdown = {
  accommodation: 900, transportation: 150, food: 360, activities: 240, travel_essentials: 80,
  contingency_and_other: 70, total_estimated: 1800, user_budget: 2000, remaining_balance: 200,
  currency: 'USD', status: 'balanced',
};

function trip(over: Partial<TripPlan> = {}): TripPlan {
  const rec = hotel('a', { total_price: 900, is_best_match: true });
  return {
    trip_id: 't1', destination: 'Cairo, Egypt', departure_date: '2026-12-01', return_date: '2026-12-04',
    total_days: 3, travelers: 2, purpose: 'Tourism', stay_preference: 'Boutique hotel', plan_tier: 'premium',
    destination_summary: 's', why_recommended: 'w', weather: {} as TripPlan['weather'], recommended_hotel: rec,
    all_hotels: [rec, hotel('b', { total_price: 600 }), hotel('c', { total_price: 1200 })], itinerary: [],
    budget_breakdown: BUDGET, travel_essentials: [], is_premium: true, ...over,
  };
}

// AG Grid applies the comparator, then reverses it for descending sorts.
function sortBy<T>(rows: T[], get: (r: T) => number | null, desc = false): T[] {
  const out = [...rows].sort((a, b) => nullsLastComparator(get(a), get(b), null, null, desc));
  return desc ? out.reverse() : out;
}

// ---- Sorting ----
test('nightly price sorts both ways with unlisted prices last', () => {
  const rows = [hotel('x', { price_per_night: 200 }), hotel('y', { price_per_night: null }),
    hotel('z', { price_per_night: 80 })];
  assert.deepEqual(sortBy(rows, (h) => h.price_per_night).map((h) => h.id), ['z', 'x', 'y']);
  assert.deepEqual(sortBy(rows, (h) => h.price_per_night, true).map((h) => h.id), ['x', 'z', 'y']);
});

test('total stay price and rating sort with blanks last; rating 0 counts as no rating', () => {
  const rows = [hotel('x', { total_price: 900, rating: 4.1 }), hotel('y', { total_price: null, rating: 0 }),
    hotel('z', { total_price: 300, rating: 4.8 })];
  assert.deepEqual(sortBy(rows, (h) => h.total_price).map((h) => h.id), ['z', 'x', 'y']);
  assert.deepEqual(sortBy(rows, (h) => ratingValue(h), true).map((h) => h.id), ['z', 'x', 'y']);
  assert.deepEqual(sortBy(rows, (h) => ratingValue(h)).map((h) => h.id), ['x', 'z', 'y']);
  assert.equal(ratingValue(hotel('p', { rating: 0 })), null);
});

// ---- Quick search ----
test('quick search covers name, area, category and amenities only', () => {
  const text = hotelSearchText(hotel('q', { name: 'Nile Ritz', location: 'Garden City', category: 'Luxury hotel',
    amenities: ['Spa', 'Outdoor pool'] }));
  for (const word of ['Nile Ritz', 'Garden City', 'Luxury hotel', 'Spa', 'Outdoor pool']) assert.ok(text.includes(word));
  assert.ok(!text.includes('300'), 'prices are filtered with the numeric filters, not the search');
});

// ---- Selection: row click and Choose share one deduplicated path ----
test('a Choose click (which is also a row click) selects once; switching selects again', () => {
  const gate = createSelectionGate('a');
  const selected: string[] = [];
  const choose = (h: Hotel) => { if (gate.select(h.id)) selected.push(h.id); };
  const b = hotel('b');
  choose(b);            // Choose button
  choose(b);            // the same click bubbling to the row
  choose(hotel('a'));   // switching back
  choose(hotel('a'));   // repeated row click
  assert.deepEqual(selected, ['b', 'a']);
});

test('selection made elsewhere (assistant, new plan) is followed without re-triggering', () => {
  const gate = createSelectionGate('a');
  gate.sync('c');
  assert.equal(gate.select('c'), false, 'already selected');
  assert.equal(gate.select('b'), true);
  assert.equal(gate.current, 'b');
});

test('row click and Choose produce exactly the same app state', () => {
  const viaRow = applyHotelSelection(trip(), null, hotel('b', { total_price: 600 }), 'premium');
  const viaButton = applyHotelSelection(trip(), null, hotel('b', { total_price: 600 }), 'premium');
  assert.deepEqual(viaRow, viaButton);
});

// ---- Budget recalculation ----
test('the existing budget formula is unchanged', () => {
  const next = recalculateBudget(BUDGET, 600);
  // accommodation = hotel total; other categories kept: 150+360+240+80+70 = 900
  assert.deepEqual(next, { ...BUDGET, accommodation: 600, total_estimated: 1500, remaining_balance: 500,
    status: 'balanced' });
  const over = recalculateBudget(BUDGET, 1300);
  assert.equal(over.remaining_balance, -200);
  assert.equal(over.status, 'over_budget');
  const noUserBudget = recalculateBudget({ ...BUDGET, user_budget: null }, 600);
  assert.equal(noUserBudget.remaining_balance, 4500 - 1500, 'existing fallback kept as before');
});

test('switching hotels updates the budget and reports the impact', () => {
  const t = trip();
  const result = applyHotelSelection(t, t.recommended_hotel, hotel('b', { total_price: 600 }), 'premium')!;
  assert.equal(result.selectedHotel.id, 'b');
  assert.equal(result.trip!.recommended_hotel.id, 'b');
  assert.equal(result.trip!.budget_breakdown!.accommodation, 600);
  assert.equal(result.trip!.budget_breakdown!.total_estimated, 1500);
  assert.deepEqual(result.impact, {
    tripId: 't1', previousName: 'Hotel a', previousTotal: 900, nextName: 'Hotel b', nextTotal: 600,
    difference: -300, direction: 'decrease', remaining: 500, currency: 'USD',
  });
  const up = applyHotelSelection(result.trip, result.selectedHotel, hotel('c', { total_price: 1200 }), 'premium')!;
  assert.equal(up.impact!.direction, 'increase');
  assert.equal(up.impact!.difference, 600);
  assert.equal(up.impact!.remaining, -100);
});

test('selecting the already selected hotel recalculates nothing', () => {
  const t = trip();
  assert.equal(applyHotelSelection(t, null, t.recommended_hotel, 'premium'), null, 'default selection');
  const first = applyHotelSelection(t, t.recommended_hotel, hotel('b', { total_price: 600 }), 'premium')!;
  assert.equal(applyHotelSelection(first.trip, first.selectedHotel, hotel('b', { total_price: 600 }), 'premium'), null);
});

test('no invented figures: unknown price keeps the budget; no remaining without a user budget', () => {
  const t = trip();
  const unknown = applyHotelSelection(t, t.recommended_hotel, hotel('b', { total_price: null }), 'premium')!;
  assert.equal(unknown.trip, t, 'budget untouched');
  assert.equal(unknown.impact!.direction, 'unknown');
  assert.equal(unknown.impact!.difference, null);
  const noUserBudget = trip({ budget_breakdown: { ...BUDGET, user_budget: null } });
  const res = applyHotelSelection(noUserBudget, null, hotel('b', { total_price: 600 }), 'premium')!;
  assert.equal(res.impact!.remaining, null, 'the 4500 fallback is never shown as the traveler’s remaining budget');
});

test('Free accounts select hotels without budget data or impact', () => {
  const free = trip({ budget_breakdown: null, plan_tier: 'free', is_premium: false });
  const res = applyHotelSelection(free, null, hotel('b'), 'free')!;
  assert.equal(res.selectedHotel.id, 'b');
  assert.equal(res.trip, free);
  assert.equal(res.impact, null);
  const expired = applyHotelSelection(trip(), null, hotel('b'), 'free')!;
  assert.equal(expired.impact, null, 'premium data is not used once /auth/me says free');
});

test('impact with same totals is "same"', () => {
  const i = budgetImpact(hotel('a', { total_price: 300 }), hotel('b', { total_price: 300 }), BUDGET, 't1');
  assert.equal(i.direction, 'same');
  assert.equal(i.difference, 0);
});
