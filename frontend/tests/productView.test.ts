// Run: npm test
// Channel3 product display rules: only returned data, Premium-only retailer links, manual search input.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  availabilityLabel,
  cleanProductQuery,
  manualSearchQuery,
  viewProductUrl,
  essentialsEmptyMessage,
  groupEssentials,
  audienceLabel,
  quantityLabel,
  missingCategoriesNote,
  productPrice,
  productSource,
} from '../src/services/productView.ts';
import type { Product } from '../src/types/index.ts';

function product(over: Partial<Product> = {}): Product {
  return { id: 'p1', name: 'Packable Rain Jacket', price: 79, currency: 'USD', image_url: 'https://img.example/p1.jpg',
    purchase_url: null, brand: 'Acme', retailer: 'shop-a.example', in_stock: true, provider: 'Channel3', ...over };
}

test('price and availability show only what Channel3 returned', () => {
  assert.equal(productPrice(product()), 'USD 79');
  assert.equal(productPrice(product({ price: 50, currency: 'EUR' })), 'EUR 50');
  assert.equal(productPrice(product({ price: null })), 'Price not listed', 'never USD 0');
  assert.equal(availabilityLabel(product()), 'In stock');
  assert.equal(availabilityLabel(product({ in_stock: false })), 'Out of stock');
  assert.equal(availabilityLabel(product({ in_stock: null })), null, 'unknown is not shown');
  assert.equal(productSource(product()), 'Acme · shop-a.example');
  assert.equal(productSource(product({ brand: null, retailer: null })), '');
});

test('View Product opens only the real retailer URL the backend sent (Premium)', () => {
  assert.equal(viewProductUrl(product()), null, 'Free: no URL from the backend, nothing to open');
  assert.equal(viewProductUrl(product({ purchase_url: 'https://shop-a.example/p1?ref=x' })), 'https://shop-a.example/p1?ref=x');
  assert.equal(viewProductUrl(product({ purchase_url: 'http://shop-b.example/p' })), 'http://shop-b.example/p');
  for (const bad of ['javascript:alert(1)', '/relative/path', 'shop.example/p', '   ', 'ftp://x.example/f', 'not a url']) {
    assert.equal(viewProductUrl(product({ purchase_url: bad })), null, bad);
  }
});

test('manual search input is tidied and validated', () => {
  assert.equal(cleanProductQuery('  Wireless   Mouse '), 'Wireless Mouse');
  assert.equal(cleanProductQuery('a'), '', 'too short');
  assert.equal(cleanProductQuery('   '), '');
  assert.equal(cleanProductQuery('<b>mouse</b>\u0000'), 'b mouse /b');
  assert.equal(cleanProductQuery('x'.repeat(300)).length, 120);
});

test('manual search sends no empty, parallel or repeated request', () => {
  const idle = { loading: false, lastQuery: null };
  assert.equal(manualSearchQuery('Wireless Mouse', idle), 'Wireless Mouse');
  assert.equal(manualSearchQuery('  ', idle), null, 'empty');
  assert.equal(manualSearchQuery('Wireless Mouse', { loading: true, lastQuery: null }), null, 'one at a time');
  assert.equal(manualSearchQuery('wireless  mouse', { loading: false, lastQuery: 'Wireless Mouse' }), null, 'already shown');
  assert.equal(manualSearchQuery('wireless mouse', { loading: false, lastQuery: 'Wireless Mouse', failed: true }), 'wireless mouse',
    'a failed search can be retried');
  assert.equal(manualSearchQuery('keyboard', { loading: false, lastQuery: 'Wireless Mouse' }), 'keyboard');
});

test('empty and error states explain what happened', () => {
  assert.match(essentialsEmptyMessage({ status: 'not_configured', queries: [] }), /aren.t set up/);
  assert.match(essentialsEmptyMessage({ status: 'ai_unavailable', queries: [] }), /AI planner/);
  assert.match(essentialsEmptyMessage({ status: 'unavailable', queries: [], message: 'Channel3 took too long to answer.' }),
    /couldn.t be loaded right now\. Channel3 took too long/);
  assert.match(essentialsEmptyMessage({ status: 'empty', queries: ['x'] }), /No matching products/);
  assert.equal(essentialsEmptyMessage({ status: 'empty', queries: ['x'], message: 'Channel3 returned products, but none were relevant enough for this trip.' }),
    'Channel3 returned products, but none were relevant enough for this trip.');
  assert.match(essentialsEmptyMessage(undefined), /No product suggestions/);
});

test('essentials are grouped by trip category in ranked order', () => {
  const groups = groupEssentials([
    product({ id: 'a', group: 'Ihram & Clothing', audience: 'men' }),
    product({ id: 'b', group: 'Modest Clothing', audience: 'women' }),
    product({ id: 'c', group: 'Ihram & Clothing' }),
    product({ id: 'd', group: null }),
  ]);
  assert.deepEqual(groups.map((g) => [g.name, g.products.map((p) => p.id)]),
    [['Ihram & Clothing', ['a', 'c']], ['Modest Clothing', ['b']], ['Travel essentials', ['d']]]);
});

test('audience and quantity labels never assume', () => {
  assert.equal(audienceLabel(product({ audience: 'men' })), 'For men');
  assert.equal(audienceLabel(product({ audience: 'women' })), 'For women');
  assert.equal(audienceLabel(product({ audience: 'all' })), null);
  assert.equal(audienceLabel(product({})), null);
  assert.equal(quantityLabel(product({ per_traveler: true }), 3), 'One per traveler (×3)');
  assert.equal(quantityLabel(product({ per_traveler: true }), 1), 'One per traveler');
  assert.equal(quantityLabel(product({ per_traveler: false }), 3), null);
});

test('missing categories are stated honestly', () => {
  assert.equal(missingCategoriesNote({ status: 'ok', queries: [], missing: ['Personal Care', 'Footwear'] }),
    'No relevant options were found for: Personal Care, Footwear.');
  assert.equal(missingCategoriesNote({ status: 'ok', queries: [] }), null);
});

test('missing needs are worded by reason, never "not found" for unselected products', () => {
  const note = missingCategoriesNote({ status: 'ok', queries: [], missing: ['Computer Mouse', 'Headphones', 'Socks'],
    missing_detail: [{ category: 'Computer Mouse', state: 'not_selected' }, { category: 'Headphones', state: 'not_searched' },
      { category: 'Socks', state: 'not_found' }] })!;
  assert.equal(note, 'No relevant options were found for: Socks. Not searched (the search limit was reached) for: Headphones.');
  assert.doesNotMatch(note, /Computer Mouse/, 'found-but-not-selected needs are not shown on Explore');
  assert.equal(missingCategoriesNote({ status: 'ok', queries: [], missing: ['Day Bag'],
    missing_detail: [{ category: 'Day Bag', state: 'not_selected' }] }), null, 'no note box at all');
  assert.equal(missingCategoriesNote({ status: 'ok', queries: [], missing: ['Footwear'] }),
    'No relevant options were found for: Footwear.', 'older responses keep the old sentence');
});
