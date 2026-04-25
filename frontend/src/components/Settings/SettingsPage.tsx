import React, { useEffect, useMemo, useState } from 'react';
import api from '../../services/api';
import { useAppStore } from '../../stores/useAppStore';
import type { AppLocale, ColorTheme } from '../../stores/types';
import { useUiStrings } from '../../hooks/useUiStrings';
import { clearToken } from '../../auth/token';
import { supabase } from '../../auth/supabase';

type CapitalScale = '3k' | '10k' | '30k';

type LiveSummary = {
  equity: number;
  cash: number;
  buying_power: number;
  portfolio_value: number;
};

const fmtUsd = (n: number) =>
  new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 }).format(n);

const selectedBorder2 = (selected: boolean, accent: 'info' | 'loss') =>
  selected
    ? `2px solid var(--border-accent, var(--${accent === 'loss' ? 'loss' : 'info'}))`
    : '2px solid var(--border-secondary)';

/** Section titles (Language, …) — match "Broker & API" / 브로커 · API heading */
const settingsSectionTitleStyle: React.CSSProperties = {
  fontSize: '15px',
  fontWeight: 700,
  margin: '0 0 8px 0',
  color: 'var(--text-primary)',
  display: 'block',
};

/** Smaller caps labels (live account, Telegram, …) */
const settingsSectionLabel: React.CSSProperties = {
  fontSize: '14px',
  fontWeight: 700,
  letterSpacing: '0.04em',
  textTransform: 'uppercase',
  color: 'var(--text-secondary)',
  display: 'block',
};

const SettingsRadioIcon: React.FC<{ selected: boolean; accent: 'info' | 'loss' }> = ({ selected, accent }) => {
  const ring = accent === 'loss' ? 'var(--loss)' : 'var(--info)';
  return (
    <span
      aria-hidden
      style={{
        width: 18,
        height: 18,
        minWidth: 18,
        marginTop: 2,
        borderRadius: '50%',
        border: `2px solid ${selected ? ring : 'var(--border-secondary)'}`,
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        flexShrink: 0,
        background: 'var(--bg-primary)',
      }}
    >
      {selected && (
        <span
          style={{
            width: 8,
            height: 8,
            borderRadius: '50%',
            background: ring,
          }}
        />
      )}
    </span>
  );
};

const SettingsPage: React.FC = () => {
  const t = useUiStrings();
  const {
    authEmail,
    authAlpacaConfigured,
    authAlpacaPaperTrading,
    setAuthProfile,
    setCurrentPage,
    setAuthMethod,
    colorTheme,
    setColorTheme,
    appLocale,
    setAppLocale,
  } = useAppStore();

  const scaleOptions = useMemo(
    () =>
      [
        { id: '3k' as const, title: t.scale3k.title, caption: t.scale3k.cap },
        { id: '10k' as const, title: t.scale10k.title, caption: t.scale10k.cap },
        { id: '30k' as const, title: t.scale30k.title, caption: t.scale30k.cap },
      ] as const,
    [t],
  );

  const chooseTheme = (next: ColorTheme) => {
    if (next === colorTheme) return;
    setColorTheme(next);
  };

  const chooseLocale = (next: AppLocale) => {
    if (next === appLocale) return;
    setAppLocale(next);
  };
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
      setErr(t.settings.errSaveFirst);
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
          ? t.settings.msgSwitchedPaper
          : t.settings.msgSwitchedLive,
      );
    } catch (e) {
      setErr(e instanceof Error ? e.message : t.settings.modeChangeFail);
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
      setNotifMsg(t.settings.notifSaved);
    } catch (e) {
      setErr(e instanceof Error ? e.message : t.settings.notifSaveFail);
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
      setNotifMsg(t.settings.testSent(res.message || ''));
    } catch (e) {
      setErr(e instanceof Error ? e.message : t.settings.testFail);
    } finally {
      setNotifLoading(false);
    }
  };

  const chooseScale = async (next: CapitalScale) => {
    if (!authAlpacaPaperTrading) {
      setErr(t.settings.errPaperOnly);
      return;
    }
    if (next === scale || scaleLoading) return;
    setScaleLoading(true);
    setScaleMsg(null);
    setErr(null);
    try {
      const info = await api.setCapitalScale(next);
      setScale(info.scale);
      setScaleMsg(t.settings.scaleSwitched(String(info.scale), String(info.level)));
    } catch (e) {
      setErr(e instanceof Error ? e.message : t.settings.scaleFail);
    } finally {
      setScaleLoading(false);
    }
  };

  const saveKeys = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr(null);
    setMsg(null);
    if (keysLocked) {
      setErr(t.settings.errDeleteFirst);
      return;
    }
    if (!key.trim() || !secret.trim()) {
      setErr(t.settings.errBothKeys);
      return;
    }
    setLoading(true);
    try {
      await api.saveAlpacaKeys(key.trim(), secret.trim());
      setAuthProfile(authEmail, true, true);
      setKey('');
      setSecret('');
      setMsg(t.settings.keysSaved);
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : t.settings.saveFail);
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
      setMsg(t.settings.keysDeleted);
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : t.settings.deleteFail);
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

  return (
    <div
      className="page-enter"
      style={{
        width: '100%',
        maxWidth: 'min(1200px, 66.67vw)',
        margin: '0 auto',
        padding: 'var(--space-xl)',
        boxSizing: 'border-box',
      }}
    >
      <div className="card" style={{ padding: 'var(--space-xl)' }}>
        <h2 style={{ fontSize: '18px', marginBottom: '8px' }}>{t.settings.settingsTitle}</h2>

        <div style={{ marginBottom: '28px', paddingBottom: '24px', borderBottom: '1px solid var(--border-secondary)' }}>
          <label style={settingsSectionTitleStyle}>
            {t.settings.languageLabel}
          </label>
          <p style={{ fontSize: '12px', color: 'var(--text-tertiary)', marginBottom: '12px', lineHeight: 1.5 }}>
            {t.settings.languageDescription}
          </p>
          <div
            role="radiogroup"
            aria-label={t.settings.languageLabel}
            style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px', maxWidth: 560 }}
          >
            <button
              type="button"
              role="radio"
              aria-checked={appLocale === 'en'}
              onClick={() => chooseLocale('en')}
              style={{
                display: 'flex',
                gap: 12,
                alignItems: 'flex-start',
                textAlign: 'left',
                padding: '12px 14px',
                borderRadius: 'var(--btn-radius)',
                border: selectedBorder2(appLocale === 'en', 'info'),
                background: appLocale === 'en' ? 'var(--bg-tertiary)' : 'var(--bg-secondary)',
                color: 'var(--text-primary)',
                cursor: 'pointer',
              }}
            >
              <SettingsRadioIcon selected={appLocale === 'en'} accent="info" />
              <div>
                <div style={{ fontSize: '14px', fontWeight: 700 }}>{t.settings.english}</div>
                <div style={{ fontSize: '11px', color: 'var(--text-tertiary)', marginTop: '4px' }}>
                  {t.settings.languageEnglishSub}
                </div>
              </div>
            </button>
            <button
              type="button"
              role="radio"
              aria-checked={appLocale === 'ko'}
              onClick={() => chooseLocale('ko')}
              style={{
                display: 'flex',
                gap: 12,
                alignItems: 'flex-start',
                textAlign: 'left',
                padding: '12px 14px',
                borderRadius: 'var(--btn-radius)',
                border: selectedBorder2(appLocale === 'ko', 'info'),
                background: appLocale === 'ko' ? 'var(--bg-tertiary)' : 'var(--bg-secondary)',
                color: 'var(--text-primary)',
                cursor: 'pointer',
              }}
            >
              <SettingsRadioIcon selected={appLocale === 'ko'} accent="info" />
              <div>
                <div style={{ fontSize: '14px', fontWeight: 700 }}>{t.settings.korean}</div>
                <div style={{ fontSize: '11px', color: 'var(--text-tertiary)', marginTop: '4px' }}>
                  {t.settings.languageKoreanSub}
                </div>
              </div>
            </button>
          </div>
        </div>

        <div style={{ marginBottom: '28px', paddingBottom: '24px', borderBottom: '1px solid var(--border-secondary)' }}>
          <label style={settingsSectionTitleStyle}>
            {t.settings.appearanceLabel}
          </label>
          <p style={{ fontSize: '12px', color: 'var(--text-tertiary)', marginBottom: '12px', lineHeight: 1.5 }}>
            {t.settings.appearanceDescription}
          </p>
          <div
            role="radiogroup"
            aria-label={t.settings.appearanceLabel}
            style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px', maxWidth: 560 }}
          >
            <button
              type="button"
              role="radio"
              aria-checked={colorTheme === 'dark'}
              onClick={() => chooseTheme('dark')}
              style={{
                display: 'flex',
                gap: 12,
                alignItems: 'flex-start',
                textAlign: 'left',
                padding: '12px 14px',
                borderRadius: 'var(--btn-radius)',
                border: selectedBorder2(colorTheme === 'dark', 'info'),
                background: colorTheme === 'dark' ? 'var(--bg-tertiary)' : 'var(--bg-secondary)',
                color: 'var(--text-primary)',
                cursor: 'pointer',
              }}
            >
              <SettingsRadioIcon selected={colorTheme === 'dark'} accent="info" />
              <div>
                <div style={{ fontSize: '14px', fontWeight: 700 }}>{t.settings.dark}</div>
                <div style={{ fontSize: '11px', color: 'var(--text-tertiary)', marginTop: '4px' }}>
                  {t.settings.darkSub}
                </div>
              </div>
            </button>
            <button
              type="button"
              role="radio"
              aria-checked={colorTheme === 'light'}
              onClick={() => chooseTheme('light')}
              style={{
                display: 'flex',
                gap: 12,
                alignItems: 'flex-start',
                textAlign: 'left',
                padding: '12px 14px',
                borderRadius: 'var(--btn-radius)',
                border: selectedBorder2(colorTheme === 'light', 'info'),
                background: colorTheme === 'light' ? 'var(--bg-tertiary)' : 'var(--bg-secondary)',
                color: 'var(--text-primary)',
                cursor: 'pointer',
              }}
            >
              <SettingsRadioIcon selected={colorTheme === 'light'} accent="info" />
              <div>
                <div style={{ fontSize: '14px', fontWeight: 700 }}>{t.settings.light}</div>
                <div style={{ fontSize: '11px', color: 'var(--text-tertiary)', marginTop: '4px' }}>
                  {t.settings.lightSub}
                </div>
              </div>
            </button>
          </div>
        </div>

        <h3 style={settingsSectionTitleStyle}>
          {t.settings.brokerSectionTitle}
        </h3>
        <p style={{ fontSize: '13px', color: 'var(--text-tertiary)', marginBottom: '20px', lineHeight: 1.5 }}>
          {t.settings.connectIntro}{' '}
          <a
            href="https://app.alpaca.markets/paper/dashboard/overview"
            target="_blank"
            rel="noreferrer"
            style={{ color: 'var(--info)', textDecoration: 'none' }}
          >
            {t.settings.paperLink}
          </a>
          {' · '}
          <a
            href="https://app.alpaca.markets/dashboard/overview"
            target="_blank"
            rel="noreferrer"
            style={{ color: 'var(--info)', textDecoration: 'none' }}
          >
            {t.settings.liveLink}
          </a>
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
          {t.settings.signedIn} <strong>{authEmail}</strong>
          {authAlpacaConfigured ? t.settings.keysOnFile : t.settings.keysNotConfig}
          {authAlpacaConfigured && (
            <button
              type="button"
              className="btn btn-danger btn-sm"
              onClick={() => setConfirmDeleteOpen(true)}
              disabled={deleting || loading}
            >
              {deleting ? t.settings.deleting : t.settings.deleteKeys}
            </button>
          )}
        </p>
        {err && <p style={{ color: 'var(--loss)', fontSize: '13px', marginBottom: '8px' }}>{err}</p>}
        {msg && <p style={{ color: 'var(--profit)', fontSize: '13px', marginBottom: '8px' }}>{msg}</p>}

        <div
          style={{
            marginTop: '28px',
            paddingTop: '24px',
            borderTop: '1px solid var(--border-secondary)',
            marginBottom: '8px',
          }}
        >
          <label style={settingsSectionTitleStyle}>
            {t.settings.tradingMode}
          </label>
          <p
            style={{
              fontSize: '12px',
              color: 'var(--text-tertiary)',
              margin: '6px 0 10px',
              lineHeight: 1.5,
            }}
          >
            {t.settings.tradingModeDesc}
          </p>
          <div
            role="radiogroup"
            aria-label={t.settings.tradingMode}
            style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }}
          >
            <button
              type="button"
              role="radio"
              aria-checked={authAlpacaPaperTrading}
              onClick={() => choosePaperOrLive(true)}
              disabled={modeLoading || !authAlpacaConfigured}
              style={{
                display: 'flex',
                gap: 12,
                alignItems: 'flex-start',
                textAlign: 'left',
                padding: '12px 14px',
                borderRadius: 'var(--btn-radius)',
                border: selectedBorder2(authAlpacaPaperTrading, 'info'),
                background: authAlpacaPaperTrading
                  ? 'var(--bg-tertiary, rgba(56,132,255,0.12))'
                  : 'var(--bg-secondary)',
                color: 'var(--text-primary)',
                cursor: modeLoading || !authAlpacaConfigured ? 'not-allowed' : 'pointer',
              }}
            >
              <SettingsRadioIcon selected={authAlpacaPaperTrading} accent="info" />
              <div>
                <div style={{ fontSize: '14px', fontWeight: 700 }}>{t.settings.paperMoney}</div>
                <div style={{ fontSize: '11px', color: 'var(--text-tertiary)', marginTop: '4px', lineHeight: 1.35 }}>
                  {t.settings.paperSub}
                </div>
              </div>
            </button>
            <button
              type="button"
              role="radio"
              aria-checked={!authAlpacaPaperTrading}
              onClick={() => choosePaperOrLive(false)}
              disabled={modeLoading || !authAlpacaConfigured}
              style={{
                display: 'flex',
                gap: 12,
                alignItems: 'flex-start',
                textAlign: 'left',
                padding: '12px 14px',
                borderRadius: 'var(--btn-radius)',
                border: selectedBorder2(!authAlpacaPaperTrading, 'loss'),
                background: !authAlpacaPaperTrading
                  ? 'var(--bg-tertiary, rgba(239,68,68,0.10))'
                  : 'var(--bg-secondary)',
                color: 'var(--text-primary)',
                cursor: modeLoading || !authAlpacaConfigured ? 'not-allowed' : 'pointer',
              }}
            >
              <SettingsRadioIcon selected={!authAlpacaPaperTrading} accent="loss" />
              <div>
                <div style={{ fontSize: '14px', fontWeight: 700 }}>{t.settings.realMoney}</div>
                <div style={{ fontSize: '11px', color: 'var(--text-tertiary)', marginTop: '4px', lineHeight: 1.35 }}>
                  {t.settings.realSub}
                </div>
              </div>
            </button>
          </div>
          {!authAlpacaConfigured && (
            <p style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: '10px', lineHeight: 1.45 }}>
              {t.settings.keysHintInactive}
            </p>
          )}
        </div>

        {!keysLocked && (
          <form onSubmit={saveKeys}>
            <label style={{ fontSize: '12px' }}>{t.settings.keyId}</label>
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
                borderRadius: 'var(--btn-radius)',
                border: '1px solid var(--border-secondary)',
                background: 'var(--bg-secondary)',
                color: 'inherit',
              }}
            />
            <label style={{ fontSize: '12px' }}>{t.settings.secret}</label>
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
                borderRadius: 'var(--btn-radius)',
                border: '1px solid var(--border-secondary)',
                background: 'var(--bg-secondary)',
                color: 'inherit',
              }}
            />
            <button type="submit" className="btn-start" disabled={loading || deleting}>
              {loading ? t.settings.saving : t.settings.saveKeys}
            </button>
          </form>
        )}

        {keysLocked && (
          <p style={{ fontSize: '12px', color: 'var(--text-tertiary)', marginTop: '12px', lineHeight: 1.5 }}>
            {t.settings.keysOnFileNote}
          </p>
        )}

        {!authAlpacaPaperTrading && authAlpacaConfigured && (
          <div style={{ marginTop: '24px' }}>
            <label style={settingsSectionLabel}>
              {t.settings.liveAccount}
            </label>
            {liveLoading && !liveSummary ? (
              <p style={{ fontSize: '12px', color: 'var(--text-tertiary)', marginTop: '8px' }}>{t.settings.loadingBalances}</p>
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
                  <strong style={{ color: 'var(--text-primary)' }}>{t.settings.equity}</strong> {fmtUsd(liveSummary.equity)}
                </li>
                <li>
                  <strong style={{ color: 'var(--text-primary)' }}>{t.settings.cash}</strong> {fmtUsd(liveSummary.cash)}
                </li>
                <li>
                  <strong style={{ color: 'var(--text-primary)' }}>{t.settings.buyPower}</strong>{' '}
                  {fmtUsd(liveSummary.buying_power)}
                </li>
                <li>
                  <strong style={{ color: 'var(--text-primary)' }}>{t.settings.portValue}</strong>{' '}
                  {fmtUsd(liveSummary.portfolio_value)}
                </li>
              </ul>
            ) : (
              <p style={{ fontSize: '12px', color: 'var(--loss)', marginTop: '8px' }}>
                {t.settings.liveLoadErr}
              </p>
            )}
          </div>
        )}

        {authAlpacaPaperTrading && (
          <div style={{ marginTop: '32px' }}>
            <label style={settingsSectionTitleStyle}>
              {t.settings.capitalScale}
            </label>
            <p
              style={{
                fontSize: '12px',
                color: 'var(--text-tertiary)',
                margin: '6px 0 10px',
                lineHeight: 1.5,
              }}
            >
              {t.settings.capitalScaleDesc}
            </p>
            <div
              role="radiogroup"
              aria-label={t.settings.capitalScale}
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(3, 1fr)',
                gap: '8px',
              }}
            >
              {scaleOptions.map((opt) => {
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
                      display: 'flex',
                      gap: 10,
                      alignItems: 'flex-start',
                      textAlign: 'left',
                      padding: '10px 12px',
                      borderRadius: 'var(--btn-radius)',
                      border: selectedBorder2(selected, 'info'),
                      background: selected ? 'var(--bg-tertiary, rgba(56,132,255,0.10))' : 'var(--bg-secondary)',
                      color: 'inherit',
                      cursor: scaleLoading ? 'not-allowed' : 'pointer',
                      transition: 'border-color 120ms, background 120ms',
                    }}
                  >
                    <SettingsRadioIcon selected={selected} accent="info" />
                    <div>
                      <div style={{ fontSize: '13px', fontWeight: 600 }}>{opt.title}</div>
                      <div style={{ fontSize: '11px', color: 'var(--text-tertiary)', marginTop: '2px', lineHeight: 1.3 }}>
                        {opt.caption}
                      </div>
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

        <div
          style={{
            marginTop: '28px',
            paddingTop: '24px',
            borderTop: '1px solid var(--border-secondary)',
          }}
        >
          <label style={settingsSectionLabel}>
            {t.settings.telegram}
          </label>
          <p style={{ fontSize: '12px', color: 'var(--text-tertiary)', margin: '6px 0 14px', lineHeight: 1.55 }}>
            {t.settings.telegramPStart}{' '}
            <strong>TELEGRAM_BOT_TOKEN</strong> {t.settings.telegramPMid}{' '}
            <code style={{ fontSize: '11px' }}>.env</code>{' '}
            (
            <a
              href="https://core.telegram.org/bots/tutorial"
              target="_blank"
              rel="noreferrer"
              style={{ color: 'var(--info)', textDecoration: 'none' }}
            >
              {t.settings.telegramSetup}
            </a>
            ), {t.settings.telegramPEnd}
          </p>
          {!tgBotOk && (
            <p style={{ fontSize: '12px', color: 'var(--loss)', marginBottom: '10px' }}>
              {t.settings.tgNotConfig}
            </p>
          )}
          <label style={{ display: 'flex', alignItems: 'center', gap: '10px', fontSize: '13px', marginBottom: '8px' }}>
            <input
              type="checkbox"
              checked={notifyTg}
              onChange={(e) => setNotifyTg(e.target.checked)}
              disabled={!tgBotOk}
            />
            {t.settings.sendTg}
          </label>
          <label style={{ fontSize: '12px' }}>{t.settings.telegramChatId}</label>
          <input
            type="text"
            value={tgChatId}
            onChange={(e) => setTgChatId(e.target.value)}
            placeholder={t.settings.telegramChatPlaceholder}
            disabled={!tgBotOk}
            style={{
              display: 'block',
              width: '100%',
              margin: '6px 0 14px',
              padding: '10px',
              borderRadius: 'var(--btn-radius)',
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
              {notifSaving ? t.settings.saving : t.settings.saveAlerts}
            </button>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => void sendTestNotification()}
              disabled={notifLoading || !notifyTg}
            >
              {notifLoading ? t.settings.sending : t.settings.sendTest}
            </button>
          </div>
          {notifMsg && (
            <p style={{ color: 'var(--profit)', fontSize: '12px', marginTop: '10px' }}>{notifMsg}</p>
          )}
        </div>

        <button
          type="button"
          className="btn btn-danger"
          onClick={signOut}
          style={{ marginTop: '40px', width: '100%' }}
        >
          {t.settings.signOut}
        </button>
      </div>

      {confirmDeleteOpen && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0, 0, 0, 0.65)',
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
            <h3 style={{ fontSize: '18px', marginBottom: '8px' }}>{t.settings.deleteModalTitle}</h3>
            <p style={{ fontSize: '14px', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
              {t.settings.deleteModalBody}
            </p>
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '18px' }}>
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => setConfirmDeleteOpen(false)}
                disabled={deleting}
              >
                {t.common.cancel}
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
                {deleting ? t.settings.deleting : t.settings.deleteKeys}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default SettingsPage;
