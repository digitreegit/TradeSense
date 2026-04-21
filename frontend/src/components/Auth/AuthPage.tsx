import React, { useState } from 'react';
import { useAppStore } from '../../stores/useAppStore';
import {
  setLastAuthMethod,
} from '../../auth/token';
import { supabase } from '../../auth/supabase';

const GoogleIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
    <path fill="#EA4335" d="M12 10.2v3.9h5.5c-.2 1.2-1.4 3.5-5.5 3.5-3.3 0-6-2.8-6-6.2s2.7-6.2 6-6.2c1.9 0 3.1.8 3.8 1.5l2.6-2.5C16.9 2.7 14.7 2 12 2 6.9 2 2.8 6.2 2.8 11.4S6.9 20.8 12 20.8c6.9 0 9.1-4.9 9.1-7.4 0-.5 0-.8-.1-1.2H12z" />
    <path fill="#34A853" d="M3.7 7.6l3.2 2.3c.9-1.9 2.7-3.2 5.1-3.2 1.9 0 3.1.8 3.8 1.5l2.6-2.5C16.9 2.7 14.7 2 12 2 8.2 2 4.9 4.2 3.7 7.6z" />
    <path fill="#FBBC05" d="M12 20.8c2.6 0 4.8-.9 6.4-2.5l-3-2.4c-.8.6-1.9 1.1-3.4 1.1-3 0-5.2-2-6-4.6l-3.2 2.4c1.3 3.8 4.8 6 9.2 6z" />
    <path fill="#4285F4" d="M21.1 13.4c0-.5 0-.8-.1-1.2H12v3.9h5.5c-.3 1.4-1.2 2.5-2.1 3.2l3 2.4c1.8-1.6 2.7-4 2.7-6.9z" />
  </svg>
);

const AuthPage: React.FC = () => {
  const { setAuthMethod } = useAppStore();
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleGoogle = async () => {
    setError(null);
    setInfo(null);
    setLoading(true);
    try {
      const redirectTo = `${window.location.origin}/`;
      const { error: oauthErr } = await supabase.auth.signInWithOAuth({
        provider: 'google',
        options: { redirectTo },
      });
      if (oauthErr) throw oauthErr;
      setLastAuthMethod('google');
      setAuthMethod('google');
      setInfo('Redirecting to Google…');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Google sign-in failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-shell">
      <div className="auth-card">
        <h1 className="auth-title">Welcome to TradeSense</h1>
        <p className="auth-subtitle">Sign in with Google to continue</p>

        {error && <p className="auth-error">{error}</p>}
        {info && <p className="auth-info">{info}</p>}

        <button
          type="button"
          className="auth-google-btn"
          onClick={handleGoogle}
          disabled={loading}
        >
          <GoogleIcon />
          {loading ? 'Redirecting…' : 'Continue with Google'}
        </button>
      </div>
    </div>
  );
};

export default AuthPage;
