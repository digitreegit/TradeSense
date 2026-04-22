import { create } from 'zustand';
import type {
  AccountInfo,
  Position,
  WatchlistItem,
  TradeLog,
  AgentMessage,
  Strategy,
  Order,
  PageId,
  RegimeData,
  ComplianceStatus,
  AlpacaApiUsage,
} from './types';

interface AppState {
  // Navigation
  currentPage: PageId;
  setCurrentPage: (page: PageId) => void;

  // Account
  account: AccountInfo;
  setAccount: (account: AccountInfo) => void;

  // Positions
  positions: Position[];
  setPositions: (positions: Position[]) => void;

  // Orders
  orders: Order[];
  setOrders: (orders: Order[]) => void;

  // Watchlist
  watchlist: WatchlistItem[];
  setWatchlist: (items: WatchlistItem[]) => void;
  selectedSymbol: string;
  setSelectedSymbol: (symbol: string) => void;

  // Trading Bot
  botActive: boolean;
  setBotActive: (active: boolean) => void;
  botDailyTrades: number;
  setBotDailyTrades: (count: number) => void;
  tradeLogs: TradeLog[];
  addTradeLog: (log: TradeLog) => void;
  setTradeLogs: (logs: TradeLog[]) => void;

  // AI Agent
  agentMessages: AgentMessage[];
  addAgentMessage: (msg: AgentMessage) => void;
  agentLoading: boolean;
  setAgentLoading: (loading: boolean) => void;

  // Strategies
  strategies: Strategy[];
  setStrategies: (strategies: Strategy[]) => void;
  activeStrategy: string | null;
  setActiveStrategy: (id: string | null) => void;

  // Connection
  connected: boolean;
  setConnected: (connected: boolean) => void;
  marketOpen: boolean;
  setMarketOpen: (open: boolean) => void;
  marketNotification: string | null;
  setMarketNotification: (msg: string | null) => void;
  regimeData: RegimeData | null;
  setRegimeData: (data: RegimeData | null) => void;
  dismissedRegimeTimestamp: string | null;
  setDismissedRegimeTimestamp: (ts: string | null) => void;
  compliance: ComplianceStatus | null;
  setCompliance: (c: ComplianceStatus | null) => void;
  alpacaUsage: AlpacaApiUsage | null;
  setAlpacaUsage: (u: AlpacaApiUsage | null) => void;

  // Playbook routing (AUTO vs MANUAL set + currently-active list)
  playbookAuto: boolean;
  setPlaybookAuto: (v: boolean) => void;
  manualPlaybooks: string[];
  setManualPlaybooks: (ids: string[]) => void;
  activePlaybooks: string[];
  setActivePlaybooks: (ids: string[]) => void;

  /** Signed-in user (null = guest / legacy env Alpaca) */
  authEmail: string | null;
  authAlpacaConfigured: boolean;
  setAuthProfile: (email: string | null, alpacaConfigured: boolean) => void;
  authMethod: 'google' | 'email' | null;
  setAuthMethod: (method: 'google' | 'email' | null) => void;
}

export const useAppStore = create<AppState>((set) => ({
  // Navigation
  currentPage: 'dashboard',
  setCurrentPage: (page) => set({ currentPage: page }),

  // Regime
  regimeData: null,
  setRegimeData: (data) => set({ regimeData: data }),
  dismissedRegimeTimestamp: null,
  setDismissedRegimeTimestamp: (ts) => set({ dismissedRegimeTimestamp: ts }),
  compliance: null,
  setCompliance: (c) => set({ compliance: c }),
  alpacaUsage: null,
  setAlpacaUsage: (u) => set({ alpacaUsage: u }),

  playbookAuto: true,
  setPlaybookAuto: (v) => set({ playbookAuto: v }),
  manualPlaybooks: ['scalp', 'vwap', 'orb', 'eod'],
  setManualPlaybooks: (ids) => set({ manualPlaybooks: ids }),
  activePlaybooks: [],
  setActivePlaybooks: (ids) => set({ activePlaybooks: ids }),

  authEmail: null,
  authAlpacaConfigured: false,
  setAuthProfile: (email, alpacaConfigured) =>
    set({ authEmail: email, authAlpacaConfigured: alpacaConfigured }),
  authMethod: null,
  setAuthMethod: (method) => set({ authMethod: method }),

  // Account - $3000 paper trading
  account: {
    equity: 3000.00,
    cash: 3000.00,
    buying_power: 3000.00,
    portfolio_value: 3000.00,
    profit_loss: 0,
    profit_loss_pct: 0,
    daily_profit_loss: 0,
    daily_profit_loss_pct: 0,
    day_trade_count: 0,
    initial_capital: 3000.00,
  },
  setAccount: (account) => set({ account }),

  // Positions
  positions: [],
  setPositions: (positions) => set({ positions }),

  // Orders
  orders: [],
  setOrders: (orders) => set({ orders }),

  // Watchlist with default stocks
  watchlist: [
    { symbol: 'AAPL', name: 'Apple Inc.', price: 195.89, change: 2.34, changePercent: 1.21 },
    { symbol: 'MSFT', name: 'Microsoft Corp.', price: 418.55, change: -1.23, changePercent: -0.29 },
    { symbol: 'NVDA', name: 'NVIDIA Corp.', price: 881.86, change: 15.42, changePercent: 1.78 },
    { symbol: 'GOOGL', name: 'Alphabet Inc.', price: 155.72, change: 0.87, changePercent: 0.56 },
    { symbol: 'AMZN', name: 'Amazon.com Inc.', price: 186.13, change: 3.21, changePercent: 1.75 },
    { symbol: 'TSLA', name: 'Tesla Inc.', price: 175.22, change: -4.18, changePercent: -2.33 },
    { symbol: 'META', name: 'Meta Platforms', price: 515.30, change: 8.44, changePercent: 1.66 },
    { symbol: 'AMD', name: 'AMD Inc.', price: 178.45, change: 3.92, changePercent: 2.25 },
  ],
  setWatchlist: (items) => set({ watchlist: items }),
  selectedSymbol: 'AAPL',
  setSelectedSymbol: (symbol) => set({ selectedSymbol: symbol }),

  // Trading Bot
  botActive: false,
  setBotActive: (active) => set({ botActive: active }),
  botDailyTrades: 0,
  setBotDailyTrades: (count) => set({ botDailyTrades: Math.max(0, Number(count) || 0) }),
  tradeLogs: [
    { time: new Date().toLocaleTimeString(), type: 'info', message: 'TradeSense v3 — Cash Account Scalp Engine Initialized ($3,000)' },
    { time: new Date().toLocaleTimeString(), type: 'info', message: 'PDT-Exempt mode active. GFV monitoring enabled.' },
    { time: new Date().toLocaleTimeString(), type: 'signal', message: 'Scanning 5-Min bars for AI Scalp opportunities...' },
  ],
  addTradeLog: (log) => set((state) => ({
    tradeLogs: [...state.tradeLogs.slice(-100), log],
  })),
  setTradeLogs: (logs) => set({ tradeLogs: logs }),

  // AI Agent
  agentMessages: [
    {
      id: '1',
      role: 'ai',
      content: 'Hi — I\'m the TradeSense v3 micro-scalping agent. ⚡️\n\n**$3,000 cash account** — targeting **+1% per day** compounded.\n\nActive playbook ideas:\n• RSI oversold bounce scalps (5-min)\n• VWAP support / resistance breaks\n• AI-driven sector rotation (paid tier)',
      timestamp: new Date().toISOString(),
    },
  ],
  addAgentMessage: (msg) => set((state) => ({
    agentMessages: [...state.agentMessages, msg],
  })),
  agentLoading: false,
  setAgentLoading: (loading) => set({ agentLoading: loading }),

  // Strategies
  strategies: [
    {
      id: 'scalp',
      name: 'Micro-Scalping v3',
      description: 'Fast intraday scalps on 5-min bars using RSI/VWAP. Targets ~1% per day.',
      active: true,
      winRate: 0,
      trades: 0,
      pnl: 0,
    },
    {
      id: 'regime-adaptive',
      name: 'AI Sector Adaptive',
      description: 'AI rotates focus sectors and symbols as macro headlines shift (war, rates, etc.).',
      active: true,
      winRate: 0,
      trades: 0,
      pnl: 0,
    },
    {
      id: 'ml-predict',
      name: 'ML Prediction',
      description: 'Gradient-boosting price outlook using technical features as inputs.',
      active: false,
      winRate: 55.8,
      trades: 0,
      pnl: 0,
    },
  ],
  setStrategies: (strategies) => set({ strategies }),
  activeStrategy: 'scalp',
  setActiveStrategy: (id) => set({ activeStrategy: id }),

  // Connection
  connected: false,
  setConnected: (connected) => set({ connected }),
  marketOpen: false,
  setMarketOpen: (open) => set({ marketOpen: open }),
  marketNotification: null,
  setMarketNotification: (msg) => set({ marketNotification: msg }),
}));
