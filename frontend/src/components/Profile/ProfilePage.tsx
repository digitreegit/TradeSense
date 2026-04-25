import React from 'react';
import { useAppStore } from '../../stores/useAppStore';
import { profilePageCopy } from '../../locale/profilePageCopy';
import type { AppLocale, ColorTheme } from '../../stores/types';

const ProfilePage: React.FC = () => {
  const { authEmail, authAlpacaConfigured, colorTheme, setColorTheme, appLocale, setAppLocale } =
    useAppStore();

  const t = profilePageCopy[appLocale];

  const chooseTheme = (next: ColorTheme) => {
    if (next === colorTheme) return;
    setColorTheme(next);
  };

  const chooseLocale = (next: AppLocale) => {
    if (next === appLocale) return;
    setAppLocale(next);
  };

  return (
    <div className="page-enter" style={{ maxWidth: 520, margin: '0 auto', padding: 'var(--space-xl)' }}>
      <div className="card" style={{ padding: 'var(--space-xl)' }}>
        <h2 style={{ fontSize: '18px', marginBottom: '16px' }}>{t.pageTitle}</h2>
        <p style={{ fontSize: '14px', color: 'var(--text-secondary)', marginBottom: '8px' }}>
          <span style={{ color: 'var(--text-tertiary)' }}>{t.emailLabel}</span>
          <br />
          <strong>{authEmail || '—'}</strong>
        </p>
        <p style={{ fontSize: '13px', color: 'var(--text-tertiary)', marginTop: '12px' }}>
          Alpaca paper keys: {authAlpacaConfigured ? t.alpacaSaved : t.alpacaNotSet}
        </p>

        <div style={{ marginTop: '28px' }}>
          <label
            style={{
              fontSize: '12px',
              letterSpacing: '0.04em',
              textTransform: 'uppercase',
              color: 'var(--text-tertiary)',
              display: 'block',
              marginBottom: '10px',
            }}
          >
            {t.languageLabel}
          </label>
          <p style={{ fontSize: '12px', color: 'var(--text-tertiary)', marginBottom: '12px', lineHeight: 1.5 }}>
            {t.languageDescription}
          </p>
          <div
            role="radiogroup"
            aria-label={t.languageLabel}
            style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }}
          >
            <button
              type="button"
              role="radio"
              aria-checked={appLocale === 'en'}
              onClick={() => chooseLocale('en')}
              style={{
                textAlign: 'left',
                padding: '12px 14px',
                borderRadius: '8px',
                border:
                  appLocale === 'en'
                    ? '3px solid var(--border-accent, var(--info))'
                    : '2px solid var(--border-secondary)',
                background: appLocale === 'en' ? 'var(--bg-tertiary)' : 'var(--bg-secondary)',
                color: 'var(--text-primary)',
                cursor: 'pointer',
              }}
            >
              <div style={{ fontSize: '14px', fontWeight: 700 }}>{t.english}</div>
              <div style={{ fontSize: '11px', color: 'var(--text-tertiary)', marginTop: '4px' }}>
                {t.languageEnglishSub}
              </div>
            </button>
            <button
              type="button"
              role="radio"
              aria-checked={appLocale === 'ko'}
              onClick={() => chooseLocale('ko')}
              style={{
                textAlign: 'left',
                padding: '12px 14px',
                borderRadius: '8px',
                border:
                  appLocale === 'ko'
                    ? '3px solid var(--border-accent, var(--info))'
                    : '2px solid var(--border-secondary)',
                background: appLocale === 'ko' ? 'var(--bg-tertiary)' : 'var(--bg-secondary)',
                color: 'var(--text-primary)',
                cursor: 'pointer',
              }}
            >
              <div style={{ fontSize: '14px', fontWeight: 700 }}>{t.korean}</div>
              <div style={{ fontSize: '11px', color: 'var(--text-tertiary)', marginTop: '4px' }}>
                {t.languageKoreanSub}
              </div>
            </button>
          </div>
        </div>

        <div style={{ marginTop: '28px' }}>
          <label
            style={{
              fontSize: '12px',
              letterSpacing: '0.04em',
              textTransform: 'uppercase',
              color: 'var(--text-tertiary)',
              display: 'block',
              marginBottom: '10px',
            }}
          >
            {t.appearanceLabel}
          </label>
          <p style={{ fontSize: '12px', color: 'var(--text-tertiary)', marginBottom: '12px', lineHeight: 1.5 }}>
            {t.appearanceDescription}
          </p>
          <div
            role="radiogroup"
            aria-label={t.appearanceLabel}
            style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }}
          >
            <button
              type="button"
              role="radio"
              aria-checked={colorTheme === 'dark'}
              onClick={() => chooseTheme('dark')}
              style={{
                textAlign: 'left',
                padding: '12px 14px',
                borderRadius: '8px',
                border:
                  colorTheme === 'dark'
                    ? '3px solid var(--border-accent, var(--info))'
                    : '2px solid var(--border-secondary)',
                background: colorTheme === 'dark' ? 'var(--bg-tertiary)' : 'var(--bg-secondary)',
                color: 'var(--text-primary)',
                cursor: 'pointer',
              }}
            >
              <div style={{ fontSize: '14px', fontWeight: 700 }}>{t.dark}</div>
              <div style={{ fontSize: '11px', color: 'var(--text-tertiary)', marginTop: '4px' }}>
                {t.darkSub}
              </div>
            </button>
            <button
              type="button"
              role="radio"
              aria-checked={colorTheme === 'light'}
              onClick={() => chooseTheme('light')}
              style={{
                textAlign: 'left',
                padding: '12px 14px',
                borderRadius: '8px',
                border:
                  colorTheme === 'light'
                    ? '3px solid var(--border-accent, var(--info))'
                    : '2px solid var(--border-secondary)',
                background: colorTheme === 'light' ? 'var(--bg-tertiary)' : 'var(--bg-secondary)',
                color: 'var(--text-primary)',
                cursor: 'pointer',
              }}
            >
              <div style={{ fontSize: '14px', fontWeight: 700 }}>{t.light}</div>
              <div style={{ fontSize: '11px', color: 'var(--text-tertiary)', marginTop: '4px' }}>
                {t.lightSub}
              </div>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default ProfilePage;
