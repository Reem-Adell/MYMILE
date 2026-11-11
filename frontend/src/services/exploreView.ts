// Pure display rules for the Explore page (unit-tested with node:test).
import type { BookingOffer, Hotel, HotelOffers, TripPlan } from '../types';

export const PRICE_DISCLAIMER =
  'Prices are estimates and may change based on availability, dates, taxes, and provider fees.';

/** Shown with every hotel price on Explore (tooltip on the "Estimated" label + a short line). */
export const PRICE_VARIES_NOTE =
  'Actual prices may vary depending on availability, booking dates, and the booking provider.';

/** The "Estimated" label is shown whenever a price is displayed (not for "no price listed"). */
export function showsEstimateLabel(view: Pick<PriceView, 'kind'>): boolean {
  return view.kind !== 'none';
}

export const LIVE_PRICE_DISCLAIMER =
  'Prices are provider-listed estimates from Google Hotels. Final availability and prices must be '
  + 'confirmed on the provider’s website. MYMILE does not complete hotel bookings.';

/** Live Google Hotels data (SerpApi) rather than MYMILE's curated list. */
export function isLiveHotel(hotel: Pick<Hotel, 'data_source'>): boolean {
  return hotel.data_source === 'serpapi';
}

export function priceDisclaimer(hotel: Pick<Hotel, 'data_source'>): string {
  return isLiveHotel(hotel) ? LIVE_PRICE_DISCLAIMER : PRICE_DISCLAIMER;
}

/** Premium view = the backend currently says Premium (GET /auth/me, expiry-aware)
 *  AND this plan was generated for a Premium account. An expired or stale plan
 *  never shows Premium-only content. */
export function isPremiumView(userPlan: 'free' | 'premium', plan: Pick<TripPlan, 'is_premium'>): boolean {
  return userPlan === 'premium' && plan.is_premium === true;
}

/** Budget Snapshot and Estimated Cost: Premium only, and only with real budget data. */
export function canShowBudget(userPlan: 'free' | 'premium',
                              plan: Pick<TripPlan, 'is_premium' | 'budget_breakdown'>): boolean {
  return isPremiumView(userPlan, plan) && !!plan.budget_breakdown;
}

/** Explicit currency, e.g. "USD 1,230". */
export function formatMoney(amount: number, currency = 'USD'): string {
  return `${currency || 'USD'} ${Math.round(Number(amount) || 0).toLocaleString('en-US')}`;
}

export interface PriceView {
  kind: 'estimate' | 'listed' | 'typical' | 'none';
  nightly: string;   // "Est. USD 95 / room / night"
  total: string;     // "USD 570"
  totalLabel: string;
  details: string;   // "3 nights · 2 rooms"
  note: string;      // what the number is (never "confirmed")
}

function checkedTime(iso?: string | null): string {
  if (!iso) return '';
  const d = new Date(iso);
  return isNaN(d.getTime()) ? '' : `, checked ${d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })}`;
}

/** "Nov 11, 10:05 AM" (local time), or '' when missing/invalid. */
export function formatChecked(iso?: string | null): string {
  if (!iso) return '';
  const d = new Date(iso);
  return isNaN(d.getTime()) ? '' : d.toLocaleString('en-US', {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  });
}

function livePriceView(hotel: Hotel, nights: number): PriceView {
  const cur = hotel.currency || 'USD';
  const n = hotel.nights || nights;
  const a = hotel.adults || 0;
  const adultsText = a ? `${a} adult${a === 1 ? '' : 's'}` : '';
  const details = `${n} night${n === 1 ? '' : 's'}${adultsText ? ` · ${adultsText}` : ''}`;
  const checked = formatChecked(hotel.price_checked_at);
  const when = hotel.results_stale
    ? `Cached results (live update unavailable)${checked ? `, last checked ${checked}` : ''}. `
    : checked ? `Last updated ${checked}. ` : '';
  if (hotel.is_placeholder || hotel.price_per_night == null) {
    return {
      kind: 'none',
      nightly: hotel.is_placeholder ? 'No live price' : 'Price not listed for your dates',
      total: '—',
      totalLabel: 'Total for your stay',
      details,
      note: hotel.is_placeholder ? '' : `${when}Google Hotels didn’t list a price for this hotel for your dates.`,
    };
  }
  const taxes = hotel.taxes_included === true ? 'incl. taxes & fees as listed'
    : hotel.taxes_included === false ? 'before taxes & fees' : 'taxes & fees may not be included';
  const computed = hotel.total_price_basis === 'nightly_x_nights';
  return {
    kind: 'listed',
    nightly: `${formatMoney(hotel.price_per_night, cur)} / night`,
    total: hotel.total_price == null ? '—' : formatMoney(hotel.total_price, cur),
    totalLabel: computed ? 'Approx. total (nightly rate × nights)' : 'Listed total for your stay',
    details,
    note: `${when}Lowest price listed on ${hotel.price_provider || 'Google Hotels'} for your dates`
      + `${adultsText ? ` and ${adultsText}` : ''}; ${taxes}. Not a confirmed rate.`,
  };
}

export function priceView(hotel: Hotel, nights: number, rooms: number): PriceView {
  if (isLiveHotel(hotel)) return livePriceView(hotel, nights);
  const cur = hotel.currency || 'USD';
  const n = hotel.nights || nights;
  const r = hotel.rooms || rooms;
  const details = `${n} night${n === 1 ? '' : 's'}${r > 1 ? ` · ${r} rooms` : ''}`;
  if (hotel.is_placeholder) {
    return {
      kind: 'typical',
      nightly: `Typical ${formatMoney(hotel.price_per_night ?? 0, cur)} / room / night`,
      total: formatMoney(hotel.total_price ?? 0, cur),
      totalLabel: 'Rough estimate for your stay',
      details,
      note: 'A typical rate for this kind of stay, not a price for a specific hotel.',
    };
  }
  if (hotel.price_source === 'live') {
    const taxes = hotel.taxes_included === true ? 'incl. taxes & fees as listed'
      : hotel.taxes_included === false ? 'before taxes & fees' : 'taxes & fees may not be included';
    const by = hotel.price_provider ? ` by ${hotel.price_provider}` : '';
    return {
      kind: 'listed',
      nightly: `${formatMoney(hotel.price_per_night ?? 0, cur)} / room / night`,
      total: formatMoney(hotel.total_price ?? 0, cur),
      totalLabel: 'Listed total for your stay',
      details,
      note: `Price listed${by} for your dates via Google Hotels${checkedTime(hotel.price_checked_at)}; ${taxes}. Not a confirmed rate.`,
    };
  }
  return {
    kind: 'estimate',
    nightly: `Est. ${formatMoney(hotel.price_per_night ?? 0, cur)} / room / night`,
    total: formatMoney(hotel.total_price ?? 0, cur),
    totalLabel: 'Estimated total for your stay',
    details,
    note: 'MYMILE estimate, not a live price. Taxes & fees may apply.',
  };
}

export interface BookingView {
  href: string;
  label: string;
  note: string;
}

/** What the Booking.com button says. A search link is never presented as the
 *  hotel's own page. Returns null when there is no link (Free plan). */
export function bookingView(hotel: Hotel): BookingView | null {
  if (!hotel.booking_link) return null;
  if (hotel.booking_link_type === 'provider') {
    const provider = hotel.booking_provider || 'the provider';
    const offer = (hotel.booking_offers || []).find((o) => o.url === hotel.booking_link);
    const price = offer?.price_per_night != null
      ? ` ${provider} lists ${formatMoney(offer.price_per_night, offer.currency || hotel.currency)} / night.` : '';
    return { href: hotel.booking_link, label: `Book on ${provider}`,
             note: `Opens ${provider}’s booking page for this hotel in a new tab.${price} `
               + 'Confirm the final price and availability there; MYMILE doesn’t complete bookings.' };
  }
  if (hotel.booking_link_type === 'property') {
    return { href: hotel.booking_link, label: 'View this hotel on Booking.com',
             note: 'Opens the hotel’s page on Booking.com with your dates and guests.' };
  }
  if (hotel.is_placeholder) {
    return { href: hotel.booking_link, label: 'Search stays on Booking.com',
             note: 'Opens Booking.com search results for your destination, dates and guests.' };
  }
  return { href: hotel.booking_link, label: 'Search this hotel on Booking.com',
           note: 'Opens Booking.com search results for this hotel’s name with your dates and guests. '
             + 'It is not a direct hotel page, so check the hotel name before booking.' };
}

/** City and country to look up the hero photo for. */
export function heroLocation(plan: Pick<TripPlan, 'destination' | 'destination_city' | 'destination_country'>) {
  const parts = plan.destination.split(',').map((p) => p.trim()).filter(Boolean);
  const city = (plan.destination_city || parts[0] || '').trim();
  const country = (plan.destination_country || (parts.length > 1 ? parts[parts.length - 1] : '')).trim();
  return { city, country };
}

/** One short supporting line under the price (the full price.note stays available as a tooltip). */
export function priceMeta(hotel: Hotel, view: PriceView): string {
  if (view.kind === 'none') return view.note;
  if (view.kind === 'typical') return 'Typical rate, not a specific hotel';
  if (view.kind === 'estimate') return 'MYMILE estimate · taxes & fees may apply';
  const parts = [
    hotel.total_price_basis === 'nightly_x_nights' ? 'Total ≈ nightly rate × nights' : null,
    hotel.taxes_included === true ? 'Incl. taxes & fees'
      : hotel.taxes_included === false ? 'Before taxes & fees' : 'Taxes & fees may be extra',
    hotel.results_stale ? 'Cached results' : null,
    formatChecked(hotel.price_checked_at) ? `Updated ${formatChecked(hotel.price_checked_at)}` : null,
  ];
  return parts.filter(Boolean).join(' · ');
}

/** "USD 304 / night on Booking.com": the chosen provider's own listed price, if it gave one. */
export function bookingPriceLine(hotel: Hotel): string | null {
  if (hotel.booking_link_type !== 'provider' || !hotel.booking_link) return null;
  const offer = (hotel.booking_offers || []).find((o) => o.url === hotel.booking_link);
  if (offer?.price_per_night == null) return null;
  return `${formatMoney(offer.price_per_night, offer.currency || hotel.currency)} / night on `
    + `${hotel.booking_provider || offer.provider}`;
}

/** Other providers with a real URL, besides the main booking button (max 3). */
export function otherOffers(hotel: Hotel, max = 3): BookingOffer[] {
  return (hotel.booking_offers || []).filter((o) => !!o.url && o.url !== hotel.booking_link).slice(0, max);
}

/** Premium + live hotel without a booking link yet: ask the backend for provider links. */
export function needsOffers(hotel: Hotel, isPremium: boolean): boolean {
  return isPremium && isLiveHotel(hotel) && !hotel.is_placeholder && !!hotel.property_token && !hotel.booking_link;
}

/** Query for GET /hotels/offers: the same search parameters the trip used. */
export function offersRequest(plan: Pick<TripPlan, 'destination' | 'destination_city' | 'destination_country'
  | 'departure_date' | 'return_date' | 'travelers'>, hotel: Hotel) {
  return {
    property_token: hotel.property_token || '',
    destination: plan.destination,
    city: plan.destination_city || null,
    country: plan.destination_country || null,
    check_in: plan.departure_date,
    check_out: plan.return_date,
    adults: plan.travelers,
  };
}

/** The hotel with provider links from /hotels/offers. Only real URLs are used. */
export function mergeOffers(hotel: Hotel, offers: HotelOffers | null): Hotel {
  if (!offers || offers.status !== 'ok' || offers.property_token !== hotel.property_token) return hotel;
  return {
    ...hotel,
    booking_link: offers.booking_link || null,
    booking_link_type: offers.booking_link ? 'provider' : null,
    booking_provider: offers.booking_provider || null,
    booking_offers: (offers.booking_offers || []).filter((o) => !!o.url),
    official_website: offers.official_website || hotel.official_website || null,
    address: offers.address || hotel.address || null,
  };
}
