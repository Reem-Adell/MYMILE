// How the Premium budget is labelled (unit-tested with node:test). The numbers come from
// the backend's optimize_budget; this only names them clearly:
//   * "allocated": the traveler's budget split into planned limits (stay + categories).
//     Unallocated $0 means fully allocated, NOT that the traveler will spend it all.
//   * "estimated": baseline cost estimates when no budget was set.
import type { BudgetBreakdown } from '../types';

export type BudgetState = 'full' | 'under' | 'over' | 'estimate';

export interface BudgetView {
  mode: 'allocated' | 'estimated';
  state: BudgetState;
  totalBudget: number | null;   // the traveler's budget
  hotel: number;                // stay cost
  allocated: number;            // stay + category allocations (or the estimated total)
  categories: number;           // category allocations (allocated - stay)
  unallocated: number | null;   // budget - allocated (negative = over-allocated); null for estimates
  allocatedPct: number | null;  // share of the budget allocated
  totalLabel: string;
  statusLabel: string;
  unallocatedLabel: string;
  note: string;
}

const cents = (n: number) => Math.round(n * 100) / 100;

export function budgetView(b: BudgetBreakdown): BudgetView {
  const totalBudget = b.user_budget ?? null;
  const mode = (b.allocation_mode as BudgetView['mode']) || (totalBudget ? 'allocated' : 'estimated');
  const allocated = b.allocated_total ?? b.total_estimated;
  const hotel = b.accommodation;
  const categories = cents(allocated - hotel);
  if (mode === 'estimated' || !totalBudget) {
    return {
      mode: 'estimated', state: 'estimate', totalBudget, hotel, allocated, categories, unallocated: null,
      allocatedPct: null, totalLabel: 'Estimated total', statusLabel: 'Estimate', unallocatedLabel: 'Unallocated',
      note: 'Estimated costs for this trip (no budget was set).',
    };
  }
  const raw = b.unallocated_budget ?? b.remaining_balance ?? totalBudget - allocated;
  const unallocated = Math.abs(raw) < 0.005 ? 0 : cents(raw);
  const state: BudgetState = unallocated < 0 ? 'over' : unallocated === 0 ? 'full' : 'under';
  const labels = {
    full: ['Fully allocated', 'Unallocated',
      'Your whole budget is allocated across your stay and categories. These are planned limits, not a forecast of what you will spend.'],
    under: ['Within budget', 'Unallocated', 'This part of your budget is not assigned to any category.'],
    over: ['Over budget', 'Over-allocated by', 'Your stay plus the minimum category amounts exceed your budget.'],
  }[state as 'full' | 'under' | 'over'];
  return {
    mode: 'allocated', state, totalBudget, hotel, allocated, categories, unallocated,
    allocatedPct: Math.min(100, Math.round((allocated / totalBudget) * 100)),
    totalLabel: 'Allocated budget', statusLabel: labels[0], unallocatedLabel: labels[1], note: labels[2],
  };
}
