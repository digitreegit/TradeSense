import React from 'react';
import { useAppStore } from '../../stores/useAppStore';
import { formatCurrency, formatPercent, getChangeClass } from '../../utils/helpers';
import { useI18n } from '../../i18n';
import { PortfolioIcon } from '../icons/PortfolioIcon';

// Heroicons v2 Outline SVGs
const ChartPieIcon = (props: React.ComponentProps<'svg'>) => (
  <svg {...props} fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
    <path strokeLinecap="round" strokeLinejoin="round" d="M10.5 6a7.5 7.5 0 1 0 7.5 7.5h-7.5V6Z" />
    <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 10.5H21A7.5 7.5 0 0 0 13.5 3v7.5Z" />
  </svg>
);

const CheckBadgeIcon = (props: React.ComponentProps<'svg'>) => (
  <svg {...props} fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
    <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75 11.25 15 15 9.75M21 12c0 1.268-.63 2.39-1.593 3.068a3.745 3.745 0 0 1-1.043 3.296 3.745 3.745 0 0 1-3.296 1.043A3.745 3.745 0 0 1 12 21c-1.268 0-2.39-.63-3.068-1.593a3.746 3.746 0 0 1-3.296-1.043 3.745 3.745 0 0 1-1.043-3.296A3.745 3.745 0 0 1 3 12c0-1.268.63-2.39 1.593-3.068a3.745 3.745 0 0 1 1.043-3.296 3.746 3.746 0 0 1 3.296-1.043A3.746 3.746 0 0 1 12 3c1.268 0 2.39.63 3.068 1.593a3.746 3.746 0 0 1 3.296 1.043 3.746 3.746 0 0 1 1.043 3.296A3.745 3.745 0 0 1 21 12Z" />
  </svg>
);

const ArchiveBoxIcon = (props: React.ComponentProps<'svg'>) => (
  <svg {...props} fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
    <path strokeLinecap="round" strokeLinejoin="round" d="M20.25 7.5l-.625 10.632a2.25 2.25 0 0 1-2.247 2.118H6.622a2.25 2.25 0 0 1-2.247-2.118L3.75 7.5m6 4.125l2.25 2.25m0 0l2.25-2.25M12 13.875V8.25M3.375 7.5h17.25c.621 0 1.125-.504 1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125H3.375c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125z" />
  </svg>
);

const Portfolio: React.FC = () => {
  const { account, positions } = useAppStore();
  const { t } = useI18n();

  const totalPL = account.equity - account.initial_capital;
  const totalPLPct = ((account.equity - account.initial_capital) / account.initial_capital) * 100;

  return (
    <div className="page-enter">
      {/* Portfolio Stats */}
      <div className="stats-grid">
        <div className={`stat-card ${totalPL >= 0 ? 'profit' : 'loss'}`}>
          <div className="stat-label">{t('totalEquity')}</div>
          <div className={`stat-value ${getChangeClass(totalPL)}`}>
            {formatCurrency(account.equity)}
          </div>
          <div className={`stat-change ${getChangeClass(totalPL)}`}>
            {formatPercent(totalPLPct)}
          </div>
        </div>

        <div className="stat-card accent">
          <div className="stat-label">{t('cash')}</div>
          <div className="stat-value" style={{ color: 'var(--text-primary)' }}>
            {formatCurrency(account.cash)}
          </div>
        </div>

        <div className="stat-card accent">
          <div className="stat-label">{t('buyingPower')}</div>
          <div className="stat-value" style={{ color: 'var(--accent-secondary)' }}>
            {formatCurrency(account.buying_power)}
          </div>
        </div>

        <div className={`stat-card ${account.daily_profit_loss >= 0 ? 'profit' : 'loss'}`}>
          <div className="stat-label">{t('dailyPL')}</div>
          <div className={`stat-value ${getChangeClass(account.daily_profit_loss)}`}>
            {account.daily_profit_loss >= 0 ? '+' : ''}{formatCurrency(account.daily_profit_loss)}
          </div>
          <div className={`stat-change ${getChangeClass(account.daily_profit_loss)}`}>
            {formatPercent(account.daily_profit_loss_pct)}
          </div>
        </div>
      </div>

      {/* Holdings */}
      <div className="card" style={{ marginBottom: 'var(--space-xl)' }}>
        <div className="card-header">
          <span className="card-title">
              <PortfolioIcon className="card-icon" /> {t('holdings')}
          </span>
          <span style={{ fontSize: '12px', color: 'var(--text-tertiary)' }}>
            {positions.length} position{positions.length !== 1 ? 's' : ''}
          </span>
        </div>
        <div>
          {positions.length === 0 ? (
            <div className="empty-state">
              <div className="empty-state-icon">
                <ArchiveBoxIcon style={{ width: '48px', height: '48px', color: 'var(--text-tertiary)' }} />
              </div>
              <div className="empty-state-title">{t('noHoldings')}</div>
              <div className="empty-state-text">
                {t('noHoldingsText')}
              </div>
            </div>
          ) : (
            <table className="positions-table">
              <thead>
                <tr>
                  <th>{t('symbol')}</th>
                  <th>{t('side')}</th>
                  <th>{t('qty')}</th>
                  <th>{t('avgEntry')}</th>
                  <th>{t('currentPrice')}</th>
                  <th>{t('marketValue')}</th>
                  <th>{t('unrealizedPL')}</th>
                  <th>{t('percentChange')}</th>
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
                        fontSize: '12px',
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
            <span className="card-title">
              <ChartPieIcon className="card-icon" /> {t('assetAllocation')}
            </span>
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
                              fontSize: '12px',
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
                        fontSize: '12px',
                        fontWeight: 600,
                        color: 'var(--text-tertiary)',
                      }}>
                        {t('cash').toUpperCase()}
                      </div>
                    </>
                  ) : (
                    <div style={{
                      width: '100%',
                      background: 'var(--accent-primary-dim)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      fontSize: '12px',
                      fontWeight: 600,
                      color: 'var(--accent-primary)',
                    }}>
                      100% {t('cash').toUpperCase()} — {formatCurrency(account.cash)}
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
                        fontSize: '12px',
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
                    fontSize: '12px',
                  }}>
                    <span style={{
                      width: 8,
                      height: 8,
                      borderRadius: '50%',
                      background: 'var(--bg-tertiary)',
                      border: '1px solid var(--border-primary)',
                    }} />
                    <span style={{ fontWeight: 600 }}>{t('cash')}</span>
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
            <span className="card-title">
              <CheckBadgeIcon className="card-icon" /> {t('performanceMetrics')}
            </span>
          </div>
          <div style={{ padding: 'var(--space-xl)' }}>
            {[
              { label: t('totalReturn'), value: formatPercent(totalPLPct), color: getChangeClass(totalPL) },
              { label: t('totalPL'), value: `${totalPL >= 0 ? '+' : ''}${formatCurrency(totalPL)}`, color: getChangeClass(totalPL) },
              { label: t('initialCapital'), value: formatCurrency(account.initial_capital), color: '' },
              { label: t('winRate'), value: account.win_rate !== undefined ? `${account.win_rate}%` : '0%', color: '' },
              { label: t('avgWin'), value: formatCurrency(account.avg_win || 0), color: '' },
              { label: t('avgLoss'), value: formatCurrency(account.avg_loss || 0), color: '' },
              { label: t('profitFactor'), value: (account.profit_factor || 0).toFixed(2), color: '' },
              { label: t('sharpeRatio'), value: (account.sharpe_ratio || 0).toFixed(2), color: '' },
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
