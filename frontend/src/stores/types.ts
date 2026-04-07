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
  day_trade_count: number;
  initial_capital: number;
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

export type PageId = 'dashboard' | 'chart' | 'agent' | 'trading' | 'portfolio' | 'history';
