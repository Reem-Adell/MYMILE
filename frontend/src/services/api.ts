import axios from 'axios';
import { TripPlan, Product, Hotel, WeatherData } from '../types';

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
    departure_date: string;
    return_date: string;
    travelers: number;
    purpose: string;
    stay_preference: string;
    priorities?: string[];
    notes?: string;
    plan: 'free' | 'premium';
    total_budget?: number;
    currency?: string;
  }): Promise<TripPlan> => {
    const res = await apiClient.post<TripPlan>('/trips/plan', payload);
    return res.data;
  },

  chatWithCompanion: async (payload: {
    message: string;
    history?: { role: string; content: string }[];
    current_trip_context?: any;
    plan?: string;
    budget?: number;
  }) => {
    const res = await apiClient.post('/trips/chat', payload);
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

  // Products (Channel3)
  searchProducts: async (params: {
    destination?: string;
    trip_type?: string;
    season?: string;
    limit?: number;
  }): Promise<{ query_context: string; products: Product[]; source: string }> => {
    const res = await apiClient.get('/products/search', { params });
    return res.data;
  },

  // Budget Optimization
  optimizeBudget: async (payload: {
    destination: string;
    duration_days: number;
    travelers: number;
    total_budget: number;
    currency?: string;
    selected_hotel_price_total?: number;
    stay_preference?: string;
  }) => {
    const res = await apiClient.post('/budget/optimize', payload);
    return res.data;
  },

  // Subscriptions
  getPlans: async () => {
    const res = await apiClient.get('/subscriptions/plans');
    return res.data;
  },

  upgradePlan: async (plan: 'free' | 'premium') => {
    const res = await apiClient.post('/subscriptions/upgrade', { plan });
    return res.data;
  },

  // APIMatic
  getApimaticPortalInfo: async () => {
    const res = await apiClient.get('/apimatic/portal-info');
    return res.data;
  },

  getApimaticSdkSnippet: async (language: 'typescript' | 'python') => {
    const res = await apiClient.get(`/apimatic/sdk/${language}`);
    return res.data;
  },
};
