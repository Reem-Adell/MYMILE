// Run: npm test
// Explore / Plan a Trip regressions, checked on the source (this project has no DOM test
// runner): no cart, no Destination Travel Essentials page or "Ready for" button, View
// Product opens the real retailer URL, manual product search, shopping audience field.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';

const app = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const api = readFileSync(new URL('../src/services/api.ts', import.meta.url), 'utf8');

test('no cart remains in product cards or the app', () => {
  assert.doesNotMatch(app, /Add to cart/i);
  assert.doesNotMatch(app, /onAddToCart|handleAddToCart|ShoppingCartDrawer|View Cart|CartItem/);
  assert.equal(existsSync(new URL('../src/components/ShoppingCartDrawer.tsx', import.meta.url)), false);
});

test('the Ready for <city> button and the Destination Travel Essentials page are gone', () => {
  assert.doesNotMatch(app, /Ready for/);
  assert.doesNotMatch(app, /Destination Travel Essentials/);
  assert.doesNotMatch(app, /go\("shop"\)|view === "shop"|\| "shop"/);
  assert.doesNotMatch(app, /function Shop\(/);
});

test('Explore still renders the plan and its Travel Essentials', () => {
  assert.match(app, /if \(view === "results"\)[\s\S]*<Results/);
  assert.match(app, /<section id="ex-essentials"/);
  assert.match(app, /plan\.travel_essentials\.map\(\(prod\) => \(\s*<ProductCard/);
});

test('View Product opens the validated retailer URL in a new tab, or is disabled', () => {
  assert.match(app, /const url = viewProductUrl\(prod\)/);
  assert.match(app, /<a className="btn btn-yellow btn-small" href=\{url\} target="_blank" rel="noopener noreferrer">\s*View Product/);
  assert.match(app, /<button className="btn btn-yellow btn-small" disabled[\s\S]{0,200}View Product/);
});

test('manual product search sends the typed product to the backend', () => {
  assert.match(app, /placeholder="What product are you looking for\?"/);
  assert.match(app, /const query = manualSearchQuery\(input, state\);\s*if \(!query\) return;/);
  assert.match(app, /api\.searchProducts\(query, audience\)/);
  assert.match(app, /YOUR SEARCH · CHANNEL3/, 'results are labelled apart from the recommended essentials');
  assert.match(api, /apiClient\.get<ProductSearchResult>\('\/products\/search', \{ params \}\)/);
  assert.match(api, /if \(audience === 'men' \|\| audience === 'women'\) params\.audience = audience;/);
});

test('"Who are you shopping for?" is optional, defaults to everyone and is sent with the trip', () => {
  assert.match(app, /Who are you shopping for\? <em>Optional<\/em>/);
  assert.match(app, /useState<"all" \| "men" \| "women">\("all"\)/);
  assert.match(app, /<option value="all">Everyone \/ No preference<\/option>/);
  assert.match(app, /<option value="men">Men<\/option>/);
  assert.match(app, /<option value="women">Women<\/option>/);
  assert.match(app, /shopping_audience: shoppingAudience,/);
  assert.match(api, /shopping_audience\?: 'men' \| 'women' \| 'all';/);
});

test('"Tell us about your trip" is required, limited to 500 characters and counted', () => {
  assert.doesNotMatch(app, /Anything we should know/);
  assert.ok(app.includes('Tell us about your trip <em className="required">*</em>'));
  assert.match(app, /maxLength=\{DESCRIPTION_MAX\}\s*required\s*aria-required="true"/);
  assert.ok(app.includes('{notes.length}/{DESCRIPTION_MAX}'), 'character counter');
  assert.ok(app.includes('disabled={(step === 3 && (isLoading || !!notesError))'), 'cannot create a plan without it');
  assert.ok(app.includes('if (descriptionError(notes)) return;'));
  assert.ok(app.includes('notes: cleanDescription(notes)'));
});

test('a new trip starts with an empty product search (nothing carried over)', () => {
  assert.ok(app.includes('<ProductSearch key={plan.trip_id}'));
});
