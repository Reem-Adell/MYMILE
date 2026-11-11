// Run: npm test
// Channel3 product display rules: only returned data, Premium links, per-retailer cart links.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  availabilityLabel,
  buyLink,
  cartSubtotal,
  essentialsEmptyMessage,
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

test('retailer link appears only when the backend sent it (Premium)', () => {
  assert.equal(buyLink(product()), null, 'Free: no link from the backend, none shown');
  assert.deepEqual(buyLink(product({ purchase_url: 'https://shop-a.example/p1' })),
    { href: 'https://shop-a.example/p1', label: 'Buy at shop-a.example' });
  assert.equal(buyLink(product({ purchase_url: 'https://x.example', retailer: null }))!.label, 'Buy at retailer');
});

test('each cart item keeps its own retailer link; there is no shared checkout', () => {
  const items = [
    { product: product({ id: 'a', purchase_url: 'https://shop-a.example/a' }), quantity: 1 },
    { product: product({ id: 'b', retailer: 'shop-b.example', purchase_url: 'https://shop-b.example/b' }), quantity: 2 },
  ];
  assert.deepEqual(items.map((i) => buyLink(i.product)!.href), ['https://shop-a.example/a', 'https://shop-b.example/b']);
});

test('cart subtotal adds known prices only and never mixes currencies', () => {
  const sub = cartSubtotal([{ product: product({ price: 79 }), quantity: 2 },
    { product: product({ id: 'b', price: 20 }), quantity: 1 }]);
  assert.deepEqual(sub, { amount: 178, currency: 'USD', complete: true });
  const partial = cartSubtotal([{ product: product({ price: 79 }), quantity: 1 },
    { product: product({ id: 'b', price: null }), quantity: 1 },
    { product: product({ id: 'c', price: 30, currency: 'EUR' }), quantity: 1 }]);
  assert.deepEqual(partial, { amount: 79, currency: 'USD', complete: false });
  assert.equal(cartSubtotal([{ product: product({ price: null }), quantity: 1 }]), null);
});

test('empty and error states explain what happened', () => {
  assert.match(essentialsEmptyMessage({ status: 'not_configured', queries: [] }), /aren.t set up/);
  assert.match(essentialsEmptyMessage({ status: 'ai_unavailable', queries: [] }), /AI planner/);
  assert.match(essentialsEmptyMessage({ status: 'unavailable', queries: [], message: 'Channel3 took too long to answer.' }),
    /couldn.t be loaded right now\. Channel3 took too long/);
  assert.match(essentialsEmptyMessage({ status: 'empty', queries: ['x'] }), /No matching products/);
  assert.match(essentialsEmptyMessage(undefined), /No product suggestions/);
});
