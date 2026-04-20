import React, { useState } from 'react';
import api from '../../services/api';
import { useAppStore } from '../../stores/useAppStore';

const SettingsPage: React.FC = () => {
  const { authEmail, authAlpacaConfigured, setAuthProfile } = useAppStore();
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
      setErr('Enter both the API Key ID and Secret Key.');
      return;
    }
    setLoading(true);
    try {
      await api.saveAlpacaKeys(key.trim(), secret.trim());
      setAuthProfile(authEmail, true);
      setKey('');
      setSecret('');
      setMsg('Alpaca paper keys saved (encrypted on the server).');
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : 'Failed to save');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="page-enter" style={{ maxWidth: 560, margin: '0 auto', padding: 'var(--space-xl)' }}>
      <div className="card" style={{ padding: 'var(--space-xl)' }}>
        <h2 style={{ fontSize: '18px', marginBottom: '8px' }}>Settings</h2>
        <p style={{ fontSize: '13px', color: 'var(--text-tertiary)', marginBottom: '20px', lineHeight: 1.5 }}>
          Connect your <strong>Alpaca paper trading</strong> account. Keys are encrypted and only your user can trade with them.
          Create keys at{' '}
          <a href="https://app.alpaca.markets/paper/dashboard/overview" target="_blank" rel="noreferrer">
            Alpaca (Paper)
          </a>
          .
        </p>
        <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginBottom: '16px' }}>
          Signed in as <strong>{authEmail}</strong>
          {authAlpacaConfigured ? ' · keys on file' : ' · keys not configured yet'}
        </p>
        <form onSubmit={saveKeys}>
          {err && <p style={{ color: 'var(--loss)', fontSize: '13px', marginBottom: '8px' }}>{err}</p>}
          {msg && <p style={{ color: 'var(--profit)', fontSize: '13px', marginBottom: '8px' }}>{msg}</p>}
          <label style={{ fontSize: '12px' }}>Alpaca API Key ID</label>
          <input
            type="password"
            autoComplete="off"
            value={key}
            onChange={(e) => setKey(e.target.value)}
            placeholder="PK…"
            style={{
              display: 'block',
              width: '100%',
              margin: '6px 0 12px',
              padding: '10px',
              borderRadius: '8px',
              border: '1px solid var(--border-secondary)',
              background: 'var(--bg-secondary)',
              color: 'inherit',
            }}
          />
          <label style={{ fontSize: '12px' }}>Alpaca Secret Key</label>
          <input
            type="password"
            autoComplete="off"
            value={secret}
            onChange={(e) => setSecret(e.target.value)}
            style={{
              display: 'block',
              width: '100%',
              margin: '6px 0 16px',
              padding: '10px',
              borderRadius: '8px',
              border: '1px solid var(--border-secondary)',
              background: 'var(--bg-secondary)',
              color: 'inherit',
            }}
          />
          <button type="submit" className="btn-start" disabled={loading}>
            {loading ? 'Saving…' : 'Save keys'}
          </button>
        </form>
      </div>
    </div>
  );
};

export default SettingsPage;
