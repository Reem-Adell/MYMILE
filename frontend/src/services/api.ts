import axios from 'axios';
import { TripPlan, Product, Hotel, WeatherData, DestinationImage, HotelOffers, ChatTurn, TripChatResult } from '../types';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api';

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
  timeout: 15000,
});

const TOKEN_KEY = 'mymile_token';
const USER_KEY = 'mymile_user';

// "Remember me" keeps the session in localStorage (survives closing the browser);
// otherwise it lives in sessionStorage and ends when the browser closes.
function saveSession(token: string, user: unknown, remember: boolean) {
  clearSession();
  const store = remember ? localStorage : sessionStorage;
  store.setItem(TOKEN_KEY, token);
  store.setItem(USER_KEY, JSON.stringify(user));
}

function clearSession() {
  for (const store of [localStorage, sessionStorage]) {
    store.removeItem(TOKEN_KEY);
    store.removeItem(USER_KEY);
  }
}

// Replace the cached user (e.g. after GET /auth/me) without touching the token.
export function updateStoredUser(user: unknown) {
  for (const store of [localStorage, sessionStorage]) {
    if (store.getItem(TOKEN_KEY)) store.setItem(USER_KEY, JSON.stringify(user));
  }
}

export function getStoredToken(): string | null {
  return localStorage.getItem(TOKEN_KEY) || sessionStorage.getItem(TOKEN_KEY);
}

export function getStoredUser<T>(): T | null {
  const raw = localStorage.getItem(USER_KEY) || sessionStorage.getItem(USER_KEY);
  if (!raw || !getStoredToken()) return null;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return null;
  }
}

// Turn an API error into a message we can show the user.
export function getErrorMessage(err: unknown, fallback = 'Something went wrong. Please try again.'): string {
  if (axios.isAxiosError(err)) {
    if (!err.response) return "Can't reach the server. Make sure the backend is running.";
    const detail = err.response.data?.detail;
    if (typeof detail === 'string') return detail;
  }
  return fallback;
}

// Attach JWT token if stored
apiClient.interceptors.request.use((config) => {
  const token = getStoredToken();
  if (token && config.headers) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

export const api = {
  // Health
  checkHealth: async () => {
    const res = await apiClient.get('/health');
    return res.data;
  },

  // Auth
  login: async (email: string, password: string, remember = true) => {
    const res = await apiClient.post('/auth/login', { email, password });
    if (res.data.access_token) {
      saveSession(res.data.access_token, res.data.user, remember);
    }
    return res.data;
  },

  logout: () => {
    clearSession();
  },

  register: async (name: string, email: string, password: string) => {
    const res = await apiClient.post('/auth/register', { name, email, password });
    if (res.data.access_token) {
      saveSession(res.data.access_token, res.data.user, true);
    }
    return res.data;
  },

  getMe: async () => {
    const res = await apiClient.get('/auth/me');
    return res.data;
  },

  // Trips & AI Agent
  planTrip: async (payload: {
    destination: string;
    destination_city?: string;
    destination_country?: string;
    departure_date: string;
    return_date: string;
    travelers: number;
    purpose: string;
    stay_preference: string;
    priorities?: string[];
    notes?: string;
    plan: 'free' | 'premium';
    total_budget?: number; // always US dollars
  }): Promise<TripPlan> => {
    // The Gemini agent may take up to AI_AGENT_DEADLINE_SECONDS (180 s) plus tool time.
    const res = await apiClient.post<TripPlan>('/trips/plan', payload, { timeout: 210000 });
    return res.data;
  },

  chatWithCompanion: async (payload: {
    message: string;
    history?: ChatTurn[];
    current_trip_context?: Record<string, unknown>;
    budget?: number;
  }): Promise<TripChatResult> => {
    const res = await apiClient.post<TripChatResult>('/trips/chat', payload, { timeout: 210000 });
    return res.data;
  },

  // Hotels
  searchHotels: async (params: {
    destination: string;
    check_in?: string;
    check_out?: string;
    nights?: number;
    stay_preference?: string;
    plan?: string;
  }) => {
    const res = await apiClient.get('/hotels/search', { params });
    return res.data;
  },

  // Weather
  getWeather: async (destination: string, days = 7): Promise<WeatherData> => {
    const res = await apiClient.get<WeatherData>('/weather', { params: { destination, days } });
    return res.data;
  },

  // Budget Optimization
  optimizeBudget: async (payload: {
    destination: string;
    duration_days: number;
    travelers: number;
    total_budget: number; // always US dollars
    selected_hotel_price_total?: number;
    stay_preference?: string;
  }) => {
    const res = await apiClient.post('/budget/optimize', payload);
    return res.data;
  },

  // Subscriptions (public). The Premium entry carries price/currency/duration
  // from backend settings. There is no upgrade call: Premium is only granted by
  // the backend after a verified PayPal capture (see services/payments.ts).
  // Real photo of the destination (Wikipedia/Wikimedia Commons, verified and
  // cached by the backend). Resolves null when no verified photo exists.
  getDestinationImage: async (city: string, country: string): Promise<DestinationImage | null> => {
    const res = await apiClient.get<{ image: DestinationImage | null }>('/places/destination-image', {
      params: { city, country },
      timeout: 10000,
    });
    return res.data?.image ?? null;
  },

  // Premium: provider booking links for one hotel from the trip's live search.
  getHotelOffers: async (params: {
    property_token: string;
    destination: string;
    city?: string | null;
    country?: string | null;
    check_in: string;
    check_out: string;
    adults: number;
  }): Promise<HotelOffers> => {
    const res = await apiClient.get<HotelOffers>('/hotels/offers', {
      params: {
        ...params,
        city: params.city || undefined,
        country: params.country || undefined,
      },
      timeout: 25000,
    });
    return res.data;
  },

  getPlans: async () => {
    const res = await apiClient.get('/subscriptions/plans');
    return res.data;
  },
};
