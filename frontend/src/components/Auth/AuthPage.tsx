import React, { useState } from 'react';
import { useAppStore } from '../../stores/useAppStore';
import {
  setLastAuthMethod,
} from '../../auth/token';
import { supabase } from '../../auth/supabase';
import { useI18n } from '../../i18n';
import api from '../../services/api';

/** Official multicolor “G” mark (Google Sign-In branding pattern, 48×48 artboard) */
const GoogleIcon = () => (
  <span className="auth-google-icon-wrap" aria-hidden="true">
    <svg className="auth-google-icon" viewBox="0 0 48 48" width={24} height={24}>
      <path
        fill="#EA4335"
        d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"
      />
      <path
        fill="#4285F4"
        d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6C43.88 39.49 46.98 32.58 46.98 24.55z"
      />
      <path
        fill="#FBBC05"
        d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"
      />
      <path
        fill="#34A853"
        d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"
      />
    </svg>
  </span>
);

const AuthPage: React.FC = () => {
  const { setAuthMethod } = useAppStore();
  const { t } = useI18n();
  const [invitationCode, setInvitationCode] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleGoogle = async () => {
    setError(null);
    setInfo(null);
    setLoading(true);
    try {
      await api.validateInvitation(invitationCode.trim());
    } catch (err) {
      const msg = err instanceof Error ? err.message : '';
      setError(/invalid invitation/i.test(msg) ? t('invitationInvalid') : t('invitationVerifyFailed'));
      setLoading(false);
      return;
    }
    try {
      const redirectTo = `${window.location.origin}/`;
      const { error: oauthErr } = await supabase.auth.signInWithOAuth({
        provider: 'google',
        options: { redirectTo },
      });
      if (oauthErr) throw oauthErr;
      setLastAuthMethod('google');
      setAuthMethod('google');
      setInfo(t('redirecting'));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Google sign-in failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-shell">
      <div className="auth-card">
        <section className="auth-hero" aria-label="TradeSense overview">
          <div>
            <span className="auth-eyebrow">{t('usStocks')}</span>
            <h1 className="auth-title">{t('authTitle')}</h1>
            <p className="auth-subtitle">
              {t('authSubtitle')}
            </p>
          </div>

          <div className="auth-agent-card" aria-hidden="true">
            <div className="auth-agent-row">
              <span>{t('marketSummary')}</span>
              <strong>{t('sectorPerformance')}</strong>
            </div>
            <div className="auth-agent-row">
              <span>{t('mostActive')}</span>
              <strong>NVDA · TSLA · AMD</strong>
            </div>
            <div className="auth-agent-row">
              <span>{t('ideas')}</span>
              <strong>{t('longShortSetups')}</strong>
            </div>
          </div>
        </section>

        <section className="auth-panel" aria-label="Sign in">
          <div className="auth-panel-logo-wrap">
            <img
              src="/logo-ts.svg"
              alt="TradeSense"
              width={150}
              height={150}
              className="auth-panel-logo"
              decoding="async"
            />
          </div>
          <h2 className="auth-panel-title">{t('openTradeSense')}</h2>
          <p className="auth-subtitle">{t('signInWithGoogle')}</p>

          <div className="auth-invitation-field">
            <label className="auth-field-label" htmlFor="invitation-code">
              {t('invitationCode')}
            </label>
            <div className="auth-input-wrap">
              <input
                id="invitation-code"
                type="text"
                className="auth-input auth-invitation-input"
                autoComplete="off"
                spellCheck={false}
                value={invitationCode}
                onChange={(e) => setInvitationCode(e.target.value)}
                placeholder={t('invitationCodePlaceholder')}
                disabled={loading}
              />
            </div>
            {error && (
              <p className="auth-error auth-invitation-error" role="alert">
                {error}
              </p>
            )}
            {info && <p className="auth-info auth-invitation-info">{info}</p>}
          </div>

          <button
            type="button"
            className="auth-google-btn"
            onClick={handleGoogle}
            disabled={loading}
          >
            <GoogleIcon />
            {loading ? t('redirecting') : t('continueWithGoogle')}
          </button>
        </section>
      </div>
    </div>
  );
};

export default AuthPage;
