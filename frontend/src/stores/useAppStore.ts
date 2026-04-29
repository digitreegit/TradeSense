import { create } from 'zustand';
import type { AccountInfo, Position, WatchlistItem, TradeLog, AgentMessage, Strategy, Order, PageId, RegimeData } from './types';
import type { ColorMode } from '../theme';
import { applyColorMode } from '../theme';

interface AppState {
  // Navigation
  currentPage: PageId;
  setCurrentPage: (page: PageId) => void;

  colorMode: ColorMode;
  setColorMode: (mode: ColorMode) => void;
  toggleColorMode: () => void;

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
}

export const useAppStore = create<AppState>((set, get) => ({
  // Navigation
  currentPage: 'dashboard',
  setCurrentPage: (page) => set({ currentPage: page }),

  colorMode: 'dark',
  setColorMode: (mode) => {
    applyColorMode(mode);
    set({ colorMode: mode });
  },
  toggleColorMode: () => {
    const next = get().colorMode === 'dark' ? 'light' : 'dark';
    applyColorMode(next);
    set({ colorMode: next });
  },

  // Regime
  regimeData: null,
  setRegimeData: (data) => set({ regimeData: data }),
  dismissedRegimeTimestamp: null,
  setDismissedRegimeTimestamp: (ts) => set({ dismissedRegimeTimestamp: ts }),

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
      content: '안녕하세요! 저는 TradeSense v3 마이크로 스캘핑 에이전트입니다. ⚡️\n\n**$3,000 캐시 어카운트**를 활용해 매일 **+1% 수익**을 목표로 복리 투자를 진행합니다.\n\n현재 모니터링 중인 스캘핑 전략:\n• RSI 과매도 반등 스캘핑 (5-min)\n• VWAP 지지/저항 돌파\n• AI 기반 섹터 순환 (Paid Tier)',
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
      description: '5분봉 기준 RSI/VWAP 지표를 활용한 빠른 단타 전략. 매일 1% 수익을 목표로 합니다.',
      active: true,
      winRate: 0,
      trades: 0,
      pnl: 0,
    },
    {
      id: 'regime-adaptive',
      name: 'AI Sector Adaptive',
      description: '실시간 시장 이슈(전쟁, 금리 등)에 따라 집중 섹터와 종목을 AI가 자동으로 변경합니다.',
      active: true,
      winRate: 0,
      trades: 0,
      pnl: 0,
    },
    {
      id: 'ml-predict',
      name: 'ML Prediction',
      description: 'Gradient Boosting 모델을 이용한 가격 예측 전략. 기술적 지표를 feature로 사용.',
      active: false,
      winRate: 55.8,
      trades: 0,
      pnl: 0,
    },
  ],
  setStrategies: (strategies) => set({ strategies }),
  activeStrategy: 'momentum',
  setActiveStrategy: (id) => set({ activeStrategy: id }),

  // Connection
  connected: false,
  setConnected: (connected) => set({ connected }),
  marketOpen: false,
  setMarketOpen: (open) => set({ marketOpen: open }),
  marketNotification: null,
  setMarketNotification: (msg) => set({ marketNotification: msg }),
}));
