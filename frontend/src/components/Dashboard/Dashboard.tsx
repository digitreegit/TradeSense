import React, { useMemo } from 'react';
import { useAppStore } from '../../stores/useAppStore';
import { formatCurrency, formatPercent, getChangeClass } from '../../utils/helpers';
import api from '../../services/api';

const Dashboard: React.FC = () => {
  const {
    account,
    positions,
    watchlist,
    setSelectedSymbol,
    setCurrentPage,
    botActive,
    setBotActive,
    tradeLogs,
    strategies,
    marketNotification,
    setMarketNotification,
  } = useAppStore();

  const totalPL = account.equity - account.initial_capital;
  const totalPLPct = ((account.equity - account.initial_capital) / account.initial_capital) * 100;

  const activePositionCount = positions.length;

  // Mock intraday performance data for the mini sparkline
  const sparklinePoints = useMemo(() => {
    const points = [];
    let val = account.initial_capital;
    for (let i = 0; i < 24; i++) {
      val += (Math.random() - 0.48) * 5;
      points.push(val);
    }
    points.push(account.equity);
    return points;
  }, [account.equity, account.initial_capital]);

  const sparkMin = Math.min(...sparklinePoints);
  const sparkMax = Math.max(...sparklinePoints);
  const sparkRange = sparkMax - sparkMin || 1;

  const sparklinePath = sparklinePoints
    .map((p, i) => {
      const x = (i / (sparklinePoints.length - 1)) * 120;
      const y = 30 - ((p - sparkMin) / sparkRange) * 28;
      return `${i === 0 ? 'M' : 'L'} ${x} ${y}`;
    })
    .join(' ');

  return (
    <div className="page-enter">
      {/* Stats Grid */}
      <div className="stats-grid">
        <div className={`stat-card ${totalPL >= 0 ? 'profit' : 'loss'}`}>
          <div className="stat-label">Portfolio Value</div>
          <div className={`stat-value ${getChangeClass(totalPL)}`}>
            {formatCurrency(account.equity)}
          </div>
          <div className={`stat-change ${getChangeClass(totalPL)}`}>
            {totalPL >= 0 ? '▲' : '▼'} {formatCurrency(Math.abs(totalPL))} ({formatPercent(totalPLPct)})
          </div>
        </div>

        <div className="stat-card accent">
          <div className="stat-label">Cash Available</div>
          <div className="stat-value" style={{ color: 'var(--text-primary)' }}>
            {formatCurrency(account.cash)}
          </div>
          <div style={{ fontSize: '11px', color: 'var(--text-tertiary)', marginTop: '6px' }}>
            Buying Power: {formatCurrency(account.buying_power)}
          </div>
        </div>

        <div className="stat-card accent">
          <div className="stat-label">Active Positions</div>
          <div className="stat-value" style={{ color: 'var(--accent-secondary)' }}>
            {activePositionCount}
          </div>
          <div style={{ fontSize: '11px', color: 'var(--text-tertiary)', marginTop: '6px' }}>
            {strategies.filter(s => s.active).length} strategies active
          </div>
        </div>

        <div className="stat-card accent">
          <div className="stat-label">Bot Status</div>
          <div className="stat-value" style={{
            color: botActive ? 'var(--profit)' : 'var(--text-tertiary)',
            fontSize: '22px',
          }}>
            {botActive ? '● ACTIVE' : '○ IDLE'}
          </div>
          <div style={{ fontSize: '11px', color: 'var(--text-tertiary)', marginTop: '6px' }}>
            {tradeLogs.length} events logged
          </div>
        </div>
      </div>

      {/* Main Grid */}
      <div className="dashboard-grid">
        <div className="dashboard-left">
          {/* Portfolio Chart mini */}
          <div className="card">
            <div className="card-header">
              <span className="card-title">📊 Portfolio Performance</span>
              <span style={{ fontSize: '11px', color: 'var(--text-tertiary)' }}>
                Starting: {formatCurrency(account.initial_capital)}
              </span>
            </div>
            <div className="card-body" style={{ padding: '24px' }}>
              <div style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                marginBottom: '16px',
              }}>
                <div>
                  <div style={{
                    fontSize: '32px',
                    fontWeight: 600,
                    fontFamily: 'var(--font-mono)',
                    color: totalPL >= 0 ? 'var(--profit)' : 'var(--loss)',
                    letterSpacing: '-1px',
                  }}>
                    {formatCurrency(account.equity)}
                  </div>
                  <div style={{
                    fontSize: '13px',
                    color: totalPL >= 0 ? 'var(--profit)' : 'var(--loss)',
                    fontWeight: 600,
                    marginTop: '4px',
                  }}>
                    {totalPL >= 0 ? '▲' : '▼'} {formatCurrency(Math.abs(totalPL))} ({formatPercent(totalPLPct)}) today
                  </div>
                </div>
                <svg width="120" height="32" viewBox="0 0 120 32">
                  <defs>
                    <linearGradient id="sparkGrad" x1="0%" y1="0%" x2="0%" y2="100%">
                      <stop offset="0%" stopColor={totalPL >= 0 ? 'var(--profit)' : 'var(--loss)'} stopOpacity="0.3" />
                      <stop offset="100%" stopColor={totalPL >= 0 ? 'var(--profit)' : 'var(--loss)'} stopOpacity="0" />
                    </linearGradient>
                  </defs>
                  <path
                    d={sparklinePath + ` L 120 32 L 0 32 Z`}
                    fill="url(#sparkGrad)"
                  />
                  <path
                    d={sparklinePath}
                    fill="none"
                    stroke={totalPL >= 0 ? 'var(--profit)' : 'var(--loss)'}
                    strokeWidth="2"
                    strokeLinejoin="round"
                  />
                </svg>
              </div>

              <div style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(3, 1fr)',
                gap: '16px',
                padding: '16px',
                background: 'var(--bg-secondary)',
                borderRadius: 'var(--radius-md)',
              }}>
                <div>
                  <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '1px' }}>
                    Initial Capital
                  </div>
                  <div style={{ fontSize: '16px', fontWeight: 700, fontFamily: 'var(--font-mono)', marginTop: '4px' }}>
                    {formatCurrency(account.initial_capital)}
                  </div>
                </div>
                <div>
                  <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '1px' }}>
                    Total P&L
                  </div>
                  <div style={{
                    fontSize: '16px',
                    fontWeight: 700,
                    fontFamily: 'var(--font-mono)',
                    marginTop: '4px',
                    color: totalPL >= 0 ? 'var(--profit)' : 'var(--loss)',
                  }}>
                    {totalPL >= 0 ? '+' : ''}{formatCurrency(totalPL)}
                  </div>
                </div>
                <div>
                  <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '1px' }}>
                    Day Trades
                  </div>
                  <div style={{ fontSize: '16px', fontWeight: 700, fontFamily: 'var(--font-mono)', marginTop: '4px' }}>
                    {account.day_trade_count}/3
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Positions */}
          <div className="card">
            <div className="card-header">
              <span className="card-title">💼 Open Positions</span>
              <button
                className="btn btn-secondary btn-sm"
                onClick={() => setCurrentPage('portfolio')}
              >
                View All
              </button>
            </div>
            <div>
              {positions.length === 0 ? (
                <div className="empty-state" style={{ padding: '32px' }}>
                  {botActive ? (
                    <>
                      <div style={{ fontSize: '32px', marginBottom: '8px' }}>🤖</div>
                      <div style={{ fontWeight: 700, color: 'var(--profit)', marginBottom: '6px', fontSize: '16px' }}>
                        Bot is Running
                      </div>
                      <div style={{ fontSize: '13px', color: 'var(--text-tertiary)' }}>
                        Scanning for entry signals… Positions will appear here when opened.
                      </div>
                    </>
                  ) : (
                    <>
                      <div className="empty-state-icon">📭</div>
                      <div className="empty-state-title">No Open Positions</div>
                      <div className="empty-state-text">
                        Start the trading bot or manually place a trade to open positions.
                      </div>
                      <button
                        className="btn btn-primary"
                        style={{ marginTop: '12px' }}
                        onClick={() => setCurrentPage('trading')}
                      >
                        ⚡ Start Trading Bot
                      </button>
                    </>
                  )}
                </div>
              ) : (
                <table className="positions-table">
                  <thead>
                    <tr>
                      <th>Symbol</th>
                      <th>Qty</th>
                      <th>Avg Entry</th>
                      <th>Current</th>
                      <th>P&L</th>
                    </tr>
                  </thead>
                  <tbody>
                    {positions.map((pos) => (
                      <tr key={pos.symbol}>
                        <td className="symbol">{pos.symbol}</td>
                        <td className="mono">{pos.qty}</td>
                        <td className="mono">{formatCurrency(pos.avg_entry_price)}</td>
                        <td className="mono">{formatCurrency(pos.current_price)}</td>
                        <td className={`mono ${getChangeClass(pos.unrealized_pl)}`} style={{
                          color: pos.unrealized_pl >= 0 ? 'var(--profit)' : 'var(--loss)',
                        }}>
                          {pos.unrealized_pl >= 0 ? '+' : ''}{formatCurrency(pos.unrealized_pl)}
                          <span style={{ fontSize: '10px', marginLeft: '4px' }}>
                            ({formatPercent(pos.unrealized_plpc * 100)})
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>

          </div>

          {/* Bot Activity Log */}
          <div className="card">
            <div className="card-header">
              <span className="card-title">⚡ Trading Bot Activity</span>
              <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                <span style={{
                  fontSize: '11px',
                  fontWeight: 600,
                  color: botActive ? 'var(--profit)' : 'var(--text-tertiary)',
                }}>
                  {botActive ? '● Running' : '○ Stopped'}
                </span>
                <button
                  className={`btn btn-sm ${botActive ? 'btn-danger' : 'btn-primary'}`}
                  onClick={async () => {
                    if (botActive) {
                      await api.stopBot();
                      setBotActive(false);
                    } else {
                      await api.startBot('momentum');
                      setBotActive(true);
                    }
                  }}
                >
                  {botActive ? 'Stop' : 'Start'}
                </button>
              </div>
            </div>
            <div className="bot-log">
              {tradeLogs.slice(-8).map((log, i) => (
                <div key={i} className="bot-log-entry">
                  <span className="bot-log-time">{log.time}</span>
                  <span className={`bot-log-type ${log.type}`}>{log.type}</span>
                  <span className="bot-log-message">{log.message}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Right Column - Watchlist */}
        <div className="dashboard-right">
          <div className="card" style={{ flex: 1 }}>
            <div className="card-header">
              <span className="card-title">👁️ Watchlist</span>
              <button className="btn btn-secondary btn-sm" onClick={() => setCurrentPage('chart')}>
                Full Chart
              </button>
            </div>
            <div className="watchlist">
              {watchlist.map((item) => (
                <div
                  key={item.symbol}
                  className="watchlist-item"
                  onClick={() => {
                    setSelectedSymbol(item.symbol);
                    setCurrentPage('chart');
                  }}
                >
                  <div className="watchlist-item-left">
                    <div>
                      <div className="watchlist-symbol">{item.symbol}</div>
                      <div className="watchlist-name">{item.name}</div>
                    </div>
                  </div>
                  <div className="watchlist-item-right">
                    <div className="watchlist-price">{formatCurrency(item.price)}</div>
                    <div className={`watchlist-change ${getChangeClass(item.change)}`}>
                      {item.change >= 0 ? '+' : ''}{item.change.toFixed(2)} ({formatPercent(item.changePercent)})
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Active Strategies */}
          <div className="card">
            <div className="card-header">
              <span className="card-title">🎯 Active Strategies</span>
              <button className="btn btn-secondary btn-sm" onClick={() => setCurrentPage('trading')}>
                Manage
              </button>
            </div>
            <div style={{ padding: 'var(--space-lg)' }}>
              {strategies.map((strat) => (
                <div key={strat.id} style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  padding: '10px 0',
                  borderBottom: '1px solid var(--border-secondary)',
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <span style={{
                      width: 8,
                      height: 8,
                      borderRadius: '50%',
                      background: strat.active ? 'var(--profit)' : 'var(--text-muted)',
                      display: 'inline-block',
                    }} />
                    <span style={{ fontSize: '13px', fontWeight: 600 }}>
                      {strat.name}
                    </span>
                  </div>
                  <span style={{
                    fontSize: '12px',
                    fontFamily: 'var(--font-mono)',
                    color: 'var(--text-tertiary)',
                  }}>
                    WR: {strat.winRate}%
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default Dashboard;
