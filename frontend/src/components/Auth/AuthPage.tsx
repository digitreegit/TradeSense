import React, { useMemo, useState } from 'react';
import api from '../../services/api';
import { setLastAuthMethod, setToken } from '../../auth/token';
import { useAppStore } from '../../stores/useAppStore';

type Mode = 'register' | 'login' | 'forgot';

const GoogleIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
    <path fill="#EA4335" d="M12 10.2v3.9h5.5c-.2 1.2-1.4 3.5-5.5 3.5-3.3 0-6-2.8-6-6.2s2.7-6.2 6-6.2c1.9 0 3.1.8 3.8 1.5l2.6-2.5C16.9 2.7 14.7 2 12 2 6.9 2 2.8 6.2 2.8 11.4S6.9 20.8 12 20.8c6.9 0 9.1-4.9 9.1-7.4 0-.5 0-.8-.1-1.2H12z"/>
    <path fill="#34A853" d="M3.7 7.6l3.2 2.3c.9-1.9 2.7-3.2 5.1-3.2 1.9 0 3.1.8 3.8 1.5l2.6-2.5C16.9 2.7 14.7 2 12 2 8.2 2 4.9 4.2 3.7 7.6z"/>
    <path fill="#FBBC05" d="M12 20.8c2.6 0 4.8-.9 6.4-2.5l-3-2.4c-.8.6-1.9 1.1-3.4 1.1-3 0-5.2-2-6-4.6l-3.2 2.4c1.3 3.8 4.8 6 9.2 6z"/>
    <path fill="#4285F4" d="M21.1 13.4c0-.5 0-.8-.1-1.2H12v3.9h5.5c-.3 1.4-1.2 2.5-2.1 3.2l3 2.4c1.8-1.6 2.7-4 2.7-6.9z"/>
  </svg>
);

const AuthPage: React.FC = () => {
  const { setAuthProfile, setCurrentPage, authMethod, setAuthMethod } = useAppStore();
  const [mode, setMode] = useState<Mode>('register');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [lastUsed, setLastUsed] = useState<'google' | 'email' | null>(authMethod);

  const subtitle = useMemo(() => {
    if (mode === 'register') return 'Create a new account';
    if (mode === 'login') return 'Sign in to your account';
    return "Enter your email and we'll send reset instructions";
  }, [mode]);

  const submitAuth = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const res =
        mode === 'login'
          ? await api.login(email, password)
          : await api.register(email, password);
      setToken(res.access_token);
      setLastAuthMethod('email');
      setLastUsed('email');
      setAuthMethod('email');
      setLastAuthMethod('email');
      setAuthProfile(res.email, false);
      setCurrentPage('dashboard');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Request failed');
    } finally {
      setLoading(false);
    }
  };

  const handleGoogle = () => {
    setError('Google Login is UI-ready. Backend OAuth hookup is next step.');
    setLastUsed('google');
    setAuthMethod('google');
    setLastAuthMethod('google');
  };

  const sendReset = (e: React.FormEvent) => {
    e.preventDefault();
    setError(`Password reset flow is UI-ready. Backend email sender not wired yet for ${email || 'this email'}.`);
  };

  return (
    <div
      className="page-enter"
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '24px',
        background: 'var(--bg-primary)',
      }}
    >
      <div
        className="card"
        style={{
          padding: 'var(--space-xl)',
          width: '100%',
          maxWidth: 460,
          border: '1px solid var(--border-secondary)',
          boxShadow: 'var(--shadow-lg)',
        }}
      >
        <h1 style={{ fontSize: '30px', marginBottom: '2px', textAlign: 'center' }}>
          {mode === 'register' ? 'Get Started' : mode === 'login' ? 'Welcome Back' : 'Forgot your password?'}
        </h1>
        <p style={{ fontSize: '13px', color: 'var(--text-tertiary)', marginBottom: '22px', textAlign: 'center' }}>
          {subtitle}
        </p>

        {(mode === 'register' || mode === 'login') && (
          <>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={handleGoogle}
              style={{
                width: '100%',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '10px',
                position: 'relative',
                marginBottom: '14px',
                background: 'rgba(255,255,255,0.04)',
              }}
            >
              <GoogleIcon />
              Continue with Google
              {lastUsed === 'google' && (
                <span
                  style={{
                    position: 'absolute',
                    right: '10px',
                    top: '8px',
                    fontSize: '10px',
                    fontWeight: 700,
                    color: 'var(--accent-primary)',
                    border: '1px solid var(--border-accent)',
                    borderRadius: '999px',
                    padding: '2px 6px',
                    background: 'var(--accent-primary-dim)',
                  }}
                >
                  LAST USED
                </span>
              )}
            </button>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '14px' }}>
              <div style={{ flex: 1, height: 1, background: 'var(--border-secondary)' }} />
              <span style={{ fontSize: '12px', color: 'var(--text-tertiary)' }}>or</span>
              <div style={{ flex: 1, height: 1, background: 'var(--border-secondary)' }} />
            </div>
          </>
        )}

        {(mode === 'register' || mode === 'login') && (
          <form onSubmit={submitAuth}>
            {error && (
              <p style={{ color: 'var(--loss)', fontSize: '13px', marginBottom: '12px' }}>{error}</p>
            )}
            <label style={{ display: 'block', fontSize: '12px', marginBottom: '4px' }}>Email</label>
            <input
              type="email"
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              style={{
                width: '100%',
                marginBottom: '12px',
                padding: '10px',
                borderRadius: '8px',
                border: '1px solid var(--border-secondary)',
                background: 'var(--bg-secondary)',
                color: 'inherit',
              }}
            />
            <label style={{ display: 'block', fontSize: '12px', marginBottom: '4px' }}>
              Password {mode === 'register' ? '(minimum 8 characters)' : ''}
            </label>
            <div style={{ position: 'relative' }}>
              <input
                type="password"
                autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                minLength={8}
                style={{
                  width: '100%',
                  marginBottom: '16px',
                  padding: '10px',
                  borderRadius: '8px',
                  border: '1px solid var(--border-secondary)',
                  background: 'var(--bg-secondary)',
                  color: 'inherit',
                }}
              />
              {lastUsed === 'email' && (
                <span
                  style={{
                    position: 'absolute',
                    right: '10px',
                    top: '8px',
                    fontSize: '10px',
                    fontWeight: 700,
                    color: 'var(--accent-primary)',
                    border: '1px solid var(--border-accent)',
                    borderRadius: '999px',
                    padding: '2px 6px',
                    background: 'var(--accent-primary-dim)',
                  }}
                >
                  LAST USED
                </span>
              )}
            </div>
            {mode === 'login' && (
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => {
                  setMode('forgot');
                  setError(null);
                }}
                style={{ width: '100%', marginBottom: '12px', background: 'transparent' }}
              >
                Forgot password?
              </button>
            )}
            <button type="submit" className="btn-start" disabled={loading} style={{ width: '100%' }}>
              {loading ? 'Please wait…' : mode === 'login' ? 'Sign In' : 'Sign Up'}
            </button>
            <p style={{ marginTop: '14px', textAlign: 'center', fontSize: '13px', color: 'var(--text-tertiary)' }}>
              {mode === 'login' ? "Don't have an account? " : 'Have an account? '}
              <button
                type="button"
                style={{ background: 'none', border: 'none', color: 'var(--text-primary)', fontWeight: 700, cursor: 'pointer', padding: 0 }}
                onClick={() => {
                  setMode(mode === 'login' ? 'register' : 'login');
                  setError(null);
                }}
              >
                {mode === 'login' ? 'Sign Up' : 'Sign In'}
              </button>
            </p>
          </form>
        )}

        {mode === 'forgot' && (
          <form onSubmit={sendReset}>
            {error && (
              <p style={{ color: 'var(--loss)', fontSize: '13px', marginBottom: '12px' }}>{error}</p>
            )}
            <label style={{ display: 'block', fontSize: '12px', marginBottom: '4px' }}>Email</label>
            <input
              type="email"
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              style={{
                width: '100%',
                marginBottom: '16px',
                padding: '10px',
                borderRadius: '8px',
                border: '1px solid var(--border-secondary)',
                background: 'var(--bg-secondary)',
                color: 'inherit',
              }}
            />
            <button type="submit" className="btn-start" style={{ width: '100%' }}>
              Send Reset Code
            </button>
            <p style={{ marginTop: '14px', textAlign: 'center', fontSize: '13px', color: 'var(--text-tertiary)' }}>
              Already have an account?{' '}
              <button
                type="button"
                style={{ background: 'none', border: 'none', color: 'var(--text-primary)', fontWeight: 700, cursor: 'pointer', padding: 0 }}
                onClick={() => {
                  setMode('login');
                  setError(null);
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
