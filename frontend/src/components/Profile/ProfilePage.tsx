import React from 'react';
import { useAppStore } from '../../stores/useAppStore';
import type { ColorTheme } from '../../stores/types';

const ProfilePage: React.FC = () => {
  const { authEmail, authAlpacaConfigured, colorTheme, setColorTheme } = useAppStore();

  const chooseTheme = (next: ColorTheme) => {
    if (next === colorTheme) return;
    setColorTheme(next);
  };

  return (
    <div className="page-enter" style={{ maxWidth: 520, margin: '0 auto', padding: 'var(--space-xl)' }}>
      <div className="card" style={{ padding: 'var(--space-xl)' }}>
        <h2 style={{ fontSize: '18px', marginBottom: '16px' }}>Profile</h2>
        <p style={{ fontSize: '14px', color: 'var(--text-secondary)', marginBottom: '8px' }}>
          <span style={{ color: 'var(--text-tertiary)' }}>Email</span>
          <br />
          <strong>{authEmail || '—'}</strong>
        </p>
        <p style={{ fontSize: '13px', color: 'var(--text-tertiary)', marginTop: '12px' }}>
          Alpaca paper keys: {authAlpacaConfigured ? 'saved on server (encrypted)' : 'not set — add them in Settings'}
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
            Appearance
          </label>
          <p style={{ fontSize: '12px', color: 'var(--text-tertiary)', marginBottom: '12px', lineHeight: 1.5 }}>
            Theme applies across the app and is saved on this browser.
          </p>
          <div
            role="radiogroup"
            aria-label="Color theme"
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
              <div style={{ fontSize: '14px', fontWeight: 700 }}>Dark</div>
              <div style={{ fontSize: '11px', color: 'var(--text-tertiary)', marginTop: '4px' }}>
                Default trading dashboard
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
              <div style={{ fontSize: '14px', fontWeight: 700 }}>Light</div>
              <div style={{ fontSize: '11px', color: 'var(--text-tertiary)', marginTop: '4px' }}>
                Bright UI for daytime
              </div>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default ProfilePage;
