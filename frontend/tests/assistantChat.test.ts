// Run: npm test
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  aiPlanLabel,
  aiProviderName,
  buildChatContext,
  recentHistory,
  suggestedHotel,
} from '../src/services/assistantChat.ts';
import type { Hotel, TripPlan } from '../src/types/index.ts';

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
    travel_essentials: [], is_premium: true,
    budget_breakdown: { accommodation: 1, transportation: 1, food: 1, activities: 1, travel_essentials: 1,
      contingency_and_other: 1, total_estimated: 6, user_budget: 1500, currency: 'USD', status: 'balanced' },
    ...over,
  };
}

test('chat context has the trip and hotel, no itinerary and no links', () => {
  const ctx = buildChatContext(trip(), true) as any;
  assert.equal(ctx.destination_city, 'Cairo');
  assert.equal(ctx.departure_date, '2026-12-01');
  assert.equal(ctx.itinerary, undefined);
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

test('suggested hotel must be one of the returned options', () => {
  const options = [hotel({ id: 'a' }), hotel({ id: 'b' })];
  assert.equal(suggestedHotel(options, 'b')?.id, 'b');
  assert.equal(suggestedHotel(options, 'zzz'), null);
  assert.equal(suggestedHotel(options, null), null);
});

test('AI label never claims AI for a template plan', () => {
  const q = aiPlanLabel({ generated_by: 'groq', model: 'openai/gpt-oss-120b', tools_used: ['search_hotels', 'get_weather_forecast'], cached: false });
  assert.equal(q.kind, 'ai');
  assert.equal(q.text, 'Trip plan by Groq (openai/gpt-oss-120b) using live hotel search, weather data.');
  const g = aiPlanLabel({ generated_by: 'gemini', model: 'gemini-3.8-flash', tools_used: [], cached: false });
  assert.equal(g.kind, 'ai');
  assert.equal(g.text, 'Trip plan by Gemini (gemini-3.8-flash).');
  const r = aiPlanLabel({ generated_by: 'rules', tools_used: [], cached: false, notice: 'Groq is not configured.' });
  assert.equal(r.kind, 'template');
  assert.match(r.text, /basic template plan\. Groq is not configured\./);
  assert.doesNotMatch(r.text, /planned by/);
  assert.equal(aiProviderName('unavailable'), null);
  assert.equal(aiProviderName('groq'), 'Groq');
  assert.equal(aiPlanLabel(undefined).kind, 'template');
});
