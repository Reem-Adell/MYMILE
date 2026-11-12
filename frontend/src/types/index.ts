export interface User {
  id: string;
  name: string;
  email: string;
  // EFFECTIVE plan computed by the backend (/api/auth/me); never set locally.
  plan: 'free' | 'premium';
  created_at: string;
  // Stored Premium expiry (ISO-8601 UTC) or null (none / permanent demo account).
  premium_until?: string | null;
}

// Premium offer as returned by GET /api/subscriptions/plans (premium entry).
export interface PremiumTerms {
  price: string;          // exact decimal string, e.g. "9.00"
  currency: string;       // e.g. "USD"
  duration_days: number;  // e.g. 30
  one_time: boolean;
  auto_renew: boolean;
}

export interface WeatherForecastDay {
  date: string;
  condition: string;
  temp_min_c: number;
  temp_max_c: number;
  temp_min_f: number;
  temp_max_f: number;
  precipitation_prob?: number;
  icon?: string;
  summary?: string;
}

export interface WeatherData {
  destination: string;
  latitude: number;
  longitude: number;
  current_temp_c: number;
  current_condition: string;
  packing_tip: string;
  forecast: WeatherForecastDay[];
  source: string;
}

export interface Hotel {
  id: string;
  name: string;
  location: string;
  rating: number;
  reviews_count: number;
  // null = no price listed (live Google Hotels results only; never invented)
  price_per_night: number | null;
  total_price: number | null;
  currency: string;
  image_url: string;
  amenities: string[];
  distance_to_center?: string;
  best_match_reason: string;
  booking_link?: string | null;
  category: string;
  is_best_match: boolean;
  // "estimate" = MYMILE's typical rate; "live" = price listed by a booking site
  // for these exact dates/guests (via Google Hotels). Neither is a confirmed rate.
  price_source?: "estimate" | "live";
  price_provider?: string | null;
  price_basis?: string;             // "per_room_per_night"
  nights?: number;
  rooms?: number;
  taxes_included?: boolean | null;  // null = unknown
  price_checked_at?: string | null;
  city?: string | null;
  country?: string | null;          // ISO code, e.g. "EG"
  // "search" = Booking.com search pre-filled with this hotel and the trip (not a
  // direct property page); "property" only for a verified property URL.
  // "provider" = a specific booking site's URL for this hotel, as returned by Google Hotels.
  booking_link_type?: "search" | "property" | "provider" | null;
  image_is_illustrative?: boolean;  // stock photo, not of this property
  is_placeholder?: boolean;         // not a hotel: no verified hotels / live results unavailable
  // ---- Live Google Hotels data (SerpApi) ----
  data_source?: "curated" | "serpapi";
  property_token?: string | null;
  description?: string | null;
  address?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  hotel_class?: string | null;
  images?: string[];
  adults?: number | null;
  total_price_basis?: "listed" | "nightly_x_nights" | null;
  booking_provider?: string | null;   // Premium only
  booking_offers?: BookingOffer[];    // Premium only
  official_website?: string | null;   // hotel's own site: NOT a booking provider link
  results_stale?: boolean;            // live refresh failed; cached results shown
}

export interface BookingOffer {
  provider: string;
  url?: string | null;
  price_per_night?: number | null;
  total_price?: number | null;
  currency: string;
  official: boolean;
  free_cancellation?: boolean | null;
}

// GET /api/hotels/offers (Premium): provider links for one live hotel.
export interface HotelOffers {
  property_token: string;
  status: "ok" | "unavailable";
  message?: string | null;
  booking_link?: string | null;
  booking_provider?: string | null;
  booking_offers: BookingOffer[];
  official_website?: string | null;
  address?: string | null;
  phone?: string | null;
  checked_at?: string | null;
  stale: boolean;
}

// A product found by Channel3. Missing fields are null: nothing is invented.
export interface ProductOffer {
  retailer: string;
  url?: string | null;              // Premium only
  price?: number | null;
  compare_at_price?: number | null;
  currency?: string | null;
  availability?: 'InStock' | 'OutOfStock' | null;
}

export interface Product {
  id: string;
  name: string;
  price: number | null;
  compare_at_price?: number | null;
  currency: string | null;
  image_url: string | null;
  description?: string | null;
  category?: string | null;
  rating?: number | null;
  rating_count?: number | null;
  // Retailer link; null when the backend does not allow external links (Free plan).
  purchase_url: string | null;
  brand?: string | null;
  retailer?: string | null;
  reason?: string | null;           // the AI's short reason (facts from the product data only)
  group?: string | null;            // trip-specific category, e.g. "Prayer Essentials"
  audience?: 'all' | 'men' | 'women' | null; // labelled options; gender is never assumed
  per_traveler?: boolean | null;    // one per traveler (true) or shared (false)
  in_stock?: boolean | null;        // null = unknown
  variants?: string[];
  offers?: ProductOffer[];
  search_query?: string | null;
  provider: string;
}

// "Who are you shopping for?" (a shopping preference, not the traveler's identity).
export type ShoppingAudience = 'men' | 'women' | 'all';

// GET /api/products/search (direct Channel3 search).
export interface ProductSearchResult {
  query_context: string;
  products: Product[];
  status: 'ok' | 'empty' | 'not_configured' | 'unavailable';
  message?: string | null;
}

export interface EssentialsInfo {
  status: 'ok' | 'empty' | 'not_configured' | 'ai_unavailable' | 'unavailable';
  message?: string | null;
  queries: string[];
  missing?: string[];                // needed categories with no product shown
  // Why each is missing: not searched, searched but nothing relevant, or relevant but not selected.
  missing_detail?: { category: string; state: 'not_searched' | 'not_found' | 'not_selected' }[];
}

export interface BudgetCategoryDetail {
  category: string;
  allocated_amount: number;
  percentage_of_total: number;
  description: string;
  is_flexible: boolean;
}

export interface BudgetBreakdown {
  accommodation: number;
  transportation: number;
  food: number;
  activities: number;
  travel_essentials: number;
  contingency_and_other: number;
  total_estimated: number;
  user_budget?: number | null;
  remaining_balance?: number | null;
  currency: string;
  status: string;
  // Clear terms (same numbers): 'allocated' = budget split into planned limits; 'estimated' = no budget set.
  allocation_mode?: 'allocated' | 'estimated' | null;
  allocated_total?: number | null;      // stay + category allocations
  unallocated_budget?: number | null;   // budget - allocated (negative = over-allocated)
  fully_allocated?: boolean | null;
  allocation_note?: string | null;
}

export interface TripPlan {
  trip_id: string;
  destination: string;
  destination_city?: string | null;
  destination_country?: string | null;
  departure_date: string;
  return_date: string;
  total_days: number;
  travelers: number;
  purpose: string;
  stay_preference: string;
  shopping_audience?: ShoppingAudience | null; // echoed: "men" | "women" | null (everyone)
  plan_tier: 'free' | 'premium';
  match_score?: number | null;  // no fabricated score is sent
  destination_summary: string;
  why_recommended: string;
  weather: WeatherData;
  recommended_hotel: Hotel;
  all_hotels: Hotel[];
  // Premium only: null for Free accounts and guests.
  budget_breakdown: BudgetBreakdown | null;
  travel_essentials: Product[];
  is_premium: boolean;
  ai?: AgentInfo;
  essentials?: EssentialsInfo;
}

// The backend's LLM provider (LLM_PROVIDER): Groq by default, Gemini optional.
export type AiProvider = 'groq' | 'gemini';

// Who produced the plan's text and picks (never claims AI when it wasn't used).
export interface AgentInfo {
  generated_by: AiProvider | 'rules';
  model?: string | null;
  tools_used: string[];
  cached: boolean;
  notice?: string | null;
}

export interface ChatTurn {
  role: 'user' | 'assistant';
  content: string;
}

// POST /api/trips/chat
export interface TripChatResult {
  reply: string;
  suggestions: string[];
  tools_called: string[];
  generated_by: AiProvider | 'unavailable';
  model?: string | null;
  hotel_options: Hotel[];
  suggested_hotel_id?: string | null;
}


// GET /api/places/destination-image
export interface DestinationImage {
  url: string;
  page_url?: string | null;
  title?: string | null;
  source: string;
}
