import React, { useState } from 'react';
import api from '../../services/api';
import { setToken } from '../../auth/token';
import { useAppStore } from '../../stores/useAppStore';

/**
 * Required login gate — no guest mode. Alpaca keys are entered in Settings after sign-in.
 */
const AuthPage: React.FC = () => {
  const { setAuthProfile, setCurrentPage } = useAppStore();
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

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
      setAuthProfile(res.email, false);
      setCurrentPage('dashboard');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Request failed');
    } finally {
      setLoading(false);
    }
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
      <div className="card" style={{ padding: 'var(--space-xl)', width: '100%', maxWidth: 420 }}>
        <h1 style={{ fontSize: '22px', marginBottom: '4px' }}>TradeSense</h1>
        <p style={{ fontSize: '13px', color: 'var(--text-tertiary)', marginBottom: '24px' }}>
          {mode === 'login' ? 'Sign in to continue' : 'Create your account'}
        </p>
        <div style={{ display: 'flex', gap: '8px', marginBottom: '20px' }}>
          <button
            type="button"
            className={mode === 'login' ? 'btn-start' : 'btn btn-secondary'}
            onClick={() => { setMode('login'); setError(null); }}
            style={{ flex: 1 }}
          >
            Sign in
          </button>
          <button
            type="button"
            className={mode === 'register' ? 'btn-start' : 'btn btn-secondary'}
            onClick={() => { setMode('register'); setError(null); }}
            style={{ flex: 1 }}
          >
            Sign up
          </button>
        </div>
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
          <label style={{ display: 'block', fontSize: '12px', marginBottom: '4px' }}>Password (min 8 characters)</label>
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
          <button type="submit" className="btn-start" disabled={loading} style={{ width: '100%' }}>
            {loading ? 'Please wait…' : mode === 'login' ? 'Sign in' : 'Create account'}
          </button>
        </form>
      </div>
    </div>
  );
};

export default AuthPage;
