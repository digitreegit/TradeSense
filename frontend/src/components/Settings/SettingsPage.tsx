import React, { useEffect, useState } from 'react';
import api from '../../services/api';
import { useAppStore } from '../../stores/useAppStore';
import type { AppLanguage } from '../../stores/types';
import { clearToken } from '../../auth/token';
import { supabase } from '../../auth/supabase';
import { useI18n } from '../../i18n';

type CapitalScale = '3k' | '10k' | '30k';

const SCALE_OPTIONS: Array<{
  id: CapitalScale;
  title: string;
  caption: string;
}> = [
  {
    id: '3k',
    title: '$3,000',
    caption: 'Starter cash-scalp · IEX feed',
  },
  {
    id: '10k',
    title: '$10,000',
    caption: 'Cash-only bridge · no PDT impact',
  },
  {
    id: '30k',
    title: '$30,000',
    caption: 'HFT paper · SIP feed + us-east-1',
  },
];

type LiveSummary = {
  equity: number;
  cash: number;
  buying_power: number;
  portfolio_value: number;
};

const fmtUsd = (n: number) =>
  new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 }).format(n);

const SettingsPage: React.FC = () => {
  const { t } = useI18n();
  const {
    authEmail,
    authAlpacaConfigured,
    authAlpacaPaperTrading,
    setAuthProfile,
    setCurrentPage,
    setAuthMethod,
    language,
    setLanguage,
  } = useAppStore();
  const [key, setKey] = useState('');
  const [secret, setSecret] = useState('');
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);
  const [scale, setScale] = useState<CapitalScale | null>(null);
  const [scaleLoading, setScaleLoading] = useState(false);
  const [scaleMsg, setScaleMsg] = useState<string | null>(null);
  const [modeLoading, setModeLoading] = useState(false);
  const [liveSummary, setLiveSummary] = useState<LiveSummary | null>(null);
  const [liveLoading, setLiveLoading] = useState(false);

  const [notifyTg, setNotifyTg] = useState(false);
  const [tgChatId, setTgChatId] = useState('');
  const [tgBotOk, setTgBotOk] = useState(false);
  const [notifLoading, setNotifLoading] = useState(false);
  const [notifSaving, setNotifSaving] = useState(false);
  const [notifMsg, setNotifMsg] = useState<string | null>(null);
  const [taxYear, setTaxYear] = useState(() => new Date().getFullYear());
  const [taxExporting, setTaxExporting] = useState(false);
  const [taxExportErr, setTaxExportErr] = useState<string | null>(null);

  const keysLocked = authAlpacaConfigured;

  useEffect(() => {
    let cancelled = false;
    api
      .getCapitalScale()
      .then((info) => {
        if (!cancelled) setScale(info.scale);
      })
      .catch(() => {
        /* non-fatal */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    api
      .getNotificationPrefs()
      .then((p) => {
        if (cancelled) return;
        setNotifyTg(Boolean(p.notify_telegram));
        setTgChatId(p.telegram_chat_id || '');
        setTgBotOk(Boolean(p.telegram_bot_configured));
      })
      .catch(() => {
        /* non-fatal */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!authEmail || !authAlpacaConfigured || authAlpacaPaperTrading) {
      setLiveSummary(null);
      return;
    }
    let cancelled = false;
    const load = async () => {
      setLiveLoading(true);
      try {
        const acc = await api.getAccount();
        if (cancelled || !acc || 'detail' in acc) return;
        setLiveSummary({
          equity: Number(acc.equity) || 0,
          cash: Number(acc.cash) || 0,
          buying_power: Number(acc.buying_power) || 0,
          portfolio_value: Number(acc.portfolio_value) || 0,
        });
      } catch {
        if (!cancelled) setLiveSummary(null);
      } finally {
        if (!cancelled) setLiveLoading(false);
      }
    };
    void load();
    const t = window.setInterval(load, 15000);
    return () => {
      cancelled = true;
      window.clearInterval(t);
    };
  }, [authEmail, authAlpacaConfigured, authAlpacaPaperTrading]);

  const choosePaperOrLive = async (paper: boolean) => {
    if (!authAlpacaConfigured) {
      setErr('Save Alpaca keys first, then choose paper or live.');
      return;
    }
    if (paper === authAlpacaPaperTrading || modeLoading) return;
    setModeLoading(true);
    setErr(null);
    setScaleMsg(null);
    try {
      const info = await api.setTradingMode(paper);
      if (authEmail) {
        setAuthProfile(authEmail, true, Boolean(info.paper_trading));
      }
      setScaleMsg(
        info.paper_trading
          ? 'Switched to paper trading API. Capital scale presets apply.'
          : 'Switched to live trading API. Balances shown are from your live Alpaca account.',
      );
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Failed to change trading mode');
    } finally {
      setModeLoading(false);
    }
  };

  const saveNotificationPrefs = async () => {
    setNotifSaving(true);
    setNotifMsg(null);
    setErr(null);
    try {
      const p = await api.setNotificationPrefs({
        notify_telegram: notifyTg,
        telegram_chat_id: tgChatId.trim(),
      });
      setTgBotOk(Boolean(p.telegram_bot_configured));
      setNotifMsg('Notification preferences saved.');
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Failed to save notifications');
    } finally {
      setNotifSaving(false);
    }
  };

  const sendTestNotification = async () => {
    setNotifLoading(true);
    setNotifMsg(null);
    setErr(null);
    try {
      const res = await api.testNotification();
      setNotifMsg(res.message || 'Test message sent.');
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Test send failed');
    } finally {
      setNotifLoading(false);
    }
  };

  const chooseScale = async (next: CapitalScale) => {
    if (!authAlpacaPaperTrading) {
      setErr('Capital scale presets apply to paper mode only. Switch to paper money to change them.');
      return;
    }
    if (next === scale || scaleLoading) return;
    setScaleLoading(true);
    setScaleMsg(null);
    setErr(null);
    try {
      const info = await api.setCapitalScale(next);
      setScale(info.scale);
      setScaleMsg(`Switched to ${info.scale.toUpperCase()} preset (${info.level}).`);
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Failed to switch capital scale');
    } finally {
      setScaleLoading(false);
    }
  };

  const saveKeys = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr(null);
    setMsg(null);
    if (keysLocked) {
      setErr('Delete existing keys first to enter new keys.');
      return;
    }
    if (!key.trim() || !secret.trim()) {
      setErr('Enter both the API Key ID and Secret Key.');
      return;
    }
    setLoading(true);
    try {
      await api.saveAlpacaKeys(key.trim(), secret.trim());
      setAuthProfile(authEmail, true, true);
      setKey('');
      setSecret('');
      setMsg('Alpaca keys saved (encrypted on the server).');
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : 'Failed to save');
    } finally {
      setLoading(false);
    }
  };

  const deleteKeys = async () => {
    setErr(null);
    setMsg(null);
    setDeleting(true);
    try {
      await api.deleteAlpacaKeys();
      setAuthProfile(authEmail, false);
      setKey('');
      setSecret('');
      setMsg('Stored Alpaca keys were deleted. You can add a new key pair now.');
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : 'Failed to delete keys');
    } finally {
      setDeleting(false);
    }
  };

  const signOut = () => {
    void supabase.auth.signOut();
    clearToken();
    setAuthProfile(null, false);
    setAuthMethod(null);
    setCurrentPage('auth');
  };

  const chooseLanguage = (next: AppLanguage) => {
    if (next === language) return;
    setLanguage(next);
  };

  return (
    <div className="page-enter" style={{ width: 'min(66.667vw, 920px)', maxWidth: 'calc(100vw - 32px)', margin: '0 auto', padding: 'var(--space-xl)' }}>
      <div className="card" style={{ padding: 'var(--space-xl)' }}>
        <h2 style={{ fontSize: '18px', marginBottom: '8px' }}>{t('Settings')}</h2>
        <p style={{ fontSize: '13px', color: 'var(--text-tertiary)', marginBottom: '20px', lineHeight: 1.5 }}>
          {t('connectAlpaca')}{' '}
          {t('paperKeys')}:{' '}
          <a
            href="https://app.alpaca.markets/paper/dashboard/overview"
            target="_blank"
            rel="noreferrer"
            style={{ color: 'var(--info)', textDecoration: 'none' }}
          >
            Alpaca Paper
          </a>
          {' · '}
          {t('liveKeys')}:{' '}
          <a
            href="https://app.alpaca.markets/dashboard/overview"
            target="_blank"
            rel="noreferrer"
            style={{ color: 'var(--info)', textDecoration: 'none' }}
          >
            Alpaca Live
          </a>
          .
        </p>
        <p
          style={{
            fontSize: '13px',
            color: 'var(--text-secondary)',
            marginBottom: '16px',
            display: 'flex',
            alignItems: 'center',
            gap: '10px',
            flexWrap: 'wrap',
          }}
        >
          {t('Signed in as')} <strong>{authEmail}</strong>
          {authAlpacaConfigured ? ` ${t('keys on file')}` : ` ${t('keysNotConfigured')}`}
          {authAlpacaConfigured && (
            <button
              type="button"
              className="btn btn-danger btn-sm"
              onClick={() => setConfirmDeleteOpen(true)}
              disabled={deleting || loading}
            >
              {deleting ? t('deleting') : t('deleteKeys')}
            </button>
          )}
        </p>
        {err && <p style={{ color: 'var(--loss)', fontSize: '13px', marginBottom: '8px' }}>{err}</p>}
        {msg && <p style={{ color: 'var(--profit)', fontSize: '13px', marginBottom: '8px' }}>{msg}</p>}

        <div style={{ marginTop: '8px', marginBottom: '28px' }}>
          <label
            style={{
              fontSize: '12px',
              letterSpacing: '0.04em',
              textTransform: 'uppercase',
              color: 'var(--text-tertiary)',
            }}
          >
            {t('language')}
          </label>
          <p style={{ fontSize: '12px', color: 'var(--text-tertiary)', margin: '6px 0 10px', lineHeight: 1.5 }}>
            {t('languageHelp')}
          </p>
          <div
            role="radiogroup"
            aria-label="Language"
            style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }}
          >
            <button
              type="button"
              role="radio"
              aria-checked={language === 'en'}
              onClick={() => chooseLanguage('en')}
              style={{
                textAlign: 'left',
                padding: '12px 14px',
                borderRadius: '8px',
                border:
                  language === 'en'
                    ? '2px solid var(--border-accent, var(--info))'
                    : '2px solid var(--border-secondary)',
                background: language === 'en' ? 'var(--state-info-bg)' : 'var(--bg-secondary)',
                color: 'var(--text-primary)',
                cursor: 'pointer',
              }}
            >
              <div style={{ fontSize: '14px', fontWeight: 700 }}>English</div>
              <div style={{ fontSize: '11px', color: 'var(--text-tertiary)', marginTop: '4px' }}>
                {t('enHelp')}
              </div>
            </button>
            <button
              type="button"
              role="radio"
              aria-checked={language === 'ko'}
              onClick={() => chooseLanguage('ko')}
              style={{
                textAlign: 'left',
                padding: '12px 14px',
                borderRadius: '8px',
                border:
                  language === 'ko'
                    ? '2px solid var(--border-accent, var(--info))'
                    : '2px solid var(--border-secondary)',
                background: language === 'ko' ? 'var(--state-info-bg)' : 'var(--bg-secondary)',
                color: 'var(--text-primary)',
                cursor: 'pointer',
              }}
            >
              <div style={{ fontSize: '14px', fontWeight: 700 }}>한국어</div>
              <div style={{ fontSize: '11px', color: 'var(--text-tertiary)', marginTop: '4px' }}>
                {t('koHelp')}
              </div>
            </button>
          </div>
        </div>

        <div style={{ marginTop: '8px', marginBottom: '8px' }}>
          <label
            style={{
              fontSize: '12px',
              letterSpacing: '0.04em',
              textTransform: 'uppercase',
              color: 'var(--text-tertiary)',
            }}
          >
            {t('tradingMode')}
          </label>
          <p
            style={{
              fontSize: '12px',
              color: 'var(--text-tertiary)',
              margin: '6px 0 10px',
              lineHeight: 1.5,
            }}
          >
            {t('tradingModeHelp')}
          </p>
          <div
            role="radiogroup"
            aria-label="Paper or live trading"
            style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }}
          >
            <button
              type="button"
              role="radio"
              aria-checked={authAlpacaPaperTrading}
              onClick={() => choosePaperOrLive(true)}
              disabled={modeLoading || !authAlpacaConfigured}
              style={{
                textAlign: 'left',
                padding: '12px 14px',
                borderRadius: '8px',
                border: authAlpacaPaperTrading
                  ? '2px solid var(--border-accent, var(--info))'
                  : '2px solid var(--border-secondary)',
                background: authAlpacaPaperTrading ? 'var(--state-info-bg)' : 'var(--bg-secondary)',
                color: 'var(--text-primary)',
                cursor: modeLoading || !authAlpacaConfigured ? 'not-allowed' : 'pointer',
              }}
            >
              <div style={{ fontSize: '14px', fontWeight: 700 }}>{t('paperMoney')}</div>
              <div style={{ fontSize: '11px', color: 'var(--text-tertiary)', marginTop: '4px', lineHeight: 1.35 }}>
                {t('paperMoneyHelp')}
              </div>
            </button>
            <button
              type="button"
              role="radio"
              aria-checked={!authAlpacaPaperTrading}
              onClick={() => choosePaperOrLive(false)}
              disabled={modeLoading || !authAlpacaConfigured}
              style={{
                textAlign: 'left',
                padding: '12px 14px',
                borderRadius: '8px',
                border: !authAlpacaPaperTrading
                  ? '2px solid var(--border-accent, var(--loss))'
                  : '2px solid var(--border-secondary)',
                background: !authAlpacaPaperTrading ? 'var(--state-danger-bg)' : 'var(--bg-secondary)',
                color: 'var(--text-primary)',
                cursor: modeLoading || !authAlpacaConfigured ? 'not-allowed' : 'pointer',
              }}
            >
              <div style={{ fontSize: '14px', fontWeight: 700 }}>{t('realMoney')}</div>
              <div style={{ fontSize: '11px', color: 'var(--text-tertiary)', marginTop: '4px', lineHeight: 1.35 }}>
                {t('realMoneyHelp')}
              </div>
            </button>
          </div>
          {!authAlpacaConfigured && (
            <p style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: '10px', lineHeight: 1.45 }}>
              {t('keysNotSaved')}
            </p>
          )}
        </div>

        {!keysLocked && (
          <form onSubmit={saveKeys}>
            <label style={{ fontSize: '12px' }}>{t('apiKeyId')}</label>
            <input
              type="password"
              autoComplete="off"
              value={key}
              onChange={(e) => setKey(e.target.value)}
              placeholder="PK…"
              disabled={loading || deleting}
              style={{
                display: 'block',
                width: '100%',
                margin: '6px 0 12px',
                padding: '10px',
                borderRadius: '8px',
                border: '1px solid var(--border-secondary)',
                background: 'var(--bg-secondary)',
                color: 'inherit',
              }}
            />
            <label style={{ fontSize: '12px' }}>{t('secretKey')}</label>
            <input
              type="password"
              autoComplete="off"
              value={secret}
              onChange={(e) => setSecret(e.target.value)}
              disabled={loading || deleting}
              style={{
                display: 'block',
                width: '100%',
                margin: '6px 0 16px',
                padding: '10px',
                borderRadius: '8px',
                border: '1px solid var(--border-secondary)',
                background: 'var(--bg-secondary)',
                color: 'inherit',
              }}
            />
            <button type="submit" className="btn-start" disabled={loading || deleting}>
              {loading ? t('saving') : t('saveKeys')}
            </button>
          </form>
        )}

        {keysLocked && (
          <p style={{ fontSize: '12px', color: 'var(--text-tertiary)', marginTop: '12px', lineHeight: 1.5 }}>
            {t('keysSavedText')}
          </p>
        )}

        {!authAlpacaPaperTrading && authAlpacaConfigured && (
          <div style={{ marginTop: '24px' }}>
            <label
              style={{
                fontSize: '12px',
                letterSpacing: '0.04em',
                textTransform: 'uppercase',
                color: 'var(--text-tertiary)',
              }}
            >
              {t('liveAccount')}
            </label>
            {liveLoading && !liveSummary ? (
              <p style={{ fontSize: '12px', color: 'var(--text-tertiary)', marginTop: '8px' }}>{t('loadingBalances')}</p>
            ) : liveSummary ? (
              <ul
                style={{
                  listStyle: 'none',
                  padding: 0,
                  margin: '10px 0 0',
                  fontSize: '13px',
                  lineHeight: 1.7,
                  color: 'var(--text-secondary)',
                }}
              >
                <li>
                  <strong style={{ color: 'var(--text-primary)' }}>{t('equity')}</strong> {fmtUsd(liveSummary.equity)}
                </li>
                <li>
                  <strong style={{ color: 'var(--text-primary)' }}>{t('cash')}</strong> {fmtUsd(liveSummary.cash)}
                </li>
                <li>
                  <strong style={{ color: 'var(--text-primary)' }}>{t('buyingPower')}</strong>{' '}
                  {fmtUsd(liveSummary.buying_power)}
                </li>
                <li>
                  <strong style={{ color: 'var(--text-primary)' }}>{t('portfolioValue')}</strong>{' '}
                  {fmtUsd(liveSummary.portfolio_value)}
                </li>
              </ul>
            ) : (
              <p style={{ fontSize: '12px', color: 'var(--loss)', marginTop: '8px' }}>
                {t('liveBalancesError')}
              </p>
            )}
          </div>
        )}

        {authAlpacaPaperTrading && (
        <div style={{ marginTop: '32px' }}>
          <label
            style={{
              fontSize: '12px',
              letterSpacing: '0.04em',
              textTransform: 'uppercase',
              color: 'var(--text-tertiary)',
            }}
          >
            {t('capitalScale')}
          </label>
          <p
            style={{
              fontSize: '12px',
              color: 'var(--text-tertiary)',
              margin: '6px 0 10px',
              lineHeight: 1.5,
            }}
          >
            {t('capitalScaleHelp')}
          </p>
          <div
            role="radiogroup"
            aria-label="Capital scale"
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(3, 1fr)',
              gap: '8px',
            }}
          >
            {SCALE_OPTIONS.map((opt) => {
              const selected = scale === opt.id;
              return (
                <button
                  key={opt.id}
                  type="button"
                  role="radio"
                  aria-checked={selected}
                  onClick={() => chooseScale(opt.id)}
                  disabled={scaleLoading}
                  style={{
                    textAlign: 'left',
                    padding: '10px 12px',
                    borderRadius: '8px',
                    border: selected
                      ? '2px solid var(--border-accent, var(--info))'
                      : '2px solid var(--border-secondary)',
                    background: selected ? 'var(--state-info-bg)' : 'var(--bg-secondary)',
                    color: 'inherit',
                    cursor: scaleLoading ? 'not-allowed' : 'pointer',
                    opacity: 1,
                    transition: 'border-color 120ms, background 120ms',
                  }}
                >
                  <div style={{ fontSize: '13px', fontWeight: 600 }}>{opt.title}</div>
                  <div style={{ fontSize: '11px', color: 'var(--text-tertiary)', marginTop: '2px', lineHeight: 1.3 }}>
                    {opt.caption}
                  </div>
                </button>
              );
            })}
          </div>
          {scaleMsg && (
            <p style={{ color: 'var(--profit)', fontSize: '12px', marginTop: '8px' }}>{scaleMsg}</p>
          )}
        </div>
        )}

        <div style={{ marginTop: '36px' }}>
          <label
            style={{
              fontSize: '12px',
              letterSpacing: '0.04em',
              textTransform: 'uppercase',
              color: 'var(--text-tertiary)',
            }}
          >
            {t('telegramAlerts')}
          </label>
          <p style={{ fontSize: '12px', color: 'var(--text-tertiary)', margin: '6px 0 14px', lineHeight: 1.55 }}>
            Trading alerts (bot start/stop, daily summary, loss limit, target hit, regime changes) can be sent to
            Telegram. Add <strong>TELEGRAM_BOT_TOKEN</strong> to server <code style={{ fontSize: '11px' }}>.env</code>{' '}
            (<a href="https://core.telegram.org/bots/tutorial" target="_blank" rel="noreferrer" style={{ color: 'var(--info)', textDecoration: 'none' }}>
              bot setup
            </a>
            ), then paste your <strong>chat ID</strong> here.
          </p>
          {!tgBotOk && (
            <p style={{ fontSize: '12px', color: 'var(--loss)', marginBottom: '10px' }}>
              Telegram is not configured on the server (<code>TELEGRAM_BOT_TOKEN</code> missing).
            </p>
          )}
          <label style={{ display: 'flex', alignItems: 'center', gap: '10px', fontSize: '13px', marginBottom: '8px' }}>
            <input
              type="checkbox"
              checked={notifyTg}
              onChange={(e) => setNotifyTg(e.target.checked)}
              disabled={!tgBotOk}
            />
            Send alerts to Telegram
          </label>
          <label style={{ fontSize: '12px' }}>Telegram chat ID</label>
          <input
            type="text"
            value={tgChatId}
            onChange={(e) => setTgChatId(e.target.value)}
            placeholder="e.g. 123456789 (from @userinfobot or getUpdates)"
            disabled={!tgBotOk}
            style={{
              display: 'block',
              width: '100%',
              margin: '6px 0 14px',
              padding: '10px',
              borderRadius: '8px',
              border: '2px solid var(--border-secondary)',
              background: 'var(--bg-secondary)',
              color: 'inherit',
            }}
          />
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '10px', marginTop: '4px' }}>
            <button
              type="button"
              className="btn-start"
              onClick={() => void saveNotificationPrefs()}
              disabled={notifSaving}
            >
              {notifSaving ? t('saving') : t('saveAlertPreferences')}
            </button>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => void sendTestNotification()}
              disabled={notifLoading || !notifyTg}
            >
              {notifLoading ? t('sending') : t('sendTest')}
            </button>
          </div>
          {notifMsg && (
            <p style={{ color: 'var(--profit)', fontSize: '12px', marginTop: '10px' }}>{notifMsg}</p>
          )}
        </div>

        <div
          className="card card-border-subtle"
          style={{
            marginTop: '28px',
            padding: '18px',
          }}
        >
          <h3 style={{ fontSize: '15px', marginBottom: '8px', fontWeight: 600 }}>{t('taxExportTitle')}</h3>
          <p style={{ fontSize: '13px', color: 'var(--text-secondary)', lineHeight: 1.55, marginBottom: '14px' }}>
            {t('taxExportHelp')}
          </p>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '10px', alignItems: 'center' }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px' }}>
              <span style={{ color: 'var(--text-secondary)' }}>{t('taxExportYear')}</span>
              <input
                type="number"
                min={2000}
                max={2100}
                value={taxYear}
                onChange={(e) => setTaxYear(Number(e.target.value) || taxYear)}
                style={{
                  width: '88px',
                  padding: '8px 10px',
                  borderRadius: '8px',
                  border: '1px solid var(--border-default)',
                  background: 'var(--bg-elevated)',
                  color: 'var(--text-primary)',
                  fontSize: '13px',
                }}
              />
            </label>
            <button
              type="button"
              className="btn btn-secondary"
              disabled={taxExporting}
              onClick={() => {
                setTaxExportErr(null);
                setTaxExporting(true);
                void api
                  .downloadTaxExportCsv(taxYear)
                  .catch((e: unknown) => {
                    setTaxExportErr(e instanceof Error ? e.message : String(e));
                  })
                  .finally(() => setTaxExporting(false));
              }}
            >
              {taxExporting ? t('taxExporting') : t('taxExportDownload')}
            </button>
          </div>
          {taxExportErr && (
            <p style={{ color: 'var(--loss)', fontSize: '12px', marginTop: '10px' }}>{taxExportErr}</p>
          )}
        </div>

        <button
          type="button"
          className="btn btn-danger"
          onClick={signOut}
          style={{ marginTop: '40px', width: '100%' }}
        >
          {t('signOut')}
        </button>
      </div>

      {confirmDeleteOpen && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            background: 'var(--bg-overlay)',
            backdropFilter: 'blur(3px)',
            WebkitBackdropFilter: 'blur(3px)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1200,
            padding: '16px',
          }}
        >
          <div
            className="card"
            style={{
              width: '100%',
              maxWidth: '460px',
              padding: '20px',
              borderColor: 'var(--border-accent)',
            }}
          >
            <h3 style={{ fontSize: '18px', marginBottom: '8px' }}>{t('deleteKeys')}?</h3>
            <p style={{ fontSize: '14px', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
              {language === 'ko'
                ? '현재 저장된 키 쌍이 삭제됩니다. 새 키를 추가할 때까지 거래는 비활성화됩니다.'
                : 'This will remove your currently saved key pair. Trading will stay disabled until you add a new key pair.'}
            </p>
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '18px' }}>
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => setConfirmDeleteOpen(false)}
                disabled={deleting}
              >
                {language === 'ko' ? '취소' : 'Cancel'}
              </button>
              <button
                type="button"
                className="btn btn-danger"
                onClick={async () => {
                  await deleteKeys();
                  setConfirmDeleteOpen(false);
                }}
                disabled={deleting}
              >
                {deleting ? t('deleting') : t('deleteKeys')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default SettingsPage;
