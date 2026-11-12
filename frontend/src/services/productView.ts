// Display rules for Channel3 products (unit-tested with node:test). Only returned data is shown.
import type { EssentialsInfo, Product } from '../types';
import { formatMoney } from './exploreView.ts';

export function productPrice(p: Pick<Product, 'price' | 'currency'>): string {
  return p.price == null ? 'Price not listed' : formatMoney(p.price, p.currency || 'USD');
}

/** "In stock" / "Out of stock", or null when the retailer didn't say. */
export function availabilityLabel(p: Pick<Product, 'in_stock'>): string | null {
  return p.in_stock === true ? 'In stock' : p.in_stock === false ? 'Out of stock' : null;
}

/** "Acme · rei.com" from whatever was returned. */
export function productSource(p: Pick<Product, 'brand' | 'retailer'>): string {
  return [p.brand, p.retailer].filter(Boolean).join(' · ');
}

/** The product's real retailer URL for "View Product" (Channel3's purchase_url, sent by the
 *  backend only to Premium accounts). Anything that isn't an absolute http(s) URL is refused,
 *  so the button never opens a broken or unsafe link. */
export function viewProductUrl(p: Pick<Product, 'purchase_url'>): string | null {
  const raw = (p.purchase_url || '').trim();
  if (!raw) return null;
  try {
    const url = new URL(raw);
    return url.protocol === 'https:' || url.protocol === 'http:' ? url.href : null;
  } catch {
    return null;
  }
}

/** The user's product search as typed, tidied: no control characters, single spaces,
 *  at most 120 characters. "" when too short to search. */
export function cleanProductQuery(raw: string): string {
  const q = String(raw || '').replace(/[\u0000-\u001f\u007f<>]/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 120);
  return q.length >= 2 ? q : '';
}

/** The query to send for a manual search, or null when nothing should be sent: empty input,
 *  a search already running, or the same query whose results are already shown. */
export function manualSearchQuery(raw: string, state: { loading: boolean; lastQuery: string | null; failed?: boolean }): string | null {
  const q = cleanProductQuery(raw);
  if (!q || state.loading) return null;
  if (!state.failed && state.lastQuery && state.lastQuery.toLowerCase() === q.toLowerCase()) return null;
  return q;
}

/** Products grouped by their trip category, in the order the AI ranked them. */
export function groupEssentials<T extends Pick<Product, 'group'>>(products: T[]): { name: string; products: T[] }[] {
  const groups: { name: string; products: T[] }[] = [];
  for (const p of products) {
    const name = p.group || 'Travel essentials';
    let g = groups.find((x) => x.name === name);
    if (!g) groups.push((g = { name, products: [] }));
    g.products.push(p);
  }
  return groups;
}

/** "For men" / "For women" for gender-specific options; nothing for everyone. */
export function audienceLabel(p: Pick<Product, 'audience'>): string | null {
  return p.audience === 'men' ? 'For men' : p.audience === 'women' ? 'For women' : null;
}

/** "One per traveler (×2)" when each traveler needs one. */
export function quantityLabel(p: Pick<Product, 'per_traveler'>, travelers?: number): string | null {
  if (!p.per_traveler) return null;
  return travelers && travelers > 1 ? `One per traveler (×${travelers})` : 'One per traveler';
}

// Same wording as the backend. Needs whose products were found but not chosen ("not_selected")
// aren't shown on Explore, and are never described as "not found".
const MISSING_WORDING: [state: 'not_found' | 'not_searched', text: string][] = [
  ['not_found', 'No relevant options were found for: {}.'],
  ['not_searched', 'Not searched (the search limit was reached) for: {}.'],
];

/** Honest note about needed categories with no product shown, by reason. */
export function missingCategoriesNote(info?: EssentialsInfo | null): string | null {
  const detail = info?.missing_detail || [];
  if (detail.length) {
    const parts = MISSING_WORDING
      .map(([state, text]) => [text, detail.filter((d) => d.state === state).map((d) => d.category)] as const)
      .filter(([, names]) => names.length)
      .map(([text, names]) => text.replace('{}', names.join(', ')));
    return parts.join(' ') || null;
  }
  const missing = info?.missing || [];  // older responses without missing_detail
  return missing.length ? `No relevant options were found for: ${missing.join(', ')}.` : null;
}

/** What to show when a trip has no product suggestions. */
export function essentialsEmptyMessage(info?: EssentialsInfo | null): string {
  switch (info?.status) {
    case 'not_configured':
      return 'Travel product suggestions aren’t set up yet.';
    case 'ai_unavailable':
      return 'Personalized product suggestions need the AI planner, which is unavailable right now.';
    case 'unavailable':
      return `Product suggestions couldn’t be loaded right now.${info.message ? ` ${info.message}` : ''}`;
    case 'empty':
      return info.message || 'No matching products were found for this trip.';
    default:
      return 'No product suggestions for this trip yet.';
  }
}
