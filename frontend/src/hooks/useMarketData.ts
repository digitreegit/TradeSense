import { useEffect, useRef } from 'react';
import { useAppStore } from '../stores/useAppStore';
import api from '../services/api';
import type {
  AccountInfo,
  Order,
  Position,
  Strategy,
  WatchlistItem,
} from '../stores/types';

const WATCHLIST_SYMBOLS = ['AAPL', 'MSFT', 'NVDA', 'GOOGL', 'AMZN', 'TSLA', 'META', 'AMD'];

/**
 * Hook that fetches real market data from the backend (Alpaca API)
 * and keeps the store updated with live prices.
 */
export function useMarketData() {
  const { 
    setWatchlist, setAccount, setPositions, setOrders, 
    setConnected, setMarketOpen, setBotActive,
    authEmail,
  } = useAppStore();
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchAll = async () => {
    if (!authEmail) return;
    // ── Strategy playbooks (AUTO/MANUAL routing from engine) ──
    try {
      const res = await api.getStrategies();
      const playbook = res.strategies ?? [];
      if (playbook.length) {
        const mapped: Strategy[] = playbook.map((s) => ({
          id: s.id,
          name: s.name,
          description: s.description,
          active: s.enabled !== false,
          enabled: s.enabled,
          winRate: 0,
          trades: 0,
          pnl: 0,
        }));
        useAppStore.getState().setStrategies(mapped);
        if (typeof res.auto === 'boolean') {
          useAppStore.getState().setPlaybookAuto(res.auto);
        }
        if (Array.isArray(res.manual)) {
          useAppStore.getState().setManualPlaybooks(res.manual);
        }
        if (Array.isArray(res.active)) {
          useAppStore.getState().setActivePlaybooks(res.active);
        }
      }
    } catch {
      // ignore
    }

    // ── Bot status ────────────────────────────
    try {
      const botStatus = await api.getBotStatus();
      setBotActive(botStatus.active);
      if (botStatus.regime_data) {
        useAppStore.getState().setRegimeData(botStatus.regime_data);
      }
      if (botStatus.regime_reason && botStatus.regime_reason !== '') {
        // Only set notification if it's new
        useAppStore.getState().setMarketNotification(botStatus.regime_reason);
      }
    } catch {
      // ignore
    }

    // ── Alpaca REST quota (rate-limit headers) ────────────────
    try {
      const usage = await api.getAlpacaUsage();
      useAppStore.getState().setAlpacaUsage(usage);
    } catch {
      useAppStore.getState().setAlpacaUsage(null);
    }

    // ── Regime + compliance (Market Status + GFV/cooldown) ────
    try {
      const status = await api.getRegimeStatus();
      if (status?.regime) {
        useAppStore.getState().setRegimeData(status.regime);
      }
      if (status?.compliance) {
        useAppStore.getState().setCompliance(status.compliance);
      }
    } catch {
      // ignore — regime is non-critical for UI
    }

    // ── Trade History (Orders) ────────────────
    try {
      const data = await api.getOrders();
      if (data?.orders) {
        setOrders(data.orders as Order[]);
      }
    } catch {
      // ignore
    }

    try {
      const account = await api.getAccount();
      if (account && !('detail' in account)) {
        const next: AccountInfo = {
          equity: Number(account.equity) || 0,
          cash: Number(account.cash) || 0,
          buying_power: Number(account.buying_power) || 0,
          portfolio_value: Number(account.portfolio_value) || 0,
          profit_loss: Number(account.profit_loss) || 0,
          profit_loss_pct: Number(account.profit_loss_pct) || 0,
          daily_profit_loss: Number(account.daily_profit_loss) || 0,
          daily_profit_loss_pct: Number(account.daily_profit_loss_pct) || 0,
          day_trade_count: Number(account.day_trade_count) || 0,
          initial_capital: Number(account.initial_capital) || 3000,
          win_rate: Number(account.win_rate) || 0,
          avg_win: Number(account.avg_win) || 0,
          avg_loss: Number(account.avg_loss) || 0,
          profit_factor: Number(account.profit_factor) || 0,
          sharpe_ratio: Number(account.sharpe_ratio) || 0,
        };
        setAccount(next);
        setConnected(true);
      }
    } catch {
      setConnected(false);
    }

    // ── Positions ─────────────────────────────
    try {
      const data = await api.getPositions();
      if (data?.positions) setPositions(data.positions as Position[]);
    } catch {
      // ignore
    }

    // ── Watchlist snapshots ───────────────────
    const updated = await Promise.all(
      WATCHLIST_SYMBOLS.map(async (symbol) => {
        try {
          const data = await api.getSnapshot(symbol) as {
            snapshot?: Record<string, unknown>;
          };
          const snap = data?.snapshot as Record<string, Record<string, unknown>> | undefined;
          if (snap && snap.daily_bar) {
            const latest = (snap.latest_trade as Record<string, number>)?.price
              ?? (snap.daily_bar as Record<string, number>)?.close ?? 0;
            const prevClose = (snap.prev_daily_bar as Record<string, number>)?.close ?? latest;
            const change = Number(latest) - Number(prevClose);
            const changePercent = prevClose ? (change / Number(prevClose)) * 100 : 0;

            const names: Record<string, string> = {
              AAPL: 'Apple Inc.', MSFT: 'Microsoft Corp.', NVDA: 'NVIDIA Corp.',
              GOOGL: 'Alphabet Inc.', AMZN: 'Amazon.com Inc.', TSLA: 'Tesla Inc.',
              META: 'Meta Platforms', AMD: 'AMD Inc.',
            };

            return {
              symbol,
              name: names[symbol] ?? symbol,
              price: Number(Number(latest).toFixed(2)),
              change: Number(change.toFixed(2)),
              changePercent: Number(changePercent.toFixed(2)),
            };
          }
        } catch {
          // fall through to null
        }
        return null;
      })
    );

    const validItems = updated.filter(Boolean) as WatchlistItem[];
    if (validItems.length > 0) setWatchlist(validItems);

    // ── Market open check ─────────────────────
    const now = new Date();
    const day = now.getDay();
    const et = new Date(now.toLocaleString('en-US', { timeZone: 'America/New_York' }));
    const hours = et.getHours();
    const minutes = et.getMinutes();
    const timeInMinutes = hours * 60 + minutes;
    const isOpen = day >= 1 && day <= 5 && timeInMinutes >= 570 && timeInMinutes < 960; // 9:30–16:00 ET
    setMarketOpen(isOpen);
  };

  useEffect(() => {
    if (!authEmail) {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
      return;
    }

    fetchAll(); // immediate first fetch

    intervalRef.current = setInterval(fetchAll, 15000);

    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [authEmail]);
}
