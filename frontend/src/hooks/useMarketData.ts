import { useEffect, useRef } from 'react';
import { useAppStore } from '../stores/useAppStore';
import api from '../services/api';

const WATCHLIST_SYMBOLS = ['AAPL', 'MSFT', 'NVDA', 'GOOGL', 'AMZN', 'TSLA', 'META', 'AMD'];

/**
 * Hook that fetches real market data from the backend (Alpaca API)
 * and keeps the store updated with live prices.
 */
export function useMarketData() {
  const { setWatchlist, setAccount, setPositions, setConnected, setMarketOpen, setBotActive } = useAppStore();
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchAll = async () => {
    // ── Bot status ────────────────────────────
    try {
      const status = await api.getBotStatus() as { active?: boolean };
      if (typeof status?.active === 'boolean') setBotActive(status.active);
    } catch {
      // ignore
    }
    try {
      const account = await api.getAccount() as Record<string, unknown>;
      if (account && !('detail' in account)) {
        setAccount({
          equity: Number(account.equity) || 1000,
          cash: Number(account.cash) || 1000,
          buying_power: Number(account.buying_power) || 1000,
          portfolio_value: Number(account.portfolio_value) || 1000,
          profit_loss: Number(account.profit_loss) || 0,
          profit_loss_pct: Number(account.profit_loss_pct) || 0,
          day_trade_count: Number(account.day_trade_count) || 0,
          initial_capital: Number(account.initial_capital) || 1000,
        });
        setConnected(true);
      }
    } catch {
      setConnected(false);
    }

    // ── Positions ─────────────────────────────
    try {
      const data = await api.getPositions() as { positions?: unknown[] };
      if (data?.positions) setPositions(data.positions as never[]);
    } catch {
      // ignore
    }

    // ── Watchlist snapshots ───────────────────
    const updated = await Promise.all(
      WATCHLIST_SYMBOLS.map(async (symbol) => {
        try {
          const data = await api.getSnapshot(symbol) as { snapshot?: Record<string, unknown> };
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

    const validItems = updated.filter(Boolean) as ReturnType<typeof useAppStore.getState>['watchlist'];
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
    fetchAll(); // immediate first fetch

    // Refresh every 15 seconds
    intervalRef.current = setInterval(fetchAll, 15000);

    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, []);
}
