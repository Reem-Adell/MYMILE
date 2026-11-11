// Run: npm test
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  aiPlanLabel,
  applyItineraryChanges,
  buildChatContext,
  recentHistory,
  suggestedHotel,
} from '../src/services/assistantChat.ts';
import type { Hotel, ItineraryDay, TripPlan } from '../src/types/index.ts';

const day = (n: number, theme = `Day ${n}`): ItineraryDay => ({
  day_number: n, date_str: `D${n}`, theme,
  activities: [{ time: '09:00 AM', title: `Visit ${n}`, description: 'd', location: 'X', icon: 'pin', cost_estimate: 10 }],
});

function hotel(over: Partial<Hotel> = {}): Hotel {
  return { id: 'h1', name: 'Hotel One', location: 'Cairo', rating: 4.5, reviews_count: 10, price_per_night: 90,
    total_price: 270, currency: 'USD', image_url: 'i', amenities: [], best_match_reason: 'r', category: 'Hotel',
    is_best_match: true, booking_link: 'https://www.booking.com/x', ...over };
}

function trip(over: Partial<TripPlan> = {}): TripPlan {
  return {
    trip_id: 't', destination: 'Cairo, Egypt', destination_city: 'Cairo', destination_country: 'Egypt',
    departure_date: '2026-12-01', return_date: '2026-12-04', total_days: 3, travelers: 2, purpose: 'Tourism',
    stay_preference: 'Boutique hotel', plan_tier: 'premium', destination_summary: 's', why_recommended: 'w',
    weather: {} as TripPlan['weather'], recommended_hotel: hotel(), all_hotels: [hotel()],
    itinerary: [day(1), day(2), day(3)], travel_essentials: [], is_premium: true,
    budget_breakdown: { accommodation: 1, transportation: 1, food: 1, activities: 1, travel_essentials: 1,
      contingency_and_other: 1, total_estimated: 6, user_budget: 1500, currency: 'USD', status: 'balanced' },
    ...over,
  };
}

test('chat context has the trip, its itinerary and hotel, but no links', () => {
  const ctx = buildChatContext(trip(), true) as any;
  assert.equal(ctx.destination_city, 'Cairo');
  assert.equal(ctx.departure_date, '2026-12-01');
  assert.equal(ctx.itinerary.length, 3);
  assert.equal(ctx.itinerary[1].activities[0].title, 'Visit 2');
  assert.deepEqual(ctx.recommended_hotel, { id: 'h1', name: 'Hotel One', price_per_night: 90, total_price: 270 });
  assert.doesNotMatch(JSON.stringify(ctx), /booking\.com|http/);
  assert.equal(ctx.total_budget, 1500);
});

test('budget is not sent when the plan may not show it', () => {
  assert.equal((buildChatContext(trip(), false) as any).total_budget, null);
});

test('placeholder hotel is not sent as the current hotel', () => {
  const ctx = buildChatContext(trip({ recommended_hotel: hotel({ is_placeholder: true }) }), false) as any;
  assert.equal(ctx.recommended_hotel, null);
});

test('history: last messages only, oldest first, UI notes excluded', () => {
  const msgs = [
    { role: 'assistant' as const, text: 'welcome', local: true },
    ...Array.from({ length: 10 }, (_, i) => ({ role: (i % 2 ? 'assistant' : 'user') as 'user' | 'assistant', text: `m${i}` })),
  ];
  const h = recentHistory(msgs, 8);
  assert.equal(h.length, 8);
  assert.equal(h[0].content, 'm2');
  assert.equal(h[7].content, 'm9');
  assert.ok(!h.some((m) => m.content === 'welcome'));
});

test('itinerary changes replace only the matching days', () => {
  const t = trip();
  const updated = applyItineraryChanges(t, [day(2, 'Slow day'), day(9, 'Ghost day')]);
  assert.deepEqual(updated.itinerary.map((d) => d.theme), ['Day 1', 'Slow day', 'Day 3']);
  assert.equal(t.itinerary[1].theme, 'Day 2', 'original trip is not mutated');
  assert.equal(applyItineraryChanges(t, []), t);
});

test('suggested hotel must be one of the returned options', () => {
  const options = [hotel({ id: 'a' }), hotel({ id: 'b' })];
  assert.equal(suggestedHotel(options, 'b')?.id, 'b');
  assert.equal(suggestedHotel(options, 'zzz'), null);
  assert.equal(suggestedHotel(options, null), null);
});

test('AI label never claims AI for a template plan', () => {
  const g = aiPlanLabel({ generated_by: 'gemini', model: 'gemini-3.8-flash', tools_used: ['search_hotels', 'get_weather_forecast'], cached: false });
  assert.equal(g.kind, 'gemini');
  assert.equal(g.text, 'Itinerary planned by Gemini (gemini-3.8-flash) using live hotel search, weather data.');
  const r = aiPlanLabel({ generated_by: 'rules', tools_used: [], cached: false, notice: 'Gemini is not configured.' });
  assert.equal(r.kind, 'template');
  assert.match(r.text, /basic template itinerary\. Gemini is not configured\./);
  assert.doesNotMatch(r.text, /planned by Gemini/);
  assert.equal(aiPlanLabel(undefined).kind, 'template');
});
