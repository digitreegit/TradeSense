import React, { useEffect, useState } from 'react';
import api from '../../services/api';
import { clearToken, setToken } from '../../auth/token';
import { useAppStore } from '../../stores/useAppStore';

type Props = { onDone: () => void; initialAlpacaStep?: boolean };

const AuthPage: React.FC<Props> = ({ onDone, initialAlpacaStep = false }) => {
  const { setAuthProfile, authEmail: storeEmail } = useAppStore();
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [email, setEmail] = useState(storeEmail || '');
  const [password, setPassword] = useState('');
  const [alpacaKey, setAlpacaKey] = useState('');
  const [alpacaSecret, setAlpacaSecret] = useState('');
  const [step, setStep] = useState<'auth' | 'alpaca'>(initialAlpacaStep ? 'alpaca' : 'auth');

  useEffect(() => {
    if (initialAlpacaStep && storeEmail) setEmail(storeEmail);
  }, [initialAlpacaStep, storeEmail]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const finishGuest = () => {
    clearToken();
    setAuthProfile(null, false);
    onDone();
  };

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
      setEmail(res.email);
      setStep('alpaca');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Request failed');
    } finally {
      setLoading(false);
    }
  };

  const submitAlpaca = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!alpacaKey.trim() || !alpacaSecret.trim()) {
      setError('Enter both Alpaca API key and secret.');
      return;
    }
    setError(null);
    setLoading(true);
    try {
      await api.saveAlpacaKeys(alpacaKey.trim(), alpacaSecret.trim());
      setAuthProfile(email, true);
      setAlpacaKey('');
      setAlpacaSecret('');
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save keys');
    } finally {
      setLoading(false);
    }
  };

  const skipAlpaca = () => {
    setAuthProfile(email, false);
    onDone();
  };

  if (step === 'alpaca') {
    return (
      <div className="page-enter" style={{ maxWidth: 440, margin: '48px auto', padding: '0 16px' }}>
        <div className="card" style={{ padding: 'var(--space-xl)' }}>
          <h1 style={{ fontSize: '20px', marginBottom: '8px' }}>Connect Alpaca (paper)</h1>
          <p style={{ fontSize: '13px', color: 'var(--text-tertiary)', marginBottom: '20px', lineHeight: 1.5 }}>
            Each user trades on their own Alpaca paper account. Keys are encrypted on the server.
            Get keys from{' '}
            <a href="https://app.alpaca.markets/paper/dashboard/overview" target="_blank" rel="noreferrer">
              Alpaca dashboard
            </a>
            .
          </p>
          <form onSubmit={submitAlpaca}>
            {error && (
              <p style={{ color: 'var(--loss)', fontSize: '13px', marginBottom: '12px' }}>{error}</p>
            )}
            <label style={{ display: 'block', fontSize: '12px', marginBottom: '4px' }}>API Key ID</label>
            <input
              type="password"
              autoComplete="off"
              value={alpacaKey}
              onChange={(e) => setAlpacaKey(e.target.value)}
              style={{ width: '100%', marginBottom: '12px', padding: '10px', borderRadius: '8px', border: '1px solid var(--border-secondary)', background: 'var(--bg-secondary)', color: 'inherit' }}
            />
            <label style={{ display: 'block', fontSize: '12px', marginBottom: '4px' }}>Secret Key</label>
            <input
              type="password"
              autoComplete="off"
              value={alpacaSecret}
              onChange={(e) => setAlpacaSecret(e.target.value)}
              style={{ width: '100%', marginBottom: '16px', padding: '10px', borderRadius: '8px', border: '1px solid var(--border-secondary)', background: 'var(--bg-secondary)', color: 'inherit' }}
            />
            <button type="submit" className="btn-start" disabled={loading} style={{ width: '100%', marginBottom: '8px' }}>
              {loading ? 'Saving…' : 'Save & continue'}
            </button>
            <button type="button" className="btn btn-secondary" style={{ width: '100%' }} onClick={skipAlpaca}>
              Skip for now (add keys in Settings later)
            </button>
          </form>
        </div>
      </div>
    );
  }

  return (
    <div className="page-enter" style={{ maxWidth: 440, margin: '48px auto', padding: '0 16px' }}>
      <div className="card" style={{ padding: 'var(--space-xl)' }}>
        <h1 style={{ fontSize: '22px', marginBottom: '4px' }}>TradeSense</h1>
        <p style={{ fontSize: '13px', color: 'var(--text-tertiary)', marginBottom: '24px' }}>
          {mode === 'login' ? 'Sign in to your account' : 'Create an account'}
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
            style={{ width: '100%', marginBottom: '12px', padding: '10px', borderRadius: '8px', border: '1px solid var(--border-secondary)', background: 'var(--bg-secondary)', color: 'inherit' }}
          />
          <label style={{ display: 'block', fontSize: '12px', marginBottom: '4px' }}>Password (min 8 chars)</label>
          <input
            type="password"
            autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={8}
            style={{ width: '100%', marginBottom: '16px', padding: '10px', borderRadius: '8px', border: '1px solid var(--border-secondary)', background: 'var(--bg-secondary)', color: 'inherit' }}
          />
          <button type="submit" className="btn-start" disabled={loading} style={{ width: '100%', marginBottom: '12px' }}>
            {loading ? 'Please wait…' : mode === 'login' ? 'Sign in' : 'Create account'}
          </button>
        </form>
        <button type="button" className="btn btn-secondary" style={{ width: '100%' }} onClick={finishGuest}>
          Continue without account (server .env Alpaca only)
        </button>
      </div>
    </div>
  );
};

export default AuthPage;
