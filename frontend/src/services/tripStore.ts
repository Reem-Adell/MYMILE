// The user's planned trips (source of truth for Explore), per account, in the
// browser.
//
// Only the trip REQUEST (what the user entered in Plan a Trip) is stored, never
// the server's plan. On every load / account change / plan change the request is
// sent to POST /trips/plan again, so the backend re-decides everything that
// depends on the account (Premium budget, booking links) and stale or expired
// Premium data is never shown from storage.
//
// Pure functions with an injectable Storage, so they can be tested with node:test.

export interface TripRequest {
  id: string;
  created_at: string;
  destination: string;          // "City, Country" (display / older backends)
  destination_city: string;     // authoritative
  destination_country: string;  // authoritative
  departure_date: string;       // YYYY-MM-DD
  return_date: string;          // YYYY-MM-DD
  travelers: number;
  purpose: string;
  stay_preference: string;
  priorities: string[];
  notes: string;                // "Tell us about your trip" (required, <= 500 characters)
  total_budget?: number;        // USD; only used by the backend for Premium
  // Who the products are for. Absent in trips saved before this field existed (= everyone).
  shopping_audience?: 'men' | 'women' | 'all';
}

export interface StoredTrips {
  activeId: string | null;
  trips: TripRequest[];        // newest first
}

export type KeyValueStore = Pick<Storage, 'getItem' | 'setItem'>;

export const MAX_TRIPS = 5;
// "Tell us about your trip": required, at most 500 characters (the backend checks the same).
export const DESCRIPTION_MAX = 500;

/** The trip description as it will be sent: trimmed, whitespace collapsed. */
export function cleanDescription(raw: string): string {
  return String(raw ?? '').replace(/\s+/g, ' ').trim();
}

/** Why the description can't be used yet, or null when it is fine. */
export function descriptionError(raw: string): string | null {
  const text = cleanDescription(raw);
  if (!text) return 'Tell us about your trip so we can recommend the right products.';
  if (text.length > DESCRIPTION_MAX) return `Please keep it to ${DESCRIPTION_MAX} characters.`;
  return null;
}
const EMPTY: StoredTrips = { activeId: null, trips: [] };
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

export const accountKey = (userId?: string | null): string => (userId ? `user:${userId}` : 'guest');
const storageKey = (account: string) => `mymile.trips.v1.${account}`;

export function newTripId(): string {
  return `t-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

const nonEmpty = (v: unknown): v is string => typeof v === 'string' && v.trim() !== '';

export function isValidTripRequest(x: unknown): x is TripRequest {
  if (!x || typeof x !== 'object') return false;
  const t = x as Record<string, unknown>;
  return (
    nonEmpty(t.id) && nonEmpty(t.destination_city) && nonEmpty(t.destination_country)
    && typeof t.departure_date === 'string' && DATE_RE.test(t.departure_date)
    && typeof t.return_date === 'string' && DATE_RE.test(t.return_date)
    && typeof t.travelers === 'number' && Number.isInteger(t.travelers) && t.travelers >= 1
    && nonEmpty(t.purpose) && nonEmpty(t.stay_preference)
    && Array.isArray(t.priorities) && t.priorities.every((p) => typeof p === 'string')
    && typeof t.notes === 'string' && descriptionError(t.notes) === null
    && (t.total_budget === undefined || (typeof t.total_budget === 'number' && t.total_budget > 0))
    && (t.shopping_audience === undefined || ['men', 'women', 'all'].includes(t.shopping_audience as string))
  );
}

export function loadTrips(store: KeyValueStore | null, account: string): StoredTrips {
  if (!store) return EMPTY;
  try {
    const raw = store.getItem(storageKey(account));
    if (!raw) return EMPTY;
    const parsed = JSON.parse(raw);
    const trips = Array.isArray(parsed?.trips) ? parsed.trips.filter(isValidTripRequest).slice(0, MAX_TRIPS) : [];
    const activeId = trips.some((t: TripRequest) => t.id === parsed?.activeId) ? parsed.activeId : null;
    return { activeId, trips };
  } catch {
    return EMPTY; // corrupt or blocked storage: behave as "no trips"
  }
}

function write(store: KeyValueStore | null, account: string, value: StoredTrips): StoredTrips {
  try {
    store?.setItem(storageKey(account), JSON.stringify(value));
  } catch {
    // storage full / blocked: the trip still works for this session
  }
  return value;
}

/** Save a successfully planned trip and make it the active one. */
export function saveTrip(store: KeyValueStore | null, account: string, trip: TripRequest): StoredTrips {
  if (!isValidTripRequest(trip)) return loadTrips(store, account);
  const current = loadTrips(store, account);
  const trips = [trip, ...current.trips.filter((t) => t.id !== trip.id)].slice(0, MAX_TRIPS);
  return write(store, account, { activeId: trip.id, trips });
}

/** Switch the active trip (only to one this account actually has). */
export function setActiveTrip(store: KeyValueStore | null, account: string, id: string): StoredTrips {
  const current = loadTrips(store, account);
  if (!current.trips.some((t) => t.id === id)) return current;
  return write(store, account, { ...current, activeId: id });
}

export function getActiveTrip(stored: StoredTrips): TripRequest | null {
  return stored.trips.find((t) => t.id === stored.activeId) ?? null;
}

/** POST /trips/plan body for a stored trip. `plan` is informational only. */
export function toPlanPayload(trip: TripRequest, userPlan: 'free' | 'premium') {
  return {
    destination: trip.destination,
    destination_city: trip.destination_city,
    destination_country: trip.destination_country,
    departure_date: trip.departure_date,
    return_date: trip.return_date,
    travelers: trip.travelers,
    purpose: trip.purpose,
    stay_preference: trip.stay_preference,
    priorities: trip.priorities,
    notes: trip.notes,
    plan: userPlan,
    total_budget: trip.total_budget,
    shopping_audience: trip.shopping_audience,
  };
}

/** The browser's localStorage, or null when unavailable (private mode, SSR...). */
export function browserStore(): KeyValueStore | null {
  try {
    return typeof window !== 'undefined' && window.localStorage ? window.localStorage : null;
  } catch {
    return null;
  }
}
