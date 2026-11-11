// Run: npm test
// Display rules for live Google Hotels results (SerpApi) on the Explore page.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  LIVE_PRICE_DISCLAIMER,
  PRICE_DISCLAIMER,
  PRICE_VARIES_NOTE,
  bookingPriceLine,
  priceMeta,
  showsEstimateLabel,
  bookingView,
  mergeOffers,
  needsOffers,
  offersRequest,
  otherOffers,
  priceDisclaimer,
  priceView,
} from '../src/services/exploreView.ts';
import type { Hotel, HotelOffers } from '../src/types/index.ts';

const BOOKING_URL = 'https://www.booking.com/hotel/pt/avenida.html?aid=1';
const EXPEDIA_URL = 'https://www.expedia.com/Lisbon-Hotels-Avenida.h123.Hotel-Information';

function live(over: Partial<Hotel> = {}): Hotel {
  return {
    id: 'gh-abc', name: 'Hotel Avenida', location: 'Lisbon, Portugal', rating: 4.6, reviews_count: 1834,
    price_per_night: 120, total_price: 365, currency: 'USD', image_url: 'https://lh.example/a.jpg', amenities: [],
    best_match_reason: 'r', category: '4-star hotel', is_best_match: true, price_source: 'live',
    price_provider: 'Google Hotels', price_basis: 'per_night_for_party', nights: 3, rooms: 1, adults: 2,
    total_price_basis: 'listed', price_checked_at: '2026-11-11T10:00:00Z', data_source: 'serpapi',
    property_token: 'tok-a', booking_link: null, ...over,
  };
}

const PLAN = { destination: 'Lisbon, Portugal', destination_city: 'Lisbon', destination_country: 'Portugal',
  departure_date: '2026-12-10', return_date: '2026-12-13', travelers: 2 };

// ---- Prices ----
test('live price: per night for the party, listed total, source, time and not a confirmed rate', () => {
  const v = priceView(live(), 3, 1);
  assert.equal(v.kind, 'listed');
  assert.equal(v.nightly, 'USD 120 / night');
  assert.equal(v.total, 'USD 365');
  assert.equal(v.totalLabel, 'Listed total for your stay');
  assert.equal(v.details, '3 nights · 2 adults');
  assert.match(v.note, /^Last updated /);
  assert.match(v.note, /Lowest price listed on Google Hotels for your dates and 2 adults/);
  assert.match(v.note, /Not a confirmed rate/);
});

test('a total computed from the nightly rate is labelled as approximate', () => {
  const v = priceView(live({ total_price: 360, total_price_basis: 'nightly_x_nights' }), 3, 1);
  assert.match(v.totalLabel, /^Approx\. total/);
});

test('missing price is shown as missing, never as 0', () => {
  const v = priceView(live({ price_per_night: null, total_price: null }), 3, 1);
  assert.equal(v.kind, 'none');
  assert.equal(v.nightly, 'Price not listed for your dates');
  assert.equal(v.total, '—');
  assert.doesNotMatch(v.total + v.nightly, /USD 0/);
});

test('cached results say so, with their last checked time', () => {
  const v = priceView(live({ results_stale: true }), 3, 1);
  assert.match(v.note, /^Cached results \(live update unavailable\), last checked /);
});

test('live error/empty placeholder shows no price', () => {
  const v = priceView(live({ is_placeholder: true, price_per_night: null, total_price: null }), 3, 1);
  assert.equal(v.kind, 'none');
  assert.equal(v.note, '');
});

test('live disclaimer: provider-listed estimates, confirm on provider site, MYMILE does not book', () => {
  assert.equal(priceDisclaimer(live()), LIVE_PRICE_DISCLAIMER);
  assert.match(LIVE_PRICE_DISCLAIMER, /provider-listed estimates/);
  assert.match(LIVE_PRICE_DISCLAIMER, /confirmed on the provider’s website/);
  assert.match(LIVE_PRICE_DISCLAIMER, /does not complete hotel bookings/);
  assert.equal(priceDisclaimer({ data_source: 'curated' }), PRICE_DISCLAIMER);
});

// ---- Booking button ----
test('provider link: "Book on <provider>" opening the returned URL', () => {
  const h = live({ booking_link: BOOKING_URL, booking_link_type: 'provider', booking_provider: 'Booking.com',
    booking_offers: [{ provider: 'Booking.com', url: BOOKING_URL, price_per_night: 130, currency: 'USD', official: false }] });
  const v = bookingView(h)!;
  assert.equal(v.label, 'Book on Booking.com');
  assert.equal(v.href, BOOKING_URL);
  assert.match(v.note, /Booking\.com lists USD 130 \/ night/);
  assert.match(v.note, /doesn’t complete bookings/);
});

test('another provider is labelled with its own name', () => {
  const v = bookingView(live({ booking_link: EXPEDIA_URL, booking_link_type: 'provider', booking_provider: 'Expedia' }))!;
  assert.equal(v.label, 'Book on Expedia');
  assert.equal(v.href, EXPEDIA_URL);
});

test('no provider URL -> no booking button', () => {
  assert.equal(bookingView(live()), null);
});

test('other providers list only offers with a URL, excluding the main one', () => {
  const h = live({ booking_link: BOOKING_URL, booking_offers: [
    { provider: 'Booking.com', url: BOOKING_URL, currency: 'USD', official: false },
    { provider: 'Expedia', url: EXPEDIA_URL, currency: 'USD', official: false },
    { provider: 'Hotels.com', url: null, currency: 'USD', official: false },
  ] });
  assert.deepEqual(otherOffers(h).map((o) => o.provider), ['Expedia']);
});

// ---- Provider-link lookup ----
test('provider links are looked up only for Premium live hotels without a link', () => {
  assert.equal(needsOffers(live(), true), true);
  assert.equal(needsOffers(live(), false), false, 'Free: no lookup, no quota spent');
  assert.equal(needsOffers(live({ booking_link: BOOKING_URL }), true), false, 'already has a link');
  assert.equal(needsOffers(live({ is_placeholder: true }), true), false);
  assert.equal(needsOffers(live({ property_token: null }), true), false);
  assert.equal(needsOffers(live({ data_source: 'curated' }), true), false);
});

test('lookup uses exactly the trip search parameters', () => {
  assert.deepEqual(offersRequest(PLAN, live()), {
    property_token: 'tok-a', destination: 'Lisbon, Portugal', city: 'Lisbon', country: 'Portugal',
    check_in: '2026-12-10', check_out: '2026-12-13', adults: 2,
  });
});

test('merging offers keeps the website separate from the booking link', () => {
  const offers: HotelOffers = { property_token: 'tok-a', status: 'ok', booking_link: EXPEDIA_URL,
    booking_provider: 'Expedia', official_website: 'https://www.avenida.example/', stale: false,
    booking_offers: [{ provider: 'Expedia', url: EXPEDIA_URL, currency: 'USD', official: false }] };
  const h = mergeOffers(live(), offers);
  assert.equal(h.booking_link, EXPEDIA_URL);
  assert.equal(h.booking_link_type, 'provider');
  assert.equal(h.official_website, 'https://www.avenida.example/');
  assert.notEqual(h.booking_link, h.official_website);
});

test('unavailable or mismatched offers change nothing', () => {
  const h = live();
  assert.equal(mergeOffers(h, null), h);
  assert.equal(mergeOffers(h, { property_token: 'tok-a', status: 'unavailable', booking_offers: [], stale: false }), h);
  assert.equal(mergeOffers(h, { property_token: 'other', status: 'ok', booking_link: BOOKING_URL,
    booking_offers: [], stale: false }), h);
  const none = mergeOffers(h, { property_token: 'tok-a', status: 'ok', booking_link: null, booking_offers: [], stale: false });
  assert.equal(none.booking_link, null);
  assert.equal(bookingView(none), null);
});

// ---- "Estimated" label ----
test('every displayed hotel price is marked as estimated, with the clarification text', () => {
  assert.equal(PRICE_VARIES_NOTE,
    'Actual prices may vary depending on availability, booking dates, and the booking provider.');
  for (const view of [
    priceView(live(), 3, 1),                                                        // live listed price
    priceView(live({ total_price_basis: 'nightly_x_nights' }), 3, 1),               // computed total
    priceView(live({ data_source: 'curated', price_source: 'estimate' }), 3, 2),    // curated estimate
    priceView(live({ data_source: 'curated', is_placeholder: true }), 3, 1),        // typical rate
  ]) {
    assert.equal(showsEstimateLabel(view), true, view.kind);
  }
});

test('no "Estimated" label when no price is shown', () => {
  assert.equal(showsEstimateLabel(priceView(live({ price_per_night: null, total_price: null }), 3, 1)), false);
  assert.equal(showsEstimateLabel(priceView(live({ is_placeholder: true, price_per_night: null }), 3, 1)), false);
});

// ---- Compact price details (card redesign) ----
test('price meta is one short line; nothing is invented', () => {
  const listed = live({ taxes_included: true });
  assert.match(priceMeta(listed, priceView(listed, 3, 1)), /^Incl\. taxes & fees · Updated /);
  const computed = live({ total_price_basis: 'nightly_x_nights', taxes_included: null, price_checked_at: null });
  assert.equal(priceMeta(computed, priceView(computed, 3, 1)), 'Total ≈ nightly rate × nights · Taxes & fees may be extra');
  const stale = live({ results_stale: true, taxes_included: false, price_checked_at: null });
  assert.equal(priceMeta(stale, priceView(stale, 3, 1)), 'Before taxes & fees · Cached results');
  const curated = live({ data_source: 'curated', price_source: 'estimate' });
  assert.equal(priceMeta(curated, priceView(curated, 3, 2)), 'MYMILE estimate · taxes & fees may apply');
  const none = live({ price_per_night: null, total_price: null });
  assert.equal(priceMeta(none, priceView(none, 3, 1)), priceView(none, 3, 1).note);
});

test("booking price line uses only the chosen provider's own listed price", () => {
  const h = live({ booking_link: BOOKING_URL, booking_link_type: 'provider', booking_provider: 'Booking.com',
    booking_offers: [{ provider: 'Booking.com', url: BOOKING_URL, price_per_night: 304, currency: 'USD', official: false }] });
  assert.equal(bookingPriceLine(h), 'USD 304 / night on Booking.com');
  assert.equal(bookingPriceLine(live({ ...h, booking_offers: [] })), null, 'no listed provider price');
  assert.equal(bookingPriceLine(live()), null, 'no booking link');
  assert.equal(bookingPriceLine(live({ booking_link: 'https://x', booking_link_type: 'search' })), null);
});
