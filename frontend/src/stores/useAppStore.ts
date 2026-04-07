import { create } from 'zustand';
import type { AccountInfo, Position, WatchlistItem, TradeLog, AgentMessage, Strategy, Order, PageId } from './types';

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
}

export const useAppStore = create<AppState>((set) => ({
  // Navigation
  currentPage: 'dashboard',
  setCurrentPage: (page) => set({ currentPage: page }),

  // Account - $1000 paper trading
  account: {
    equity: 1000.00,
    cash: 1000.00,
    buying_power: 1000.00,
    portfolio_value: 1000.00,
    profit_loss: 0,
    profit_loss_pct: 0,
    day_trade_count: 0,
    initial_capital: 1000.00,
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
    { time: '15:30:01', type: 'info', message: 'TradeSense Bot initialized — Paper Trading mode ($1,000)' },
    { time: '15:30:02', type: 'info', message: 'Connected to Alpaca Markets API' },
    { time: '15:30:03', type: 'signal', message: 'Scanning market for opportunities...' },
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
      content: '안녕하세요! 저는 TradeSense AI 분석 에이전트입니다. 📊\n\n$1,000 페이퍼 트레이딩 포트폴리오를 관리하겠습니다. 주식 분석, 매매 시그널, 전략 추천 등 무엇이든 물어보세요!\n\n현재 모니터링 중인 전략:\n• 모멘텀 전략 (RSI + MACD)\n• 평균회귀 전략 (Bollinger Bands)\n• ML 예측 모델 (Gradient Boosting)',
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
      id: 'momentum',
      name: 'Momentum Breakout',
      description: 'RSI + MACD 크로스오버를 이용한 모멘텀 전략. 강한 상승/하락 추세를 포착합니다.',
      active: true,
      winRate: 62.5,
      trades: 0,
      pnl: 0,
    },
    {
      id: 'mean-reversion',
      name: 'Mean Reversion',
      description: 'Bollinger Bands를 이용한 평균회귀 전략. 과매수/과매도 구간에서 진입합니다.',
      active: false,
      winRate: 58.3,
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
