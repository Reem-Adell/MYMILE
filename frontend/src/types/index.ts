export interface User {
  id: string;
  name: string;
  email: string;
  plan: 'free' | 'premium';
  created_at: string;
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
  price_per_night: number;
  total_price: number;
  currency: string;
  image_url: string;
  amenities: string[];
  distance_to_center?: string;
  best_match_reason: string;
  booking_link?: string | null;
  category: string;
  is_best_match: boolean;
  price_source?: "estimate" | "live";
  price_provider?: string | null;
}

export interface Product {
  id: string;
  name: string;
  price: number;
  currency: string;
  image_url: string;
  description: string;
  category: string;
  rating: number;
  purchase_url: string;
  brand?: string;
  reason: string;
  in_stock: boolean;
  provider: string;
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
}

export interface ItineraryActivity {
  time: string;
  title: string;
  description: string;
  location?: string;
  icon?: string;
  cost_estimate: number;
}

export interface ItineraryDay {
  day_number: number;
  date_str: string;
  theme: string;
  activities: ItineraryActivity[];
}

export interface TripPlan {
  trip_id: string;
  destination: string;
  departure_date: string;
  return_date: string;
  total_days: number;
  travelers: number;
  purpose: string;
  stay_preference: string;
  plan_tier: 'free' | 'premium';
  match_score: number;
  destination_summary: string;
  why_recommended: string;
  weather: WeatherData;
  recommended_hotel: Hotel;
  all_hotels: Hotel[];
  itinerary: ItineraryDay[];
  budget_breakdown: BudgetBreakdown;
  travel_essentials: Product[];
  is_premium: boolean;
}

export interface CartItem {
  product: Product;
  quantity: number;
}
