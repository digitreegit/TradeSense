import React, { useMemo, useState } from 'react';
import { useAppStore } from '../../stores/useAppStore';
import {
  getLastAuthMethod,
  setLastAuthMethod,
  setToken,
  type AuthMethod,
} from '../../auth/token';
import { supabase } from '../../auth/supabase';

type Mode = 'register' | 'login' | 'forgot';

const GoogleIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
    <path fill="#EA4335" d="M12 10.2v3.9h5.5c-.2 1.2-1.4 3.5-5.5 3.5-3.3 0-6-2.8-6-6.2s2.7-6.2 6-6.2c1.9 0 3.1.8 3.8 1.5l2.6-2.5C16.9 2.7 14.7 2 12 2 6.9 2 2.8 6.2 2.8 11.4S6.9 20.8 12 20.8c6.9 0 9.1-4.9 9.1-7.4 0-.5 0-.8-.1-1.2H12z" />
    <path fill="#34A853" d="M3.7 7.6l3.2 2.3c.9-1.9 2.7-3.2 5.1-3.2 1.9 0 3.1.8 3.8 1.5l2.6-2.5C16.9 2.7 14.7 2 12 2 8.2 2 4.9 4.2 3.7 7.6z" />
    <path fill="#FBBC05" d="M12 20.8c2.6 0 4.8-.9 6.4-2.5l-3-2.4c-.8.6-1.9 1.1-3.4 1.1-3 0-5.2-2-6-4.6l-3.2 2.4c1.3 3.8 4.8 6 9.2 6z" />
    <path fill="#4285F4" d="M21.1 13.4c0-.5 0-.8-.1-1.2H12v3.9h5.5c-.3 1.4-1.2 2.5-2.1 3.2l3 2.4c1.8-1.6 2.7-4 2.7-6.9z" />
  </svg>
);

const AuthPage: React.FC = () => {
  const { setAuthMethod, setAuthProfile } = useAppStore();
  const [mode, setMode] = useState<Mode>('register');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [lastUsed, setLastUsed] = useState<AuthMethod | null>(getLastAuthMethod());

  const subtitle = useMemo(() => {
    if (mode === 'register') return 'Create a new account';
    if (mode === 'login') return 'Sign in to your account';
    return "Enter your email and we'll send a reset link";
  }, [mode]);

  const captureSession = async () => {
    const { data, error: sessionErr } = await supabase.auth.getSession();
    if (sessionErr) throw sessionErr;
    const token = data.session?.access_token;
    const userEmail = data.session?.user?.email;
    if (!token || !userEmail) throw new Error('No active Supabase session');
    setToken(token);
    setAuthProfile(userEmail, false);
  };

  const submitEmailAuth = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setInfo(null);
    setLoading(true);
    try {
      if (mode === 'register') {
        const { error: signUpErr } = await supabase.auth.signUp({ email, password });
        if (signUpErr) throw signUpErr;
      } else {
        const { error: signInErr } = await supabase.auth.signInWithPassword({ email, password });
        if (signInErr) throw signInErr;
      }
      await captureSession();
      setLastUsed('email');
      setLastAuthMethod('email');
      setAuthMethod('email');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Request failed');
    } finally {
      setLoading(false);
    }
  };

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
      setLastUsed('google');
      setLastAuthMethod('google');
      setAuthMethod('google');
      setInfo('Redirecting to Google…');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Google sign-in failed');
    } finally {
      setLoading(false);
    }
  };

  const sendReset = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setInfo(null);
    setLoading(true);
    try {
      const redirectTo = `${window.location.origin}/`;
      const { error: resetErr } = await supabase.auth.resetPasswordForEmail(email, {
        redirectTo,
      });
      if (resetErr) throw resetErr;
      setInfo('Password reset email sent. Check your inbox.');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Reset request failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-shell">
      <div className="auth-card">
        <h1 className="auth-title">
          {mode === 'register'
            ? 'Get Started'
            : mode === 'login'
              ? 'Welcome Back'
              : 'Forgot your password?'}
        </h1>
        <p className="auth-subtitle">{subtitle}</p>

        {(mode === 'register' || mode === 'login') && (
          <>
            <button
              type="button"
              className="auth-google-btn"
              onClick={handleGoogle}
              disabled={loading}
            >
              <GoogleIcon />
              Continue with Google
              {lastUsed === 'google' && <span className="auth-last-used">LAST USED</span>}
            </button>
            <div className="auth-divider">
              <span />
              <em>or</em>
              <span />
            </div>
          </>
        )}

        {(mode === 'register' || mode === 'login') && (
          <form onSubmit={submitEmailAuth} className="auth-form">
            {error && <p className="auth-error">{error}</p>}
            {info && <p className="auth-info">{info}</p>}

            <label>Email</label>
            <input
              type="email"
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              className="auth-input"
            />

            <label>Password {mode === 'register' ? '(minimum 8 characters)' : ''}</label>
            <div className="auth-input-wrap">
              <input
                type="password"
                autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                minLength={8}
                className="auth-input"
              />
              {lastUsed === 'email' && <span className="auth-last-used-inline">LAST USED</span>}
            </div>

            {mode === 'login' && (
              <button
                type="button"
                className="auth-link-btn"
                onClick={() => {
                  setMode('forgot');
                  setError(null);
                  setInfo(null);
                }}
              >
                Forgot password?
              </button>
            )}

            <button type="submit" className="auth-submit" disabled={loading}>
              {loading ? 'Please wait…' : mode === 'register' ? 'Sign Up' : 'Sign In'}
            </button>

            <p className="auth-switch">
              {mode === 'login' ? "Don't have an account?" : 'Have an account?'}{' '}
              <button
                type="button"
                onClick={() => {
                  setMode(mode === 'login' ? 'register' : 'login');
                  setError(null);
                  setInfo(null);
                }}
              >
                {mode === 'login' ? 'Sign Up' : 'Sign In'}
              </button>
            </p>
          </form>
        )}

        {mode === 'forgot' && (
          <form onSubmit={sendReset} className="auth-form">
            {error && <p className="auth-error">{error}</p>}
            {info && <p className="auth-info">{info}</p>}

            <label>Email</label>
            <input
              type="email"
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              className="auth-input"
            />

            <button type="submit" className="auth-submit" disabled={loading}>
              {loading ? 'Sending…' : 'Send Reset Link'}
            </button>

            <p className="auth-switch">
              Already have an account?{' '}
              <button
                type="button"
                onClick={() => {
                  setMode('login');
                  setError(null);
                  setInfo(null);
                }}
              >
                Sign In
              </button>
            </p>
          </form>
        )}
      </div>
    </div>
  );
};

export default AuthPage;
