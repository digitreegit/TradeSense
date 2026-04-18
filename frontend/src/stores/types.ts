// Zustand store types and shared interfaces

export interface Position {
  symbol: string;
  qty: number;
  avg_entry_price: number;
  current_price: number;
  market_value: number;
  unrealized_pl: number;
  unrealized_plpc: number;
  side: 'long' | 'short';
}

export interface Order {
  id: string;
  symbol: string;
  side: 'buy' | 'sell';
  qty: number;
  type: 'market' | 'limit' | 'stop' | 'stop_limit';
  status: string;
  filled_at?: string;
  filled_avg_price?: number;
  submitted_at: string;
  limit_price?: number;
  stop_price?: number;
}

export interface AccountInfo {
  equity: number;
  cash: number;
  buying_power: number;
  portfolio_value: number;
  profit_loss: number;
  profit_loss_pct: number;
  daily_profit_loss: number;
  daily_profit_loss_pct: number;
  day_trade_count: number;
  initial_capital: number;
  win_rate?: number;
  avg_win?: number;
  avg_loss?: number;
  profit_factor?: number;
  sharpe_ratio?: number;
}

export interface WatchlistItem {
  symbol: string;
  name: string;
  price: number;
  change: number;
  changePercent: number;
  volume?: number;
}

export interface TradeLog {
  time: string;
  type: 'buy' | 'sell' | 'signal' | 'info' | 'error';
  message: string;
}

export interface AgentMessage {
  id: string;
  role: 'ai' | 'user';
  content: string;
  timestamp: string;
}

export interface Strategy {
  id: string;
  name: string;
  description: string;
  active: boolean;
  /** Optional: from API playbook list */
  enabled?: boolean;
  winRate: number;
  trades: number;
  pnl: number;
}

export interface BarData {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
}

export interface RegimeData {
  strategy: string;
  reasoning: string;
  risk_level: string;
  max_position_percent: number;
  stop_loss_percent: number;
  take_profit_percent?: number;
  prev_strategy?: string;
  prev_risk_level?: string;
  timestamp?: string;
  focus_sectors?: string[];
  focus_symbols?: string[];
  daily_target?: string;
  daily_pnl?: string;
  account_type?: string;
  /** AI regime sub-scores (war/earnings/fed/gold/crypto/others) */
  market_level?: string;
  market_score?: number;
  ai_market_score?: number;
  market_scores?: Record<string, number>;
  /** Quantitative regime sub-scores (vix/bonds/dxy/gold/energy/crypto/spy) */
  quant_scores?: Record<string, number>;
  quant_changes_5d_pct?: Record<string, number | null>;
  vix_proxy_level?: number;
  sector_tilt?: string | null;
  blackout?: boolean;
  blackout_reason?: string;
  news_score?: number;
  /** Currently enabled playbooks in engine (AUTO or MANUAL routing) */
  active_playbooks?: string[];
  playbook_mode?: 'auto' | 'manual';
}

/** `/api/trading/playbooks` payload */
export interface PlaybookConfig {
  auto: boolean;
  manual: string[];
  active: string[];
  playbooks: Array<{
    id: string;
    name: string;
    description: string;
    manual_enabled: boolean;
    active_now: boolean;
  }>;
}

/** Alpaca REST rate-limit snapshot (from response headers via /v2/clock probe). */
export interface AlpacaApiUsage {
  ok: boolean;
  connected?: boolean;
  error?: string;
  note?: string;
  http_probe_error?: string;
  limit?: number | null;
  remaining?: number | null;
  used?: number | null;
  reset_epoch?: number | null;
  reset_in_seconds?: number | null;
  percent_used?: number | null;
  /** False when Alpaca responded OK but sent no rate-limit headers */
  headers_available?: boolean;
}

export interface ComplianceStatus {
  unsettled_cash: number;
  open_unsettled_lots: number;
  gfv_count_12mo: number;
  gfv_level: 'OK' | 'NOTICE' | 'WARNING' | 'RESTRICTED';
  loss_streak: number;
  cooling_down: boolean;
  cooldown_remaining_s: number;
  wash_sale_cooldowns: Record<string, string>;
}

export interface BotStatusResponse {
  active: boolean;
  strategy?: string;
  regime_data?: RegimeData;
  regime_reason?: string;
}

export type PageId = 'dashboard' | 'chart' | 'agent' | 'trading' | 'portfolio' | 'history';
