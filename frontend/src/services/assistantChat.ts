// Pure helpers for the AI assistant and AI labels (unit-tested with node:test).
import type { AgentInfo, ChatTurn, Hotel, ItineraryDay, TripPlan } from '../types';

export const HISTORY_LIMIT = 8;

export const DEFAULT_SUGGESTIONS = [
  'Find a cheaper hotel',
  'Make day 2 more relaxed',
  'Suggest activities within my budget',
  'What should I pack?',
];

/** The current trip as the chat API expects it. Budget is included only when
 *  the plan may show it (Premium); the server still verifies the plan itself. */
export function buildChatContext(trip: TripPlan, canSeeBudget: boolean): Record<string, unknown> {
  const hotel = trip.recommended_hotel;
  return {
    destination: trip.destination,
    destination_city: trip.destination_city || null,
    destination_country: trip.destination_country || null,
    departure_date: trip.departure_date,
    return_date: trip.return_date,
    travelers: trip.travelers,
    purpose: trip.purpose,
    stay_preference: trip.stay_preference,
    total_budget: canSeeBudget ? trip.budget_breakdown?.user_budget ?? null : null,
    recommended_hotel: hotel && !hotel.is_placeholder
      ? { id: hotel.id, name: hotel.name, price_per_night: hotel.price_per_night, total_price: hotel.total_price }
      : null,
    itinerary: trip.itinerary.map((d) => ({
      day_number: d.day_number,
      theme: d.theme,
      activities: d.activities.slice(0, 10).map((a) => ({
        time: a.time, title: a.title, location: a.location ?? null, cost_estimate: a.cost_estimate,
      })),
    })),
  };
}

/** Last messages of the conversation, oldest first, without UI-only notes. */
export function recentHistory(messages: { role: 'user' | 'assistant'; text: string; local?: boolean }[],
                              limit = HISTORY_LIMIT): ChatTurn[] {
  return messages.filter((m) => !m.local && m.text.trim())
    .slice(-limit)
    .map((m) => ({ role: m.role, content: m.text }));
}

/** The trip with the given days replaced (matched by day_number). Unknown days are ignored. */
export function applyItineraryChanges(trip: TripPlan, days: ItineraryDay[]): TripPlan {
  if (!days.length) return trip;
  const byNumber = new Map(days.map((d) => [d.day_number, d]));
  return { ...trip, itinerary: trip.itinerary.map((d) => byNumber.get(d.day_number) ?? d) };
}

/** The hotel the assistant suggested, only if it is one of the returned options. */
export function suggestedHotel(options: Hotel[], id?: string | null): Hotel | null {
  return (id && options.find((h) => h.id === id)) || null;
}

const TOOL_LABELS: Record<string, string> = {
  get_weather_forecast: 'weather',
  search_hotels: 'hotel search',
  find_activities: 'activities',
  estimate_budget: 'budget',
};

export function toolList(tools: string[]): string {
  return tools.map((t) => TOOL_LABELS[t] || t).join(', ');
}

/** Banner text for how the itinerary was produced. */
export function aiPlanLabel(ai?: AgentInfo | null): { kind: 'gemini' | 'template'; text: string } {
  if (ai?.generated_by === 'gemini') {
    const tools = ai.tools_used.length ? ` using live ${toolList(ai.tools_used)} data` : '';
    return { kind: 'gemini', text: `Itinerary planned by Gemini${ai.model ? ` (${ai.model})` : ''}${tools}.` };
  }
  return {
    kind: 'template',
    text: `AI planning is unavailable, so this is a basic template itinerary.${ai?.notice ? ` ${ai.notice}` : ''}`,
  };
}
