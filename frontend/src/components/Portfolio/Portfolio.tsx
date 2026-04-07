import React from 'react';
import { useAppStore } from '../../stores/useAppStore';
import { formatCurrency, formatPercent, getChangeClass } from '../../utils/helpers';

const Portfolio: React.FC = () => {
  const { account, positions } = useAppStore();

  const totalPL = account.equity - account.initial_capital;
  const totalPLPct = ((account.equity - account.initial_capital) / account.initial_capital) * 100;

  return (
    <div className="page-enter">
      {/* Portfolio Stats */}
      <div className="stats-grid">
        <div className={`stat-card ${totalPL >= 0 ? 'profit' : 'loss'}`}>
          <div className="stat-label">Total Equity</div>
          <div className={`stat-value ${getChangeClass(totalPL)}`}>
            {formatCurrency(account.equity)}
          </div>
          <div className={`stat-change ${getChangeClass(totalPL)}`}>
            {formatPercent(totalPLPct)}
          </div>
        </div>

        <div className="stat-card accent">
          <div className="stat-label">Cash</div>
          <div className="stat-value" style={{ color: 'var(--text-primary)' }}>
            {formatCurrency(account.cash)}
          </div>
        </div>

        <div className="stat-card accent">
          <div className="stat-label">Buying Power</div>
          <div className="stat-value" style={{ color: 'var(--accent-secondary)' }}>
            {formatCurrency(account.buying_power)}
          </div>
        </div>

        <div className="stat-card accent">
          <div className="stat-label">Day Trades Used</div>
          <div className="stat-value" style={{ color: 'var(--accent-gold)' }}>
            {account.day_trade_count}/3
          </div>
          <div style={{ fontSize: '11px', color: 'var(--text-tertiary)', marginTop: '6px' }}>
            PDT Rule (5-day rolling)
          </div>
        </div>
      </div>

      {/* Holdings */}
      <div className="card" style={{ marginBottom: 'var(--space-xl)' }}>
        <div className="card-header">
          <span className="card-title">💼 Holdings</span>
          <span style={{ fontSize: '12px', color: 'var(--text-tertiary)' }}>
            {positions.length} position{positions.length !== 1 ? 's' : ''}
          </span>
        </div>
        <div>
          {positions.length === 0 ? (
            <div className="empty-state">
              <div className="empty-state-icon">📭</div>
              <div className="empty-state-title">No Holdings</div>
              <div className="empty-state-text">
                Your portfolio is all cash. Start the trading bot to begin automated trading with $1,000 paper money.
              </div>
            </div>
          ) : (
            <table className="positions-table">
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Side</th>
                  <th>Qty</th>
                  <th>Avg Entry</th>
                  <th>Current Price</th>
                  <th>Market Value</th>
                  <th>Unrealized P&L</th>
                  <th>% Change</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((pos) => (
                  <tr key={pos.symbol}>
                    <td className="symbol">{pos.symbol}</td>
                    <td>
                      <span style={{
                        padding: '2px 8px',
                        borderRadius: 'var(--radius-full)',
                        fontSize: '10px',
                        fontWeight: 600,
                        textTransform: 'uppercase',
                        background: pos.side === 'long' ? 'var(--profit-dim)' : 'var(--loss-dim)',
                        color: pos.side === 'long' ? 'var(--profit)' : 'var(--loss)',
                      }}>
                        {pos.side}
                      </span>
                    </td>
                    <td className="mono">{pos.qty}</td>
                    <td className="mono">{formatCurrency(pos.avg_entry_price)}</td>
                    <td className="mono">{formatCurrency(pos.current_price)}</td>
                    <td className="mono">{formatCurrency(pos.market_value)}</td>
                    <td className="mono" style={{
                      color: pos.unrealized_pl >= 0 ? 'var(--profit)' : 'var(--loss)',
                      fontWeight: 600,
                    }}>
                      {pos.unrealized_pl >= 0 ? '+' : ''}{formatCurrency(pos.unrealized_pl)}
                    </td>
                    <td className="mono" style={{
                      color: pos.unrealized_plpc >= 0 ? 'var(--profit)' : 'var(--loss)',
                      fontWeight: 600,
                    }}>
                      {formatPercent(pos.unrealized_plpc * 100)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* Allocation Chart (simple) */}
      <div className="dashboard-grid">
        <div className="card">
          <div className="card-header">
            <span className="card-title">📊 Asset Allocation</span>
          </div>
          <div className="card-body">
            <div style={{
              display: 'flex',
              alignItems: 'center',
              gap: '24px',
            }}>
              {/* Simple allocation bar */}
              <div style={{ flex: 1 }}>
                <div style={{
                  height: '32px',
                  borderRadius: 'var(--radius-md)',
                  overflow: 'hidden',
                  display: 'flex',
                  background: 'var(--bg-secondary)',
                }}>
                  {positions.length > 0 ? (
                    <>
                      {positions.map((pos, i) => {
                        const pct = (pos.market_value / account.equity) * 100;
                        const colors = ['#10b981', '#6366f1', '#f59e0b', '#ef4444', '#8b5cf6'];
                        return (
                          <div
                            key={pos.symbol}
                            style={{
                              width: `${pct}%`,
                              background: colors[i % colors.length],
                              display: 'flex',
                              alignItems: 'center',
                              justifyContent: 'center',
                              fontSize: '10px',
                              fontWeight: 700,
                              color: 'white',
                            }}
                          >
                            {pct > 8 ? pos.symbol : ''}
                          </div>
                        );
                      })}
                      <div style={{
                        flex: 1,
                        background: 'var(--bg-tertiary)',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        fontSize: '10px',
                        fontWeight: 600,
                        color: 'var(--text-tertiary)',
                      }}>
                        CASH
                      </div>
                    </>
                  ) : (
                    <div style={{
                      width: '100%',
                      background: 'var(--accent-primary-dim)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      fontSize: '11px',
                      fontWeight: 600,
                      color: 'var(--accent-primary)',
                    }}>
                      100% CASH — {formatCurrency(account.cash)}
                    </div>
                  )}
                </div>

                {/* Legend */}
                <div style={{
                  display: 'flex',
                  gap: '16px',
                  marginTop: '12px',
                  flexWrap: 'wrap',
                }}>
                  {positions.map((pos, i) => {
                    const colors = ['#10b981', '#6366f1', '#f59e0b', '#ef4444', '#8b5cf6'];
                    const pct = (pos.market_value / account.equity) * 100;
                    return (
                      <div key={pos.symbol} style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '6px',
                        fontSize: '11px',
                      }}>
                        <span style={{
                          width: 8,
                          height: 8,
                          borderRadius: '50%',
                          background: colors[i % colors.length],
                        }} />
                        <span style={{ fontWeight: 600 }}>{pos.symbol}</span>
                        <span style={{ color: 'var(--text-tertiary)' }}>{pct.toFixed(1)}%</span>
                      </div>
                    );
                  })}
                  <div style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px',
                    fontSize: '11px',
                  }}>
                    <span style={{
                      width: 8,
                      height: 8,
                      borderRadius: '50%',
                      background: 'var(--bg-tertiary)',
                      border: '1px solid var(--border-primary)',
                    }} />
                    <span style={{ fontWeight: 600 }}>Cash</span>
                    <span style={{ color: 'var(--text-tertiary)' }}>
                      {((account.cash / account.equity) * 100).toFixed(1)}%
                    </span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div className="card">
          <div className="card-header">
            <span className="card-title">🎯 Performance Metrics</span>
          </div>
          <div style={{ padding: 'var(--space-xl)' }}>
            {[
              { label: 'Total Return', value: formatPercent(totalPLPct), color: getChangeClass(totalPL) },
              { label: 'Total P&L', value: `${totalPL >= 0 ? '+' : ''}${formatCurrency(totalPL)}`, color: getChangeClass(totalPL) },
              { label: 'Initial Capital', value: formatCurrency(account.initial_capital), color: '' },
              { label: 'Win Rate', value: 'N/A', color: '' },
              { label: 'Avg Win', value: 'N/A', color: '' },
              { label: 'Avg Loss', value: 'N/A', color: '' },
              { label: 'Profit Factor', value: 'N/A', color: '' },
              { label: 'Sharpe Ratio', value: 'N/A', color: '' },
            ].map((item, i) => (
              <div key={i} style={{
                display: 'flex',
                justifyContent: 'space-between',
                padding: '8px 0',
                borderBottom: i < 7 ? '1px solid var(--border-secondary)' : 'none',
              }}>
                <span style={{ fontSize: '12px', color: 'var(--text-tertiary)' }}>{item.label}</span>
                <span style={{
                  fontSize: '13px',
                  fontWeight: 600,
                  fontFamily: 'var(--font-mono)',
                  color: item.color === 'profit' ? 'var(--profit)' : item.color === 'loss' ? 'var(--loss)' : 'var(--text-primary)',
                }}>
                  {item.value}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};

export default Portfolio;
