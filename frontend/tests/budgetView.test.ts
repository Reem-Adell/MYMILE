// Run: npm test
// Premium budget labels: allocated vs estimated, unallocated vs over-allocated. Same numbers as the backend.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { budgetView } from '../src/services/budgetView.ts';
import { recalculateBudget } from '../src/services/hotelComparison.ts';
import type { BudgetBreakdown } from '../src/types/index.ts';

// Exactly what optimize_budget returns for a $3,000 budget with a $1,000 hotel (5 days, 2 travelers).
const FULL: BudgetBreakdown = {
  accommodation: 1000, food: 700, transportation: 440, activities: 480, travel_essentials: 240,
  contingency_and_other: 140, total_estimated: 3000, user_budget: 3000, remaining_balance: 0,
  currency: 'USD', status: 'balanced', allocation_mode: 'allocated', allocated_total: 3000,
  unallocated_budget: 0, fully_allocated: true,
  allocation_note: 'Your whole budget is allocated across your stay and categories.',
};

test('a fully allocated budget says so instead of implying it will all be spent', () => {
  const v = budgetView(FULL);
  assert.equal(v.state, 'full');
  assert.equal(v.totalLabel, 'Allocated budget');
  assert.equal(v.statusLabel, 'Fully allocated');
  assert.equal(v.unallocatedLabel, 'Unallocated');
  assert.equal(v.unallocated, 0);
  assert.match(v.note, /planned limits, not a forecast/);
  assert.equal(v.allocatedPct, 100);
});

test('values match the backend and add up', () => {
  const v = budgetView(FULL);
  assert.equal(v.totalBudget, FULL.user_budget);
  assert.equal(v.allocated, FULL.allocated_total);
  assert.equal(v.hotel, FULL.accommodation);
  const cats = FULL.food + FULL.transportation + FULL.activities + FULL.travel_essentials + FULL.contingency_and_other;
  assert.equal(v.categories, cats);
  assert.equal(v.hotel + v.categories, v.allocated);
  assert.equal(v.unallocated, (v.totalBudget as number) - v.allocated);
});

test('over-allocation is labelled clearly with a positive amount to show', () => {
  const over: BudgetBreakdown = { ...FULL, accommodation: 2700, food: 300, transportation: 150, activities: 150,
    travel_essentials: 30, contingency_and_other: 15, total_estimated: 3345, allocated_total: 3345,
    remaining_balance: -345, unallocated_budget: -345, fully_allocated: false, status: 'over_budget' };
  const v = budgetView(over);
  assert.equal(v.state, 'over');
  assert.equal(v.statusLabel, 'Over budget');
  assert.equal(v.unallocatedLabel, 'Over-allocated by');
  assert.equal(v.unallocated, -345);
  assert.equal(v.allocatedPct, 100, 'capped for the progress text');
});

test('a part left unassigned is shown as unallocated', () => {
  const v = budgetView({ ...FULL, unallocated_budget: 250, remaining_balance: 250, allocated_total: 2750,
    total_estimated: 2750, fully_allocated: false });
  assert.equal(v.state, 'under');
  assert.equal(v.statusLabel, 'Within budget');
  assert.equal(v.unallocated, 250);
});

test('older responses without the new fields still work', () => {
  const legacy: BudgetBreakdown = { ...FULL, allocation_mode: undefined, allocated_total: undefined,
    unallocated_budget: undefined, fully_allocated: undefined, allocation_note: undefined };
  const v = budgetView(legacy);
  assert.equal(v.mode, 'allocated');
  assert.equal(v.unallocated, 0);
  assert.equal(v.allocated, 3000);
});

test('without a budget it is an estimate, never an allocation', () => {
  const v = budgetView({ ...FULL, user_budget: null, remaining_balance: null, allocation_mode: 'estimated',
    allocated_total: null, unallocated_budget: null, status: 'estimated' });
  assert.equal(v.state, 'estimate');
  assert.equal(v.totalLabel, 'Estimated total');
  assert.equal(v.unallocated, null);
});

test('switching hotels keeps the labels consistent with the recalculated numbers', () => {
  const cheaper = budgetView(recalculateBudget(FULL, 600));
  assert.equal(cheaper.unallocated, 400);
  assert.equal(cheaper.state, 'under');
  const dearer = budgetView(recalculateBudget(FULL, 1500));
  assert.equal(dearer.unallocated, -500);
  assert.equal(dearer.unallocatedLabel, 'Over-allocated by');
});
