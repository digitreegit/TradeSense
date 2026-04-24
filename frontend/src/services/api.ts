import type {
  AlpacaApiUsage,
  BotStatusResponse,
  ComplianceStatus,
  PlaybookConfig,
  RegimeData,
} from '../stores/types';
import { getToken } from '../auth/token';

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

function authHeaders(): Record<string, string> {
  const t = getToken();
  return t ? { Authorization: `Bearer ${t}` } : {};
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const url = `${API_PREFIX}${path.startsWith('/') ? path : `/${path}`}`;
  const response = await fetch(url, {
    headers: {
      'Content-Type': 'application/json',
      ...authHeaders(),
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
      auto?: boolean;
      manual?: string[];
      active?: string[];
      strategies: Array<{
        id: string;
        name: string;
        description: string;
        enabled?: boolean;
        manual_enabled?: boolean;
      }>;
    }>('/trading/strategies'),

  getPlaybookConfig: () => request<PlaybookConfig>('/trading/playbooks'),

  setPlaybookConfig: (body: { auto?: boolean; manual?: string[] }) =>
    request<PlaybookConfig>('/trading/playbooks', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  getCapitalScale: () =>
    request<{
      scale: '3k' | '10k' | '30k';
      level: string;
      auto: boolean;
      available: Array<'3k' | '10k' | '30k'>;
      preset: Record<string, unknown>;
      paper_trading?: boolean;
      initial_capital?: number;
    }>('/trading/scale'),

  setCapitalScale: (scale: '3k' | '10k' | '30k') =>
    request<{
      scale: '3k' | '10k' | '30k';
      level: string;
      preset: Record<string, unknown>;
      paper_trading?: boolean;
      initial_capital?: number;
    }>('/trading/scale', {
      method: 'POST',
      body: JSON.stringify({ scale }),
    }),

  setTradingMode: (paper: boolean) =>
    request<{
      scale: '3k' | '10k' | '30k';
      level: string;
      preset: Record<string, unknown>;
      paper_trading: boolean;
      initial_capital?: number;
    }>('/trading/mode', {
      method: 'POST',
      body: JSON.stringify({ paper }),
    }),

  backtestStrategy: (strategy: string, params: Record<string, unknown>) =>
    request<unknown>('/trading/backtest', {
      method: 'POST',
      body: JSON.stringify({ strategy, params }),
    }),

  getMe: () =>
    request<{
      authenticated: boolean;
      user_id?: number;
      email?: string;
      alpaca_configured?: boolean;
      alpaca_paper_trading?: boolean;
      notify_telegram?: boolean;
      telegram_chat_id?: string;
      telegram_bot_configured?: boolean;
    }>('/auth/me'),

  getNotificationPrefs: () =>
    request<{
      notify_telegram: boolean;
      telegram_chat_id: string;
      telegram_bot_configured: boolean;
    }>('/auth/notification-prefs'),

  setNotificationPrefs: (body: { notify_telegram: boolean; telegram_chat_id: string }) =>
    request<{
      notify_telegram: boolean;
      telegram_chat_id: string;
      telegram_bot_configured: boolean;
    }>('/auth/notification-prefs', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  testNotification: () =>
    request<{ ok: boolean; message: string }>('/auth/notification-test', {
      method: 'POST',
    }),

  saveAlpacaKeys: (api_key: string, secret_key: string) =>
    request<{ ok: boolean; message: string }>('/auth/alpaca-keys', {
      method: 'POST',
      body: JSON.stringify({ api_key, secret_key }),
    }),

  deleteAlpacaKeys: () =>
    request<{ ok: boolean; message: string }>('/auth/alpaca-keys', {
      method: 'DELETE',
    }),
} as const;

export default api;
