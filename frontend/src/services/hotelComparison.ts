// Pure rules for the hotel comparison grid and its budget impact (unit-tested with node:test).
import type { BudgetBreakdown, Hotel, TripPlan } from '../types';

/** AG Grid comparator: missing values (null/undefined) always sort last, in both directions. */
export function nullsLastComparator(a: number | null | undefined, b: number | null | undefined,
                                    _nodeA?: unknown, _nodeB?: unknown, isDescending = false): number {
  const aMissing = a == null;
  const bMissing = b == null;
  if (aMissing && bMissing) return 0;
  // AG Grid reverses the result for descending sorts, so flip it here to keep blanks at the bottom.
  if (aMissing) return isDescending ? -1 : 1;
  if (bMissing) return isDescending ? 1 : -1;
  return (a as number) - (b as number);
}

/** A rating of 0 means "no rating" (placeholders, hotels without reviews), not a zero-star rating. */
export function ratingValue(hotel: Pick<Hotel, 'rating'> | undefined): number | null {
  return hotel && hotel.rating > 0 ? hotel.rating : null;
}

/** Text the quick search matches: name, location, category and amenities. */
export function hotelSearchText(hotel: Hotel): string {
  return [hotel.name, hotel.location, hotel.category, ...(hotel.amenities || [])].filter(Boolean).join(' ');
}

/**
 * One selection path for row clicks and the Choose button: a hotel is only reported
 * once, so a click on the Choose button (which also clicks its row) or a repeated
 * click never triggers a second selection or budget recalculation.
 */
export function createSelectionGate(initialId?: string | null) {
  let current = initialId ?? null;
  return {
    /** true when this is a new selection the app should act on. */
    select(id: string): boolean {
      if (!id || id === current) return false;
      current = id;
      return true;
    },
    /** Follow the selection made elsewhere (e.g. the assistant or a new plan). */
    sync(id?: string | null) {
      current = id ?? null;
    },
    get current() {
      return current;
    },
  };
}

/**
 * The existing Premium budget recalculation (moved here unchanged from App.handleSelectHotel):
 * accommodation becomes the hotel's total; every other category is kept as the backend set it.
 */
export function recalculateBudget(budget: BudgetBreakdown, hotelTotal: number): BudgetBreakdown {
  const userBudget = budget.user_budget || 4500;
  const otherCosts = budget.food + budget.transportation + budget.activities
    + budget.travel_essentials + budget.contingency_and_other;
  const newTotal = hotelTotal + otherCosts;
  const newRemaining = userBudget - newTotal;
  return {
    ...budget,
    accommodation: hotelTotal,
    total_estimated: newTotal,
    remaining_balance: newRemaining,
    status: newRemaining >= 0 ? 'balanced' : 'over_budget',
  };
}

export interface BudgetImpact {
  tripId: string;
  previousName: string | null;
  previousTotal: number | null;
  nextName: string;
  nextTotal: number | null;
  difference: number | null;      // next - previous, when both totals are known
  direction: 'increase' | 'decrease' | 'same' | 'unknown';
  remaining: number | null;       // only when the traveler set a budget (no fallback figures)
  currency: string;
}

export function budgetImpact(previous: Hotel | null, next: Hotel, after: BudgetBreakdown | null,
                             tripId: string): BudgetImpact {
  const previousTotal = previous?.total_price ?? null;
  const nextTotal = next.total_price ?? null;
  const difference = previousTotal != null && nextTotal != null
    ? Math.round((nextTotal - previousTotal) * 100) / 100 : null;
  return {
    tripId,
    previousName: previous?.name ?? null,
    previousTotal,
    nextName: next.name,
    nextTotal,
    difference,
    direction: difference == null ? 'unknown' : difference > 0 ? 'increase' : difference < 0 ? 'decrease' : 'same',
    remaining: after && after.user_budget != null && after.remaining_balance != null ? after.remaining_balance : null,
    currency: next.currency || 'USD',
  };
}

export interface HotelSelectionResult {
  selectedHotel: Hotel;
  trip: TripPlan | null;          // same object when nothing about the trip changed
  impact: BudgetImpact | null;    // Premium with budget data only
}

/**
 * What selecting `hotel` changes. Returns null when it is already the selected hotel,
 * so a repeated selection never recalculates anything.
 */
export function applyHotelSelection(trip: TripPlan | null, current: Hotel | null, hotel: Hotel,
                                    userPlan: 'free' | 'premium'): HotelSelectionResult | null {
  const currentId = current?.id ?? trip?.recommended_hotel?.id ?? null;
  if (hotel.id === currentId) return null;
  const previous = current ?? trip?.recommended_hotel ?? null;
  const budget = trip?.budget_breakdown;
  if (!trip || !budget || userPlan !== 'premium') {
    return { selectedHotel: hotel, trip, impact: null };
  }
  // A hotel without a listed price can't change the budget (its cost is unknown, not 0).
  if (hotel.total_price == null) {
    return { selectedHotel: hotel, trip, impact: budgetImpact(previous, hotel, null, trip.trip_id) };
  }
  const updated = recalculateBudget(budget, hotel.total_price);
  return {
    selectedHotel: hotel,
    trip: { ...trip, recommended_hotel: hotel, budget_breakdown: updated },
    impact: budgetImpact(previous, hotel, updated, trip.trip_id),
  };
}
