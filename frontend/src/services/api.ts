import type {
  AlpacaApiUsage,
  BotStatusResponse,
  ComplianceStatus,
  RegimeData,
} from '../stores/types';

/**
 * HTTP client for the FastAPI backend.
 *
 * - Local dev: Vite proxies `/api` → http://localhost:8000 (see vite.config.ts).
 * - Production: set `VITE_API_BASE` to the public API prefix (e.g. `/quant/api`).
 */
const API_PREFIX =
  (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, '') ??
  (import.meta.env.DEV ? '/api' : '/quant/api');

type ErrorBody = { detail?: string; message?: string };

async function parseError(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as ErrorBody;
    if (typeof body.detail === 'string') return body.detail;
    if (Array.isArray(body.detail)) return JSON.stringify(body.detail);
    if (typeof body.message === 'string') return body.message;
  } catch {
    /* ignore */
  }
  return `HTTP ${response.status}`;
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const url = `${API_PREFIX}${path.startsWith('/') ? path : `/${path}`}`;
  const response = await fetch(url, {
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
    ...options,
  });

  if (!response.ok) {
    throw new Error(await parseError(response));
  }

  return response.json() as Promise<T>;
}

export const api = {
  getAccount: () => request<Record<string, unknown>>('/account'),

  getPositions: () => request<{ positions?: unknown[] }>('/portfolio/positions'),

  getOrders: () => request<{ orders?: unknown[] }>('/trading/orders'),

  submitOrder: (order: {
    symbol: string;
    qty: number;
    side: 'buy' | 'sell';
    type: 'market' | 'limit';
    limit_price?: number;
  }) =>
    request<unknown>('/trading/order', {
      method: 'POST',
      body: JSON.stringify(order),
    }),

  getBars: (symbol: string, timeframe = '1Day', limit = 100) =>
    request<unknown>(`/market/bars?symbol=${encodeURIComponent(symbol)}&timeframe=${encodeURIComponent(timeframe)}&limit=${limit}`),

  getQuote: (symbol: string) =>
    request<unknown>(`/market/quote?symbol=${encodeURIComponent(symbol)}`),

  getSnapshot: (symbol: string) =>
    request<unknown>(`/market/snapshot?symbol=${encodeURIComponent(symbol)}`),

  analyzeStock: (symbol: string) =>
    request<unknown>(`/agent/analyze?symbol=${encodeURIComponent(symbol)}`),

  chat: (message: string) =>
    request<unknown>('/agent/chat', {
      method: 'POST',
      body: JSON.stringify({ message }),
    }),

  startBot: (
    strategy: string,
    riskSettings?: { stop_loss?: number; take_profit?: number; max_position?: number },
  ) =>
    request<unknown>('/trading/bot/start', {
      method: 'POST',
      body: JSON.stringify({ strategy, ...riskSettings }),
    }),

  stopBot: () =>
    request<unknown>('/trading/bot/stop', {
      method: 'POST',
    }),

  getBotStatus: () => request<BotStatusResponse>('/trading/bot/status'),

  getRegimeStatus: () =>
    request<{
      regime: RegimeData;
      active_preset: Record<string, unknown>;
      compliance: ComplianceStatus;
    }>('/regime/status'),

  getRiskPresets: () => request<Record<string, Record<string, unknown>>>('/regime/presets'),

  /** Prefer health path so SPA catch-all in production never returns HTML here */
  getAlpacaUsage: () => request<AlpacaApiUsage>('/health/alpaca-usage'),

  getStrategies: () =>
    request<{
      strategies: Array<{ id: string; name: string; description: string; enabled?: boolean }>;
    }>('/trading/strategies'),

  backtestStrategy: (strategy: string, params: Record<string, unknown>) =>
    request<unknown>('/trading/backtest', {
      method: 'POST',
      body: JSON.stringify({ strategy, params }),
    }),
} as const;

export default api;
