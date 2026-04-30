import React, { useMemo } from 'react';
import { useAppStore } from '../../stores/useAppStore';
import type { AppLanguage, RegimeData } from '../../stores/types';
import { formatCurrency, formatPercent, getChangeClass } from '../../utils/helpers';
import api from '../../services/api';
import { useI18n } from '../../i18n';
import { PortfolioIcon } from '../icons/PortfolioIcon';

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

function clampMarketScore(raw: unknown): number {
  const n = typeof raw === 'number' ? raw : Number(raw);
  if (!Number.isFinite(n)) return 50;
  return Math.max(0, Math.min(100, n));
}

function marketBandKey(score: number): string {
  const s = clampMarketScore(score);
  if (s >= 80) return 'marketBandExcellent';
  if (s >= 60) return 'marketBandGood';
  if (s >= 40) return 'marketBandNeutral';
  if (s >= 20) return 'marketBandPoor';
  return 'marketBandDangerous';
}

function avgQuantScore(regime: { quant_scores?: Record<string, number> } | null | undefined): number | null {
  const q = regime?.quant_scores;
  if (!q || typeof q !== 'object') return null;
  const vals = Object.values(q).filter((v): v is number => typeof v === 'number' && Number.isFinite(v));
  if (!vals.length) return null;
  return vals.reduce((a, b) => a + b, 0) / vals.length;
}

const AI_SCORE_ORDER = ['war', 'earnings', 'fed', 'gold', 'crypto', 'others'] as const;

const AI_DIM_LABEL: Record<string, { ko: string; en: string }> = {
  war: { ko: '지정학·안보', en: 'Geopolitics' },
  earnings: { ko: '실적·기업', en: 'Earnings' },
  fed: { ko: '연준·금리', en: 'Fed / rates' },
  gold: { ko: '금(위험회피)', en: 'Gold (risk-off cue)' },
  crypto: { ko: '크립토(위험선호)', en: 'Crypto (risk-on cue)' },
  others: { ko: '기타 거시', en: 'Other macro' },
};

function splitReasoningToBullets(text: string, max: number): string[] {
  const raw = text.trim();
  if (!raw) return [];
  const parts = raw
    .split(/\n+/)
    .flatMap((line) => line.split(/(?<=[.!?。…])\s+/))
    .map((s) => s.trim())
    .filter((s) => s.length > 1);
  const out = parts.length ? parts : [raw];
  return out.slice(0, max);
}

/** Capital scale / daily target lines are user goals, not macro regime rationale. */
const TRADING_GOAL_NOISE_RES: RegExp[] = [
  /-scale\s+scalp/i,
  /\d+k-scale/i,
  /\$\s*[\d,]+\s*[→\-]\s*\+/i,
  /\+\s*[\d.]+%\s*\/\s*day/i,
  /\+\s*1[\s.]*%\s*(per\s*)?day/i,
  /compounding\s+target/i,
  /daily\s*\+?\s*[\d.]+%/i,
  /good\s+faith|\bgfv\b/i,
  /\$3,?000\b/i,
  /일일\s*\+?[\d.]+%/,
  /목표\s*\+?[\d.]+%/,
  /스캘프\s*목표/,
];

function isTradingGoalNoiseBullet(s: string): boolean {
  const t = s.trim();
  if (!t) return true;
  return TRADING_GOAL_NOISE_RES.some((re) => re.test(t));
}

function filterMacroRationaleBullets(items: string[]): string[] {
  return items.filter((line) => !isTradingGoalNoiseBullet(line));
}

function normalizeBulletList(raw: unknown): string[] {
  if (!Array.isArray(raw)) return [];
  const out: string[] = [];
  for (const x of raw) {
    const s = String(x ?? '').trim();
    if (s.length < 4) continue;
    if (!out.includes(s)) out.push(s);
  }
  return out;
}

function buildRegimeRationaleBullets(regime: RegimeData | null | undefined, lang: AppLanguage): string[] {
  if (!regime) return [];

  const primary = normalizeBulletList(lang === 'ko' ? regime.rationale_points_ko : regime.rationale_points_en);
  const secondary = normalizeBulletList(lang === 'ko' ? regime.rationale_points_en : regime.rationale_points_ko);

  let bullets = filterMacroRationaleBullets([...primary]);
  if (bullets.length < 3) {
    for (const s of filterMacroRationaleBullets(secondary)) {
      if (bullets.includes(s)) continue;
      bullets.push(s);
      if (bullets.length >= 6) break;
    }
  }
  if (bullets.length > 0) {
    return bullets.slice(0, 6);
  }

  const legacy: string[] = [];
  const reasoning = String(regime.reasoning || '').trim();
  legacy.push(
    ...filterMacroRationaleBullets(splitReasoningToBullets(reasoning, 3)),
  );

  const ms = regime.market_scores;
  if (ms && typeof ms === 'object') {
    for (const key of AI_SCORE_ORDER) {
      const v = ms[key];
      if (typeof v !== 'number' || !Number.isFinite(v)) continue;
      const label = AI_DIM_LABEL[key]?.[lang === 'ko' ? 'ko' : 'en'] ?? key;
      legacy.push(`${label}: ${Math.round(v)}/100`);
    }
  }

  const qAvg = avgQuantScore(regime);
  if (qAvg != null) {
    legacy.push(
      lang === 'ko'
        ? `양적 매크로(ETF) 보조 평균 ≈ ${qAvg.toFixed(1)}`
        : `Quant macro (ETF) average ≈ ${qAvg.toFixed(1)}`,
    );
  }

  if (regime.sector_tilt) {
    legacy.push(
      lang === 'ko' ? `섹터 기울기: ${regime.sector_tilt}` : `Sector tilt: ${regime.sector_tilt}`,
    );
  }

  const ns = regime.news_score;
  if (typeof ns === 'number' && Number.isFinite(ns) && Math.abs(ns) >= 0.25) {
    const tone =
      lang === 'ko'
        ? ns <= -0.35
          ? '뉴스 톤: 공포·피로(페이드 후보)'
          : ns >= 0.35
            ? '뉴스 톤: 상대적으로 안정'
            : `뉴스 톤: ${ns.toFixed(2)}`
        : ns <= -0.35
          ? 'News tone: panic / exhaustion (fade candidate)'
          : ns >= 0.35
            ? 'News tone: relatively constructive'
            : `News tone: ${ns.toFixed(2)}`;
    legacy.push(tone);
  }

  const seen = new Set<string>();
  const out: string[] = [];
  for (const b of legacy) {
    if (seen.has(b)) continue;
    seen.add(b);
    out.push(b);
    if (out.length >= 10) break;
  }
  return out;
}

const Dashboard: React.FC = () => {
  const { language, t } = useI18n();
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
  } = useAppStore();

  const strategyBanner = useMemo(() => {
    const mode = playbookAuto ? 'AUTO' : 'MANUAL';
    const ids = playbookAuto
      ? (activePlaybooks.length ? activePlaybooks : [])
      : manualPlaybooks;
    const upper = ids.map((s) => s.toUpperCase());
    return `${mode} · ${upper.join(' + ') || '—'}`;
  }, [playbookAuto, activePlaybooks, manualPlaybooks]);

  const compositeMarketScore = regimeData ? clampMarketScore(regimeData.market_score) : 50;
  const regimeRationaleBullets = useMemo(
    () => buildRegimeRationaleBullets(regimeData, language),
    [regimeData, language],
  );

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
            background: 'var(--bg-card)',
            border: '1px solid var(--border-primary)',
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
                borderRadius: '50%',
                transition: 'all 0.2s'
              }}
              onMouseOver={(e) => e.currentTarget.style.background = 'var(--surface-hover-soft)'}
              onMouseOut={(e) => e.currentTarget.style.background = 'none'}
            >
              <XMarkIcon style={{ width: 18, height: 18 }} />
            </button>

            <div className="regime-notification-title-row">
              <div className="regime-notification-title-main">
                <BoltIcon style={{ width: 20, height: 20, flexShrink: 0 }} aria-hidden />
                <h3 className="regime-notification-heading">
                  {language === 'ko' ? 'AI 시장 적응 시스템' : 'AI Market Adaptive System'}
                </h3>
              </div>
              <span className="regime-notification-updated">
                {language === 'ko' ? '최근 업데이트' : 'Last Updated'}: {regimeData.timestamp}
              </span>
            </div>

            <div className="regime-notification-stats">
              <div className="regime-stat-chip regime-stat-chip--market-score">
                <div className="regime-market-score-split">
                  <div className="regime-market-score-col regime-market-score-col--primary">
                    <div className="regime-market-score-head">
                      <div className="regime-market-status-inline">
                        <span className="regime-market-status-label">
                          {language === 'ko' ? '시장 상태' : 'Market Status'}:
                        </span>
                        <strong
                          className="regime-market-level-pill"
                          style={{
                            color:
                              (regimeData.market_level?.toUpperCase() === 'EXCELLENT' ||
                                regimeData.market_level?.toUpperCase() === 'GOOD')
                                ? 'var(--profit)'
                                : regimeData.market_level?.toUpperCase() === 'NORMAL'
                                  ? 'var(--warning)'
                                  : regimeData.market_level?.toUpperCase() === 'BAD' ||
                                      regimeData.market_level?.toUpperCase() === 'DANGEROUS'
                                    ? 'var(--loss)'
                                    : 'var(--text-secondary)',
                          }}
                        >
                          {(regimeData.market_level || 'NORMAL').toUpperCase()}
                        </strong>
                      </div>
                    </div>
                    <div className="regime-market-score-main-row">
                      <span className="regime-market-score-number">
                        {compositeMarketScore % 1 === 0
                          ? compositeMarketScore.toFixed(0)
                          : compositeMarketScore.toFixed(1)}
                        <span className="regime-market-score-denom">/ 100</span>
                      </span>
                      <span
                        className="regime-market-band-label"
                        style={{
                          color:
                            compositeMarketScore >= 70
                              ? 'var(--profit)'
                              : compositeMarketScore >= 40
                                ? 'var(--warning)'
                                : 'var(--loss)',
                        }}
                      >
                        {t(marketBandKey(compositeMarketScore))}
                      </span>
                    </div>
                    <div className="regime-market-score-meter" aria-hidden="true">
                      <div
                        className="regime-market-score-meter-fill"
                        style={{
                          width: `${compositeMarketScore}%`,
                          background:
                            compositeMarketScore >= 70
                              ? 'var(--profit)'
                              : compositeMarketScore >= 40
                                ? 'var(--warning)'
                                : 'var(--loss)',
                        }}
                      />
                    </div>
                    <p className="regime-market-score-hint">{t('marketScorePercentileHint')}</p>
                  </div>
                  <div className="regime-market-score-divider" aria-hidden="true" />
                  <div className="regime-market-score-col regime-market-score-col--rationale">
                    <div className="regime-rationale-title">{t('marketRationaleTitle')}</div>
                    {regimeRationaleBullets.length > 0 ? (
                      <ul className="regime-rationale-list">
                        {regimeRationaleBullets.map((line, idx) => (
                          <li key={`${idx}-${line.slice(0, 24)}`}>{line}</li>
                        ))}
                      </ul>
                    ) : (
                      <p className="regime-rationale-fallback">{t('marketRationaleFallback')}</p>
                    )}
                  </div>
                </div>
              </div>

              <div className="regime-stat-chips-row">
                <div className="regime-stat-chip regime-stat-chip--compact">
                  <span className="regime-stat-chip-label">{language === 'ko' ? '전략' : 'Strategy'}</span>
                  <strong className="regime-stat-chip-value regime-stat-chip-value--accent regime-stat-chip-value--strategy">
                    {regimeData.playbook_mode && regimeData.active_playbooks?.length
                      ? `${regimeData.playbook_mode.toUpperCase()} · ${regimeData.active_playbooks
                          .map((s) => s.toUpperCase())
                          .join(' + ')}`
                      : strategyBanner}
                  </strong>
                </div>

                <div className="regime-stat-chip regime-stat-chip--compact">
                  <span className="regime-stat-chip-label">{language === 'ko' ? '리스크 설정' : 'Risk Setting'}</span>
                  <strong
                    className="regime-stat-chip-value"
                    style={{
                      color:
                        regimeData.risk_level === 'aggressive'
                          ? 'var(--loss)'
                          : regimeData.risk_level === 'moderate'
                            ? 'var(--warning)'
                            : 'var(--profit)',
                    }}
                  >
                    {regimeData.risk_level?.toUpperCase() || 'MODERATE'}
                  </strong>
                </div>

                <div className="regime-stat-chip regime-stat-chip--compact">
                  <span className="regime-stat-chip-label">{t('stopLoss')}</span>
                  <strong className="regime-stat-chip-value" style={{ color: 'var(--loss)' }}>
                    {regimeData.stop_loss_percent}%
                  </strong>
                </div>

                {(regimeData as any).daily_pnl && (
                  <div className="regime-stat-chip regime-stat-chip--compact">
                    <span className="regime-stat-chip-label">{t('dailyPL')}</span>
                    <strong
                      className="regime-stat-chip-value"
                      style={{
                        color: String((regimeData as any).daily_pnl).includes('-')
                          ? 'var(--loss)'
                          : 'var(--profit)',
                      }}
                    >
                      {(regimeData as any).daily_pnl}
                    </strong>
                  </div>
                )}
              </div>
            </div>

            {(((regimeData as any).market_scores) || ((regimeData as any).focus_symbols)) && (
              <div
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '6px',
                  marginTop: (regimeData as any).market_scores ? '8px' : '6px',
                  paddingTop: (regimeData as any).market_scores ? '8px' : '0',
                  borderTop: (regimeData as any).market_scores
                    ? '1px solid var(--border-primary)'
                    : 'none',
                }}
              >
            {(regimeData as any).market_scores && (
              <div style={{ 
                display: 'grid', 
                gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', 
                gap: '8px',
              }}>
                {Object.entries((regimeData as any).market_scores).map(([key, val]) => {
                  const score = Number(val);
                  return (
                  <div key={key} style={{ 
                    fontSize: '11px', 
                    display: 'flex', 
                    justifyContent: 'space-between',
                    padding: '6px 10px',
                    background: 'var(--surface-soft-bg)',
                    borderRadius: 'var(--radius-sm)',
                    border: '1px solid var(--surface-soft-border)'
                  }}>
                    <span style={{ color: 'var(--text-tertiary)', textTransform: 'capitalize' }}>
                      {key === 'fed' ? 'Fed Policy' : key === 'war' ? 'Geopolitical' : key}
                    </span>
                    <strong style={{ 
                      color: score >= 70 ? 'var(--profit)' : score >= 40 ? 'var(--warning)' : 'var(--loss)'
                    }}>{score}</strong>
                  </div>
                  );
                })}
              </div>
            )}

            {(regimeData as any).focus_symbols && (
              <div>
                <div style={{ fontSize: '12px', color: 'var(--text-tertiary)', marginBottom: '12px' }}>
                  {language === 'ko' ? '집중 섹터' : 'Focus Sectors'}: <strong style={{ color: 'var(--text-secondary)' }}>{((regimeData as any).focus_sectors || []).join(', ')}</strong>
                </div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                  {((regimeData as any).focus_symbols || []).map((sym: string) => (
                    <span key={sym} style={{
                      padding: '3px 10px',
                      background: 'var(--bg-tertiary)',
                      border: '1px solid var(--border-secondary)',
                      borderRadius: 'var(--radius-full)',
                      fontSize: '12px',
                      fontWeight: 600,
                      fontFamily: 'var(--font-mono)',
                      color: 'var(--text-primary)',
                    }}>{sym}</span>
                  ))}
                </div>
              </div>
            )}
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
              background: 'var(--state-warning-bg)',
              border: '1px solid var(--state-warning-border)',
              color: 'var(--warning)',
              fontWeight: 600,
            }}>
              ⏸ Entry blackout: {regimeData.blackout_reason || 'active'}
            </span>
          )}
          {compliance && compliance.gfv_level !== 'OK' && (
            <span style={{
              padding: '4px 10px',
              borderRadius: 'var(--radius-full)',
              background: 'var(--state-danger-bg)',
              border: '1px solid var(--state-danger-border)',
              color: 'var(--loss)',
              fontWeight: 600,
            }}>
              GFV {compliance.gfv_level} ({compliance.gfv_count_12mo}/3 in 12mo)
            </span>
          )}
          {compliance && compliance.cooling_down && (
            <span style={{
              padding: '4px 10px',
              borderRadius: 'var(--radius-full)',
              background: 'var(--state-warning-bg)',
              border: '1px solid var(--state-warning-border)',
              color: 'var(--warning)',
              fontWeight: 600,
            }}>
              ⏲ Cooldown {compliance.cooldown_remaining_s}s (loss streak {compliance.loss_streak})
            </span>
          )}
          {compliance && compliance.unsettled_cash > 0 && (
            <span style={{
              padding: '4px 10px',
              borderRadius: 'var(--radius-full)',
              background: 'var(--state-info-bg)',
              border: '1px solid var(--state-info-border)',
              color: 'var(--accent-primary)',
              fontFamily: 'var(--font-mono)',
            }}>
              Unsettled ${compliance.unsettled_cash.toFixed(2)} · T+1
            </span>
          )}
        </div>
      )}

      {/* Stats Grid */}
      <div className="stats-grid">
        <div className={`stat-card ${totalPL >= 0 ? 'profit' : 'loss'}`}>
          <div className="stat-label">{t('portfolioValueLabel')}</div>
          <div className={`stat-value ${getChangeClass(totalPL)}`}>
            {formatCurrency(account.equity)}
          </div>
          <div className={`stat-change ${getChangeClass(totalPL)}`}>
            {totalPL >= 0 ? '▲' : '▼'} {formatCurrency(Math.abs(totalPL))} ({formatPercent(totalPLPct)})
          </div>
        </div>

        <div className="stat-card accent">
          <div className="stat-label">{t('cashAvailable')}</div>
          <div className="stat-value" style={{ color: 'var(--text-primary)' }}>
            {formatCurrency(account.cash)}
          </div>
          <div style={{ fontSize: '12px', color: 'var(--text-tertiary)', marginTop: '6px' }}>
            {t('buyingPower')}: {formatCurrency(account.buying_power)}
          </div>
        </div>

        <div className="stat-card accent">
          <div className="stat-label">{t('activePositions')}</div>
          <div className="stat-value" style={{ color: 'var(--accent-secondary)' }}>
            {activePositionCount}
          </div>
          <div style={{ fontSize: '12px', color: 'var(--text-tertiary)', marginTop: '6px' }}>
            {strategies.filter(s => s.active).length} {language === 'ko' ? '개 전략 활성' : 'strategies active'}
          </div>
        </div>

        <div className="stat-card accent">
          <div className="stat-label">{t('botStatus')}</div>
          <div className="stat-value" style={{
            color: botActive ? 'var(--profit)' : 'var(--text-tertiary)',
            fontSize: '22px',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
          }}>
            <span style={{ fontSize: '14px', lineHeight: 1 }}>{botActive ? '●' : '○'}</span>
            <span>{botActive ? (language === 'ko' ? '활성' : 'ACTIVE') : (language === 'ko' ? '대기' : 'IDLE')}</span>
          </div>
          <div style={{ fontSize: '12px', color: 'var(--text-tertiary)', marginTop: '6px' }}>
            {language === 'ko' ? (
              <>
                {tradeLogs.length}개 이벤트 기록 ·{' '}
                {Number.isFinite(botDailyTrades) ? botDailyTrades : 0} 데일리 스캘핑
              </>
            ) : (
              <>
                {tradeLogs.length} events logged ·{' '}
                {Number.isFinite(botDailyTrades) ? botDailyTrades : 0} daily scalping
              </>
            )}
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
                <ChartBarIcon className="card-icon" /> {t('portfolioPerformance')}
              </span>
              <span style={{ fontSize: '12px', color: 'var(--text-tertiary)' }}>
                {t('starting')}: {formatCurrency(account.initial_capital)}
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
                    {account.daily_profit_loss >= 0 ? '▲' : '▼'} {formatCurrency(Math.abs(account.daily_profit_loss))} ({formatPercent(account.daily_profit_loss_pct)}) {t('todaysReturn')}
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
                    {t('initialCapital')}
                  </div>
                  <div style={{ fontSize: '16px', fontWeight: 700, fontFamily: 'var(--font-mono)', marginTop: '4px' }}>
                    {formatCurrency(account.initial_capital)}
                  </div>
                </div>
                <div>
                  <div style={{ fontSize: '12px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '1px' }}>
                    {t('totalPL')}
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
                    {t('dailyPL')}
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
                <PortfolioIcon className="card-icon" /> {t('openPositions')}
              </span>
              <button
                className="btn btn-secondary btn-sm"
                onClick={() => setCurrentPage('portfolio')}
              >
                {t('viewAll')}
              </button>
            </div>
            <div>
              {positions.length === 0 ? (
                <div className="empty-state" style={{ padding: '32px' }}>
                  {botActive ? (
                    <>
                      <div style={{ fontSize: '32px', marginBottom: '8px' }}>🤖</div>
                      <div style={{ fontWeight: 700, color: 'var(--profit)', marginBottom: '6px', fontSize: '16px' }}>
                        {language === 'ko' ? '봇 실행 중' : 'Bot is Running'}
                      </div>
                      <div style={{ fontSize: '13px', color: 'var(--text-tertiary)' }}>
                        {language === 'ko' ? '진입 신호를 스캔 중입니다… 포지션이 열리면 여기에 표시됩니다.' : 'Scanning for entry signals… Positions will appear here when opened.'}
                      </div>
                    </>
                  ) : (
                    <>
                      <div className="empty-state-icon">📭</div>
                      <div className="empty-state-title">{t('noOpenPositions')}</div>
                      <div className="empty-state-text">
                        {t('noOpenPositionsText')}
                      </div>
                      <button
                        className="btn btn-primary"
                        style={{ marginTop: '12px' }}
                        onClick={() => setCurrentPage('trading')}
                      >
                        ⚡ {t('startTradingBot')}
                      </button>
                    </>
                  )}
                </div>
              ) : (
                <table className="positions-table">
                  <thead>
                    <tr>
                      <th>{t('symbol')}</th>
                      <th>{t('qty')}</th>
                      <th>{t('avgEntry')}</th>
                      <th>{t('current')}</th>
                      <th>{t('totalPL')}</th>
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
                <BoltIcon className="card-icon" /> {t('tradingBotActivity')}
              </span>
              <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                <span style={{
                  fontSize: '12px',
                  fontWeight: 600,
                  color: botActive ? 'var(--profit)' : 'var(--text-tertiary)',
                }}>
                  {botActive ? `● ${t('running')}` : `○ ${t('stopped')}`}
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
                  {botActive ? t('stop') : t('start')}
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
                <EyeIcon className="card-icon" /> {t('watchlist')}
              </span>
              <button className="btn btn-secondary btn-sm" onClick={() => setCurrentPage('chart')}>
                {t('fullChart')}
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
                <CheckBadgeIcon className="card-icon" /> {t('activeStrategies')}
              </span>
              <button className="btn btn-secondary btn-sm" onClick={() => setCurrentPage('trading')}>
                {t('manage')}
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
