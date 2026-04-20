import React, { useState } from 'react';
import api from '../../services/api';
import { clearToken } from '../../auth/token';
import { useAppStore } from '../../stores/useAppStore';

const SettingsPage: React.FC = () => {
  const { authEmail, authAlpacaConfigured, setAuthProfile, setCurrentPage } = useAppStore();
  const [key, setKey] = useState('');
  const [secret, setSecret] = useState('');
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const saveKeys = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr(null);
    setMsg(null);
    if (!key.trim() || !secret.trim()) {
      setErr('Enter both keys.');
      return;
    }
    setLoading(true);
    try {
      await api.saveAlpacaKeys(key.trim(), secret.trim());
      setAuthProfile(authEmail, true);
      setKey('');
      setSecret('');
      setMsg('Alpaca keys saved.');
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : 'Failed');
    } finally {
      setLoading(false);
    }
  };

  const signOut = () => {
    clearToken();
    setAuthProfile(null, false);
    setCurrentPage('auth');
  };

  return (
    <div className="page-enter" style={{ maxWidth: 520, margin: '0 auto', padding: 'var(--space-xl)' }}>
      <div className="card" style={{ padding: 'var(--space-xl)' }}>
        <h2 style={{ fontSize: '18px', marginBottom: '16px' }}>Account &amp; Alpaca</h2>
        {authEmail ? (
          <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginBottom: '16px' }}>
            Signed in as <strong>{authEmail}</strong>
            {authAlpacaConfigured ? ' · Alpaca keys on file' : ' · Alpaca keys not set'}
          </p>
        ) : (
          <p style={{ fontSize: '13px', color: 'var(--text-tertiary)', marginBottom: '16px' }}>
            Guest mode: using server <code>.env</code> Alpaca keys. Sign in from Auth to use your own paper account.
          </p>
        )}
        <form onSubmit={saveKeys}>
          {err && <p style={{ color: 'var(--loss)', fontSize: '13px', marginBottom: '8px' }}>{err}</p>}
          {msg && <p style={{ color: 'var(--profit)', fontSize: '13px', marginBottom: '8px' }}>{msg}</p>}
          <label style={{ fontSize: '12px' }}>Alpaca API Key ID (paper)</label>
          <input
            type="password"
            value={key}
            onChange={(e) => setKey(e.target.value)}
            style={{ display: 'block', width: '100%', margin: '6px 0 12px', padding: '10px', borderRadius: '8px', border: '1px solid var(--border-secondary)', background: 'var(--bg-secondary)', color: 'inherit' }}
          />
          <label style={{ fontSize: '12px' }}>Alpaca Secret Key</label>
          <input
            type="password"
            value={secret}
            onChange={(e) => setSecret(e.target.value)}
            style={{ display: 'block', width: '100%', margin: '6px 0 16px', padding: '10px', borderRadius: '8px', border: '1px solid var(--border-secondary)', background: 'var(--bg-secondary)', color: 'inherit' }}
          />
          <button type="submit" className="btn-start" disabled={loading || !authEmail}>
            {loading ? 'Saving…' : 'Save encrypted keys'}
          </button>
          {!authEmail && (
            <p style={{ fontSize: '12px', color: 'var(--text-tertiary)', marginTop: '12px' }}>
              Sign in first to store your keys.
            </p>
          )}
        </form>
        {authEmail && (
          <button type="button" className="btn btn-secondary" style={{ marginTop: '20px' }} onClick={signOut}>
            Sign out
          </button>
        )}
      </div>
    </div>
  );
};

export default SettingsPage;
