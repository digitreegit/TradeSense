import React, { useState, useEffect, useCallback } from 'react';
import { useAppStore } from '../../stores/useAppStore';
import { formatCurrency, formatPercent } from '../../utils/helpers';
import api from '../../services/api';

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

  // Poll bot status & logs from backend every 5 seconds
  const pollBotStatus = useCallback(async () => {
    try {
      const data = await api.getBotStatus() as {
        active?: boolean;
        logs?: Array<{ time: string; type: string; message: string }>;
      };
      if (data) {
        if (typeof data.active === 'boolean') setBotActive(data.active);
        if (data.logs && data.logs.length > 0) {
          setTradeLogs(data.logs as typeof tradeLogs);
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
              fontSize: '28px',
              transition: 'all var(--transition-base)',
              boxShadow: botActive ? 'var(--shadow-glow-green)' : 'none',
            }}>
              ⚡
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

          <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
            <span style={{
              fontSize: '14px',
              fontWeight: 700,
              color: botActive ? 'var(--profit)' : 'var(--text-tertiary)',
            }}>
              {botActive ? '● RUNNING' : '○ STOPPED'}
            </span>
            <button
              className={`btn ${botActive ? 'btn-danger' : 'btn-primary'}`}
              onClick={handleToggleBot}
              style={{ minWidth: '120px' }}
            >
              {botActive ? '🛑 Stop Bot' : '🚀 Start Bot'}
            </button>
          </div>
        </div>
      </div>

      <div className="dashboard-grid">
        <div className="dashboard-left">
          {/* Strategy Selection */}
          <div className="card">
            <div className="card-header">
              <span className="card-title">🎯 Trading Strategies</span>
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
              <span className="card-title">📋 Activity Log</span>
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
                  <span className={`bot-log-type ${log.type}`}>{log.type}</span>
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
              <span className="card-title">⚙️ Risk Settings</span>
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
                <div style={{ fontWeight: 600, marginBottom: '8px', color: 'var(--text-primary)' }}>
                  📊 Configuration Summary
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
              <span className="card-title">📈 Session Stats</span>
            </div>
            <div style={{ padding: 'var(--space-xl)' }}>
              {[
                { label: 'Total Trades', value: '0', color: 'var(--text-primary)' },
                { label: 'Win Rate', value: 'N/A', color: 'var(--text-tertiary)' },
                { label: 'Profit Factor', value: 'N/A', color: 'var(--text-tertiary)' },
                { label: 'Max Drawdown', value: '$0.00', color: 'var(--text-tertiary)' },
                { label: 'Sharpe Ratio', value: 'N/A', color: 'var(--text-tertiary)' },
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
