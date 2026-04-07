// API service for communicating with FastAPI backend

const isDev = import.meta.env.DEV;
const BASE_URL = isDev ? '/api' : '/quant/api';

class ApiService {
  private baseUrl: string;

  constructor(baseUrl: string = BASE_URL) {
    this.baseUrl = baseUrl;
  }

  private async request<T>(endpoint: string, options?: RequestInit): Promise<T> {
    const response = await fetch(`${this.baseUrl}${endpoint}`, {
      headers: {
        'Content-Type': 'application/json',
        ...options?.headers,
      },
      ...options,
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: 'Unknown error' }));
      throw new Error(error.detail || `HTTP ${response.status}`);
    }

    return response.json();
  }

  // Account
  async getAccount() {
    return this.request('/account');
  }

  // Positions
  async getPositions() {
    return this.request('/portfolio/positions');
  }

  // Orders
  async getOrders() {
    return this.request('/trading/orders');
  }

  async submitOrder(order: {
    symbol: string;
    qty: number;
    side: 'buy' | 'sell';
    type: 'market' | 'limit';
    limit_price?: number;
  }) {
    return this.request('/trading/order', {
      method: 'POST',
      body: JSON.stringify(order),
    });
  }

  // Market Data
  async getBars(symbol: string, timeframe: string = '1Day', limit: number = 100) {
    return this.request(`/market/bars?symbol=${symbol}&timeframe=${timeframe}&limit=${limit}`);
  }

  async getQuote(symbol: string) {
    return this.request(`/market/quote?symbol=${symbol}`);
  }

  async getSnapshot(symbol: string) {
    return this.request(`/market/snapshot?symbol=${symbol}`);
  }

  // AI Agent
  async analyzeStock(symbol: string) {
    return this.request(`/agent/analyze?symbol=${symbol}`);
  }

  async chat(message: string) {
    return this.request('/agent/chat', {
      method: 'POST',
      body: JSON.stringify({ message }),
    });
  }

  // Trading Bot
  async startBot(strategy: string) {
    return this.request('/trading/bot/start', {
      method: 'POST',
      body: JSON.stringify({ strategy }),
    });
  }

  async stopBot() {
    return this.request('/trading/bot/stop', {
      method: 'POST',
    });
  }

  async getBotStatus() {
    return this.request('/trading/bot/status');
  }

  // Strategies
  async getStrategies() {
    return this.request('/trading/strategies');
  }

  async backtestStrategy(strategy: string, params: Record<string, unknown>) {
    return this.request('/trading/backtest', {
      method: 'POST',
      body: JSON.stringify({ strategy, params }),
    });
  }
}

export const api = new ApiService();
export default api;
