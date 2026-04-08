import React, { useState, useEffect, useCallback } from 'react';
import { useAppStore } from '../../stores/useAppStore';
import { formatCurrency, formatPercent } from '../../utils/helpers';
import api from '../../services/api';

// Heroicons v2 Outline SVGs
const BoltIcon = (props: React.ComponentProps<'svg'>) => (
  <svg {...props} fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
    <path strokeLinecap="round" strokeLinejoin="round" d="m3.75 13.5 10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75Z" />
  </svg>
);

const RocketIcon = (props: React.ComponentProps<'svg'>) => (
  <svg {...props} fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
    <path strokeLinecap="round" strokeLinejoin="round" d="M15.59 14.37a6 6 0 0 1-5.84 7.38v-4.8m5.84-2.58a14.98 14.98 0 0 0 6.16-12.12A14.98 14.98 0 0 0 9.631 8.41m5.96 5.96a14.926 14.926 0 0 1-5.841 2.58m-.119-8.54a6 6 0 0 0-7.381 5.84h4.8m2.581-5.84a14.927 14.927 0 0 0-2.58 5.84m2.699 2.7c-.103.021-.207.041-.311.06a15.09 15.09 0 0 1-2.448-2.448 14.9 14.9 0 0 1 .06-.312m-2.24 2.39a4.493 4.493 0 0 0-1.757 4.306 4.493 4.493 0 0 0 4.306-1.758M16.5 9a1.5 1.5 0 1 1-3 0 1.5 1.5 0 0 1 3 0Z" />
  </svg>
);

const StopIcon = (props: React.ComponentProps<'svg'>) => (
  <svg {...props} fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
    <path strokeLinecap="round" strokeLinejoin="round" d="M5.25 7.5A2.25 2.25 0 0 1 7.5 5.25h9a2.25 2.25 0 0 1 2.25 2.25v9a2.25 2.25 0 0 1-2.25 2.25h-9a2.25 2.25 0 0 1-2.25-2.25v-9Z" />
  </svg>
);

const ShieldIcon = (props: React.ComponentProps<'svg'>) => (
  <svg {...props} fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
    <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75 11.25 15 15 9.75m-3-7.036A11.959 11.959 0 0 1 3.598 6 11.99 11.99 0 0 0 3 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285Z" />
  </svg>
);

const ListIcon = (props: React.ComponentProps<'svg'>) => (
  <svg {...props} fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
    <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 6.75h12M8.25 12h12m-12 5.25h12M3.75 6.75h.007v.008H3.75V6.75Zm.375 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0ZM3.75 12h.007v.008H3.75V12Zm.375 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0ZM3.75 17.25h.007v.008H3.75v-.008Zm.375 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Z" />
  </svg>
);

const ChartBarIcon = (props: React.ComponentProps<'svg'>) => (
  <svg {...props} fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
    <path strokeLinecap="round" strokeLinejoin="round" d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 0 1 3 19.875v-6.75ZM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 0 1-1.125-1.125V8.625ZM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 0 1-1.125-1.125V4.125Z" />
  </svg>
);

const CheckBadgeIcon = (props: React.ComponentProps<'svg'>) => (
  <svg {...props} fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
    <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75 11.25 15 15 9.75M21 12c0 1.268-.63 2.39-1.593 3.068a3.745 3.745 0 0 1-1.043 3.296 3.745 3.745 0 0 1-3.296 1.043A3.745 3.745 0 0 1 12 21c-1.268 0-2.39-.63-3.068-1.593a3.746 3.746 0 0 1-3.296-1.043 3.745 3.745 0 0 1-1.043-3.296A3.745 3.745 0 0 1 3 12c0-1.268.63-2.39 1.593-3.068a3.745 3.745 0 0 1 1.043-3.296 3.746 3.746 0 0 1 3.296-1.043A3.746 3.746 0 0 1 12 3c1.268 0 2.39.63 3.068 1.593a3.746 3.746 0 0 1 3.296 1.043 3.746 3.746 0 0 1 1.043 3.296A3.745 3.745 0 0 1 21 12Z" />
  </svg>
);

const InfoIcon = (props: React.ComponentProps<'svg'>) => (
  <svg {...props} fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
    <path strokeLinecap="round" strokeLinejoin="round" d="M11.25 11.25l.041-.02a.75.75 0 0 1 1.063.852l-.708 2.836a.75.75 0 0 0 1.063.853l.041-.021M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0zm-9-3.75h.008v.008H12V8.25z" />
  </svg>
);

const BuyIcon = (props: React.ComponentProps<'svg'>) => (
  <svg {...props} fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
    <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75l3 3m0 0l3-3m-3 3v-7.5M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
  </svg>
);

const SellIcon = (props: React.ComponentProps<'svg'>) => (
  <svg {...props} fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
    <path strokeLinecap="round" strokeLinejoin="round" d="M15 11.25l-3-3m0 0l-3 3m3-3v7.5M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
  </svg>
);

const SignalIcon = (props: React.ComponentProps<'svg'>) => (
  <svg {...props} fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
    <path strokeLinecap="round" strokeLinejoin="round" d="M12 18v-5.25m0 0a6.01 6.01 0 0 0 1.5-.189m-1.5.189a6.01 6.01 0 0 1-1.5-.189m3.75 7.478a12.06 12.06 0 0 1-4.5 0m3.75 2.383a14.406 14.406 0 0 1-3 0M14.25 18v-.192c0-.983.658-1.823 1.508-2.316a7.503 7.503 0 0 0 1.5-1.539c.567-.946.75-2.107.75-3.203a6 6 0 0 0-12 0c0 1.096.183 2.257.75 3.203.555.927 1.157 1.045 1.5 1.539a3.388 3.388 0 0 1 .508 2.316V18" />
  </svg>
);

const ErrorIcon = (props: React.ComponentProps<'svg'>) => (
  <svg {...props} fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
    <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m9-.75a9 9 0 1 1-18 0 9 9 0 0 1 18 0zm-9 3.75h.008v.008H12v-.008z" />
  </svg>
);

const TradingBot: React.FC = () => {
  const {
    botActive,
    setBotActive,
    tradeLogs,
    setTradeLogs,
    strategies,
    activeStrategy,
    setActiveStrategy,
    account,
  } = useAppStore();

  const [riskLevel, setRiskLevel] = useState<'conservative' | 'moderate' | 'aggressive'>('moderate');
  const [maxPositionSize, setMaxPositionSize] = useState(20);
  const [stopLossPercent, setStopLossPercent] = useState(2);
  const [takeProfitPercent, setTakeProfitPercent] = useState(5);

  const [sessionStats, setSessionStats] = useState({
    total_trades: 0,
    winning_trades: 0,
    losing_trades: 0,
    total_pnl: 0,
    win_rate: 0,
    max_drawdown: 0,
  });

  // Poll bot status & logs from backend every 5 seconds
  const pollBotStatus = useCallback(async () => {
    try {
      const data = await api.getBotStatus() as {
        active?: boolean;
        logs?: Array<{ time: string; type: string; message: string }>;
        stats?: typeof sessionStats;
      };
      if (data) {
        if (typeof data.active === 'boolean') setBotActive(data.active);
        if (data.logs && data.logs.length > 0) {
          setTradeLogs(data.logs as typeof tradeLogs);
        }
        if (data.stats) {
          setSessionStats(data.stats);
        }
      }
    } catch {
      // backend might be restarting
    }
  }, [setBotActive, setTradeLogs]);

  useEffect(() => {
    pollBotStatus();
    const interval = setInterval(pollBotStatus, 5000);
    return () => clearInterval(interval);
  }, [pollBotStatus]);

  const handleToggleBot = async () => {
    try {
      if (!botActive) {
        await api.startBot(activeStrategy || 'momentum');
        setBotActive(true);
      } else {
        await api.stopBot();
        setBotActive(false);
      }
      setTimeout(pollBotStatus, 500);
    } catch (err) {
      console.error('Bot toggle failed:', err);
    }
  };


  const getLogIcon = (type: string) => {
    const iconStyle = { width: '14px', height: '14px', marginRight: '6px' };
    switch (type.toLowerCase()) {
      case 'buy': return <BuyIcon style={{ ...iconStyle, color: 'var(--profit)' }} />;
      case 'sell': return <SellIcon style={{ ...iconStyle, color: 'var(--loss)' }} />;
      case 'signal': return <SignalIcon style={{ ...iconStyle, color: 'var(--accent-primary)' }} />;
      case 'error': case 'critical': return <ErrorIcon style={{ ...iconStyle, color: 'var(--loss)' }} />;
      default: return <InfoIcon style={{ ...iconStyle, color: 'var(--text-tertiary)' }} />;
    }
  };

  return (
    <div className="page-enter">
      {/* Bot Control Header */}
      <div className="card" style={{ marginBottom: 'var(--space-xl)' }}>
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: 'var(--space-xl)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
            <div style={{
              width: 56,
              height: 56,
              borderRadius: 'var(--radius-lg)',
              background: botActive ? 'var(--profit-dim)' : 'var(--bg-secondary)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              transition: 'all var(--transition-base)',
              boxShadow: botActive ? 'var(--shadow-glow-green)' : 'none',
              color: botActive ? 'var(--profit)' : 'var(--text-tertiary)',
            }}>
              <BoltIcon style={{ width: '32px', height: '32px' }} />
            </div>
            <div>
              <h2 style={{ fontSize: '18px', fontWeight: 700, marginBottom: '4px' }}>
                TradeSense Trading Bot
              </h2>
              <p style={{ fontSize: '12px', color: 'var(--text-tertiary)' }}>
                Automated quant trading • Paper Trading Mode • Capital: {formatCurrency(account.equity)}
              </p>
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '20px' }}>
            <span style={{
              fontSize: '14px',
              fontWeight: 700,
              color: botActive ? 'var(--profit)' : 'var(--text-tertiary)',
              letterSpacing: '0.5px',
            }}>
              {botActive ? '● RUNNING' : '○ STOPPED'}
            </span>
            <button
              className={botActive ? 'btn-stop' : 'btn-start'}
              onClick={handleToggleBot}
            >
              {botActive ? (
                <>
                  <StopIcon style={{ width: '18px', height: '18px' }} />
                  Stop Bot
                </>
              ) : (
                <>
                  <RocketIcon style={{ width: '18px', height: '18px' }} />
                  Start Bot
                </>
              )}
            </button>
          </div>
        </div>
      </div>

      <div className="dashboard-grid">
        <div className="dashboard-left">
          {/* Strategy Selection */}
          <div className="card">
            <div className="card-header">
              <span className="card-title">
                <CheckBadgeIcon className="card-icon" /> Trading Strategies
              </span>
            </div>
            <div style={{ padding: 'var(--space-lg)' }}>
              <div className="strategy-grid">
                {strategies.map((strat) => (
                  <div
                    key={strat.id}
                    className={`strategy-card ${activeStrategy === strat.id ? 'active' : ''}`}
                    onClick={() => setActiveStrategy(strat.id)}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span className="strategy-name">{strat.name}</span>
                      <span style={{
                        width: 12,
                        height: 12,
                        borderRadius: '50%',
                        border: '2px solid',
                        borderColor: activeStrategy === strat.id ? 'var(--accent-primary)' : 'var(--text-muted)',
                        background: activeStrategy === strat.id ? 'var(--accent-primary)' : 'transparent',
                        display: 'inline-block',
                      }} />
                    </div>
                    <p className="strategy-description">{strat.description}</p>
                    <div className="strategy-stats">
                      <div className="strategy-stat">
                        <span className="strategy-stat-label">Win Rate</span>
                        <span className="strategy-stat-value" style={{ color: 'var(--profit)' }}>
                          {strat.winRate}%
                        </span>
                      </div>
                      <div className="strategy-stat">
                        <span className="strategy-stat-label">Trades</span>
                        <span className="strategy-stat-value">{strat.trades}</span>
                      </div>
                      <div className="strategy-stat">
                        <span className="strategy-stat-label">P&L</span>
                        <span className="strategy-stat-value" style={{
                          color: strat.pnl >= 0 ? 'var(--profit)' : 'var(--loss)',
                        }}>
                          {strat.pnl >= 0 ? '+' : ''}{formatCurrency(strat.pnl)}
                        </span>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Activity Log */}
          <div className="card">
            <div className="card-header">
              <span className="card-title">
                <ListIcon className="card-icon" /> Activity Log
              </span>
              <span style={{
                fontSize: '11px',
                color: 'var(--text-tertiary)',
                fontFamily: 'var(--font-mono)',
              }}>
                {tradeLogs.length} events
              </span>
            </div>
            <div className="bot-log" style={{ maxHeight: '400px' }}>
              {[...tradeLogs].reverse().map((log, i) => (
                <div key={i} className="bot-log-entry">
                  <span className="bot-log-time">{log.time}</span>
                  <span className={`bot-log-type ${log.type}`} style={{ display: 'flex', alignItems: 'center' }}>
                    {getLogIcon(log.type)}
                    {log.type}
                  </span>
                  <span className="bot-log-message">{log.message}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Right Column - Settings */}
        <div className="dashboard-right">
          <div className="card">
            <div className="card-header">
              <span className="card-title">
                <ShieldIcon className="card-icon" /> Risk Settings
              </span>
            </div>
            <div style={{ padding: 'var(--space-xl)', display: 'flex', flexDirection: 'column', gap: '20px' }}>
              {/* Risk Level */}
              <div>
                <label style={{
                  fontSize: '11px',
                  textTransform: 'uppercase',
                  letterSpacing: '1px',
                  color: 'var(--text-muted)',
                  fontWeight: 600,
                  display: 'block',
                  marginBottom: '8px',
                }}>
                  Risk Level
                </label>
                <div style={{ display: 'flex', gap: '4px' }}>
                  {(['conservative', 'moderate', 'aggressive'] as const).map((level) => (
                    <button
                      key={level}
                      className={`btn btn-sm ${riskLevel === level ? 'btn-primary' : 'btn-secondary'}`}
                      onClick={() => {
                        setRiskLevel(level);
                        if (level === 'conservative') {
                          setMaxPositionSize(10);
                          setStopLossPercent(1);
                          setTakeProfitPercent(2);
                        } else if (level === 'moderate') {
                          setMaxPositionSize(20);
                          setStopLossPercent(2);
                          setTakeProfitPercent(5);
                        } else if (level === 'aggressive') {
                          setMaxPositionSize(40);
                          setStopLossPercent(5);
                          setTakeProfitPercent(10);
                        }
                      }}
                      style={{ flex: 1, textTransform: 'capitalize' }}
                    >
                      {level}
                    </button>
                  ))}
                </div>
              </div>

              {/* Max Position */}
              <div>
                <label style={{
                  fontSize: '11px',
                  textTransform: 'uppercase',
                  letterSpacing: '1px',
                  color: 'var(--text-muted)',
                  fontWeight: 600,
                  display: 'block',
                  marginBottom: '8px',
                }}>
                  Max Position Size: {maxPositionSize}% ({formatCurrency(account.equity * maxPositionSize / 100)})
                </label>
                <input
                  type="range"
                  min={5}
                  max={50}
                  value={maxPositionSize}
                  onChange={(e) => setMaxPositionSize(parseInt(e.target.value))}
                  style={{ width: '100%', accentColor: 'var(--accent-primary)' }}
                />
              </div>

              {/* Stop Loss */}
              <div>
                <label style={{
                  fontSize: '11px',
                  textTransform: 'uppercase',
                  letterSpacing: '1px',
                  color: 'var(--text-muted)',
                  fontWeight: 600,
                  display: 'block',
                  marginBottom: '8px',
                }}>
                  Stop Loss: -{stopLossPercent}%
                </label>
                <input
                  type="range"
                  min={1}
                  max={10}
                  step={0.5}
                  value={stopLossPercent}
                  onChange={(e) => setStopLossPercent(parseFloat(e.target.value))}
                  style={{ width: '100%', accentColor: 'var(--loss)' }}
                />
              </div>

              {/* Take Profit */}
              <div>
                <label style={{
                  fontSize: '11px',
                  textTransform: 'uppercase',
                  letterSpacing: '1px',
                  color: 'var(--text-muted)',
                  fontWeight: 600,
                  display: 'block',
                  marginBottom: '8px',
                }}>
                  Take Profit: +{takeProfitPercent}%
                </label>
                <input
                  type="range"
                  min={2}
                  max={20}
                  step={0.5}
                  value={takeProfitPercent}
                  onChange={(e) => setTakeProfitPercent(parseFloat(e.target.value))}
                  style={{ width: '100%', accentColor: 'var(--profit)' }}
                />
              </div>

              {/* Summary */}
              <div style={{
                padding: '16px',
                background: 'var(--bg-secondary)',
                borderRadius: 'var(--radius-md)',
                fontSize: '12px',
                lineHeight: 1.8,
              }}>
                  <div style={{ fontWeight: 600, marginBottom: '8px', color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <ListIcon style={{ width: '16px', height: '16px' }} /> Configuration Summary
                  </div>
                <div style={{ color: 'var(--text-secondary)' }}>
                  • Capital: {formatCurrency(account.equity)}<br/>
                  • Strategy: {strategies.find(s => s.id === activeStrategy)?.name}<br/>
                  • Max per trade: {formatCurrency(account.equity * maxPositionSize / 100)}<br/>
                  • Stop Loss: {formatPercent(-stopLossPercent)}<br/>
                  • Take Profit: {formatPercent(takeProfitPercent)}<br/>
                  • Risk/Reward: 1:{(takeProfitPercent / stopLossPercent).toFixed(1)}
                </div>
              </div>
            </div>
          </div>

          {/* Quick Stats */}
          <div className="card">
            <div className="card-header">
              <span className="card-title">
                <ChartBarIcon className="card-icon" /> Session Stats
              </span>
            </div>
            <div style={{ padding: 'var(--space-xl)' }}>
              {[
                { label: 'Total Trades', value: sessionStats.total_trades.toString(), color: 'var(--text-primary)' },
                { label: 'Win Rate', value: `${sessionStats.win_rate.toFixed(1)}%`, color: sessionStats.win_rate >= 50 ? 'var(--profit)' : 'var(--text-tertiary)' },
                { label: 'Winning Trades', value: sessionStats.winning_trades.toString(), color: 'var(--profit)' },
                { label: 'Losing Trades', value: sessionStats.losing_trades.toString(), color: 'var(--loss)' },
                { label: 'Total P&L', value: formatCurrency(sessionStats.total_pnl), color: sessionStats.total_pnl >= 0 ? 'var(--profit)' : 'var(--loss)' },
              ].map((stat, i) => (
                <div key={i} style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  padding: '10px 0',
                  borderBottom: i < 4 ? '1px solid var(--border-secondary)' : 'none',
                }}>
                  <span style={{ fontSize: '12px', color: 'var(--text-tertiary)' }}>
                    {stat.label}
                  </span>
                  <span style={{
                    fontSize: '13px',
                    fontWeight: 600,
                    fontFamily: 'var(--font-mono)',
                    color: stat.color,
                  }}>
                    {stat.value}
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

export default TradingBot;
