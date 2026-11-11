// Display rules for Channel3 products (unit-tested with node:test). Only returned data is shown.
import type { CartItem, EssentialsInfo, Product } from '../types';
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

/** The retailer link for this product. Only present when the backend sent it (Premium). */
export function buyLink(p: Pick<Product, 'purchase_url' | 'retailer'>): { href: string; label: string } | null {
  if (!p.purchase_url) return null;
  return { href: p.purchase_url, label: p.retailer ? `Buy at ${p.retailer}` : 'Buy at retailer' };
}

/** Subtotal of the items whose price is known. Mixed currencies are not added together. */
export function cartSubtotal(items: CartItem[]): { amount: number; currency: string; complete: boolean } | null {
  const priced = items.filter((i) => i.product.price != null);
  if (!priced.length) return null;
  const currency = priced[0].product.currency || 'USD';
  const same = priced.filter((i) => (i.product.currency || 'USD') === currency);
  const amount = same.reduce((sum, i) => sum + (i.product.price as number) * i.quantity, 0);
  return { amount, currency, complete: same.length === items.length };
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
      return 'No matching products were found for this trip.';
    default:
      return 'No product suggestions for this trip yet.';
  }
}
