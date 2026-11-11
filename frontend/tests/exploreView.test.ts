// Run: npm test
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  PRICE_DISCLAIMER,
  bookingView,
  canShowBudget,
  formatMoney,
  heroLocation,
  isPremiumView,
  priceView,
} from '../src/services/exploreView.ts';
import type { Hotel } from '../src/types/index.ts';

const BUDGET = { accommodation: 500, transportation: 1, food: 1, activities: 1, travel_essentials: 1,
  contingency_and_other: 1, total_estimated: 505, currency: 'USD', status: 'balanced' };

function hotel(over: Partial<Hotel> = {}): Hotel {
  return {
    id: 'cai-02', name: 'Steigenberger Hotel El Tahrir', location: 'Tahrir Square, Downtown Cairo', rating: 4.5,
    reviews_count: 2840, price_per_night: 95, total_price: 570, currency: 'USD', image_url: 'i', amenities: [],
    best_match_reason: 'r', category: 'Boutique hotel', is_best_match: true, price_source: 'estimate',
    nights: 3, rooms: 2, booking_link: null, ...over,
  };
}

// ---- Premium gating ----
test('Budget Snapshot / Estimated Cost: only for an active Premium account with a Premium plan', () => {
  assert.equal(canShowBudget('premium', { is_premium: true, budget_breakdown: BUDGET }), true);
  assert.equal(canShowBudget('free', { is_premium: false, budget_breakdown: null }), false, 'free');
  assert.equal(canShowBudget('free', { is_premium: true, budget_breakdown: BUDGET }), false,
    'expired Premium: /auth/me says free, a stale Premium plan is not shown');
  assert.equal(canShowBudget('premium', { is_premium: false, budget_breakdown: null }), false,
    'plan generated before the upgrade: no budget data yet');
  assert.equal(canShowBudget('premium', { is_premium: true, budget_breakdown: null }), false);
});

test('Premium view requires both the verified account and a Premium plan', () => {
  assert.equal(isPremiumView('premium', { is_premium: true }), true);
  assert.equal(isPremiumView('free', { is_premium: true }), false);
  assert.equal(isPremiumView('premium', { is_premium: false }), false);
});

// ---- Pricing ----
test('estimates are labelled as estimates, with currency, nights and rooms', () => {
  const v = priceView(hotel(), 3, 2);
  assert.equal(v.kind, 'estimate');
  assert.equal(v.nightly, 'Est. USD 95 / room / night');
  assert.equal(v.total, 'USD 570');
  assert.equal(v.totalLabel, 'Estimated total for your stay');
  assert.equal(v.details, '3 nights · 2 rooms');
  assert.match(v.note, /not a live price/);
});

test('a listed price says where it comes from, the tax status and that it is not confirmed', () => {
  const v = priceView(hotel({ price_source: 'live', price_provider: 'Booking.com', price_per_night: 100,
    total_price: 620, taxes_included: true, price_checked_at: '2026-11-11T10:00:00Z' }), 3, 2);
  assert.equal(v.kind, 'listed');
  assert.equal(v.nightly, 'USD 100 / room / night');
  assert.equal(v.totalLabel, 'Listed total for your stay');
  assert.match(v.note, /listed by Booking\.com/);
  assert.match(v.note, /incl\. taxes & fees as listed/);
  assert.match(v.note, /Not a confirmed rate/);
  assert.doesNotMatch(v.note, /confirmed live/i);
  const unknownTax = priceView(hotel({ price_source: 'live', taxes_included: null }), 3, 2);
  assert.match(unknownTax.note, /may not be included/);
  const beforeTax = priceView(hotel({ price_source: 'live', taxes_included: false }), 3, 2);
  assert.match(beforeTax.note, /before taxes & fees/);
});

test('nightly and total are never confused', () => {
  const v = priceView(hotel({ price_per_night: 95, total_price: 570 }), 3, 2);
  assert.ok(v.nightly.includes('95') && v.nightly.includes('/ night'));
  assert.ok(v.total.includes('570') && !v.total.includes('night'));
});

test('a placeholder shows a typical rate, not a hotel price', () => {
  const v = priceView(hotel({ is_placeholder: true, price_per_night: 150, total_price: 450 }), 3, 1);
  assert.equal(v.kind, 'typical');
  assert.match(v.nightly, /^Typical USD 150/);
  assert.match(v.note, /not a price for a specific hotel/);
});

test('currency is always explicit', () => {
  assert.equal(formatMoney(1230.4, 'USD'), 'USD 1,230');
  assert.equal(formatMoney(50, 'EUR'), 'EUR 50');
  assert.equal(formatMoney(5, ''), 'USD 5');
  assert.match(PRICE_DISCLAIMER, /estimates and may change/);
});

// ---- Booking.com button ----
test('a search link is never presented as the hotel’s own page', () => {
  const v = bookingView(hotel({ booking_link: 'https://www.booking.com/searchresults.html?ss=x',
    booking_link_type: 'search' }));
  assert.equal(v?.label, 'Search this hotel on Booking.com');
  assert.match(v!.note, /not a direct hotel page/);
  assert.doesNotMatch(v!.label, /live price|view this hotel/i);
});

test('only a verified property link says it opens the hotel page', () => {
  const v = bookingView(hotel({ booking_link: 'https://www.booking.com/hotel/eg/x.html', booking_link_type: 'property' }));
  assert.equal(v?.label, 'View this hotel on Booking.com');
  const missingType = bookingView(hotel({ booking_link: 'https://www.booking.com/searchresults.html?ss=x' }));
  assert.equal(missingType?.label, 'Search this hotel on Booking.com', 'unknown type is treated as a search');
});

test('no link (Free plan) -> no button; placeholder -> destination search', () => {
  assert.equal(bookingView(hotel({ booking_link: null })), null);
  const p = bookingView(hotel({ is_placeholder: true, booking_link: 'https://www.booking.com/searchresults.html?ss=Lisbon',
    booking_link_type: 'search' }));
  assert.equal(p?.label, 'Search stays on Booking.com');
});

// ---- Hero location ----
test('hero photo uses the structured city and country', () => {
  assert.deepEqual(heroLocation({ destination: 'x', destination_city: 'Cairo', destination_country: 'Egypt' }),
    { city: 'Cairo', country: 'Egypt' });
  assert.deepEqual(heroLocation({ destination: 'Kyoto, Japan' }), { city: 'Kyoto', country: 'Japan' });
  assert.deepEqual(heroLocation({ destination: 'Lisbon' }), { city: 'Lisbon', country: '' });
});
