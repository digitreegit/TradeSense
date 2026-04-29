import React, { useMemo } from 'react';
import { useAppStore } from '../../stores/useAppStore';
import { formatCurrency, formatPercent, getChangeClass } from '../../utils/helpers';
import api from '../../services/api';
import { useUiStrings } from '../../hooks/useUiStrings';

// Heroicons v2 Outline SVGs
const ChartBarIcon = (props: React.ComponentProps<'svg'>) => (
  <svg {...props} fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
    <path strokeLinecap="round" strokeLinejoin="round" d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 0 1 3 19.875v-6.75ZM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 0 1-1.125-1.125V8.625ZM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 0 1-1.125-1.125V4.125Z" />
  </svg>
);

const EyeIcon = (props: React.ComponentProps<'svg'>) => (
  <svg {...props} fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
    <path strokeLinecap="round" strokeLinejoin="round" d="M2.036 12.322a1.012 1.012 0 0 1 0-.639C3.423 7.51 7.36 4.5 12 4.5c4.638 0 8.573 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.638 0-8.573-3.007-9.963-7.178Z" />
    <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" />
  </svg>
);

const BriefcaseIcon = (props: React.ComponentProps<'svg'>) => (
  <svg {...props} fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
    <path strokeLinecap="round" strokeLinejoin="round" d="M20.25 14.15v4.25c0 .621-.504 1.125-1.125 1.125H4.875A1.125 1.125 0 0 1 3.75 18.4V14.15m16.5 0a5.122 5.122 0 0 0-4.75-4.65M16.5 14.15m16.5 0a1.125 1.125 0 0 1-1.125 1.125H4.875a1.125 1.125 0 0 1-1.125-1.125m16.5 0h-16.5" />
  </svg>
);

const BoltIcon = (props: React.ComponentProps<'svg'>) => (
  <svg {...props} fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
    <path strokeLinecap="round" strokeLinejoin="round" d="m3.75 13.5 10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75Z" />
  </svg>
);

const CheckBadgeIcon = (props: React.ComponentProps<'svg'>) => (
  <svg {...props} fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
    <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75 11.25 15 15 9.75M21 12c0 1.268-.63 2.39-1.593 3.068a3.745 3.745 0 0 1-1.043 3.296 3.745 3.745 0 0 1-3.296 1.043A3.745 3.745 0 0 1 12 21c-1.268 0-2.39-.63-3.068-1.593a3.746 3.746 0 0 1-3.296-1.043 3.745 3.745 0 0 1-1.043-3.296A3.745 3.745 0 0 1 3 12c0-1.268.63-2.39 1.593-3.068a3.745 3.745 0 0 1 1.043-3.296 3.746 3.746 0 0 1 3.296-1.043A3.746 3.746 0 0 1 12 3c1.268 0 2.39.63 3.068 1.593a3.746 3.746 0 0 1 3.296 1.043 3.746 3.746 0 0 1 1.043 3.296A3.745 3.745 0 0 1 21 12Z" />
  </svg>
);

const XMarkIcon = (props: React.ComponentProps<'svg'>) => (
  <svg {...props} fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
    <path strokeLinecap="round" strokeLinejoin="round" d="M6 18 18 6M6 6l12 12" />
  </svg>
);

const Dashboard: React.FC = () => {
  const t = useUiStrings();
  const d = t.dashboard;
  const c = t.common;
  const tr = t.trading;
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
    regimeData,
    dismissedRegimeTimestamp,
    setDismissedRegimeTimestamp,
    compliance,
    playbookAuto,
    activePlaybooks,
    manualPlaybooks,
    botDailyTrades,
    colorTheme,
    appLocale,
  } = useAppStore();

  const playbookName = (id: string, fallback: string) => {
    if (appLocale !== 'ko') return fallback;
    const loc = tr.playbookById[id as keyof typeof tr.playbookById];
    return loc?.name ?? fallback;
  };

  const regimeDivider =
    colorTheme === 'light' ? '1px solid rgba(15, 23, 42, 0.16)' : '1px solid rgba(255, 255, 255, 0.12)';

  const strategyBanner = useMemo(() => {
    const mode = playbookAuto ? 'AUTO' : 'MANUAL';
    const ids = playbookAuto
      ? (activePlaybooks.length ? activePlaybooks : [])
      : manualPlaybooks;
    const upper = ids.map((s) => s.toUpperCase());
    return `${mode} · ${upper.join(' + ') || '—'}`;
  }, [playbookAuto, activePlaybooks, manualPlaybooks]);

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
      {/* Market Regime Notification */}
      {regimeData &&
        regimeData.timestamp &&
        (dismissedRegimeTimestamp !== regimeData.timestamp) && (
          <div className="card regime-notification" style={{
            background: 'rgba(59, 130, 246, 0.05)',
            border: '1px solid rgba(59, 130, 246, 0.18)',
            color: 'var(--text-primary)',
            marginBottom: '24px',
            padding: '20px',
            borderRadius: 'var(--radius-lg)',
            position: 'relative',
            overflow: 'hidden',
            display: 'flex',
            flexDirection: 'column',
            gap: '12px'
          }}>
            <button
              onClick={() => setDismissedRegimeTimestamp(regimeData.timestamp || null)}
              style={{
                position: 'absolute',
                top: '12px',
                right: '12px',
                background: 'none',
                border: 'none',
                color: 'var(--text-tertiary)',
                cursor: 'pointer',
                padding: '4px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                borderRadius: 'var(--btn-radius-sm)',
                transition: 'all 0.2s'
              }}
              onMouseOver={(e) => e.currentTarget.style.background = 'rgba(255,255,255,0.05)'}
              onMouseOut={(e) => e.currentTarget.style.background = 'none'}
            >
              <XMarkIcon style={{ width: 18, height: 18 }} />
            </button>

            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', color: 'var(--accent-primary)' }}>
              <BoltIcon style={{ width: 20, height: 20 }} />
              <h3 style={{ margin: 0, fontSize: '16px', fontWeight: 700 }}>{d.regimeTitle}</h3>
              <span
                style={{
                  fontSize: '12px',
                  marginLeft: 'auto',
                  marginRight: '32px',
                  color: 'var(--text-tertiary)',
                }}
              >
                {d.lastUpdated} {regimeData.timestamp}
              </span>
            </div>

            <p style={{ margin: 0, fontSize: '14px', lineHeight: 1.5, color: 'var(--text-secondary)' }}>
              <strong>{d.reasoning}</strong> {regimeData.reasoning}
            </p>

            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '20px', fontSize: '13px', marginTop: '4px' }}>
              <div style={{ background: 'var(--bg-secondary)', padding: '8px 12px', borderRadius: 'var(--radius-sm)' }}>
                <span style={{ color: 'var(--text-tertiary)', marginRight: '8px' }}>{d.strategy}</span>
                <strong style={{ color: 'var(--accent-primary)' }}>
                  {regimeData.playbook_mode && regimeData.active_playbooks?.length
                    ? `${regimeData.playbook_mode.toUpperCase()} · ${regimeData.active_playbooks
                        .map((s) => s.toUpperCase())
                        .join(' + ')}`
                    : strategyBanner}
                </strong>
              </div>

               <div style={{ background: 'var(--bg-secondary)', padding: '8px 12px', borderRadius: 'var(--radius-sm)' }}>
                <span style={{ color: 'var(--text-tertiary)', marginRight: '8px' }}>{d.marketStatus}</span>
                <strong style={{ 
                  color: (regimeData.market_level?.toUpperCase() === 'EXCELLENT' || regimeData.risk_level?.toUpperCase() === 'LOW') ? 'var(--profit)' : 
                         (regimeData.market_level?.toUpperCase() === 'GOOD') ? '#34d399' :
                         (regimeData.market_level?.toUpperCase() === 'NORMAL' || regimeData.risk_level?.toUpperCase() === 'MODERATE') ? '#ca8a04' :
                         (regimeData.market_level?.toUpperCase() === 'BAD') ? '#f97316' : 
                         (regimeData.market_level?.toUpperCase() === 'DANGEROUS' || regimeData.risk_level?.toUpperCase() === 'AGGRESSIVE') ? 'var(--loss)' : '#ffffff',
                  padding: '2px 8px',
                  borderRadius: '4px',
                  background: 'rgba(255,255,255,0.05)',
                  fontSize: '14px'
                }}>
                  {(regimeData.market_level || 'NORMAL').toUpperCase()} ({(regimeData.market_score || 50)})
                </strong>
              </div>

              <div style={{ background: 'var(--bg-secondary)', padding: '8px 12px', borderRadius: 'var(--radius-sm)' }}>
                <span style={{ color: 'var(--text-tertiary)', marginRight: '8px' }}>{d.riskSetting}</span>
                <strong style={{ 
                  color: regimeData.risk_level === 'aggressive' ? 'var(--loss)' : 
                         regimeData.risk_level === 'moderate' ? '#ca8a04' : 'var(--profit)' 
                }}>
                  {regimeData.risk_level?.toUpperCase() || 'MODERATE'}
                </strong>
              </div>

              <div style={{ background: 'var(--bg-secondary)', padding: '8px 12px', borderRadius: 'var(--radius-sm)' }}>
                <span style={{ color: 'var(--text-tertiary)', marginRight: '8px' }}>{d.stopLoss}</span>
                <strong style={{ color: 'var(--loss)' }}>{regimeData.stop_loss_percent}%</strong>
              </div>

              {(regimeData as any).daily_pnl && (
                <div style={{ background: 'var(--bg-secondary)', padding: '8px 12px', borderRadius: 'var(--radius-sm)' }}>
                  <span style={{ color: 'var(--text-tertiary)', marginRight: '8px' }}>{d.dailyPnL}</span>
                  <strong style={{ color: String((regimeData as any).daily_pnl).includes('-') ? 'var(--loss)' : 'var(--profit)' }}>
                    {(regimeData as any).daily_pnl}
                  </strong>
                </div>
              )}
            </div>
 
            {/* 6 Core Indicators Grid (Market Adaptive) */}
            {(regimeData as any).market_scores && (
              <div style={{ 
                display: 'grid', 
                gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', 
                gap: '8px', 
                marginTop: '4px',
                paddingTop: '6px',
                borderTop: regimeDivider,
              }}>
                {Object.entries((regimeData as any).market_scores).map(([key, val]) => {
                  const score = Number(val);
                  return (
                  <div key={key} style={{ 
                    fontSize: '11px', 
                    display: 'flex', 
                    justifyContent: 'space-between',
                    padding: '6px 10px',
                    background: 'rgba(255,255,255,0.03)',
                    borderRadius: 'var(--radius-sm)',
                    border: '1px solid rgba(255,255,255,0.05)'
                  }}>
                    <span style={{ color: 'var(--text-tertiary)', textTransform: 'capitalize' }}>
                      {key === 'fed' ? d.fedPolicy : key === 'war' ? d.geopolitical : key}
                    </span>
                    <strong style={{ 
                      color: score >= 70 ? 'var(--profit)' : score >= 40 ? 'var(--warning)' : 'var(--loss)'
                    }}>{score}</strong>
                  </div>
                  );
                })}
              </div>
            )}

            {/* Focus Sectors & Symbols */}
            {(regimeData as any).focus_symbols && (
              <div
                style={{
                  marginTop: (regimeData as any).market_scores ? '4px' : '6px',
                }}
              >
                <div style={{ fontSize: '12px', color: 'var(--text-tertiary)', marginBottom: '10px' }}>
                  {d.focusSectors} <strong style={{ color: 'var(--text-secondary)' }}>{((regimeData as any).focus_sectors || []).join(', ')}</strong>
                </div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                  {((regimeData as any).focus_symbols || []).map((sym: string) => (
                    <span key={sym} style={{
                      padding: '3px 10px',
                      background: 'rgba(59, 130, 246, 0.15)',
                      border: '1px solid rgba(59, 130, 246, 0.3)',
                      borderRadius: 'var(--radius-full)',
                      fontSize: '12px',
                      fontWeight: 600,
                      fontFamily: 'var(--font-mono)',
                      color: 'var(--accent-primary)',
                    }}>{sym}</span>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

      {/* Compliance / Blackout banner */}
      {(compliance || regimeData?.blackout) && (
        <div style={{
          display: 'flex',
          flexWrap: 'wrap',
          gap: '8px',
          marginBottom: '16px',
          fontSize: '12px',
        }}>
          {regimeData?.blackout && (
            <span style={{
              padding: '4px 10px',
              borderRadius: 'var(--radius-full)',
              background: 'rgba(249, 115, 22, 0.15)',
              border: '1px solid rgba(249, 115, 22, 0.4)',
              color: '#f97316',
              fontWeight: 600,
            }}>
              {d.entryBlackout(regimeData.blackout_reason || '')}
            </span>
          )}
          {compliance && compliance.gfv_level !== 'OK' && (
            <span style={{
              padding: '4px 10px',
              borderRadius: 'var(--radius-full)',
              background: 'rgba(239, 68, 68, 0.15)',
              border: '1px solid rgba(239, 68, 68, 0.4)',
              color: 'var(--loss)',
              fontWeight: 600,
            }}>
              {d.gfv(String(compliance.gfv_level), String(compliance.gfv_count_12mo))}
            </span>
          )}
          {compliance && compliance.cooling_down && (
            <span style={{
              padding: '4px 10px',
              borderRadius: 'var(--radius-full)',
              background: 'rgba(250, 204, 21, 0.15)',
              border: '1px solid rgba(250, 204, 21, 0.4)',
              color: '#facc15',
              fontWeight: 600,
            }}>
              {d.cooldown(compliance.cooldown_remaining_s, compliance.loss_streak)}
            </span>
          )}
          {compliance && compliance.unsettled_cash > 0 && (
            <span style={{
              padding: '4px 10px',
              borderRadius: 'var(--radius-full)',
              background: 'rgba(59, 130, 246, 0.12)',
              border: '1px solid rgba(59, 130, 246, 0.3)',
              color: 'var(--accent-primary)',
              fontFamily: 'var(--font-mono)',
            }}>
              {d.unsettled(compliance.unsettled_cash.toFixed(2))}
            </span>
          )}
        </div>
      )}

      {/* Stats Grid */}
      <div className="stats-grid">
        <div className={`stat-card ${totalPL >= 0 ? 'profit' : 'loss'}`}>
          <div className="stat-label">{d.portfolioValue}</div>
          <div className={`stat-value ${getChangeClass(totalPL)}`}>
            {formatCurrency(account.equity)}
          </div>
          <div className={`stat-change ${getChangeClass(totalPL)}`}>
            {totalPL >= 0 ? '▲' : '▼'} {formatCurrency(Math.abs(totalPL))} ({formatPercent(totalPLPct)})
          </div>
        </div>

        <div className="stat-card accent">
          <div className="stat-label">{d.cashAvailable}</div>
          <div className="stat-value" style={{ color: 'var(--text-primary)' }}>
            {formatCurrency(account.cash)}
          </div>
          <div style={{ fontSize: '12px', color: 'var(--text-tertiary)', marginTop: '6px' }}>
            {d.buyingPower}: {formatCurrency(account.buying_power)}
          </div>
        </div>

        <div className="stat-card accent">
          <div className="stat-label">{d.activePositions}</div>
          <div className="stat-value" style={{ color: 'var(--accent-secondary)' }}>
            {activePositionCount}
          </div>
          <div style={{ fontSize: '12px', color: 'var(--text-tertiary)', marginTop: '6px' }}>
            {d.strategiesActive(String(strategies.filter(s => s.active).length))}
          </div>
        </div>

        <div className="stat-card accent">
          <div className="stat-label">{d.botStatus}</div>
          <div className="stat-value" style={{
            color: botActive ? 'var(--profit)' : 'var(--text-tertiary)',
            fontSize: '22px',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
          }}>
            <span style={{ fontSize: '14px', lineHeight: 1 }}>{botActive ? '●' : '○'}</span>
            <span>{botActive ? d.active : d.idle}</span>
          </div>
          <div style={{ fontSize: '12px', color: 'var(--text-tertiary)', marginTop: '6px' }}>
            {d.eventsLogged(String(tradeLogs.length))} · {d.dailyScalping}{' '}
            <strong style={{ color: 'var(--accent-primary)', fontFamily: 'var(--font-mono)' }}>
              {Number.isFinite(botDailyTrades) ? botDailyTrades : 0}
            </strong>
          </div>
        </div>
      </div>

      {/* Main Grid */}
      <div className="dashboard-grid">
        <div className="dashboard-left">
          {/* Portfolio Chart mini */}
          <div className="card">
            <div className="card-header">
              <span className="card-title">
                <ChartBarIcon className="card-icon" /> {d.performanceTitle}
              </span>
              <span style={{ fontSize: '12px', color: 'var(--text-tertiary)' }}>
                {d.starting(formatCurrency(account.initial_capital))}
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
                    letterSpacing: '0',
                  }}>
                    {formatCurrency(account.equity)}
                  </div>
                  <div style={{
                    fontSize: '13px',
                    color: account.daily_profit_loss >= 0 ? 'var(--profit)' : 'var(--loss)',
                    fontWeight: 600,
                    marginTop: '4px',
                  }}>
                    {account.daily_profit_loss >= 0 ? '▲' : '▼'} {formatCurrency(Math.abs(account.daily_profit_loss))} ({formatPercent(account.daily_profit_loss_pct)}) {d.todaysReturn}
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
                  <div style={{ fontSize: '12px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '1px' }}>
                    {d.initialCapital}
                  </div>
                  <div style={{ fontSize: '16px', fontWeight: 700, fontFamily: 'var(--font-mono)', marginTop: '4px' }}>
                    {formatCurrency(account.initial_capital)}
                  </div>
                </div>
                <div>
                  <div style={{ fontSize: '12px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '1px' }}>
                    {d.totalPL}
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
                  <div style={{ fontSize: '12px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '1px' }}>
                    {d.dailyPnL}
                  </div>
                  <div style={{
                    fontSize: '16px',
                    fontWeight: 700,
                    fontFamily: 'var(--font-mono)',
                    marginTop: '4px',
                    color: account.daily_profit_loss >= 0 ? 'var(--profit)' : 'var(--loss)'
                  }}>
                    {account.daily_profit_loss >= 0 ? '+' : ''}{formatCurrency(account.daily_profit_loss)}
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Positions */}
          <div className="card">
            <div className="card-header">
              <span className="card-title">
                <BriefcaseIcon className="card-icon" /> {d.openPositions}
              </span>
              <button
                className="btn btn-secondary btn-sm"
                onClick={() => setCurrentPage('portfolio')}
              >
                {c.viewAll}
              </button>
            </div>
            <div>
              {positions.length === 0 ? (
                <div className="empty-state" style={{ padding: '32px' }}>
                  {botActive ? (
                    <>
                      <div style={{ fontSize: '32px', marginBottom: '8px' }}>🤖</div>
                      <div style={{ fontWeight: 700, color: 'var(--profit)', marginBottom: '6px', fontSize: '16px' }}>
                        {d.noPositionsBot.title}
                      </div>
                      <div style={{ fontSize: '13px', color: 'var(--text-tertiary)' }}>
                        {d.noPositionsBot.sub}
                      </div>
                    </>
                  ) : (
                    <>
                      <div className="empty-state-icon">📭</div>
                      <div className="empty-state-title">{d.noPositions.title}</div>
                      <div className="empty-state-text">
                        {d.noPositions.sub}
                      </div>
                      <button
                        className="btn btn-primary"
                        style={{ marginTop: '12px' }}
                        onClick={() => setCurrentPage('trading')}
                      >
                        {d.noPositions.cta}
                      </button>
                    </>
                  )}
                </div>
              ) : (
                <table className="positions-table">
                  <thead>
                    <tr>
                      <th>{d.tableSymbol}</th>
                      <th>{d.tableQty}</th>
                      <th>{d.tableAvg}</th>
                      <th>{d.tableCurrent}</th>
                      <th>{d.tablePL}</th>
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
                          <span style={{ fontSize: '12px', marginLeft: '4px' }}>
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
              <span className="card-title">
                <BoltIcon className="card-icon" /> {d.botActivity}
              </span>
              <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                <span style={{
                  fontSize: '12px',
                  fontWeight: 600,
                  color: botActive ? 'var(--profit)' : 'var(--text-tertiary)',
                }}>
                  {botActive ? d.running : d.stopped}
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
                  {botActive ? d.stop : d.start}
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
              <span className="card-title">
                <EyeIcon className="card-icon" /> {d.watchlist}
              </span>
              <button className="btn btn-secondary btn-sm" onClick={() => setCurrentPage('chart')}>
                {c.fullChart}
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
              <span className="card-title">
                <CheckBadgeIcon className="card-icon" /> {d.activeStrategies}
              </span>
              <button className="btn btn-secondary btn-sm" onClick={() => setCurrentPage('trading')}>
                {c.manage}
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
                      {playbookName(strat.id, strat.name)}
                    </span>
                  </div>
                  <span style={{
                    fontSize: '12px',
                    fontFamily: 'var(--font-mono)',
                    color: 'var(--text-tertiary)',
                  }}>
                    {d.winRate(String(strat.winRate))}
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
